"""Lightweight column segmentation for whole-page OCR reading-order hints.

Does NOT replace layout_engine.propose(). Column bands are advisory only;
article boundaries and true reading order are decided by AI aggregation.

Reading-order conventions (also referenced in AI prompts):
- vertical-rtl columns: original-image right → left (x descending)
- within a column: original-image top → bottom
  (in 90°-CW rotated space that is x descending)
"""

from __future__ import annotations

from typing import Dict, List

import cv2
import numpy as np


def segment_columns(
    image: np.ndarray,
    blocks: List[Dict] | None = None,
    direction: str = "vertical-rtl",
) -> List[Dict]:
    """Find column bands via projection profile and assign column_index to blocks.

    Args:
        image: Original (unrotated) page image BGR/gray.
        blocks: OCR blocks with bbox in original-image coordinates. Mutated
            in place to add ``column_index``.
        direction: ``vertical-rtl`` or ``horizontal-ltr``.

    Returns:
        List of column band dicts:
        ``{column_index, y_range (rotated space), x_center (original)}``.
    """
    if image is None or image.size == 0:
        return []

    gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY) if image.ndim == 3 else image
    blocks = blocks if blocks is not None else []

    if direction == "vertical-rtl":
        columns = _segment_vertical_columns(gray)
        _assign_vertical_column_indices(blocks, columns)
    else:
        columns = _segment_horizontal_rows(gray, image.shape[1])
        _assign_horizontal_row_indices(blocks, columns)

    return columns


def _binarize_ink(gray: np.ndarray) -> np.ndarray:
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    _, ink = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    return ink


def _segment_vertical_columns(gray: np.ndarray) -> List[Dict]:
    """Rotate 90°CW then horizontal projection; each band ≈ one vertical column."""
    ink = _binarize_ink(gray)
    rotated = cv2.rotate(ink, cv2.ROTATE_90_CLOCKWISE)
    # projection[i] = ink density of row i in rotated space (= original column strip)
    projection = rotated.sum(axis=1).astype(np.float64)
    bands = _bands_from_projection(projection)

    columns: List[Dict] = []
    for y0, y1 in bands:
        # Rotated y maps to original x: x = yr (plan: (xr,yr)→(yr, H-xr))
        x_center = (y0 + y1) / 2.0
        columns.append(
            {
                "column_index": 0,  # filled after sort
                "y_range": [int(y0), int(y1)],
                "x_center": float(x_center),
            }
        )

    # 列阅读顺序：原图右 → 左（x 降序）
    columns.sort(key=lambda col: -col["x_center"])
    for index, col in enumerate(columns):
        col["column_index"] = index
    return columns


def _segment_horizontal_rows(gray: np.ndarray, orig_w: int) -> List[Dict]:
    """Horizontal-ltr: vertical projection gaps separate text rows."""
    ink = _binarize_ink(gray)
    projection = ink.sum(axis=1).astype(np.float64)
    bands = _bands_from_projection(projection)

    columns: List[Dict] = []
    for index, (y0, y1) in enumerate(bands):
        columns.append(
            {
                "column_index": index,
                "y_range": [int(y0), int(y1)],
                "x_center": float(orig_w) / 2.0,
            }
        )
    return columns


def _bands_from_projection(projection: np.ndarray) -> List[tuple[int, int]]:
    if projection.size == 0:
        return []
    threshold = max(1.0, float(np.percentile(projection, 50)) * 0.15)
    ink_rows = projection >= threshold
    bands: List[tuple[int, int]] = []
    start = None
    for index, active in enumerate(ink_rows.tolist()):
        if active and start is None:
            start = index
        elif not active and start is not None:
            if index - start >= 2:
                bands.append((start, index))
            start = None
    if start is not None and len(projection) - start >= 2:
        bands.append((start, len(projection)))
    if not bands:
        bands = [(0, len(projection))]
    return bands


def _assign_vertical_column_indices(
    blocks: List[Dict], columns: List[Dict]
) -> None:
    """Assign column_index by mapping block center into rotated-space y bands."""
    if not blocks:
        return
    if not columns:
        for block in blocks:
            block["column_index"] = 0
        return

    for block in blocks:
        cx, _cy = _bbox_center(block["bbox"])
        # Original (x,y) → rotated (xr, yr) for 90°CW: xr = H - y, yr = x
        rotated_y = cx
        best = columns[0]["column_index"]
        best_dist = float("inf")
        for col in columns:
            y0, y1 = col["y_range"]
            if y0 <= rotated_y < y1:
                best = col["column_index"]
                break
            mid = (y0 + y1) / 2.0
            dist = abs(rotated_y - mid)
            if dist < best_dist:
                best_dist = dist
                best = col["column_index"]
        block["column_index"] = best


def _assign_horizontal_row_indices(
    blocks: List[Dict], columns: List[Dict]
) -> None:
    if not blocks:
        return
    if not columns:
        for block in blocks:
            block["column_index"] = 0
        return

    for block in blocks:
        _, cy = _bbox_center(block["bbox"])
        best = columns[0]["column_index"]
        best_dist = float("inf")
        for col in columns:
            y0, y1 = col["y_range"]
            if y0 <= cy < y1:
                best = col["column_index"]
                break
            mid = (y0 + y1) / 2.0
            dist = abs(cy - mid)
            if dist < best_dist:
                best_dist = dist
                best = col["column_index"]
        block["column_index"] = best


def _bbox_center(bbox: List[List[float]]) -> tuple[float, float]:
    xs = [p[0] for p in bbox]
    ys = [p[1] for p in bbox]
    return sum(xs) / len(xs), sum(ys) / len(ys)
