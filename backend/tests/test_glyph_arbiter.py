import unittest
from unittest.mock import Mock

from ai_service import UNCERTAIN_MARK
from glyph_arbiter import GlyphArbiter, majority_vote


class MajorityVoteTests(unittest.TestCase):
    def test_majority_wins(self):
        result = majority_vote(["組", "組", "租"])
        self.assertEqual("組", result["glyph"])
        self.assertEqual("majority-vote", result["source"])

    def test_tie_is_uncertain(self):
        result = majority_vote(["組", "租"])
        self.assertEqual(UNCERTAIN_MARK, result["glyph"])
        self.assertEqual("vote-tie", result["source"])

    def test_empty(self):
        result = majority_vote([])
        self.assertEqual(UNCERTAIN_MARK, result["glyph"])


class GlyphArbiterTests(unittest.TestCase):
    def test_single_candidate_skips_vision(self):
        ai = Mock()
        ai.supports_vision = True
        arbiter = GlyphArbiter(ai)
        result = arbiter.arbitrate("crop.jpg", ["組織"])
        self.assertEqual("組織", result["glyph"])
        self.assertEqual("single-candidate", result["source"])
        ai._vision_json.assert_not_called()

    def test_vision_unavailable_returns_uncertain(self):
        ai = Mock()
        ai.supports_vision = False
        arbiter = GlyphArbiter(ai)
        result = arbiter.arbitrate("crop.jpg", ["組", "租"])
        self.assertEqual(UNCERTAIN_MARK, result["glyph"])
        self.assertEqual("vision-unavailable", result["source"])

    def test_candidate_constrained_arbitration(self):
        ai = Mock()
        ai.supports_vision = True
        ai._vision_json = Mock(
            return_value={"glyph": "組織", "confidence": 0.92, "reason": "糸旁可見"}
        )
        arbiter = GlyphArbiter(ai, min_confidence=0.75)
        result = arbiter.arbitrate("crop.jpg", ["組織", "租酸"])
        self.assertEqual("組織", result["glyph"])
        self.assertEqual("vlm-candidates", result["source"])
        prompt = ai._vision_json.call_args.args[1]
        self.assertIn("只根据笔画", prompt)
        self.assertIn("組織", prompt)
        self.assertIn("租酸", prompt)
        self.assertIn(UNCERTAIN_MARK, prompt)

    def test_low_confidence_becomes_uncertain(self):
        ai = Mock()
        ai.supports_vision = True
        ai._vision_json = Mock(
            return_value={"glyph": "組織", "confidence": 0.4, "reason": "模糊"}
        )
        arbiter = GlyphArbiter(ai, min_confidence=0.75)
        result = arbiter.arbitrate("crop.jpg", ["組織", "租酸"])
        self.assertEqual(UNCERTAIN_MARK, result["glyph"])

    def test_out_of_candidate_rejected(self):
        ai = Mock()
        ai.supports_vision = True
        ai._vision_json = Mock(
            return_value={"glyph": "编造字", "confidence": 0.99, "reason": "猜的"}
        )
        arbiter = GlyphArbiter(ai)
        result = arbiter.arbitrate("crop.jpg", ["組織", "租酸"])
        self.assertEqual(UNCERTAIN_MARK, result["glyph"])


if __name__ == "__main__":
    unittest.main()
