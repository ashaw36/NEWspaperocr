import unittest

from coverage import build_region_index, check_coverage, mark_transcribed


class CoverageIndexTests(unittest.TestCase):
    def test_builds_p01_b01_c01_l01_style_ids(self):
        regions = [
            {
                "region_id": "r1",
                "order": 1,
                "article_id": "a1",
                "label": "title",
                "raw_text": "標題一行\n標題二行",
            },
            {
                "region_id": "r2",
                "order": 2,
                "article_id": "a1",
                "label": "body",
                "raw_text": "正文",
            },
        ]
        index = build_region_index(1, regions)
        self.assertEqual("P01-B01", index[0]["index_id"])
        self.assertEqual("P01-B01-C01", index[0]["column_id"])
        self.assertEqual("P01-B01-C01-L01", index[0]["lines"][0]["index_id"])
        self.assertEqual("P01-B01-C01-L02", index[0]["lines"][1]["index_id"])
        self.assertEqual("P01-B02", index[1]["index_id"])
        self.assertEqual("P01-B02-C02", index[1]["column_id"])

    def test_missing_region_emits_warning(self):
        regions = [
            {
                "region_id": "r1",
                "order": 1,
                "article_id": "a1",
                "label": "body",
                "raw_text": "有字",
            },
            {
                "region_id": "r2",
                "order": 2,
                "article_id": "a1",
                "label": "body",
                "raw_text": "也有字",
            },
        ]
        index = build_region_index(2, regions)
        mark_transcribed(index, ["r1"])  # r2 未誊录
        report = check_coverage(index)
        self.assertFalse(report["ok"])
        self.assertEqual(1, report["missing_regions"])
        self.assertTrue(any("P02-B02" in w for w in report["warnings"]))

    def test_full_coverage_ok(self):
        regions = [
            {
                "region_id": "r1",
                "order": 1,
                "article_id": "a1",
                "label": "body",
                "raw_text": "全文",
            }
        ]
        index = build_region_index(1, regions)
        mark_transcribed(index, ["r1"])
        report = check_coverage(index)
        self.assertTrue(report["ok"])
        self.assertEqual([], report["warnings"])
        self.assertEqual(1.0, report["coverage_ratio"])


if __name__ == "__main__":
    unittest.main()
