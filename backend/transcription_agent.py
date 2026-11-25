"""忠实誊录 Agent：组装 → 自检 → 冲突回炉 → 收敛（最多 3 轮）。

不替代既有 columnwise OCR / 视觉分区骨架；只在聚合后增加可审计的多轮收敛。
"""

from __future__ import annotations

from typing import Callable, Dict, List, Sequence

from ai_service import UNCERTAIN_MARK
from aggregation_quality import score_aggregation
from collation_report import build_collation_report
from coverage import check_coverage
from glyph_arbiter import GlyphArbiter, majority_vote

MAX_AGENT_ROUNDS = 3

# 誊录稿相对 OCR raw 的虚增/萎缩阈值（字符比）
INFLATION_RATIO = 1.35
DEFLATION_RATIO = 0.45


class TranscriptionAgent:
    def __init__(self, ai=None, max_rounds: int = MAX_AGENT_ROUNDS):
        self.ai = ai
        self.max_rounds = max(1, int(max_rounds))
        self.arbiter = GlyphArbiter(ai) if ai is not None else None

    def run(
        self,
        *,
        page_number: int,
        regions: List[Dict],
        aggregate_once: Callable[[List[Dict]], Dict],
        coverage: Dict | None = None,
        task: Dict | None = None,
        reocr_region: Callable[[Dict], Dict] | None = None,
    ) -> Dict:
        """多轮：聚合 → 忠实/完整自检 → 回炉 → 校勘报告。

        ``aggregate_once(regions)`` 应返回与 ``aggregate_by_regions`` 同形的 dict。
        ``reocr_region`` 可选：对低置信区域换引擎重取，返回更新后的 region dict。
        """
        current = [dict(region) for region in regions]
        audit: List[Dict] = []
        best: Dict | None = None
        best_score = -1.0

        for round_n in range(1, self.max_rounds + 1):
            aggregated = aggregate_once(current)
            if not isinstance(aggregated, dict):
                aggregated = {"articles": [], "warnings": ["聚合返回非 dict"]}
            quality = score_aggregation(aggregated)
            issues = self.self_check(aggregated, current, coverage)
            ok = not issues and bool(quality.get("ok"))
            action = "accept" if ok else "refurnace"
            audit.append(
                {
                    "round": round_n,
                    "ok": ok,
                    "issues": issues,
                    "quality_score": quality.get("score"),
                    "action": action,
                    "conflict_regions": [
                        r.get("region_id")
                        for r in current
                        if r.get("ocr_conflicts") or r.get("glyph_arbitrations")
                    ],
                }
            )
            score = float(quality.get("score") or 0.0) - 0.02 * len(issues)
            if best is None or score > best_score:
                best = aggregated
                best_score = score
            if ok:
                break
            if round_n >= self.max_rounds:
                audit[-1]["action"] = "stop-max-rounds"
                break
            current = self.refurnace(current, issues, reocr_region=reocr_region)
            audit[-1]["action"] = "refurnace"
            audit[-1]["refurnace_regions"] = [
                r.get("region_id") for r in current if r.get("_refurnaced")
            ]

        assert best is not None
        # 末轮仍有问题：把未决冲突落成〔待辨〕，避免虚假确定
        if audit and not audit[-1].get("ok"):
            best = self._finalize_uncertain(best, current)
            audit[-1]["action"] = audit[-1].get("action") or "finalize-uncertain"
            audit[-1]["finalized_uncertain"] = True

        report = build_collation_report(
            task=task,
            page_number=page_number,
            coverage=coverage,
            regions=current,
            aggregated=best,
            agent_audit=audit,
        )
        best = dict(best)
        best["agent_audit"] = audit
        best["collation_report"] = report
        best.setdefault("warnings", [])
        if isinstance(best["warnings"], list):
            for issue in (audit[-1].get("issues") if audit else None) or []:
                msg = f"Agent自检: {issue}"
                if msg not in best["warnings"]:
                    best["warnings"].append(msg)
        return best

    def self_check(
        self,
        aggregated: Dict,
        regions: Sequence[Dict],
        coverage: Dict | None,
    ) -> List[str]:
        """忠实性 + 完整性启发式自检（确定性，不另调 LLM）。"""
        issues: List[str] = []
        raw = "".join(
            str(r.get("raw_text") or r.get("final_region_text") or "") for r in regions
        )
        raw_compact = _compact(raw)
        corrected = str(aggregated.get("corrected_text") or "")
        corr_compact = _compact(corrected)

        if raw_compact and corr_compact:
            ratio = len(corr_compact) / max(1, len(raw_compact))
            if ratio > INFLATION_RATIO:
                issues.append(
                    f"疑似虚增：誊录稿/OCR 字符比={ratio:.2f}>{INFLATION_RATIO}"
                )
            if ratio < DEFLATION_RATIO:
                issues.append(
                    f"疑似漏字：誊录稿/OCR 字符比={ratio:.2f}<{DEFLATION_RATIO}"
                )

        # 语义替换常见客户案例的硬探针（若 OCR 有而誊录改成现代说法）
        probes = [
            ("今本", "今天"),
            ("幾十年來", "十幾年來"),
            ("几十年来", "十几年来"),
            ("開放", "放開"),
            ("开放", "放开"),
        ]
        for original, modern in probes:
            if original in raw and modern in corrected and original not in corrected:
                issues.append(f"疑似语义替换：原文含「{original}」却出现「{modern}」")

        unresolved_conflicts = 0
        for region in regions:
            conflicts = region.get("ocr_conflicts") or []
            arbs = region.get("glyph_arbitrations") or []
            if conflicts and not arbs:
                unresolved_conflicts += len(conflicts)
            for item in arbs:
                glyph = (item.get("arbitration") or {}).get("glyph")
                if (
                    item.get("conflict")
                    and glyph not in {None, UNCERTAIN_MARK}
                    and not glyph
                ):
                    unresolved_conflicts += 1
        if unresolved_conflicts:
            issues.append(f"仍有 {unresolved_conflicts} 处引擎冲突未仲裁")

        if coverage and coverage.get("check"):
            check = coverage["check"]
        elif coverage and coverage.get("regions"):
            check = check_coverage(coverage["regions"])
        else:
            check = None
        if check and not check.get("ok"):
            if check.get("missing_regions"):
                issues.append(f"覆盖缺失 {check['missing_regions']} 个区域")
            if check.get("pending_regions"):
                issues.append(f"覆盖未核 {check['pending_regions']} 个区域")

        articles = aggregated.get("articles") or []
        if raw_compact and not articles and not corr_compact:
            issues.append("聚合结果为空")

        return issues

    def refurnace(
        self,
        regions: List[Dict],
        issues: Sequence[str],
        *,
        reocr_region: Callable[[Dict], Dict] | None = None,
    ) -> List[Dict]:
        """回炉：低置信/冲突区域重取或仲裁；无法解决则标〔待辨〕。"""
        updated: List[Dict] = []
        issue_text = " ".join(issues)
        want_reocr = (
            "漏字" in issue_text or "冲突" in issue_text or "虚增" in issue_text
        )
        for region in regions:
            item = dict(region)
            item.pop("_refurnaced", None)
            conflicts = list(item.get("ocr_conflicts") or [])
            low_conf = float(item.get("confidence") or 1.0) < 0.72
            touched = False

            if want_reocr and reocr_region and (conflicts or low_conf):
                try:
                    refreshed = reocr_region(item)
                    if isinstance(refreshed, dict) and (
                        refreshed.get("raw_text") or refreshed.get("final_region_text")
                    ):
                        item.update(refreshed)
                        touched = True
                except Exception:
                    pass

            if conflicts:
                crop = item.get("_crop_image") or item.get("crop_path")
                decisions = []
                text = str(item.get("raw_text") or "")
                compact = list(_compact(text))
                for conflict in conflicts:
                    candidates = list(conflict.get("candidates") or [])
                    if self.arbiter and crop is not None and self.arbiter.available:
                        decision = self.arbiter.arbitrate(crop, candidates)
                    else:
                        decision = majority_vote(candidates)
                        if (
                            decision.get("glyph") != UNCERTAIN_MARK
                            and len(set(candidates)) > 1
                        ):
                            # 平票已是待辨；多数有结果则用，否则待辨
                            pass
                        if not candidates:
                            decision = {
                                "glyph": UNCERTAIN_MARK,
                                "confidence": 0.0,
                                "source": "refurnace-empty",
                                "candidates": [],
                            }
                    decisions.append({**conflict, "arbitration": decision})
                    idx = int(conflict.get("index") or 0)
                    glyph = str(decision.get("glyph") or UNCERTAIN_MARK)
                    if 0 <= idx < len(compact):
                        compact[idx] = glyph
                item["glyph_arbitrations"] = decisions
                item["raw_text"] = "".join(compact) or text
                item["final_region_text"] = item["raw_text"]
                touched = True

            if touched:
                item["_refurnaced"] = True
            updated.append(item)
        return updated

    @staticmethod
    def _finalize_uncertain(aggregated: Dict, regions: Sequence[Dict]) -> Dict:
        result = dict(aggregated)
        warnings = list(result.get("warnings") or [])
        pending = sum(len(r.get("ocr_conflicts") or []) for r in regions)
        if pending:
            msg = f"收敛结束仍有 {pending} 处冲突，已优先保留 OCR 并在校勘报告列出；不可辨处用「{UNCERTAIN_MARK}」。"
            if msg not in warnings:
                warnings.append(msg)
        result["warnings"] = warnings
        return result


def _compact(text: str) -> str:
    return "".join(ch for ch in str(text or "") if not ch.isspace())
