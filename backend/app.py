"""HTTP API for the reviewable historical-newspaper OCR workflow."""

from __future__ import annotations

import os
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from werkzeug.exceptions import HTTPException
from werkzeug.utils import secure_filename

from ai_service import AIService, AIUnavailableError
from ocr_engine import OCREngine
from task_store import TaskNotFoundError, TaskStore
from workflow import DocumentWorkflow, WorkflowStateError


BASE_DIR = Path(__file__).resolve().parent
UPLOAD_ROOT = BASE_DIR / "uploads"
RESULT_ROOT = BASE_DIR / "results_v2"
ALLOWED_EXTENSIONS = {"pdf", "png", "jpg", "jpeg", "bmp", "tif", "tiff"}

app = Flask(__name__)
app.config.update(MAX_CONTENT_LENGTH=100 * 1024 * 1024, JSON_AS_ASCII=False)
CORS(app, resources={r"/api/*": {"origins": os.getenv("CORS_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(",")}})
UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

store = TaskStore(RESULT_ROOT)
for interrupted in store.list_recent(limit=1000):
    if interrupted.get("status") in {"layout_running", "ocr_queued", "ocr_running", "correction_queued", "correction_running"}:
        interrupted.update(
            status="interrupted",
            error={"message": "服务曾在任务运行时停止。已完成的分页结果仍然保留，可以重新启动该阶段。", "type": "InterruptedTask"},
        )
        store.save(interrupted)
ocr_engine = OCREngine(use_gpu=os.getenv("OCR_USE_GPU", "false").lower() == "true")
ai_service = AIService()
workflow = DocumentWorkflow(store, ocr_engine, ai_service)
executor = ThreadPoolExecutor(max_workers=max(1, int(os.getenv("WORKFLOW_WORKERS", "2"))), thread_name_prefix="newspaper-ocr")


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_EXTENSIONS


def public_task(task):
    result = deepcopy(task)
    result.pop("source_path", None)
    if result.get("error") and os.getenv("FLASK_DEBUG", "false").lower() != "true":
        result["error"].pop("trace", None)
    result["links"] = {
        "self": f"/api/tasks/{task['id']}",
        "ocr": f"/api/tasks/{task['id']}/ocr",
        "correction": f"/api/tasks/{task['id']}/correction",
    }
    return result


@app.get("/")
def index():
    return jsonify({"service": "Historical Newspaper OCR Workflow", "version": "2.0", "health": "/api/health"})


@app.get("/api/health")
def health():
    return jsonify({"status": "healthy" if ocr_engine.engine_ready else "degraded", "ocr": ocr_engine.health(), "ai": ai_service.health()})


@app.get("/api/tasks")
def list_tasks():
    return jsonify({"tasks": [public_task(task) for task in store.list_recent()]})


@app.post("/api/tasks")
@app.post("/api/upload")
def create_task():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        return jsonify({"error": "A PDF or image file is required"}), 400
    if not allowed_file(upload.filename):
        return jsonify({"error": "Unsupported file type"}), 400

    try:
        dpi = min(300, max(100, int(request.form.get("dpi", 180))))
        max_pages_raw = request.form.get("max_pages", "").strip()
        max_pages = min(500, max(1, int(max_pages_raw))) if max_pages_raw else None
    except ValueError:
        return jsonify({"error": "dpi and max_pages must be integers"}), 400

    options = {
        "dpi": dpi,
        "max_pages": max_pages,
        "ai_layout": request.form.get("ai_layout", "true").lower() in {"1", "true", "yes", "on"},
    }
    task = store.create(upload.filename, options)
    extension = Path(upload.filename).suffix.lower()
    filename = secure_filename(upload.filename) or f"source{extension}"
    upload_dir = UPLOAD_ROOT / task["id"]
    upload_dir.mkdir(parents=True, exist_ok=False)
    source_path = upload_dir / filename
    upload.save(source_path)
    task["source_path"] = str(source_path)
    store.save(task)
    executor.submit(workflow.analyze_layout, task["id"])
    return jsonify(public_task(store.load(task["id"]))), 202


@app.get("/api/tasks/<task_id>")
def get_task(task_id):
    return jsonify(public_task(store.load(task_id)))


@app.put("/api/tasks/<task_id>/layout")
def update_layout(task_id):
    payload = request.get_json(silent=True) or {}
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return jsonify({"error": "pages must be an array"}), 400
    return jsonify(public_task(workflow.save_layout(task_id, pages)))


@app.post("/api/tasks/<task_id>/ocr")
def start_ocr(task_id):
    payload = request.get_json(silent=True) or {}
    if isinstance(payload.get("pages"), list):
        workflow.save_layout(task_id, payload["pages"])
    page_numbers = payload.get("page_numbers")
    if page_numbers is not None and not isinstance(page_numbers, list):
        return jsonify({"error": "page_numbers must be an array"}), 400
    task = workflow.queue_ocr(task_id, page_numbers)
    executor.submit(workflow.run_ocr, task_id, page_numbers)
    return jsonify(public_task(task)), 202


@app.get("/api/tasks/<task_id>/ocr")
def get_ocr(task_id):
    return jsonify(workflow.result(task_id, "ocr"))


@app.put("/api/tasks/<task_id>/ocr")
def update_ocr(task_id):
    payload = request.get_json(silent=True) or {}
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return jsonify({"error": "pages must be an array"}), 400
    return jsonify(workflow.update_ocr_text(task_id, pages))


@app.post("/api/tasks/<task_id>/correction")
def start_correction(task_id):
    payload = request.get_json(silent=True) or {}
    page_numbers = payload.get("page_numbers")
    if page_numbers is not None and not isinstance(page_numbers, list):
        return jsonify({"error": "page_numbers must be an array"}), 400
    task = workflow.queue_correction(task_id, page_numbers)
    executor.submit(workflow.run_correction, task_id, page_numbers)
    return jsonify(public_task(task)), 202


@app.get("/api/tasks/<task_id>/correction")
def get_correction(task_id):
    return jsonify(workflow.result(task_id, "correction"))


@app.put("/api/tasks/<task_id>/correction")
def update_correction(task_id):
    payload = request.get_json(silent=True) or {}
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return jsonify({"error": "pages must be an array"}), 400
    return jsonify(workflow.update_corrected_text(task_id, pages))


@app.post("/api/tasks/<task_id>/analysis")
def analyze(task_id):
    payload = request.get_json(silent=True) or {}
    action = payload.get("action", "summary")
    if action == "summary":
        return jsonify(workflow.summarize(task_id, str(payload.get("instruction", ""))))
    if action == "question":
        question = str(payload.get("question", "")).strip()
        if not question:
            return jsonify({"error": "question is required"}), 400
        return jsonify(workflow.answer(task_id, question))
    return jsonify({"error": "action must be summary or question"}), 400


@app.get("/api/tasks/<task_id>/pages/<int:page_number>/image")
def page_image(task_id, page_number):
    store.load(task_id)
    path = store.task_dir(task_id) / "pages" / f"page_{page_number:03d}.png"
    if not path.exists():
        return jsonify({"error": "Page image is not ready"}), 404
    return send_file(path, mimetype="image/png", conditional=True)


@app.get("/api/tasks/<task_id>/crops/<name>")
def crop_image(task_id, name):
    store.load(task_id)
    safe_name = secure_filename(name)
    if safe_name != name:
        return jsonify({"error": "Invalid crop name"}), 400
    path = store.task_dir(task_id) / "crops" / safe_name
    if not path.exists():
        return jsonify({"error": "Crop is not ready"}), 404
    return send_file(path, mimetype="image/png", conditional=True)


@app.get("/api/tasks/<task_id>/export/<kind>")
def export(task_id, kind):
    task_dir = store.task_dir(task_id)
    candidates = {"raw": ("raw.txt", "text/plain"), "corrected": ("corrected.txt", "text/plain"), "json": ("corrected.json", "application/json")}
    if kind not in candidates:
        return jsonify({"error": "kind must be raw, corrected or json"}), 400
    name, mimetype = candidates[kind]
    path = task_dir / name
    if kind == "json" and not path.exists():
        path = task_dir / "ocr.json"
    if not path.exists():
        return jsonify({"error": "Export is not ready"}), 404
    return send_file(path, as_attachment=True, download_name=f"{task_id}_{path.name}", mimetype=mimetype)


@app.errorhandler(TaskNotFoundError)
def task_not_found(_error):
    return jsonify({"error": "Task not found"}), 404


@app.errorhandler(WorkflowStateError)
@app.errorhandler(AIUnavailableError)
def workflow_error(error):
    return jsonify({"error": str(error)}), 409


@app.errorhandler(413)
def too_large(_error):
    return jsonify({"error": "File exceeds the 100 MB upload limit"}), 413


@app.errorhandler(Exception)
def unexpected_error(error):
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code
    if app.debug:
        raise error
    return jsonify({"error": str(error)}), 500


if __name__ == "__main__":
    app.run(host=os.getenv("FLASK_HOST", "127.0.0.1"), port=int(os.getenv("FLASK_PORT", "5000")), debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", threaded=True)
