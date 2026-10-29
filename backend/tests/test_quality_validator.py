import unittest

from quality_validator import QualityValidator


class QualityValidatorTests(unittest.TestCase):
    def test_validates_nested_layout_and_ocr_results(self):
        task = {
            "pages": [
                {
                    "page_number": 1,
                    "layout": {
                        "source": "ai+computer-vision",
                        "regions": [{"id": "layout-region", "label": "body"}],
                    },
                }
            ],
            "ocr_result": {
                "pages": [
                    {
                        "page_number": 1,
                        "regions": [
                            {
                                "region_id": "body-region",
                                "label": "body",
                                "article_id": "article-1",
                                "raw_text": "local draft",
                                "final_region_text": "visual transcription",
                                "visual_confidence": 0.8,
                            },
                            {
                                "region_id": "ignored-region",
                                "label": "ignore",
                                "article_id": "ignored-article",
                                "raw_text": "",
                            },
                        ],
                    }
                ],
            },
        }

        report = QualityValidator().validate_task(task)

        self.assertEqual(1, report["completeness"]["total_regions"])
        self.assertEqual(1, report["completeness"]["processed_regions"])
        self.assertEqual(1.0, report["completeness"]["score"])
        self.assertEqual(len("visual transcription"), report["accuracy"]["total_chars"])
        self.assertEqual(0.8, report["accuracy"]["avg_confidence"])
        self.assertEqual(1.0, report["layout_quality"]["score"])
        self.assertEqual(1, report["article_quality"]["total_articles"])
        self.assertFalse(report["passed"])


if __name__ == "__main__":
    unittest.main()
