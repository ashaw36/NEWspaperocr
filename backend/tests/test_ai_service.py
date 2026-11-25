import unittest
from types import SimpleNamespace
from unittest.mock import Mock

from ai_service import AIInsufficientBalanceError, AIService


class AIServiceTests(unittest.TestCase):
    def test_summary_prompt_requires_simplified_chinese(self):
        service = AIService.__new__(AIService)
        service._text_json = Mock(return_value={"summary": "中文摘要"})

        result = service.summarize_document(
            "A historical newspaper article", "Explain the key points"
        )

        self.assertEqual({"summary": "中文摘要"}, result)
        prompt = service._text_json.call_args.args[0]
        self.assertIn("必须使用简体中文", prompt)
        self.assertIn("无论原文或用户要求使用何种语言", prompt)
        self.assertIn("Explain the key points", prompt)

    def test_deepseek_vision_requests_structured_non_reasoning_output(self):
        completion = SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"regions":[]}'))]
        )
        create = Mock(return_value=completion)
        service = AIService.__new__(AIService)
        service.backend = "deepseek"
        service.model = "deepseek-chat"
        service.vision_model = "deepseek-flash"
        service.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        service._require_client = Mock()
        service._encode_vision_image = Mock(return_value=("image/jpeg", "encoded"))

        result = service._vision_json("page.jpg", "Return a layout", max_tokens=100)

        self.assertEqual([], result["regions"])
        options = create.call_args.kwargs
        self.assertEqual({"type": "json_object"}, options["response_format"])
        self.assertEqual({"thinking": {"type": "disabled"}}, options["extra_body"])
        self.assertIn("Return json only", options["messages"][0]["content"][0]["text"])

    def test_insufficient_balance_error_is_localized_and_preserves_request_id(self):
        request_id = "0e46abf3-502a-43f1-87ca-267259bdd6e3"
        error = RuntimeError(f"Insufficient Balance (request_id: {request_id})")
        error.status_code = 402
        error.body = {"error": {"message": str(error), "code": "invalid_request_error"}}
        create = Mock(side_effect=error)
        service = AIService.__new__(AIService)
        service.backend = "deepseek"
        service.model = "deepseek-chat"
        service.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        service._require_client = Mock()

        with self.assertRaises(AIInsufficientBalanceError) as raised:
            service._text_json("请总结", max_tokens=100)

        self.assertIn("AI 服务账户余额不足", str(raised.exception))
        self.assertIn(request_id, str(raised.exception))
        create.assert_called_once()

    def test_vision_balance_error_does_not_trigger_provider_fallback(self):
        error = RuntimeError("Insufficient Balance")
        error.status_code = 402
        create = Mock(side_effect=error)
        service = AIService.__new__(AIService)
        service.backend = "deepseek"
        service.model = "deepseek-chat"
        service.vision_model = "deepseek-flash"
        service.client = SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        )
        service._require_client = Mock()
        service._encode_vision_image = Mock(return_value=("image/jpeg", "encoded"))

        with self.assertRaises(AIInsufficientBalanceError):
            service._vision_json("page.jpg", "Return a layout", max_tokens=100)

        create.assert_called_once()

    def test_correction_balance_error_does_not_fallback_to_text(self):
        service = AIService.__new__(AIService)
        service.vision_model = "deepseek-flash"
        service.client = object()
        service._vision_json = Mock(
            side_effect=AIInsufficientBalanceError("AI 服务账户余额不足")
        )
        service._text_json = Mock()

        with self.assertRaises(AIInsufficientBalanceError):
            service.correct_page(1, [], page_image="page.jpg")

        service._text_json.assert_not_called()

    def test_aggregate_by_regions_prompt_uses_ordered_region_text(self):
        service = AIService.__new__(AIService)
        service.vision_model = None
        service.client = None
        service._text_json = Mock(
            return_value={
                "articles": [
                    {
                        "id": "a1",
                        "title": "標題",
                        "subtitle": "",
                        "body": "正文",
                        "direction": "vertical-rtl",
                    }
                ],
                "corrected_text": "標題\n正文",
                "corrections": [],
                "warnings": [],
            }
        )

        regions = [
            {
                "region_id": "r1",
                "order": 1,
                "label": "title",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "raw_text": "標題文字",
                "confidence": 0.9,
            },
            {
                "region_id": "r2",
                "order": 2,
                "label": "body",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "raw_text": "正文文字",
                "confidence": 0.85,
            },
        ]
        result = service.aggregate_by_regions(1, regions, direction="vertical-rtl")

        self.assertEqual("a1", result["articles"][0]["id"])
        prompt = service._text_json.call_args.args[0]
        self.assertIn("已按视觉版面分区", prompt)
        self.assertIn("標題文字", prompt)
        self.assertIn("正文文字", prompt)
        self.assertIn("保留繁体", prompt)
        self._assert_faithfulness_constraints(prompt)

    def test_aggregate_prompt_includes_faithfulness_constitution(self):
        service = AIService.__new__(AIService)
        prompt = service._aggregate_prompt(
            1,
            [{"block_id": 1, "text": "今本創刊", "confidence": 0.9, "bbox": None}],
            [{"column_index": 0}],
            "vertical-rtl",
        )
        self._assert_faithfulness_constraints(prompt)
        self.assertIn("今本創刊", prompt)
        self.assertNotIn("用 □ 表示", prompt)

    def test_correct_page_prompt_includes_faithfulness_constitution(self):
        service = AIService.__new__(AIService)
        service.vision_model = None
        service.client = object()
        service._text_json = Mock(
            return_value={
                "corrected_text": "今本",
                "articles": [],
                "corrections": [],
                "warnings": [],
            }
        )
        regions = [
            {
                "region_id": "r1",
                "order": 1,
                "label": "body",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "raw_text": "今本創刊號出版",
                "confidence": 0.8,
                "quality": {},
            }
        ]
        service.correct_page(1, regions, page_text="今本創刊號出版")
        prompt = service._text_json.call_args.args[0]
        self._assert_faithfulness_constraints(prompt)
        self.assertIn("今本創刊號出版", prompt)

    def test_compose_page_and_transcribe_region_prompts_are_faithful(self):
        service = AIService.__new__(AIService)
        service.vision_model = "deepseek-flash"
        service.client = object()
        service._text_json = Mock(
            return_value={
                "corrected_text": "正文",
                "articles": [],
                "corrections": [],
                "warnings": [],
            }
        )
        service._vision_json = Mock(
            return_value={"text": "正文", "uncertain": "", "confidence": 0.9}
        )

        service.compose_page(1, [{"region_id": "r1", "text": "正文"}], page_text="正文")
        compose_prompt = service._text_json.call_args.args[0]
        self._assert_faithfulness_constraints(compose_prompt)

        service.transcribe_region(
            "crop.jpg",
            {"label": "body", "direction": "vertical-rtl"},
            page_number=1,
        )
        transcribe_prompt = service._vision_json.call_args.args[1]
        self._assert_faithfulness_constraints(transcribe_prompt)
        self.assertIn("〔待辨〕", transcribe_prompt)
        self.assertNotIn("Use □", transcribe_prompt)

    def _assert_faithfulness_constraints(self, prompt: str) -> None:
        self.assertIn("忠实誊录宪法", prompt)
        self.assertIn("〔待辨〕", prompt)
        self.assertIn("禁止改写", prompt)
        self.assertIn("禁止语义替换", prompt)
        self.assertIn("忠实度自检", prompt)
        self.assertIn("字形证据", prompt)
        # Classic customer failure modes must be explicitly banned.
        self.assertIn("今本", prompt)
        self.assertIn("今天", prompt)


if __name__ == "__main__":
    unittest.main()
