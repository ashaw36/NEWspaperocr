"""Incremental PDF and image rendering for the document workflow."""

from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import cv2
import numpy as np
from PIL import Image

from image_io import read_image, write_image


class PDFProcessor:
    def __init__(self, dpi: int = 180):
        self.dpi = dpi

    def render_document(self, source_path: str | Path, output_dir: str | Path, max_pages: Optional[int] = None) -> List[Dict]:
        source, output = Path(source_path), Path(output_dir)
        output.mkdir(parents=True, exist_ok=True)
        return self._render_pdf(source, output, max_pages) if source.suffix.lower() == ".pdf" else [self._render_image(source, output)]

    def page_count(self, source_path: str | Path) -> int:
        source = Path(source_path)
        if source.suffix.lower() != ".pdf":
            return 1
        import pymupdf
        document = pymupdf.open(source)
        try:
            return document.page_count
        finally:
            document.close()

    def _render_pdf(self, source: Path, output: Path, max_pages: Optional[int]) -> List[Dict]:
        import pymupdf
        document = pymupdf.open(source)
        count = min(document.page_count, max_pages) if max_pages else document.page_count
        scale, pages = self.dpi / 72.0, []
        try:
            for index in range(count):
                pixmap = document.load_page(index).get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
                path = output / f"page_{index + 1:03d}.png"
                pixmap.save(path)
                pages.append({"page_number": index + 1, "path": str(path), "width": pixmap.width, "height": pixmap.height})
        finally:
            document.close()
        return pages

    def _render_image(self, source: Path, output: Path) -> Dict:
        with Image.open(source) as image:
            converted = image.convert("RGB")
            path = output / "page_001.png"
            converted.save(path, "PNG")
            width, height = converted.size
        return {"page_number": 1, "path": str(path), "width": width, "height": height}

    def pdf_to_images(self, pdf_path: str, max_pages: Optional[int] = None):
        import tempfile
        with tempfile.TemporaryDirectory(prefix="newspaper-pages-") as temp:
            pages = self.render_document(pdf_path, temp, max_pages=max_pages)
            return [(page["page_number"], read_image(page["path"])) for page in pages]

    def preprocess_image(self, image: np.ndarray) -> np.ndarray:
        from ocr_engine import prepare_crop_for_ocr
        return prepare_crop_for_ocr(image)

    def process_pdf_for_ocr(self, pdf_path: str, output_dir: str | None = None, preprocess: bool = True, max_pages: Optional[int] = None):
        images = self.pdf_to_images(pdf_path, max_pages=max_pages)
        processed = [(number, self.preprocess_image(image) if preprocess else image) for number, image in images]
        result = {"original_images": images, "processed_images": processed}
        if output_dir:
            target = Path(output_dir)
            target.mkdir(parents=True, exist_ok=True)
            paths = []
            for number, image in processed:
                path = target / f"page_{number:03d}.png"
                write_image(path, image)
                paths.append(str(path))
            result["saved_paths"] = paths
        return result
