"""Classical layout proposals that remain fully editable by the user."""

from __future__ import annotations

import uuid
from typing import Dict, List, Sequence, Tuple

import cv2
import numpy as np

Box = Tuple[int, int, int, int]


class LayoutEngine:
    LABELS = (
        "masthead",
        "title",
        "subtitle",
        "body",
        "caption",
        "metadata",
        "advertisement",
        "ignore",
    )
    DIRECTIONS = ("vertical-rtl", "horizontal-ltr")

    def propose(self, image: np.ndarray, page_number: int) -> Dict:
        if image is None or image.size == 0:
            raise ValueError("Empty page image")

        height, width = image.shape[:2]
        gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
        # Newspaper line art and dense text react differently to a single
        # threshold. Build connected regions from a lightly cleaned, locally
        # normalized image and use the original resolution for final boxes.
        normalized = cv2.createCLAHE(clipLimit=1.4, tileGridSize=(12, 12)).apply(gray)
        blurred = cv2.GaussianBlur(normalized, (3, 3), 0)
        _, ink = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
        ink = cv2.morphologyEx(ink, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))

        content = self._content_box(ink)
        grid_boxes = self._grid_cells(ink, width, height)
        if len(grid_boxes) >= 2:
            boxes = grid_boxes
            layout_type = "grid"
            direction = "vertical-rtl"
        else:
            vertical_boxes = self._column_boxes(ink, width, height)
            if len(vertical_boxes) >= 3:
                boxes = self._group_columns(vertical_boxes, width, height)
                layout_type = "vertical-columns"
                direction = "vertical-rtl"
            else:
                boxes = self._row_boxes(ink, width, height)
                layout_type = "horizontal-rows" if len(boxes) > 1 else "single-region"
                direction = "horizontal-ltr"

        if not boxes:
            boxes = [content]

        boxes = self._deduplicate(boxes, width, height)
        if direction == "vertical-rtl" and layout_type != "grid":
            boxes = self._split_oversized_vertical_regions(boxes, ink, width, height)
        regions = [
            self._region(box, width, height, direction, layout_type, ink, page_number)
            for box in boxes
        ]
        regions = self.sort_regions(regions, direction, layout_type)
        for order, region in enumerate(regions, 1):
            region["order"] = order

        # Structural labels and article grouping are intentionally conservative:
        # geometry cannot reliably infer semantic article boundaries.
        if layout_type == "vertical-columns":
            self._label_vertical_regions(regions, width, height)

        return {
            "layout_type": layout_type,
            "reading_direction": direction,
            "source": "computer-vision",
            "regions": regions,
        }

    def normalize_regions(self, regions: Sequence[Dict]) -> List[Dict]:
        normalized = []
        for index, item in enumerate(regions, 1):
            bbox = item.get("bbox", {})
            x = min(max(float(bbox.get("x", 0)), 0.0), 1.0)
            y = min(max(float(bbox.get("y", 0)), 0.0), 1.0)
            w = min(max(float(bbox.get("width", 0)), 0.002), 1.0 - x)
            h = min(max(float(bbox.get("height", 0)), 0.002), 1.0 - y)
            label = item.get("label", "body")
            direction = item.get("direction", "vertical-rtl")
            normalized.append(
                {
                    "id": str(item.get("id") or uuid.uuid4().hex[:12]),
                    "order": int(item.get("order", index)),
                    "label": label if label in self.LABELS else "body",
                    "article_id": str(item.get("article_id", "article-1"))[:80],
                    "direction": (
                        direction if direction in self.DIRECTIONS else "vertical-rtl"
                    ),
                    "bbox": {"x": x, "y": y, "width": w, "height": h},
                    "source": item.get("source", "user"),
                    "confidence": round(float(item.get("confidence", 1.0)), 4),
                    "notes": str(item.get("notes", ""))[:500],
                }
            )
        return sorted(normalized, key=lambda region: region["order"])

    def sort_regions(
        self, regions: List[Dict], direction: str, layout_type: str
    ) -> List[Dict]:
        if layout_type == "grid":
            return sorted(
                regions, key=lambda r: (round(r["bbox"]["y"], 2), -r["bbox"]["x"])
            )
        if direction == "vertical-rtl":
            return sorted(regions, key=lambda r: (-r["bbox"]["x"], r["bbox"]["y"]))
        return sorted(regions, key=lambda r: (r["bbox"]["y"], r["bbox"]["x"]))

    def _content_box(self, ink: np.ndarray) -> Box:
        points = cv2.findNonZero(ink)
        if points is None:
            return (0, 0, ink.shape[1], ink.shape[0])
        x, y, w, h = cv2.boundingRect(points)
        pad = max(4, int(min(ink.shape) * 0.008))
        return (
            max(0, x - pad),
            max(0, y - pad),
            min(ink.shape[1] - x + pad, w + pad * 2),
            min(ink.shape[0] - y + pad, h + pad * 2),
        )

    def _column_boxes(self, ink: np.ndarray, width: int, height: int) -> List[Box]:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(2, width // 450), max(15, height // 42))
        )
        joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
        joined = cv2.dilate(joined, np.ones((3, 3), np.uint8), iterations=1)
        contours, _ = cv2.findContours(
            joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if h < height * 0.055 or w < max(5, width * 0.004):
                continue
            if w * h < width * height * 0.0008 or w > width * 0.45:
                continue
            if h / max(w, 1) < 1.25 and h < height * 0.18:
                continue
            boxes.append(self._pad((x, y, w, h), width, height))
        return boxes

    def _row_boxes(self, ink: np.ndarray, width: int, height: int) -> List[Box]:
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (max(15, width // 35), max(2, height // 600))
        )
        joined = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, kernel)
        contours, _ = cv2.findContours(
            joined, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        boxes = []
        for contour in contours:
            x, y, w, h = cv2.boundingRect(contour)
            if w < width * 0.08 or h < max(6, height * 0.006):
                continue
            if w * h < width * height * 0.001:
                continue
            boxes.append(self._pad((x, y, w, h), width, height))
        return boxes

    def _group_columns(
        self, boxes: Sequence[Box], width: int, height: int
    ) -> List[Box]:
        """Combine narrow neighboring columns into OCR windows with enough visual context."""
        wide = [box for box in boxes if box[2] >= width * 0.16]
        narrow = [box for box in boxes if box[2] < width * 0.16]
        partitions = [
            sorted(
                (box for box in narrow if box[3] >= height * 0.25),
                key=lambda box: -box[0],
            ),
            sorted(
                (box for box in narrow if box[3] < height * 0.25),
                key=lambda box: -box[0],
            ),
        ]
        groups: List[List[Box]] = []
        for partition in partitions:
            partition_groups: List[List[Box]] = []
            for box in partition:
                if not partition_groups:
                    partition_groups.append([box])
                    continue
                current = partition_groups[-1]
                gx1 = min(item[0] for item in current)
                gx2 = max(item[0] + item[2] for item in current)
                gy1 = min(item[1] for item in current)
                gy2 = max(item[1] + item[3] for item in current)
                x, y, w, h = box
                overlap = max(0, min(gy2, y + h) - max(gy1, y)) / max(
                    1, min(gy2 - gy1, h)
                )
                gap = max(0, gx1 - (x + w))
                combined_width = gx2 - min(gx1, x)
                if (
                    overlap >= 0.68
                    and gap <= width * 0.012
                    and combined_width <= width * 0.18
                    and len(current) < 3
                ):
                    current.append(box)
                else:
                    partition_groups.append([box])
            groups.extend(partition_groups)

        merged = []
        for group in groups:
            x1 = min(box[0] for box in group)
            y1 = min(box[1] for box in group)
            x2 = max(box[0] + box[2] for box in group)
            y2 = max(box[1] + box[3] for box in group)
            merged.append(self._pad((x1, y1, x2 - x1, y2 - y1), width, height))
        return wide + merged

    def _split_oversized_vertical_regions(
        self, boxes: Sequence[Box], ink: np.ndarray, width: int, height: int
    ) -> List[Box]:
        """Split merged vertical regions at strong whitespace gutters."""
        result: List[Box] = []
        for x, y, w, h in boxes:
            if w < width * 0.19:
                result.append((x, y, w, h))
                continue
            projection = np.count_nonzero(ink[y : y + h, x : x + w], axis=0)
            smooth = cv2.GaussianBlur(
                projection.astype(np.float32).reshape(1, -1), (1, 0), 0
            ).ravel()
            baseline = max(1.0, float(np.percentile(smooth, 55)))
            valleys = np.flatnonzero(smooth < baseline * 0.18)
            cuts = []
            if valleys.size:
                groups = np.split(
                    valleys,
                    np.where(np.diff(valleys) > max(2, int(width * 0.004)))[0] + 1,
                )
                for group in groups:
                    if group.size >= max(3, int(width * 0.006)):
                        center = int((group[0] + group[-1]) / 2)
                        if w * 0.18 < center < w * 0.82:
                            cuts.append(center)
            boundaries = [0] + cuts + [w]
            pieces = [
                (x + left, y, right - left, h)
                for left, right in zip(boundaries, boundaries[1:])
                if right - left >= width * 0.045
            ]
            if len(pieces) > 1:
                result.extend(self._pad(piece, width, height) for piece in pieces)
            else:
                result.append((x, y, w, h))
        return self._deduplicate(result, width, height)

    def _label_vertical_regions(
        self, regions: List[Dict], width: int, height: int
    ) -> None:
        ordered = sorted(regions, key=lambda region: -region["bbox"]["x"])
        for index, region in enumerate(ordered, 1):
            box = region["bbox"]
            x, y, w, h = box["x"], box["y"], box["width"], box["height"]
            if x > 0.57 and w > 0.15 and y < 0.12 and h > 0.36:
                region["label"] = "masthead"
            elif w > 0.1 and h < 0.35 and (y > 0.58 or w > 0.18):
                region["label"] = "title"
            elif y > 0.86 and h < 0.14:
                region["label"] = "metadata"
            else:
                region["label"] = "body"
            region["article_id"] = (
                f"page-{region.get('page_number', 'x')}-article-{index}"
            )
            region["notes"] = "自动布局建议；请确认跨栏标题和文章分组"

    def _grid_cells(self, ink: np.ndarray, width: int, height: int) -> List[Box]:
        horizontal = cv2.morphologyEx(
            ink,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (max(40, width // 5), 2)),
        )
        vertical = cv2.morphologyEx(
            ink,
            cv2.MORPH_OPEN,
            cv2.getStructuringElement(cv2.MORPH_RECT, (2, max(40, height // 8))),
        )
        horizontal_contours, _ = cv2.findContours(
            horizontal, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        long_horizontal = [
            cv2.boundingRect(contour)
            for contour in horizontal_contours
            if cv2.boundingRect(contour)[2] > width * 0.55
        ]
        y_lines = self._cluster_positions(
            [y + h / 2 for _x, y, _w, h in long_horizontal],
            tolerance=max(5, height * 0.008),
        )
        if len(y_lines) < 3:
            return []

        left = int(min(x for x, _y, _w, _h in long_horizontal))
        right = int(max(x + w for x, _y, w, _h in long_horizontal))
        vertical_contours, _ = cv2.findContours(
            vertical, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )
        vertical_segments = [cv2.boundingRect(contour) for contour in vertical_contours]
        cells = []
        for top_value, bottom_value in zip(y_lines, y_lines[1:]):
            top, bottom = int(top_value), int(bottom_value)
            band_height = bottom - top
            if band_height < height * 0.10:
                continue
            separators = [left, right]
            for x, y, w, h in vertical_segments:
                overlap = max(0, min(y + h, bottom) - max(y, top))
                if overlap >= band_height * 0.35:
                    separators.append(x + w / 2)
            x_lines = self._cluster_positions(
                separators, tolerance=max(5, width * 0.008)
            )
            for left_value, right_value in zip(x_lines, x_lines[1:]):
                cell_left, cell_right = int(left_value), int(right_value)
                if cell_right - cell_left < width * 0.14:
                    continue
                inset = max(3, int(min(width, height) * 0.004))
                cells.append(
                    (
                        cell_left + inset,
                        top + inset,
                        cell_right - cell_left - inset * 2,
                        band_height - inset * 2,
                    )
                )
        return self._deduplicate(cells, width, height)

    def _cluster_positions(
        self, values: Sequence[float], tolerance: float
    ) -> List[float]:
        clusters: List[List[float]] = []
        for value in sorted(values):
            if not clusters or value - clusters[-1][-1] > tolerance:
                clusters.append([value])
            else:
                clusters[-1].append(value)
        return [sum(cluster) / len(cluster) for cluster in clusters]

    def _region(
        self,
        box: Box,
        width: int,
        height: int,
        direction: str,
        layout_type: str,
        ink: np.ndarray,
        page: int,
    ) -> Dict:
        x, y, w, h = box
        roi = ink[y : y + h, x : x + w]
        components = (
            cv2.connectedComponentsWithStats(roi, 8)[2]
            if roi.size
            else np.empty((0, 5))
        )
        component_heights = (
            components[1:, cv2.CC_STAT_HEIGHT] if len(components) > 1 else np.array([0])
        )
        font_scale = float(np.percentile(component_heights, 75) / max(height, 1))
        if layout_type == "grid":
            label = "advertisement"
        elif (
            x > width * 0.58
            and w > width * 0.07
            and h > height * 0.25
            and (font_scale > 0.04 or w > width * 0.2)
        ):
            label = "masthead"
        elif font_scale > 0.09 or (w > width * 0.16 and h < height * 0.35):
            label = "title"
        elif y > height * 0.86 and h < height * 0.14:
            label = "metadata"
        else:
            label = "body"
        return {
            "id": uuid.uuid4().hex[:12],
            "order": 0,
            "label": label,
            "article_id": f"page-{page}-article-1",
            "direction": direction,
            "bbox": {
                "x": x / width,
                "y": y / height,
                "width": w / width,
                "height": h / height,
            },
            "source": "computer-vision",
            "confidence": 0.72 if layout_type != "single-region" else 0.45,
            "notes": "",
        }

    def _pad(self, box: Box, width: int, height: int, pad: int | None = None) -> Box:
        x, y, w, h = box
        pad = pad if pad is not None else max(4, int(min(width, height) * 0.006))
        left, top = max(0, x - pad), max(0, y - pad)
        right, bottom = min(width, x + w + pad), min(height, y + h + pad)
        return left, top, right - left, bottom - top

    def _deduplicate(self, boxes: Sequence[Box], width: int, height: int) -> List[Box]:
        ordered = sorted(boxes, key=lambda b: b[2] * b[3], reverse=True)
        kept: List[Box] = []
        for box in ordered:
            x, y, w, h = box
            if w <= 0 or h <= 0:
                continue
            duplicate = False
            for other in kept:
                ox, oy, ow, oh = other
                ix = max(0, min(x + w, ox + ow) - max(x, ox))
                iy = max(0, min(y + h, oy + oh) - max(y, oy))
                overlap = ix * iy / min(w * h, ow * oh)
                if overlap > 0.84:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(
                    (max(0, x), max(0, y), min(w, width - x), min(h, height - y))
                )
        return kept
