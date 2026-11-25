import unittest
from unittest.mock import Mock

from ai_service import UNCERTAIN_MARK
from transcription_agent import TranscriptionAgent


class TranscriptionAgentTests(unittest.TestCase):
    def test_accepts_clean_aggregation_in_one_round(self):
        agent = TranscriptionAgent(ai=None, max_rounds=3)
        regions = [
            {
                "region_id": "r1",
                "raw_text": "今本創刊號出版，幾十年來思想開放。",
                "confidence": 0.9,
            }
        ]

        def aggregate_once(_regions):
            return {
                "articles": [
                    {
                        "id": "a1",
                        "title": "發刊辭",
                        "subtitle": "",
                        "body": "今本創刊號出版，幾十年來思想開放。",
                    }
                ],
                "corrected_text": "發刊辭\n今本創刊號出版，幾十年來思想開放。",
                "warnings": [],
            }

        coverage = {
            "regions": [
                {
                    "index_id": "P01-B01",
                    "region_id": "r1",
                    "status": "completed",
                    "lines": [],
                }
            ],
            "check": {
                "ok": True,
                "total_regions": 1,
                "completed_regions": 1,
                "missing_regions": 0,
                "pending_regions": 0,
                "warnings": [],
            },
        }
        result = agent.run(
            page_number=1,
            regions=regions,
            aggregate_once=aggregate_once,
            coverage=coverage,
        )
        self.assertEqual(1, len(result["agent_audit"]))
        self.assertTrue(result["agent_audit"][0]["ok"])
        self.assertIn("collation_report", result)
        self.assertEqual("collation-report-v1", result["collation_report"]["schema"])
        self.assertIn("今本", result["corrected_text"])

    def test_detects_semantic_rewrite_and_refurnaces(self):
        agent = TranscriptionAgent(ai=None, max_rounds=2)
        regions = [
            {
                "region_id": "r1",
                "raw_text": "今本創刊號出版",
                "confidence": 0.9,
                "ocr_conflicts": [],
            }
        ]
        calls = {"n": 0}

        def aggregate_once(_regions):
            calls["n"] += 1
            if calls["n"] == 1:
                return {
                    "articles": [
                        {
                            "id": "a1",
                            "title": "x",
                            "subtitle": "",
                            "body": "今天創刊號出版",
                        }
                    ],
                    "corrected_text": "今天創刊號出版",
                    "warnings": [],
                }
            return {
                "articles": [
                    {
                        "id": "a1",
                        "title": "x",
                        "subtitle": "",
                        "body": "今本創刊號出版",
                    }
                ],
                "corrected_text": "今本創刊號出版",
                "warnings": [],
            }

        coverage = {
            "check": {
                "ok": True,
                "missing_regions": 0,
                "pending_regions": 0,
                "warnings": [],
            }
        }
        result = agent.run(
            page_number=1,
            regions=regions,
            aggregate_once=aggregate_once,
            coverage=coverage,
        )
        self.assertGreaterEqual(calls["n"], 2)
        self.assertFalse(result["agent_audit"][0]["ok"])
        self.assertTrue(
            any("语义替换" in issue for issue in result["agent_audit"][0]["issues"])
        )
        self.assertIn("今本", result["corrected_text"])

    def test_self_check_flags_inflation(self):
        agent = TranscriptionAgent(ai=None)
        issues = agent.self_check(
            {
                "corrected_text": "一二三四五六七八九十" * 5,
                "articles": [{"id": "a1", "title": "t", "body": "b"}],
            },
            [{"raw_text": "一二三"}],
            coverage={
                "check": {"ok": True, "missing_regions": 0, "pending_regions": 0}
            },
        )
        self.assertTrue(any("虚增" in i for i in issues))

    def test_collation_report_lists_uncertain_mark(self):
        agent = TranscriptionAgent(ai=None, max_rounds=1)
        regions = [
            {
                "region_id": "r1",
                "raw_text": f"字{UNCERTAIN_MARK}詞",
                "confidence": 0.5,
                "glyph_arbitrations": [
                    {
                        "index": 1,
                        "conflict": True,
                        "arbitration": {
                            "glyph": UNCERTAIN_MARK,
                            "reason": "看不清",
                        },
                    }
                ],
            }
        ]

        def aggregate_once(_regions):
            return {
                "articles": [
                    {
                        "id": "a1",
                        "title": "t",
                        "subtitle": "",
                        "body": f"字{UNCERTAIN_MARK}詞",
                    }
                ],
                "corrected_text": f"字{UNCERTAIN_MARK}詞",
                "warnings": [],
            }

        result = agent.run(
            page_number=3,
            regions=regions,
            aggregate_once=aggregate_once,
            coverage={
                "check": {
                    "ok": True,
                    "missing_regions": 0,
                    "pending_regions": 0,
                    "warnings": [],
                }
            },
        )
        uncertain = result["collation_report"]["uncertain_glyphs"]
        self.assertTrue(uncertain)
        self.assertTrue(any(u.get("glyph") == UNCERTAIN_MARK for u in uncertain))


class CollationReportWriteTests(unittest.TestCase):
    def test_write_json_and_markdown(self):
        import tempfile
        from pathlib import Path

        from collation_report import build_collation_report, write_collation_report

        report = build_collation_report(
            page_number=1,
            regions=[{"region_id": "r1", "raw_text": "甲", "label": "body"}],
            aggregated={
                "corrected_text": "甲",
                "articles": [{"id": "a1", "title": "題", "body": "甲"}],
                "warnings": [],
            },
            coverage={
                "regions": [
                    {
                        "index_id": "P01-B01",
                        "region_id": "r1",
                        "status": "completed",
                        "lines": [],
                    }
                ],
                "check": {
                    "ok": True,
                    "total_regions": 1,
                    "completed_regions": 1,
                    "missing_regions": 0,
                    "pending_regions": 0,
                    "warnings": [],
                },
            },
            document_meta={"filename": "demo.pdf"},
        )
        with tempfile.TemporaryDirectory() as tmp:
            paths = write_collation_report(Path(tmp), report, also_markdown=True)
            self.assertTrue((Path(tmp) / paths["json"]).exists())
            self.assertTrue((Path(tmp) / paths["markdown"]).exists())
            md = (Path(tmp) / paths["markdown"]).read_text(encoding="utf-8")
            self.assertIn("校勘与完整性报告", md)
            self.assertIn("demo.pdf", md)


if __name__ == "__main__":
    unittest.main()
