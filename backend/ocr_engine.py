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

        blocks = self._sort(blocks, direction)
        for index, block in enumerate(blocks, 1):
            block["reading_order"] = index
        confidence = sum(block["confidence"] for block in blocks) / len(blocks) if blocks else 0.0
        return {
            "text_blocks": blocks,
            "full_text": "\n".join(block["text"] for block in blocks),
            "total_blocks": len(blocks),
            "confidence": confidence,
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


def prepare_crop_for_ocr(image: np.ndarray) -> np.ndarray:
    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image.copy()
    denoised = cv2.fastNlMeansDenoising(gray, None, h=7, templateWindowSize=7, searchWindowSize=21)
    enhanced = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(denoised)
    return cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
