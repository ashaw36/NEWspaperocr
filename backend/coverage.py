"""版面覆盖清单与区域索引（P01-B01-C01-L01）。

用于「原图→誊录稿」完整性核对：漏区域/漏行标 warning，不静默跳过。
"""

from __future__ import annotations

import re
from typing import Dict, Iterable, List, Sequence


def page_code(page_number: int) -> str:
    return f"P{int(page_number):02d}"


def build_region_index(
    page_number: int,
    regions: Sequence[Dict],
    *,
    line_split: bool = True,
) -> List[Dict]:
    """为每页区域生成层级索引。

    - P01-B01：文字区块（按 region.order）
    - P01-B01-C01：若同一 article 多栏，按栏序；单栏区域亦给 C01
    - P01-B01-C01-L01：栏内按换行切分的行（可选）
    """
    index: List[Dict] = []
    page = page_code(page_number)
    ordered = sorted(
        enumerate(regions, 1),
        key=lambda item: (int(item[1].get("order") or item[0]), item[0]),
    )

    # article_id → 栏序号（同一文章下按 order 递增）
    article_column_seq: Dict[str, int] = {}

    for fallback_order, region in ordered:
        block_n = int(region.get("order") or fallback_order)
        block_id = f"{page}-B{block_n:02d}"
        article_id = str(
            region.get("article_id") or region.get("region_id") or block_id
        )
        article_column_seq[article_id] = article_column_seq.get(article_id, 0) + 1
        col_n = article_column_seq[article_id]
        column_id = f"{block_id}-C{col_n:02d}"

        text = str(
            region.get("raw_text")
            or region.get("final_region_text")
            or region.get("text")
            or ""
        )
        lines = _split_lines(text) if line_split else ([text] if text.strip() else [])

        entry = {
            "index_id": block_id,
            "column_id": column_id,
            "page_number": int(page_number),
            "region_id": str(region.get("region_id") or region.get("id") or block_id),
            "article_id": article_id,
            "label": region.get("label") or "body",
            "order": block_n,
            "status": "pending",
            "char_count": len(re.sub(r"\s+", "", text)),
            "line_count": len(lines),
            "lines": [],
        }
        for line_i, line in enumerate(lines, 1):
            line_id = f"{column_id}-L{line_i:02d}"
            entry["lines"].append(
                {
                    "index_id": line_id,
                    "text_preview": line[:40],
                    "char_count": len(re.sub(r"\s+", "", line)),
                    "status": "pending",
                }
            )
        index.append(entry)
    return index


def mark_transcribed(
    index: List[Dict],
    transcribed_region_ids: Iterable[str] | None = None,
    *,
    require_nonempty: bool = True,
) -> List[Dict]:
    """根据已誊录 region_id 更新状态：completed / empty / missing。"""
    done = {str(rid) for rid in (transcribed_region_ids or [])}
    # 若未显式传入，则按 index 内 char_count 推断
    for entry in index:
        rid = entry["region_id"]
        has_text = int(entry.get("char_count") or 0) > 0
        if require_nonempty and not has_text:
            entry["status"] = "empty"
            for line in entry.get("lines") or []:
                line["status"] = "empty"
            continue
        if done and rid in done:
            entry["status"] = "completed"
        elif has_text:
            entry["status"] = "completed" if not done else "missing"
        else:
            entry["status"] = "empty"
        for line in entry.get("lines") or []:
            if entry["status"] == "completed" and int(line.get("char_count") or 0) > 0:
                line["status"] = "completed"
            elif entry["status"] == "empty":
                line["status"] = "empty"
            else:
                line["status"] = entry["status"]
    return index


def check_coverage(index: Sequence[Dict]) -> Dict:
    """原图→誊录稿覆盖核对。漏区域/漏行进入 warnings，不静默跳过。"""
    total = len(index)
    completed = sum(1 for e in index if e.get("status") == "completed")
    empty = sum(1 for e in index if e.get("status") == "empty")
    missing = [e for e in index if e.get("status") == "missing"]
    pending = [e for e in index if e.get("status") == "pending"]

    warnings: List[str] = []
    for entry in missing:
        warnings.append(
            f"覆盖缺失：区域 {entry.get('index_id')} (region_id={entry.get('region_id')}) "
            f"label={entry.get('label')} 未进入誊录稿"
        )
    for entry in pending:
        warnings.append(
            f"覆盖未核：区域 {entry.get('index_id')} (region_id={entry.get('region_id')}) "
            f"仍为 pending，不得视为已完成"
        )

    missing_lines = []
    for entry in index:
        for line in entry.get("lines") or []:
            if (
                line.get("status") in {"missing", "pending"}
                and entry.get("status") == "completed"
            ):
                # 区块已完成但行仍 pending：标出来
                missing_lines.append(line.get("index_id"))
            elif line.get("status") == "missing":
                missing_lines.append(line.get("index_id"))
                warnings.append(f"覆盖缺失：行 {line.get('index_id')}")

    return {
        "total_regions": total,
        "completed_regions": completed,
        "empty_regions": empty,
        "missing_regions": len(missing),
        "pending_regions": len(pending),
        "missing_lines": missing_lines,
        "coverage_ratio": (completed / total) if total else 1.0,
        "warnings": warnings,
        "ok": not missing and not pending,
    }


def _split_lines(text: str) -> List[str]:
    if not text or not str(text).strip():
        return []
    parts = re.split(r"\r\n|\n|\r", str(text))
    return [p for p in parts if p.strip()]
