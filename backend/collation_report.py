"""校勘与完整性报告：誊录稿配套交付物（JSON + 可选 Markdown）。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Sequence

from ai_service import UNCERTAIN_MARK


def build_collation_report(
    *,
    task: Dict | None = None,
    page_number: int,
    coverage: Dict | None = None,
    regions: Sequence[Dict] | None = None,
    aggregated: Dict | None = None,
    agent_audit: Sequence[Dict] | None = None,
    document_meta: Dict | None = None,
) -> Dict:
    """组装客户提示词「第二部分」结构的校勘报告。"""
    coverage = coverage or {}
    regions = list(regions or [])
    aggregated = aggregated or {}
    audit = list(agent_audit or [])
    meta = dict(document_meta or {})
    if task:
        meta.setdefault("filename", task.get("filename") or task.get("name"))
        meta.setdefault("task_id", task.get("id"))

    corrected = str(aggregated.get("corrected_text") or "")
    uncertain_items = _collect_uncertain(corrected, regions, aggregated)
    structure_pending = _collect_structure_pending(aggregated, coverage)
    coverage_check = coverage.get("check") or check_from_coverage_regions(
        coverage.get("regions") or []
    )

    report = {
        "schema": "collation-report-v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "document": {
            "title": meta.get("title") or meta.get("filename") or "〔待辨〕",
            "date": meta.get("date") or "〔待辨〕",
            "edition": meta.get("edition") or "〔待辨〕",
            "page_number": page_number,
            "page_count": meta.get("page_count"),
            "task_id": meta.get("task_id"),
            "filename": meta.get("filename"),
            "notes": "无法确认的项目已标〔待辨〕",
        },
        "layout_regions": coverage.get("regions")
        or [
            {
                "index_id": f"P{page_number:02d}-B{i:02d}",
                "region_id": r.get("region_id"),
                "article_id": r.get("article_id"),
                "label": r.get("label"),
                "status": (
                    "completed" if str(r.get("raw_text") or "").strip() else "empty"
                ),
            }
            for i, r in enumerate(regions, 1)
        ],
        "uncertain_glyphs": uncertain_items,
        "structure_pending": structure_pending,
        "coverage_check": coverage_check,
        "agent_audit": audit,
        "collation_notes": _collation_notes(
            aggregated, coverage_check, uncertain_items, structure_pending, audit
        ),
        "warnings": list(aggregated.get("warnings") or [])
        + list(coverage_check.get("warnings") or []),
    }
    return report


def check_from_coverage_regions(index: Sequence[Dict]) -> Dict:
    from coverage import check_coverage

    return check_coverage(list(index))


def write_collation_report(
    task_dir: Path, report: Dict, *, also_markdown: bool = True
) -> Dict[str, str]:
    """写入 collation_report.json（及可选 .md），返回相对文件名。"""
    task_dir = Path(task_dir)
    task_dir.mkdir(parents=True, exist_ok=True)
    json_name = "collation_report.json"
    json_path = task_dir / json_name
    # 多页时合并追加
    existing = {"pages": []}
    if json_path.exists():
        try:
            existing = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception:
            existing = {"pages": []}
    if not isinstance(existing, dict):
        existing = {"pages": []}
    pages = list(existing.get("pages") or [])
    page_number = report.get("document", {}).get("page_number")
    pages = [
        p for p in pages if p.get("document", {}).get("page_number") != page_number
    ]
    pages.append(report)
    pages.sort(key=lambda p: int(p.get("document", {}).get("page_number") or 0))
    payload = {
        "schema": "collation-report-bundle-v1",
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "pages": pages,
    }
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    paths = {"json": json_name}
    if also_markdown:
        md_name = "collation_report.md"
        (task_dir / md_name).write_text(
            render_collation_markdown(payload), encoding="utf-8"
        )
        paths["markdown"] = md_name
    return paths


def render_collation_markdown(bundle_or_report: Dict) -> str:
    pages = bundle_or_report.get("pages")
    if pages is None:
        pages = [bundle_or_report]
    lines = ["# 校勘与完整性报告", ""]
    for report in pages:
        doc = report.get("document") or {}
        lines.append(f"## 第 {doc.get('page_number', '?')} 页")
        lines.append("")
        lines.append("### 原件基本信息")
        lines.append(f"- 文件：{doc.get('filename') or '〔待辨〕'}")
        lines.append(f"- 报刊名称：{doc.get('title') or '〔待辨〕'}")
        lines.append(f"- 日期：{doc.get('date') or '〔待辨〕'}")
        lines.append(f"- 版次：{doc.get('edition') or '〔待辨〕'}")
        lines.append("")
        lines.append("### 版面区域清单")
        for region in report.get("layout_regions") or []:
            lines.append(
                f"- `{region.get('index_id')}` region={region.get('region_id')} "
                f"label={region.get('label')} status={region.get('status')}"
            )
        lines.append("")
        lines.append("### 待辨文字清单")
        uncertain = report.get("uncertain_glyphs") or []
        if not uncertain:
            lines.append("- （无）")
        for item in uncertain:
            lines.append(
                f"- {item.get('glyph', UNCERTAIN_MARK)} @ {item.get('location', '?')} "
                f"— {item.get('reason', '')}"
            )
        lines.append("")
        lines.append("### 结构待核清单")
        pending = report.get("structure_pending") or []
        if not pending:
            lines.append("- （无）")
        for item in pending:
            lines.append(f"- {item.get('issue')} — {item.get('detail', '')}")
        lines.append("")
        cov = report.get("coverage_check") or {}
        lines.append("### 完整性核查结果")
        lines.append(
            f"- 区域完成 {cov.get('completed_regions', 0)}/"
            f"{cov.get('total_regions', 0)}；"
            f"缺失 {cov.get('missing_regions', 0)}；"
            f"pending {cov.get('pending_regions', 0)}；"
            f"ok={cov.get('ok')}"
        )
        for warning in cov.get("warnings") or []:
            lines.append(f"- ⚠ {warning}")
        lines.append("")
        lines.append("### 校勘说明")
        for note in report.get("collation_notes") or []:
            lines.append(f"- {note}")
        lines.append("")
        audit = report.get("agent_audit") or []
        if audit:
            lines.append("### Agent 轮次审计")
            for round_info in audit:
                lines.append(
                    f"- 第 {round_info.get('round')} 轮："
                    f"ok={round_info.get('ok')} "
                    f"issues={len(round_info.get('issues') or [])} "
                    f"action={round_info.get('action', '')}"
                )
            lines.append("")
    return "\n".join(lines)


def _collect_uncertain(
    corrected: str, regions: Sequence[Dict], aggregated: Dict
) -> List[Dict]:
    items: List[Dict] = []
    for match in re.finditer(re.escape(UNCERTAIN_MARK), corrected):
        start = max(0, match.start() - 8)
        end = min(len(corrected), match.end() + 8)
        items.append(
            {
                "glyph": UNCERTAIN_MARK,
                "location": f"corrected_text[{match.start()}:{match.end()}]",
                "context": corrected[start:end],
                "reason": "誊录稿中的待辨标记",
            }
        )
    for region in regions:
        for decision in region.get("glyph_arbitrations") or []:
            arb = decision.get("arbitration") or {}
            if arb.get("glyph") == UNCERTAIN_MARK:
                items.append(
                    {
                        "glyph": UNCERTAIN_MARK,
                        "location": f"region:{region.get('region_id')}#{decision.get('index')}",
                        "candidates": decision.get("candidates")
                        or arb.get("candidates"),
                        "reason": arb.get("reason") or "字形仲裁未决",
                    }
                )
    for warning in aggregated.get("warnings") or []:
        if "待辨" in str(warning) or "缺失" in str(warning):
            items.append(
                {
                    "glyph": UNCERTAIN_MARK,
                    "location": "warning",
                    "reason": str(warning),
                }
            )
    return items


def _collect_structure_pending(aggregated: Dict, coverage: Dict) -> List[Dict]:
    pending: List[Dict] = []
    for warning in aggregated.get("warnings") or []:
        text = str(warning)
        if any(key in text for key in ("边界", "接续", "结构", "分块", "跨列", "跨组")):
            pending.append({"issue": "结构待核", "detail": text})
    check = coverage.get("check") or {}
    if check.get("missing_regions"):
        pending.append(
            {
                "issue": "覆盖缺失",
                "detail": f"有 {check['missing_regions']} 个区域未进入誊录",
            }
        )
    for article in aggregated.get("articles") or []:
        title = str(article.get("title") or "").strip()
        body = str(article.get("body") or "").strip()
        if title and not body:
            pending.append(
                {
                    "issue": "标题无正文",
                    "detail": f"article={article.get('id')} title={title[:40]}",
                }
            )
        if not title and body:
            pending.append(
                {
                    "issue": "正文无标题（可能结构待核）",
                    "detail": f"article={article.get('id')} body={body[:40]}",
                }
            )
    return pending


def _collation_notes(
    aggregated: Dict,
    coverage_check: Dict,
    uncertain: Sequence[Dict],
    structure_pending: Sequence[Dict],
    audit: Sequence[Dict],
) -> List[str]:
    notes = [
        "本报告为誊录稿配套交付；推测不得写入誊录正文。",
        f"不确定标记统一为「{UNCERTAIN_MARK}」。",
    ]
    if coverage_check.get("ok"):
        notes.append("完整性核查：已编号区域均已覆盖或明确标为空。")
    else:
        notes.append("完整性核查未完全通过，见 coverage_check.warnings。")
    if uncertain:
        notes.append(f"待辨文字 {len(uncertain)} 处，需人工回原图核验。")
    if structure_pending:
        notes.append(f"结构待核 {len(structure_pending)} 项。")
    if audit:
        last = audit[-1]
        notes.append(
            f"Agent 共 {len(audit)} 轮，末轮 ok={last.get('ok')} action={last.get('action')}。"
        )
    mode = aggregated.get("transcription_mode")
    if mode:
        notes.append(f"聚合模式：{mode}。")
    return notes
