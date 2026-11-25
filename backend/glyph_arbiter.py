"""字符级字形仲裁：候选约束 + DeepSeek 视觉「只看字形」。

Phase 0 spike 结论：开放式整词辨认不稳定；给定候选后仲裁很稳。
因此本模块只做「从候选中选，或标〔待辨〕」，绝不开放编造。
"""

from __future__ import annotations

import json
import re
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence

import cv2
import numpy as np

from ai_service import AIService, UNCERTAIN_MARK

# 低于此置信度的仲裁结果降为〔待辨〕，避免虚假确定性。
DEFAULT_MIN_CONFIDENCE = 0.75


class GlyphArbiter:
    """对 OCR 冲突/低置信字做候选约束的字形仲裁。"""

    def __init__(
        self,
        ai: AIService,
        min_confidence: float = DEFAULT_MIN_CONFIDENCE,
    ):
        self.ai = ai
        self.min_confidence = min_confidence

    @property
    def available(self) -> bool:
        return bool(getattr(self.ai, "supports_vision", False))

    def arbitrate(
        self,
        image: np.ndarray | str | Path,
        candidates: Sequence[str],
        *,
        expected_span: str | None = None,
    ) -> Dict:
        """对一小块字形图做仲裁。

        Returns:
            glyph, confidence, source, candidates, reason
        """
        cleaned = []
        seen = set()
        for item in candidates:
            text = str(item or "").strip()
            if not text or text in seen:
                continue
            seen.add(text)
            cleaned.append(text)
        if expected_span and expected_span.strip() and expected_span not in seen:
            cleaned.insert(0, expected_span.strip())

        if not cleaned:
            return {
                "glyph": UNCERTAIN_MARK,
                "confidence": 0.0,
                "source": "no-candidates",
                "candidates": [],
                "reason": "无候选字",
            }

        if len(cleaned) == 1:
            return {
                "glyph": cleaned[0],
                "confidence": 1.0,
                "source": "single-candidate",
                "candidates": cleaned,
                "reason": "仅一个候选，无需视觉仲裁",
            }

        if not self.available:
            # 无视觉时：不猜，标待辨（调用方可再走多数投票兜底）
            return {
                "glyph": UNCERTAIN_MARK,
                "confidence": 0.0,
                "source": "vision-unavailable",
                "candidates": cleaned,
                "reason": "视觉模型不可用，拒绝无依据猜测",
            }

        crop_path = self._ensure_image_path(image)
        prompt = self._prompt(cleaned)
        try:
            result = self.ai._vision_json(crop_path, prompt, max_tokens=400)
        except Exception as error:
            return {
                "glyph": UNCERTAIN_MARK,
                "confidence": 0.0,
                "source": "vision-error",
                "candidates": cleaned,
                "reason": f"视觉仲裁失败: {error}",
            }

        glyph = str(result.get("glyph") or UNCERTAIN_MARK).strip()
        try:
            confidence = min(1.0, max(0.0, float(result.get("confidence", 0.0))))
        except (TypeError, ValueError):
            confidence = 0.0

        if glyph not in cleaned and glyph != UNCERTAIN_MARK:
            # 模型输出了候选外的字 → 视为不可靠
            glyph = UNCERTAIN_MARK
            confidence = min(confidence, 0.3)

        if confidence < self.min_confidence:
            glyph = UNCERTAIN_MARK

        return {
            "glyph": glyph,
            "confidence": confidence,
            "source": "vlm-candidates",
            "candidates": cleaned,
            "reason": str(result.get("reason") or "").strip(),
            "raw": {
                "ai_backend": result.get("ai_backend"),
                "ai_model": result.get("ai_model"),
            },
        }

    def resolve_conflicts(
        self,
        image: np.ndarray | str | Path,
        conflicts: Sequence[Dict],
    ) -> List[Dict]:
        """批量处理 align_ocr_chars 产出的 conflict 条目。"""
        resolved = []
        for conflict in conflicts:
            candidates = list(conflict.get("candidates") or [])
            decision = self.arbitrate(image, candidates)
            resolved.append({**conflict, "arbitration": decision})
        return resolved

    @staticmethod
    def _prompt(candidates: Sequence[str]) -> str:
        return f"""你是字形辨认专家。只看这张裁切小图里的汉字字形。

硬性规则：
1. 只根据笔画/字形判断，不要根据语义、上下文、历史常识猜测。
2. 必须从下列候选中选一个；若都不像、看不清、或多选无法确定，返回「{UNCERTAIN_MARK}」。
3. 禁止输出候选列表以外的字（除非返回〔待辨〕）。
4. 全文繁体；不要润色、不要补字。

候选：{json.dumps(list(candidates), ensure_ascii=False)}

只返回 JSON：
{{"glyph":"候选之一或{UNCERTAIN_MARK}","confidence":0.0,"reason":"仅描述可见笔画特征"}}"""

    @staticmethod
    def _ensure_image_path(image: np.ndarray | str | Path) -> Path:
        if isinstance(image, (str, Path)):
            return Path(image)
        if not isinstance(image, np.ndarray) or image.size == 0:
            raise ValueError("empty glyph crop")
        handle = tempfile.NamedTemporaryFile(suffix=".jpg", delete=False)
        path = Path(handle.name)
        handle.close()
        bgr = image if image.ndim == 3 else cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        cv2.imwrite(str(path), bgr)
        return path


def majority_vote(candidates: Sequence[str]) -> Dict:
    """无 VLM 时的降级：多引擎多数投票；平票则〔待辨〕。"""
    cleaned = [str(c).strip() for c in candidates if str(c).strip()]
    if not cleaned:
        return {
            "glyph": UNCERTAIN_MARK,
            "confidence": 0.0,
            "source": "vote-empty",
            "candidates": [],
        }
    counts: Dict[str, int] = {}
    for item in cleaned:
        counts[item] = counts.get(item, 0) + 1
    best, best_n = max(counts.items(), key=lambda kv: kv[1])
    ties = [k for k, n in counts.items() if n == best_n]
    if len(ties) > 1:
        return {
            "glyph": UNCERTAIN_MARK,
            "confidence": 0.0,
            "source": "vote-tie",
            "candidates": cleaned,
        }
    return {
        "glyph": best,
        "confidence": best_n / len(cleaned),
        "source": "majority-vote",
        "candidates": cleaned,
    }
