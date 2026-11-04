"""文字纠错策略层单测。"""

import unittest

from correction import (
    BaseCorrector,
    ConservativeCorrector,
    apply_page_correction,
    get_corrector,
    register_corrector,
    registered_correctors,
)


class CorrectionRegistryTests(unittest.TestCase):
    def test_conservative_is_registered_and_factory_returns_it(self):
        self.assertIn("conservative", registered_correctors())
        corrector = get_corrector("conservative")
        self.assertIsInstance(corrector, ConservativeCorrector)
        self.assertEqual("conservative", corrector.name)

    def test_unknown_mode_raises(self):
        with self.assertRaises(ValueError):
            get_corrector("does-not-exist")

    def test_custom_corrector_can_register(self):
        @register_corrector
        class _ProbeCorrector(BaseCorrector):
            @property
            def name(self) -> str:
                return "probe-test-only"

            def correct(self, text: str) -> str:
                return text + "!"

        try:
            self.assertEqual("x!", get_corrector("probe-test-only").correct("x"))
        finally:
            from correction import _REGISTRY

            _REGISTRY.pop("probe-test-only", None)


class ConservativeCorrectorTests(unittest.TestCase):
    def setUp(self):
        self.corrector = ConservativeCorrector()

    def test_ocr_misreads_to_traditional(self):
        # 租酸→組織（繁体），不得落到简体「组织」
        out = self.corrector.correct("租酸")
        self.assertIn("組織", out)
        self.assertNotIn("组织", out)
        self.assertEqual("組織", out)

        self.assertEqual("委員", self.corrector.correct("委目"))
        self.assertEqual("老申報", self.corrector.correct("老申銀"))
        self.assertEqual("活動", self.corrector.correct("活勤"))
        self.assertEqual("大公報", self.corrector.correct("大公服"))
        self.assertEqual("停刊", self.corrector.correct("停利"))
        self.assertEqual("組織", self.corrector.correct("粗織"))
        self.assertEqual("組織", self.corrector.correct("組辆"))

    def test_no_script_conversion_on_correct_or_simplified(self):
        # 正确繁体与纯简体均不发生简繁变化
        self.assertEqual("組織", self.corrector.correct("組織"))
        self.assertEqual("组织", self.corrector.correct("组织"))
        self.assertEqual("委員活動", self.corrector.correct("委員活動"))
        self.assertEqual("委员活动", self.corrector.correct("委员活动"))

    def test_unknown_characters_preserved(self):
        sample = "𠀀罕见字XYZ123"
        self.assertEqual(sample, self.corrector.correct(sample))

    def test_correct_is_idempotent(self):
        once = self.corrector.correct("租酸委目活勤與會議")
        twice = self.corrector.correct(once)
        self.assertEqual(once, twice)
        self.assertNotIn("租酸", once)
        self.assertNotIn("委目", once)
        self.assertIn("組織", once)
        self.assertIn("委員", once)
        self.assertIn("活動", once)

    def test_empty_and_none_like(self):
        self.assertEqual("", self.corrector.correct(""))

    def test_apply_page_correction_fields(self):
        page = {
            "page_number": 1,
            "corrected_text": "組織活勤",
            "articles": [
                {
                    "id": "a1",
                    "title": "委目會議",
                    "subtitle": "關於租酸",
                    "body": "開展活動",
                    "direction": "vertical-rtl",
                }
            ],
            "corrections": [
                {
                    "region_id": "r1",
                    "original": "組織",
                    "corrected": "組織",
                    "reason": "keep",
                }
            ],
            "warnings": ["組織提示保留"],
        }
        apply_page_correction(page, self.corrector)
        self.assertEqual("組織活動", page["corrected_text"])
        article = page["articles"][0]
        self.assertEqual("委員會議", article["title"])
        self.assertEqual("關於組織", article["subtitle"])
        self.assertEqual("開展活動", article["body"])
        # 审计/警告字段不动
        self.assertEqual("組織", page["corrections"][0]["original"])
        self.assertEqual("組織提示保留", page["warnings"][0])


class WorkflowCorrectionHookTests(unittest.TestCase):
    """确认 workflow 钩子：none 跳过、conservative 生效。"""

    def test_none_mode_skips(self):
        from workflow import DocumentWorkflow

        class _Stub:
            pass

        wf = DocumentWorkflow(_Stub(), _Stub(), _Stub())
        page = {"corrected_text": "組織", "articles": []}
        out = wf._apply_pluggable_correction({"options": {}}, page)
        self.assertIs(out, page)
        self.assertEqual("組織", page["corrected_text"])

        out = wf._apply_pluggable_correction(
            {"options": {"correction_mode": "none"}}, page
        )
        self.assertEqual("組織", page["corrected_text"])

    def test_conservative_mode_rewrites_text(self):
        from workflow import DocumentWorkflow

        class _Stub:
            pass

        wf = DocumentWorkflow(_Stub(), _Stub(), _Stub())
        page = {
            "corrected_text": "租酸",
            "articles": [{"title": "委目", "subtitle": "", "body": "活勤"}],
        }
        out = wf._apply_pluggable_correction(
            {"options": {"correction_mode": "conservative"}}, page
        )
        self.assertEqual("組織", out["corrected_text"])
        self.assertNotIn("组织", out["corrected_text"])
        self.assertEqual("委員", out["articles"][0]["title"])
        self.assertEqual("活動", out["articles"][0]["body"])


if __name__ == "__main__":
    unittest.main()
