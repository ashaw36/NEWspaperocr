import unittest
from unittest.mock import Mock

from ocr_engine import OCREngine, align_ocr_chars


class AlignOcrCharsTests(unittest.TestCase):
    def test_identical_no_conflict(self):
        result = align_ocr_chars(
            "組織活動", "組織活動", name_a="rapid", name_b="paddle"
        )
        self.assertEqual(0, result["conflict_count"])
        self.assertEqual("組織活動", result["consensus_text"])

    def test_detects_char_conflict(self):
        result = align_ocr_chars("組織", "租酸", name_a="rapid", name_b="paddle")
        self.assertGreaterEqual(result["conflict_count"], 1)
        self.assertTrue(all(c.get("conflict") for c in result["conflicts"]))
        for conflict in result["conflicts"]:
            self.assertIn("candidates", conflict)
            self.assertEqual("low", conflict["confidence_hint"])

    def test_ignores_whitespace(self):
        result = align_ocr_chars("組 織", "組織", name_a="a", name_b="b")
        self.assertEqual(0, result["conflict_count"])


class RecognizeConsensusTests(unittest.TestCase):
    def test_without_secondary_returns_primary(self):
        engine = OCREngine.__new__(OCREngine)
        engine.backend = "rapidocr"
        engine.secondary_engine = None
        engine.secondary_backend = None
        engine.recognize = Mock(
            return_value={
                "full_text": "組織",
                "confidence": 0.9,
                "text_blocks": [],
                "quality": {"flags": []},
            }
        )
        result = engine.recognize_consensus("img", "horizontal-ltr")
        self.assertEqual(["rapidocr"], result["engines"])
        self.assertEqual([], result["conflicts"])
        self.assertEqual("組織", result["full_text"])

    def test_with_secondary_marks_conflicts(self):
        engine = OCREngine.__new__(OCREngine)
        engine.backend = "rapidocr"
        engine.secondary_backend = "paddleocr"
        secondary = Mock()
        secondary.recognize = Mock(
            return_value={"full_text": "租酸", "confidence": 0.8, "text_blocks": []}
        )
        engine.secondary_engine = secondary
        engine.recognize = Mock(
            return_value={
                "full_text": "組織",
                "confidence": 0.95,
                "text_blocks": [],
                "quality": {"flags": []},
            }
        )
        result = engine.recognize_consensus("img", "horizontal-ltr")
        self.assertEqual(["rapidocr", "paddleocr"], result["engines"])
        self.assertGreaterEqual(len(result["conflicts"]), 1)
        self.assertIn("engine-conflict", result["quality"]["flags"])
        self.assertLessEqual(result["confidence"], 0.7)


if __name__ == "__main__":
    unittest.main()
