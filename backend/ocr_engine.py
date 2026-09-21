"""OCR backend adapter with explicit failures and deterministic reading order."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import cv2
import numpy as np


class OCRUnavailableError(RuntimeError):
    pass


class OCRExecutionError(RuntimeError):
    pass


class OCREngine:
    def __init__(self, use_gpu: bool = False):
        self.use_gpu = use_gpu
        self.backend = "unavailable"
        self.engine_ready = False
        self.ocr = None
        self.load_error = None
        try:
            from rapidocr_onnxruntime import RapidOCR
            self.ocr = RapidOCR()
            self.backend = "rapidocr"
            self.engine_ready = True
        except Exception as rapid_error:
            try:
                from paddleocr import PaddleOCR
                self.ocr = PaddleOCR(use_angle_cls=True, lang="ch", use_gpu=use_gpu, show_log=False)
                self.backend = "paddleocr"
                self.engine_ready = True
            except Exception as paddle_error:
                self.load_error = f"RapidOCR: {rapid_error}; PaddleOCR: {paddle_error}"

    def health(self) -> Dict:
        return {"backend": self.backend, "ready": self.engine_ready, "gpu_requested": self.use_gpu, "error": self.load_error}

    def recognize(self, image: np.ndarray | str | Path, direction: str = "horizontal-ltr") -> Dict:
        if not self.engine_ready:
            raise OCRUnavailableError(self.load_error or "No OCR backend is installed")
        source = str(image) if isinstance(image, (str, Path)) else image
        try:
            if self.backend == "rapidocr":
                raw, _ = self.ocr(source)
                blocks = self._rapid_blocks(raw or [])
            else:
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
