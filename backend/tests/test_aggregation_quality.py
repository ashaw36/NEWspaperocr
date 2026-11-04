"""LLM 文章聚合质量评分与重试兜底单测。"""

import unittest
from unittest.mock import Mock

from aggregation_quality import OK_THRESHOLD, score_aggregation
from workflow import DocumentWorkflow


def _good_result() -> dict:
    """模拟好结果：标题完整、正文通顺，得分约 0.85+，应 ok=True。"""
    return {
        "articles": [
            {
                "id": "a1",
                "title": "齊燮元視察各地",
                "subtitle": "",
                "body": "齊燮元於日前赴各地視察地方行政情形，並召集各縣縣長訓話，囑其認真辦理地方要政。",
                "direction": "vertical-rtl",
            },
            {
                "id": "a2",
                "title": "滬市商況近訊",
                "subtitle": "米價微漲",
                "body": "本埠米市近日略見上漲，標米每石較上周約增三角，各幫客商進貨尚見踴躍。",
                "direction": "vertical-rtl",
            },
        ],
        "corrected_text": "齊燮元視察各地\n...",
        "corrections": [],
        "warnings": [],
    }


def _bad_result() -> dict:
    """模拟坏结果（对齐真实坏聚合 ~0.725）：部分乱码/悬空标题 + 多篇空标题，正文尚可。

    在 OK_THRESHOLD=0.8 下应 ok=False，从而触发 _aggregate_with_retry 重试。
    """
    body = (
        "南京失守以後、北平即將有新組織成立之說，各方傳說甚盛，惟內容尚未發表。"
        "尚有若干字以湊足正文長度，避免短正文罰分干擾標題信號。"
    )
    return {
        "articles": [
            {
                "id": "b1",
                "title": "北平新组织成立说",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b2",
                "title": "口大公报上海版亦停口",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b3",
                "title": "改委员长聲明我軍退出南京意L一、而报之",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b4",
                "title": "新开之靠文版所改、",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b5",
                "title": "王正廷近",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b6",
                "title": "而至脉隔电溪",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b7",
                "title": "",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b8",
                "title": "",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b9",
                "title": "",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
            {
                "id": "b10",
                "title": "",
                "subtitle": "",
                "body": body,
                "direction": "vertical-rtl",
            },
        ],
        "corrected_text": "",
        "corrections": [],
        "warnings": [],
    }


class ScoreAggregationTests(unittest.TestCase):
    def test_good_scores_higher_than_bad(self):
        good = score_aggregation(_good_result())
        bad = score_aggregation(_bad_result())

        self.assertGreaterEqual(good["score"], 0.85)
        self.assertGreaterEqual(good["score"], OK_THRESHOLD)
        self.assertTrue(good["ok"])
        self.assertEqual([], good["issues"])

        # 坏结果约 0.7 档：高于旧阈值 0.6，但低于校准后的 0.8 → 必须触发重试
        self.assertGreater(bad["score"], 0.65)
        self.assertLess(bad["score"], OK_THRESHOLD)
        self.assertFalse(bad["ok"])
        self.assertTrue(bad["issues"])
        self.assertGreater(good["score"], bad["score"])

    def test_empty_articles_score_zero(self):
        quality = score_aggregation(
            {"articles": [], "corrected_text": "", "warnings": []}
        )
        self.assertEqual(0.0, quality["score"])
        self.assertFalse(quality["ok"])
        self.assertIn("articles 为空", quality["issues"])

    def test_missing_articles_key_treated_as_empty(self):
        quality = score_aggregation({})
        self.assertEqual(0.0, quality["score"])
        self.assertFalse(quality["ok"])


class AggregateWithRetryTests(unittest.TestCase):
    def setUp(self):
        # DocumentWorkflow.__init__ 需要真实依赖；此处仅测实例方法，绕过构造。
        self.workflow = DocumentWorkflow.__new__(DocumentWorkflow)

    def test_retry_keeps_good_result_after_bad_first_attempt(self):
        bad = _bad_result()
        good = _good_result()
        aggregate_fn = Mock(side_effect=[bad, good])

        result = self.workflow._aggregate_with_retry(
            aggregate_fn, 1, [], max_attempts=3
        )

        self.assertEqual(2, aggregate_fn.call_count)
        self.assertEqual("齊燮元視察各地", result["articles"][0]["title"])
        joined = " ".join(result.get("warnings") or [])
        self.assertIn("聚合质量校验", joined)
        self.assertIn("ok=True", joined)
        self.assertIn("attempts=2/3", joined)
        # 第二次起应带 hint（Mock 接受任意 kwargs）
        second_kwargs = aggregate_fn.call_args_list[1].kwargs
        self.assertIn("hint", second_kwargs)
        self.assertTrue(second_kwargs["hint"])

    def test_all_bad_returns_best_without_raising(self):
        # 三次都坏，但第二次相对「没那么碎」——仍不达标，应选最高分且不抛错。
        worse = {
            "articles": [
                {
                    "id": "x1",
                    "title": "",
                    "body": "",
                    "direction": "vertical-rtl",
                }
            ],
            "warnings": [],
        }
        bad_but_better = _bad_result()
        bad_but_better["warnings"] = ["prior"]
        also_bad = {
            "articles": [
                {
                    "id": "y1",
                    "title": "之",
                    "body": "口",
                    "direction": "vertical-rtl",
                }
            ],
            "warnings": [],
        }
        aggregate_fn = Mock(side_effect=[worse, bad_but_better, also_bad])

        result = self.workflow._aggregate_with_retry(aggregate_fn, max_attempts=3)

        self.assertEqual(3, aggregate_fn.call_count)
        # 最高分应是 bad_but_better（有若干非空字段）而非全空
        self.assertEqual(bad_but_better["articles"], result["articles"])
        joined = " ".join(result.get("warnings") or [])
        self.assertIn("聚合质量未达标", joined)
        self.assertIn("ok=False", joined)
        self.assertIn("attempts=3/3", joined)
        self.assertIn("prior", result["warnings"])


if __name__ == "__main__":
    unittest.main()
