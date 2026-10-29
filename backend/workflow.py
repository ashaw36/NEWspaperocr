"""Stateful, reviewable newspaper recognition workflow."""

from __future__ import annotations

import json
import traceback
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List

import cv2

from ai_service import AIService
from image_io import read_image, write_image
from layout_engine import LayoutEngine
from ocr_engine import OCREngine, prepare_crop_for_ocr
from pdf_processor import PDFProcessor
from task_store import TaskStore, utc_now


class WorkflowStateError(RuntimeError):
    pass


class DocumentWorkflow:
    def __init__(self, store: TaskStore, ocr: OCREngine, ai: AIService):
        self.store, self.ocr, self.ai = store, ocr, ai
        self.layout = LayoutEngine()

    def analyze_layout(
        self, task_id: str, max_pages_override: int | None = None
    ) -> None:
        try:
            task = self.store.load(task_id)
            task.update(status="layout_running", stage="layout", error=None)
            self.store.save(task)
            task_dir = self.store.task_dir(task_id)
            processor = PDFProcessor(dpi=int(task["options"].get("dpi", 180)))
            document_page_count = processor.page_count(task["source_path"])
            requested_limit = max_pages_override or task["options"].get("max_pages")
            if requested_limit is None and not task["options"].get("layout_expanded"):
                requested_limit = 1
            pages = processor.render_document(
                task["source_path"],
                task_dir / "pages",
                max_pages=requested_limit or None,
            )
            task["document_page_count"] = document_page_count
            task["progress"] = {
                "current": 0,
                "total": len(pages),
                "message": "正在分析页面结构",
            }
            self.store.save(task)

            existing_pages = {
                page["page_number"]: page for page in task.get("pages", [])
            }
            planned = []
            warnings = []
            use_ai = bool(task["options"].get("ai_layout", True)) and getattr(
                self.ai, "supports_vision", False
            )
            layout_ai_success = 0
            layout_ai_failed = 0
            for index, page in enumerate(pages, 1):
                image = read_image(page["path"])
                prior_layout = existing_pages.get(page["page_number"], {}).get("layout")
                proposal = prior_layout or self.layout.propose(
                    image, page["page_number"]
                )
                if use_ai and (
                    prior_layout is None
                    or prior_layout.get("source") != "user-reviewed"
                ):
                    try:
                        enriched = self.ai.enrich_layout(page["path"], proposal)
                        enriched["regions"] = self.layout.normalize_regions(
                            enriched.get("regions", proposal["regions"])
                        )
                        proposal = enriched
                        proposal["source"] = "ai+computer-vision"
                        layout_ai_success += 1
                    except Exception as error:
                        layout_ai_failed += 1
                        warnings.append(
                            f"Page {page['page_number']} AI layout review failed: {error}"
                        )
                page_record = {
                    "page_number": page["page_number"],
                    "width": page["width"],
                    "height": page["height"],
                    "image_url": f"/api/tasks/{task_id}/pages/{page['page_number']}/image",
                    "layout": proposal,
                }
                planned.append(page_record)
                task["pages"] = planned
                task["progress"] = {
                    "current": index,
                    "total": len(pages),
                    "message": f"已分析第 {index}/{len(pages)} 页",
                }
                self.store.save(task)

            task.update(
                pages=planned,
                status="awaiting_layout_review",
                stage="layout",
                confirmed=False,
                warnings=warnings,
                progress={
                    "current": len(pages),
                    "total": len(pages),
                    "message": "请检查并确认 OCR 窗口",
                },
            )
            task["layout_quality"] = {
                "mode": (
                    "vision-reviewed"
                    if layout_ai_success
                    else "computer-vision-fallback"
                ),
                "vision_succeeded": layout_ai_success,
                "vision_failed": layout_ai_failed,
            }
            if max_pages_override:
                task["options"]["layout_expanded"] = True
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "layout", error)

    def expand_layout(self, task_id: str) -> None:
        task = self.store.load(task_id)
        if task.get("status") in {
            "layout_running",
            "ocr_running",
            "correction_running",
        }:
            raise WorkflowStateError("The task is currently running")
        total = int(task.get("document_page_count") or 1)
        task["options"]["layout_expanded"] = True
        task["options"]["layout_target_pages"] = total
        return self.store.save(task)

    def save_layout(self, task_id: str, page_updates: List[Dict]) -> Dict:
        task = self.store.load(task_id)
        if task["status"] in {"layout_running", "ocr_running", "correction_running"}:
            raise WorkflowStateError("The task is currently running")
        updates = {int(page["page_number"]): page for page in page_updates}
        for page in task.get("pages", []):
            incoming = updates.get(page["page_number"])
            if not incoming:
                continue
            page["layout"]["regions"] = self.layout.normalize_regions(
                incoming.get("regions", [])
            )
            page["layout"]["source"] = "user-reviewed"
        task.update(
            status="awaiting_layout_review", stage="layout", confirmed=False, error=None
        )
        return self.store.save(task)

    def queue_ocr(self, task_id: str, page_numbers: List[int] | None = None) -> Dict:
        task = self.store.load(task_id)
        if not task.get("pages"):
            raise WorkflowStateError("Layout analysis is not complete")
        if task["status"] in {"layout_running", "ocr_running", "correction_running"}:
            raise WorkflowStateError("The task is currently running")
        available = {page["page_number"] for page in task["pages"]}
        requested = sorted(set(page_numbers or available))
        if not requested or not set(requested).issubset(available):
            raise WorkflowStateError("OCR page selection is invalid")
        task.update(
            status="ocr_queued",
            stage="ocr",
            confirmed=True,
            error=None,
            ocr_request={"page_numbers": requested},
        )
        return self.store.save(task)

    def run_ocr(self, task_id: str, page_numbers: List[int] | None = None) -> None:
        try:
            task = self.store.load(task_id)
            requested = sorted(
                set(
                    page_numbers
                    or task.get("ocr_request", {}).get("page_numbers")
                    or [page["page_number"] for page in task["pages"]]
                )
            )
            selected_pages = [
                page for page in task["pages"] if page["page_number"] in requested
            ]
            task.update(status="ocr_running", stage="ocr", error=None)
            regions_total = sum(
                1
                for page in selected_pages
                for region in page["layout"]["regions"]
                if region["label"] != "ignore"
            )
            task["progress"] = {
                "current": 0,
                "total": regions_total,
                "message": "正在识别已确认的 OCR 窗口",
            }
            self.store.save(task)

            result_path = self.store.task_dir(task_id) / "ocr.json"
            previous = (
                self._read_json(task_id, "ocr.json")
                if result_path.exists()
                else {"pages": []}
            )
            page_results = {
                page["page_number"]: page for page in previous.get("pages", [])
            }
            completed = 0
            crops_dir = self.store.task_dir(task_id) / "crops"
            crops_dir.mkdir(exist_ok=True)
            for page in selected_pages:
                image_path = (
                    self.store.task_dir(task_id)
                    / "pages"
                    / f"page_{page['page_number']:03d}.png"
                )
                image = read_image(image_path)
                if image is None:
                    raise RuntimeError(
                        f"Cannot load rendered page {page['page_number']}"
                    )
                page_regions = []
                for region in sorted(
                    page["layout"]["regions"], key=lambda item: item["order"]
                ):
                    if region["label"] == "ignore":
                        continue
                    crop, pixel_box = self._crop(image, region["bbox"])
                    prepared = prepare_crop_for_ocr(crop, region["direction"])
                    crop_path = (
                        crops_dir / f"p{page['page_number']:03d}_{region['id']}.png"
                    )
                    if not write_image(crop_path, crop):
                        raise RuntimeError(f"Cannot save OCR crop: {crop_path.name}")
                    recognition = self.ocr.recognize(prepared, region["direction"])
                    visual = None
                    vision_error = None
                    if getattr(self.ai, "supports_vision", False) and hasattr(
                        self.ai, "transcribe_region"
                    ):
                        try:
                            visual = self.ai.transcribe_region(
                                crop_path, region, page["page_number"]
                            )
                        except Exception as error:
                            vision_error = str(error)
                    visual_text = visual["text"] if visual else ""
                    chosen_text = (
                        visual_text if visual_text else recognition["full_text"]
                    )
                    disagreements = (
                        self._texts_disagree(visual_text, recognition["full_text"])
                        if visual_text
                        else False
                    )
                    quality = recognition.get(
                        "quality",
                        {
                            "status": "unknown",
                            "score": recognition["confidence"],
                            "flags": [],
                        },
                    )
                    if visual and visual.get("text"):
                        visual_confidence = float(visual.get("confidence") or 0)
                        quality = {
                            "status": (
                                "needs_review"
                                if visual.get("uncertain") or disagreements
                                else ("check" if visual_confidence < 0.75 else "pass")
                            ),
                            "score": round(visual_confidence, 4),
                            "flags": (
                                ["vision-uncertain"] if visual.get("uncertain") else []
                            )
                            + (["ocr-disagreement"] if disagreements else []),
                        }
                    page_regions.append(
                        {
                            "region_id": region["id"],
                            "order": region["order"],
                            "label": region["label"],
                            "article_id": region["article_id"],
                            "direction": region["direction"],
                            "bbox": region["bbox"],
                            "pixel_bbox": pixel_box,
                            "raw_text": recognition["full_text"],
                            "visual_text": visual["text"] if visual else "",
                            "final_region_text": chosen_text,
                            "visual_confidence": (
                                visual.get("confidence") if visual else None
                            ),
                            "visual_uncertain": (
                                visual.get("uncertain", "") if visual else ""
                            ),
                            "vision_error": vision_error,
                            "confidence": recognition["confidence"],
                            "quality": quality,
                            "text_blocks": recognition["text_blocks"],
                            "crop_url": f"/api/tasks/{task_id}/crops/{crop_path.name}",
                        }
                    )
                    completed += 1
                    task["progress"] = {
                        "current": completed,
                        "total": regions_total,
                        "message": f"正在识别第 {page['page_number']} 页窗口 {region['order']}",
                    }
                    self.store.save(task)
                page_text = "\n\n".join(
                    item["raw_text"] for item in page_regions if item["raw_text"]
                )
                visual_page_text = "\n\n".join(
                    item["final_region_text"]
                    for item in sorted(page_regions, key=lambda item: item["order"])
                    if item["final_region_text"]
                )
                page_results[page["page_number"]] = {
                    "page_number": page["page_number"],
                    "regions": page_regions,
                    "raw_text": page_text,
                    "visual_text": visual_page_text,
                }
                result = self._save_ocr_result(task_id, list(page_results.values()))
                task["ocr"] = {
                    "pages": len(result["pages"]),
                    "regions": sum(len(item["regions"]) for item in result["pages"]),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                }
                self.store.save(task)

            result = self._save_ocr_result(task_id, list(page_results.values()))
            visual_regions = sum(
                1
                for page in result["pages"]
                for region in page["regions"]
                if region.get("visual_text")
            )
            vision_failures = sum(
                1
                for page in result["pages"]
                for region in page["regions"]
                if region.get("vision_error")
            )
            task.update(
                status="ocr_ready",
                stage="ocr",
                ocr={
                    "pages": len(result["pages"]),
                    "regions": sum(len(item["regions"]) for item in result["pages"]),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                },
                recognition_quality={
                    "vision_regions": visual_regions,
                    "vision_failures": vision_failures,
                    "mode": (
                        "vision-primary-with-local-crosscheck"
                        if visual_regions
                        else "local-ocr-fallback"
                    ),
                },
                progress={
                    "current": regions_total,
                    "total": regions_total,
                    "message": "识别完成，可查看视觉转录与本地 OCR 对照",
                },
            )
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "ocr", error)

    def queue_correction(
        self, task_id: str, page_numbers: List[int] | None = None
    ) -> Dict:
        if not self.ai.available:
            raise WorkflowStateError(
                "AI is not configured. Add an API key before semantic correction"
            )
        task = self.store.load(task_id)
        if task["status"] not in {"ocr_ready", "correction_ready"}:
            raise WorkflowStateError("OCR must finish before AI correction")
        raw = self._read_json(task_id, "ocr.json")
        available = {page["page_number"] for page in raw["pages"]}
        requested = sorted(set(page_numbers or available))
        if not requested or not set(requested).issubset(available):
            raise WorkflowStateError("Only pages with completed OCR can be corrected")
        task.update(
            status="correction_queued",
            stage="correction",
            error=None,
            correction_request={"page_numbers": requested},
        )
        return self.store.save(task)

    def run_correction(
        self, task_id: str, page_numbers: List[int] | None = None
    ) -> None:
        try:
            task = self.store.load(task_id)
            raw = self._read_json(task_id, "ocr.json")
            requested = sorted(
                set(
                    page_numbers
                    or task.get("correction_request", {}).get("page_numbers")
                    or [page["page_number"] for page in raw["pages"]]
                )
            )
            raw_pages = [
                page for page in raw["pages"] if page["page_number"] in requested
            ]
            corrected_path = self.store.task_dir(task_id) / "corrected.json"
            previous = (
                self._read_json(task_id, "corrected.json")
                if corrected_path.exists()
                else {"pages": []}
            )
            corrected_by_page = {
                page["page_number"]: page for page in previous.get("pages", [])
            }
            task.update(status="correction_running", stage="correction")
            task["progress"] = {
                "current": 0,
                "total": len(raw_pages),
                "message": "正在进行 AI 语义校正",
            }
            self.store.save(task)
            for index, page in enumerate(raw_pages, 1):
                page_image = (
                    self.store.task_dir(task_id)
                    / "pages"
                    / f"page_{page['page_number']:03d}.png"
                )
                if hasattr(self.ai, "compose_page") and any(
                    region.get("visual_text") for region in page["regions"]
                ):
                    corrected = self.ai.compose_page(
                        page["page_number"], page["regions"], page.get("raw_text", "")
                    )
                    corrected["transcription_mode"] = "vision-regions+text-compose"
                else:
                    try:
                        corrected = self.ai.correct_page(
                            page["page_number"],
                            page["regions"],
                            page.get("raw_text", ""),
                            page_image=page_image,
                        )
                    except TypeError:
                        corrected = self.ai.correct_page(
                            page["page_number"],
                            page["regions"],
                            page.get("raw_text", ""),
                        )
                corrected["page_number"] = page["page_number"]
                corrected_by_page[page["page_number"]] = corrected
                result = self._save_corrected_result(
                    task_id, list(corrected_by_page.values()), raw
                )
                task["progress"] = {
                    "current": index,
                    "total": len(raw_pages),
                    "message": f"已校正第 {index}/{len(raw_pages)} 页",
                }
                self.store.save(task)
            result = self._save_corrected_result(
                task_id, list(corrected_by_page.values()), raw
            )
            task.update(
                status="correction_ready",
                stage="correction",
                correction={
                    "completed_pages": [
                        page["page_number"] for page in result["pages"]
                    ],
                    "result_url": f"/api/tasks/{task_id}/correction",
                },
                progress={
                    "current": len(raw_pages),
                    "total": len(raw_pages),
                    "message": "AI 语义校正完成",
                },
            )
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "correction", error)

    def result(self, task_id: str, kind: str) -> Dict:
        name = "corrected.json" if kind == "correction" else "ocr.json"
        return self._read_json(task_id, name)

    def update_ocr_text(self, task_id: str, page_updates: List[Dict]) -> Dict:
        result = self._read_json(task_id, "ocr.json")
        updates = {
            int(item["page_number"]): str(item.get("raw_text", ""))
            for item in page_updates
        }
        available = {page["page_number"] for page in result["pages"]}
        if not updates or not set(updates).issubset(available):
            raise WorkflowStateError("Only pages with completed OCR can be edited")
        for page in result["pages"]:
            if page["page_number"] in updates:
                page["raw_text"] = updates[page["page_number"]]
                page["manually_edited"] = True
        saved = self._save_ocr_result(task_id, result["pages"])
        corrected_path = self.store.task_dir(task_id) / "corrected.json"
        if corrected_path.exists():
            corrected = self._read_json(task_id, "corrected.json")
            remaining = [
                page
                for page in corrected.get("pages", [])
                if page["page_number"] not in updates
            ]
            self._save_corrected_result(task_id, remaining, saved)
            task = self.store.load(task_id)
            task.update(
                status="ocr_ready",
                stage="ocr",
                correction={
                    "completed_pages": [page["page_number"] for page in remaining],
                    "result_url": f"/api/tasks/{task_id}/correction",
                    "stale_pages": sorted(updates),
                },
            )
            self.store.save(task)
        return saved

    def update_corrected_text(self, task_id: str, page_updates: List[Dict]) -> Dict:
        raw = self._read_json(task_id, "ocr.json")
        result = self._read_json(task_id, "corrected.json")
        updates = {
            int(item["page_number"]): str(item.get("corrected_text", ""))
            for item in page_updates
        }
        available = {page["page_number"] for page in result.get("pages", [])}
        if not updates or not set(updates).issubset(available):
            raise WorkflowStateError(
                "Only pages with an AI correction draft can be edited"
            )
        for page in result["pages"]:
            if page["page_number"] in updates:
                page["corrected_text"] = updates[page["page_number"]]
                page["manually_edited"] = True
        saved = self._save_corrected_result(task_id, result["pages"], raw)
        task = self.store.load(task_id)
        task.update(
            status="correction_ready",
            stage="correction",
            correction={
                "completed_pages": [page["page_number"] for page in saved["pages"]],
                "result_url": f"/api/tasks/{task_id}/correction",
            },
        )
        self.store.save(task)
        return saved

    def document_text(self, task_id: str) -> str:
        task_dir = self.store.task_dir(task_id)
        corrected = task_dir / "corrected.txt"
        raw = task_dir / "raw.txt"
        path = corrected if corrected.exists() else raw
        if not path.exists():
            raise WorkflowStateError("No OCR text is available")
        return path.read_text(encoding="utf-8")

    def summarize(self, task_id: str, instruction: str) -> Dict:
        return self.ai.summarize_document(self.document_text(task_id), instruction)

    def answer(self, task_id: str, question: str) -> Dict:
        return self.ai.answer(self.document_text(task_id), question)

    def _crop(self, image, bbox: Dict):
        height, width = image.shape[:2]
        x1, y1 = int(bbox["x"] * width), int(bbox["y"] * height)
        x2, y2 = int((bbox["x"] + bbox["width"]) * width), int(
            (bbox["y"] + bbox["height"]) * height
        )
        pad = max(2, int(min(width, height) * 0.003))
        x1, y1, x2, y2 = (
            max(0, x1 - pad),
            max(0, y1 - pad),
            min(width, x2 + pad),
            min(height, y2 + pad),
        )
        if x2 <= x1 or y2 <= y1:
            raise ValueError("OCR region has an empty bounding box")
        return image[y1:y2, x1:x2], {
            "x": x1,
            "y": y1,
            "width": x2 - x1,
            "height": y2 - y1,
        }

    @staticmethod
    def _texts_disagree(left: str, right: str) -> bool:
        left_chars = "".join((left or "").split())
        right_chars = "".join((right or "").split())
        if not left_chars or not right_chars:
            return bool(left_chars or right_chars)
        if left_chars == right_chars:
            return False
        matcher = SequenceMatcher(None, left_chars, right_chars)
        return 1.0 - matcher.ratio() > 0.18

    def _write_json(self, task_id: str, name: str, value: Dict):
        path = self.store.task_dir(task_id) / name
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    def _save_ocr_result(self, task_id: str, pages: List[Dict]) -> Dict:
        ordered = sorted(pages, key=lambda page: page["page_number"])
        lines = []
        for page in ordered:
            lines.extend(
                [
                    f"========== Page {page['page_number']} ==========",
                    page.get("raw_text", ""),
                    "",
                ]
            )
        result = {
            "task_id": task_id,
            "engine": self.ocr.backend,
            "pages": ordered,
            "full_text": "\n".join(lines),
            "updated_at": utc_now(),
        }
        self._write_json(task_id, "ocr.json", result)
        (self.store.task_dir(task_id) / "raw.txt").write_text(
            result["full_text"], encoding="utf-8"
        )
        return result

    def _save_corrected_result(
        self, task_id: str, pages: List[Dict], raw: Dict
    ) -> Dict:
        ordered = sorted(pages, key=lambda page: page["page_number"])
        corrected_by_page = {page["page_number"]: page for page in ordered}
        lines = []
        for raw_page in sorted(raw["pages"], key=lambda page: page["page_number"]):
            corrected_page = corrected_by_page.get(raw_page["page_number"])
            text = (
                corrected_page.get("corrected_text", raw_page.get("raw_text", ""))
                if corrected_page
                else raw_page.get("raw_text", "")
            )
            lines.extend(
                [f"========== Page {raw_page['page_number']} ==========", text, ""]
            )
        result = {
            "task_id": task_id,
            "pages": ordered,
            "full_text": "\n".join(lines),
            "generated_at": utc_now(),
        }
        self._write_json(task_id, "corrected.json", result)
        (self.store.task_dir(task_id) / "corrected.txt").write_text(
            result["full_text"], encoding="utf-8"
        )
        return result

    def _read_json(self, task_id: str, name: str) -> Dict:
        path = self.store.task_dir(task_id) / name
        if not path.exists():
            raise WorkflowStateError(f"Result is not available: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _fail(self, task_id: str, stage: str, error: Exception):
        try:
            task = self.store.load(task_id)
            task.update(
                status="failed",
                stage=stage,
                error={
                    "message": str(error),
                    "type": type(error).__name__,
                    "trace": traceback.format_exc(),
                },
            )
            self.store.save(task)
        except Exception:
            pass

    def generate_final_document(self, task_id: str, format: str = "markdown") -> str:
        """Generate a structured final document from OCR results.

        Args:
            task_id: Task identifier
            format: Output format ('markdown' or 'html')

        Returns:
            Path to generated document
        """
        from document_composer import DocumentComposer

        task = self.store.load(task_id)

        # Get OCR or corrected results
        try:
            result = self._read_json(task_id, "corrected.json")
        except FileNotFoundError:
            result = self._read_json(task_id, "ocr.json")

        composer = DocumentComposer()

        if format == "html":
            content = composer.compose_html(task, result["pages"])
            extension = "html"
        else:
            content = composer.compose_markdown(task, result["pages"])
            extension = "md"

        output_path = self.store.task_dir(task_id) / f"final_document.{extension}"
        output_path.write_text(content, encoding="utf-8")

        return str(output_path)

    def validate_quality(self, task_id: str) -> Dict:
        """Validate OCR quality and completeness.

        Args:
            task_id: Task identifier

        Returns:
            Validation report
        """
        from quality_validator import QualityValidator

        task = self.store.load(task_id)
        ocr_result_path = self.store.task_dir(task_id) / "ocr.json"
        task["ocr_result"] = (
            self._read_json(task_id, "ocr.json")
            if ocr_result_path.exists()
            else {"pages": []}
        )
        validator = QualityValidator(target_accuracy=0.95)

        return validator.validate_task(task)
