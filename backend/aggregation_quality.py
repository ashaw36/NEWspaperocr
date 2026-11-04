"""Deterministic quality scoring for LLM article aggregation results.

Pure functions only — no LLM calls. Used as a retry gate around
``aggregate_by_regions`` / ``aggregate_whole_page``.
"""

from __future__ import annotations

import re
from typing import Dict, List

# ---- Tunable thresholds & weights -------------------------------------------

# 达标阈值：score >= OK_THRESHOLD → ok=True，_aggregate_with_retry 可提前退出。
# 校准（2026-11-02，真实 corrected.json / pages[0]）：
#   好结果 score≈0.864（11 篇通顺、标题基本正确）→ 应 ok
#   坏结果 score≈0.725（标题乱码/悬空片段 + 多篇空标题）→ 应不 ok、触发重试
# 0.6 过松（坏结果也被放过）；0.8 可区分二者。
OK_THRESHOLD = 0.8

# Contribution of each signal family to the final 0~1 score.
WEIGHT_TITLE = 0.50
WEIGHT_BODY = 0.50

# Title length (CJK / visible chars after strip).
TITLE_MIN_LEN = 2
TITLE_MAX_LEN = 25

# Body too short to be a real article.
BODY_MIN_LEN = 8

# Average contiguous Han-run length below this → fragmented OCR debris.
BODY_MIN_AVG_HAN_RUN = 3.0

# Per-article title sub-score penalties (subtracted from 1.0, floored at 0).
PENALTY_EMPTY_TITLE = 1.0
PENALTY_DANGLING_TITLE = 0.55
PENALTY_TITLE_NOISE = 0.40
PENALTY_TITLE_LENGTH = 0.35

# Per-article body sub-score penalties.
PENALTY_EMPTY_BODY = 1.0
PENALTY_SHORT_BODY = 0.50
PENALTY_FRAGMENTED_BODY = 0.55

# Title endings that look like cut-off fragments rather than complete phrases.
_DANGLING_TITLE_SUFFIXES = (
    "、",
    "，",
    "。",
    "；",
    "：",
    "之",
    "的",
    "與",
    "及",
    "於",
    "在",
    "為",
    "而",
)

# OCR noise markers commonly seen in garbled titles.
_TITLE_NOISE_RE = re.compile(
    r"(?:"
    r"□|囗|"  # placeholder boxes
    r"(?<![\u4e00-\u9fff])口(?![\u4e00-\u9fff])|"  # lone 口
    r"[A-Za-z0-9]"  # Latin / digit intrusion in a Chinese headline
    r")"
)

_HAN_RUN_RE = re.compile(r"[\u4e00-\u9fff]+")


def score_aggregation(result: Dict) -> Dict:
    """Score an aggregation result for title/body sanity.

    Returns ``{"score": float, "ok": bool, "issues": List[str]}``.
    ``score`` is in ``[0, 1]``; ``ok`` is True when ``score >= OK_THRESHOLD``.
    Empty ``articles`` yields score 0 / ok False.
    """
    articles = result.get("articles") or []
    if not articles:
        return {"score": 0.0, "ok": False, "issues": ["articles 为空"]}

    title_scores: List[float] = []
    body_scores: List[float] = []
    issues: List[str] = []

    for index, article in enumerate(articles, 1):
        aid = str(article.get("id") or index)
        title = str(article.get("title") or "").strip()
        body = str(article.get("body") or "").strip()

        t_score, t_issues = _score_title(title, aid)
        b_score, b_issues = _score_body(body, aid)
        title_scores.append(t_score)
        body_scores.append(b_score)
        issues.extend(t_issues)
        issues.extend(b_issues)

    avg_title = sum(title_scores) / len(title_scores)
    avg_body = sum(body_scores) / len(body_scores)
    score = round(WEIGHT_TITLE * avg_title + WEIGHT_BODY * avg_body, 4)
    score = max(0.0, min(1.0, score))
    return {
        "score": score,
        "ok": score >= OK_THRESHOLD,
        "issues": issues,
    }


def _score_title(title: str, article_id: str) -> tuple[float, List[str]]:
    if not title:
        return 0.0, [f"文章 {article_id}: 空标题"]

    score = 1.0
    issues: List[str] = []

    if any(title.endswith(suffix) for suffix in _DANGLING_TITLE_SUFFIXES):
        score -= PENALTY_DANGLING_TITLE
        issues.append(f"文章 {article_id}: 标题为悬空片段（以连接/标点结尾）")

    if _TITLE_NOISE_RE.search(title):
        score -= PENALTY_TITLE_NOISE
        issues.append(f"文章 {article_id}: 标题含 OCR 噪声（□/口/拉丁数字混入）")

    visible_len = len(title)
    if visible_len < TITLE_MIN_LEN or visible_len > TITLE_MAX_LEN:
        score -= PENALTY_TITLE_LENGTH
        issues.append(
            f"文章 {article_id}: 标题长度异常（{visible_len}，期望 {TITLE_MIN_LEN}~{TITLE_MAX_LEN}）"
        )

    return max(0.0, score), issues


def _score_body(body: str, article_id: str) -> tuple[float, List[str]]:
    if not body:
        return 0.0, [f"文章 {article_id}: 正文为空"]

    score = 1.0
    issues: List[str] = []

    if len(body) < BODY_MIN_LEN:
        score -= PENALTY_SHORT_BODY
        issues.append(f"文章 {article_id}: 正文过短（{len(body)} 字）")

    avg_run = _avg_han_run_length(body)
    if avg_run > 0 and avg_run < BODY_MIN_AVG_HAN_RUN:
        score -= PENALTY_FRAGMENTED_BODY
        issues.append(
            f"文章 {article_id}: 正文碎片化（平均连续汉字段长 {avg_run:.1f} < {BODY_MIN_AVG_HAN_RUN}）"
        )
    elif avg_run == 0 and len(body) >= BODY_MIN_LEN:
        # Non-empty but no Han at all — unusual for this corpus; treat as weak body.
        score -= PENALTY_FRAGMENTED_BODY
        issues.append(f"文章 {article_id}: 正文无汉字内容")

    return max(0.0, score), issues


def _avg_han_run_length(text: str) -> float:
    runs = _HAN_RUN_RE.findall(text)
    if not runs:
        return 0.0
    return sum(len(run) for run in runs) / len(runs)
