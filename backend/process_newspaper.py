#!/usr/bin/env python
"""Command-line entry point for the same workflow used by the web application."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from ai_service import AIService
from ocr_engine import OCREngine
from task_store import TaskStore
from workflow import DocumentWorkflow


def main():
    parser = argparse.ArgumentParser(description="Historical newspaper OCR workflow")
    parser.add_argument("source", help="PDF or image path")
    parser.add_argument(
        "-o", "--output", default="results_cli", help="Task output root"
    )
    parser.add_argument("-p", "--pages", type=int, help="Maximum number of pages")
    parser.add_argument(
        "--dpi", type=int, default=180, choices=range(100, 301), metavar="100-300"
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Request GPU when the selected OCR backend supports it",
    )
    parser.add_argument(
        "--ocr-backend",
        choices=("auto", "paddleocr", "rapidocr"),
        default=os.getenv("OCR_BACKEND", "auto"),
    )
    parser.add_argument(
        "--paddle-version",
        choices=("PP-OCRv5", "PP-OCRv6"),
        default=os.getenv("OCR_PADDLE_VERSION", "PP-OCRv5"),
    )
    parser.add_argument(
        "--ai-layout",
        action="store_true",
        help="Use a configured vision model to review layout proposals",
    )
    parser.add_argument(
        "--ai-correct", action="store_true", help="Run semantic correction after OCR"
    )
    args = parser.parse_args()

    source = Path(args.source).resolve()
    if not source.exists():
        parser.error(f"Source file does not exist: {source}")

    store = TaskStore(Path(args.output).resolve())
    ocr = OCREngine(
        use_gpu=args.gpu, backend=args.ocr_backend, paddle_version=args.paddle_version
    )
    ai = AIService()
    if not ocr.engine_ready:
        parser.error(ocr.load_error or "OCR backend is unavailable")
    if (args.ai_layout or args.ai_correct) and not ai.available:
        parser.error(
            "AI was requested but DEEPSEEK_API_KEY, ANTHROPIC_API_KEY or OPENAI_API_KEY is not configured"
        )

    task = store.create(
        source.name,
        {"dpi": args.dpi, "max_pages": args.pages, "ai_layout": args.ai_layout},
    )
    task["source_path"] = str(source)
    store.save(task)
    workflow = DocumentWorkflow(store, ocr, ai)

    print(f"Task: {task['id']}")
    print("1/3 Analyzing layout...")
    workflow.analyze_layout(task["id"])
    current = store.load(task["id"])
    if current["status"] == "failed":
        raise RuntimeError(current["error"]["message"])

    print("2/3 Running OCR with the proposed layout...")
    workflow.queue_ocr(task["id"])
    workflow.run_ocr(task["id"])
    current = store.load(task["id"])
    if current["status"] == "failed":
        raise RuntimeError(current["error"]["message"])

    if args.ai_correct:
        print("3/3 Running AI correction...")
        workflow.queue_correction(task["id"])
        workflow.run_correction(task["id"])
    else:
        print("3/3 AI correction skipped")

    current = store.load(task["id"])
    print(
        json.dumps(
            {
                "task_id": task["id"],
                "status": current["status"],
                "output": str(store.task_dir(task["id"])),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
