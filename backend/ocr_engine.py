"""OCR backend adapter with explicit failures and deterministic reading order."""

from __future__ import annotations

import inspect
import json
import os
import threading
from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np


class OCRUnavailableError(RuntimeError):
    pass


class OCRExecutionError(RuntimeError):
    pass


class OCREngine:
    def __init__(self, use_gpu: bool = False, backend: str = "auto", paddle_version: str | None = None):
        self.use_gpu = use_gpu
        self.requested_backend = backend.strip().lower()
        self.paddle_version = paddle_version or os.getenv("OCR_PADDLE_VERSION", "PP-OCRv5")
        self._paddle_lock = threading.Lock()
        self.backend = "unavailable"
        self.engine_ready = False
        self.ocr = None
        self.load_error = None
        if self.requested_backend not in {"auto", "paddleocr", "rapidocr"}:
            self.load_error = f"Unsupported OCR backend: {backend}"
            return

        candidates = ("paddleocr", "rapidocr") if self.requested_backend == "auto" else (self.requested_backend,)
        errors = []
        for candidate in candidates:
            try:
                if candidate == "paddleocr":
                    self._load_paddle()
                else:
                    self._load_rapid()
                self.backend = candidate
                self.engine_ready = True
                break
            except Exception as error:
                errors.append(f"{candidate}: {error}")

        if not self.engine_ready:
            self.load_error = "; ".join(errors)

    def _load_paddle(self) -> None:
        from paddleocr import PaddleOCR

        parameters = inspect.signature(PaddleOCR).parameters
        if "ocr_version" in parameters:
            self.ocr = PaddleOCR(
                lang="ch",
                ocr_version=self.paddle_version,
                device="gpu:0" if self.use_gpu else "cpu",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
        else:
            self.ocr = PaddleOCR(
                use_angle_cls=True,
                lang="ch",
                use_gpu=self.use_gpu,
                show_log=False,
            )

    def _load_rapid(self) -> None:
        from rapidocr_onnxruntime import RapidOCR

        self.ocr = RapidOCR()

    def health(self) -> Dict:
        return {
            "backend": self.backend,
            "requested_backend": self.requested_backend,
            "ready": self.engine_ready,
            "gpu_requested": self.use_gpu,
            "model_version": self.paddle_version if self.backend == "paddleocr" else None,
            "error": self.load_error,
        }

    def recognize(self, image: np.ndarray | str | Path, direction: str = "horizontal-ltr") -> Dict:
        if not self.engine_ready:
            raise OCRUnavailableError(self.load_error or "No OCR backend is installed")
        source = str(image) if isinstance(image, (str, Path)) else image
        try:
            if self.backend == "rapidocr":
                raw, _ = self.ocr(source)
                blocks = self._rapid_blocks(raw or [])
            elif callable(getattr(self.ocr, "predict", None)):
                with self._paddle_lock:
                    raw = self.ocr.predict(source)
                blocks = self._paddle_v3_blocks(raw)
            else:
                with self._paddle_lock:
                    raw = self.ocr.ocr(source, cls=True)
                blocks = self._paddle_blocks(raw[0] if raw and raw[0] else [])
        except Exception as error:
            raise OCRExecutionError(str(error)) from error

        # Vertical crops are rotated by prepare_crop_for_ocr before reaching
        # the engine, so their OCR blocks are now horizontally ordered.
        blocks = self._sort(blocks, "horizontal-ltr" if direction == "vertical-rtl" else direction)
        for index, block in enumerate(blocks, 1):
            block["reading_order"] = index
        confidence = sum(block["confidence"] for block in blocks) / len(blocks) if blocks else 0.0
        full_text = "\n".join(block["text"] for block in blocks)
        return {
            "text_blocks": blocks,
            "full_text": full_text,
            "total_blocks": len(blocks),
            "confidence": confidence,
            "quality": assess_quality(full_text, confidence, len(blocks)),
            "engine": self.backend,
        }

    def recognize_text(self, image_path: str) -> Dict:
        return self.recognize(image_path)

    def _rapid_blocks(self, raw: List) -> List[Dict]:
        blocks = []
        for index, item in enumerate(raw, 1):
            if not item or len(item) < 3:
                continue
            bbox, text, score = item[:3]
            blocks.append({"block_id": index, "text": str(text), "confidence": float(score), "bbox": [[float(p[0]), float(p[1])] for p in bbox]})
        return blocks

    def _paddle_blocks(self, raw: List) -> List[Dict]:
        blocks = []
        for index, item in enumerate(raw, 1):
            bbox, result = item
            blocks.append({"block_id": index, "text": str(result[0]), "confidence": float(result[1]), "bbox": [[float(p[0]), float(p[1])] for p in bbox]})
        return blocks

    def _paddle_v3_blocks(self, raw: List) -> List[Dict]:
        if isinstance(raw, (dict, str)) or hasattr(raw, "json"):
            raw = [raw]

        blocks = []
        for item in raw or []:
            payload = getattr(item, "json", item)
            if callable(payload):
                payload = payload()
            if isinstance(payload, str):
                payload = json.loads(payload)
            if not isinstance(payload, dict):
                continue

            payload = payload.get("res", payload)
            texts = payload.get("rec_texts")
            scores = payload.get("rec_scores")
            texts = [] if texts is None else texts
            scores = [] if scores is None else scores
            polygons = payload.get("rec_polys")
            if polygons is None:
                polygons = payload.get("dt_polys")
            if polygons is None:
                polygons = payload.get("rec_boxes")
            if polygons is None:
                continue

            for index, text in enumerate(texts):
                if index >= len(polygons) or not str(text).strip():
                    continue
                points = np.asarray(polygons[index], dtype=np.float32)
                if points.ndim == 1 and points.size == 4:
                    left, top, right, bottom = points.tolist()
                    points = np.asarray(
                        [[left, top], [right, top], [right, bottom], [left, bottom]],
                        dtype=np.float32,
                    )
                if points.ndim != 2 or points.shape[1] < 2:
                    continue
                confidence = float(scores[index]) if index < len(scores) else 0.0
                blocks.append({
                    "block_id": len(blocks) + 1,
                    "text": str(text),
                    "confidence": confidence,
                    "bbox": [[float(point[0]), float(point[1])] for point in points],
                })
        return blocks

    def _sort(self, blocks: List[Dict], direction: str) -> List[Dict]:
        def center(block: Dict):
            points = block["bbox"]
            return sum(p[0] for p in points) / len(points), sum(p[1] for p in points) / len(points)
        if direction == "vertical-rtl":
            return sorted(blocks, key=lambda block: (-center(block)[0], center(block)[1]))
        return sorted(blocks, key=lambda block: (center(block)[1], center(block)[0]))


def prepare_crop_for_ocr(image: np.ndarray, direction: str = "horizontal-ltr") -> np.ndarray:
    # OCR engines are much more reliable on horizontal lines than on narrow
    # traditional vertical columns. Rotate only the vertical crop; the region
    # metadata still preserves the original historical reading direction.
    if direction == "vertical-rtl":
        image = cv2.rotate(image, cv2.ROTATE_90_CLOCKWISE)
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    denoised = cv2.fastNlMeansDenoising(gray, None, h=5, templateWindowSize=7, searchWindowSize=21)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)


def assess_quality(text: str, confidence: float, block_count: int) -> Dict:
    """Return explainable local-OCR quality signals for UI and routing."""
    compact = "".join((text or "").split())
    flags = []
    if not compact:
        flags.append("empty")
    if confidence < 0.5:
        flags.append("low-confidence")
    elif confidence < 0.72:
        flags.append("medium-confidence")
    if compact and len(compact) < 4:
        flags.append("too-short")
    if block_count == 0:
        flags.append("no-text-blocks")
    repeated = sum(1 for left, right in zip(compact, compact[1:]) if left == right)
    if len(compact) >= 8 and repeated / max(1, len(compact) - 1) > 0.35:
        flags.append("repeated-characters")
    if "empty" in flags or "no-text-blocks" in flags or "low-confidence" in flags:
        status = "needs_review"
    elif flags:
        status = "check"
    else:
        status = "pass"
    return {"status": status, "score": round(float(confidence), 4), "flags": flags}
