import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from layout_engine import LayoutEngine
from task_store import TaskStore
from workflow import DocumentWorkflow, WorkflowStateError
from ocr_engine import OCREngine, assess_quality, prepare_crop_for_ocr


class FakeOCR:
    backend = "fake-ocr"

    def recognize(self, image, direction):
        return {
            "full_text": f"识别文本-{direction}",
            "confidence": 0.9,
            "text_blocks": [],
        }


class FakeAI:
    available = True

    def correct_page(self, page_number, regions, page_text=""):
        return {
            "corrected_text": f"校正：{page_text}",
            "articles": [],
            "corrections": [],
            "warnings": [],
        }


class LayoutEngineTests(unittest.TestCase):
    def setUp(self):
        self.engine = LayoutEngine()

    def test_detects_two_by_two_ruled_grid(self):
        image = np.full((800, 600, 3), 255, dtype=np.uint8)
        cv2.rectangle(image, (40, 40), (560, 760), (0, 0, 0), 4)
        cv2.line(image, (300, 40), (300, 760), (0, 0, 0), 4)
        cv2.line(image, (40, 400), (560, 400), (0, 0, 0), 4)
        result = self.engine.propose(image, 1)
        self.assertEqual("grid", result["layout_type"])
        self.assertEqual(4, len(result["regions"]))
        self.assertTrue(all(region["label"] == "advertisement" for region in result["regions"]))

    def test_normalizes_user_regions(self):
        regions = self.engine.normalize_regions([{
            "id": "r1", "order": "2", "label": "body", "article_id": "article-a",
            "direction": "vertical-rtl", "bbox": {"x": -0.1, "y": 0.2, "width": 1.4, "height": 0.5},
        }])
        self.assertEqual(0.0, regions[0]["bbox"]["x"])
        self.assertEqual(1.0, regions[0]["bbox"]["width"])
        self.assertEqual(2, regions[0]["order"])

    def test_ocr_quality_flags_empty_and_low_confidence(self):
        result = assess_quality("", 0.0, 0)
        self.assertEqual("needs_review", result["status"])
        self.assertIn("empty", result["flags"])

    def test_vertical_preprocessing_changes_orientation(self):
        image = np.zeros((20, 40, 3), dtype=np.uint8)
        prepared = prepare_crop_for_ocr(image, "vertical-rtl")
        self.assertEqual((40, 20), prepared.shape[:2])

    def test_paddle_v3_result_maps_polygons_text_and_scores(self):
        class PaddleResult:
            json = {
                "res": {
                    "dt_polys": [[[1, 2], [11, 2], [11, 12], [1, 12]]],
                    "rec_texts": ["古籍文字"],
                    "rec_scores": [0.93],
                }
            }

        engine = OCREngine.__new__(OCREngine)
        blocks = engine._paddle_v3_blocks([PaddleResult()])

        self.assertEqual(1, len(blocks))
        self.assertEqual("古籍文字", blocks[0]["text"])
        self.assertEqual(0.93, blocks[0]["confidence"])
        self.assertEqual([[1.0, 2.0], [11.0, 2.0], [11.0, 12.0], [1.0, 12.0]], blocks[0]["bbox"])

    def test_paddle_v3_result_accepts_rectangle_boxes(self):
        engine = OCREngine.__new__(OCREngine)
        blocks = engine._paddle_v3_blocks([{
            "rec_boxes": [[2, 3, 18, 24]],
            "rec_texts": ["报纸"],
            "rec_scores": [0.8],
        }])

        self.assertEqual([[2.0, 3.0], [18.0, 3.0], [18.0, 24.0], [2.0, 24.0]], blocks[0]["bbox"])


class TaskStoreTests(unittest.TestCase):
    def test_create_save_and_load(self):
        with tempfile.TemporaryDirectory() as temp:
            store = TaskStore(Path(temp))
            task = store.create("sample.pdf", {"dpi": 180})
            task["status"] = "layout_running"
            store.save(task)
            loaded = store.load(task["id"])
            self.assertEqual("sample.pdf", loaded["source_name"])
            self.assertEqual("layout_running", loaded["status"])
            self.assertTrue((Path(temp) / task["id"] / "task.json").exists())


class DocumentWorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = TaskStore(Path(self.temp.name))
        self.workflow = DocumentWorkflow(self.store, FakeOCR(), FakeAI())
        self.task = self.store.create("sample.pdf", {"dpi": 180})
        self.task["pages"] = [self._page(1), self._page(2)]
        self.task["status"] = "awaiting_layout_review"
        self.store.save(self.task)
        pages_dir = self.store.task_dir(self.task["id"]) / "pages"
        pages_dir.mkdir()
        image = np.full((120, 120, 3), 255, dtype=np.uint8)
        cv2.imwrite(str(pages_dir / "page_001.png"), image)
        cv2.imwrite(str(pages_dir / "page_002.png"), image)

    def tearDown(self):
        self.temp.cleanup()

    @staticmethod
    def _page(number):
        return {
            "page_number": number,
            "width": 120,
            "height": 120,
            "image_url": f"/pages/{number}",
            "layout": {
                "regions": [{
                    "id": f"r{number}",
                    "order": 1,
                    "label": "body",
                    "article_id": f"article-{number}",
                    "direction": "vertical-rtl",
                    "bbox": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                }],
            },
        }

    def test_page_scoped_ocr_merges_results(self):
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1])
        self.workflow.run_ocr(task_id, [1])
        first = self.workflow.result(task_id, "ocr")
        self.assertEqual([1], [page["page_number"] for page in first["pages"]])

        self.workflow.queue_ocr(task_id, [2])
        self.workflow.run_ocr(task_id, [2])
        merged = self.workflow.result(task_id, "ocr")
        self.assertEqual([1, 2], [page["page_number"] for page in merged["pages"]])
        self.assertEqual([1, 2], self.store.load(task_id)["ocr"]["completed_pages"])

    def test_manual_edit_invalidates_only_that_pages_correction(self):
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1, 2])
        self.workflow.run_ocr(task_id, [1, 2])
        self.workflow.queue_correction(task_id, [1, 2])
        self.workflow.run_correction(task_id, [1, 2])

        result = self.workflow.update_ocr_text(task_id, [{"page_number": 1, "raw_text": "人工修订文本"}])
        page_one = next(page for page in result["pages"] if page["page_number"] == 1)
        corrected = self.workflow.result(task_id, "correction")
        self.assertEqual("人工修订文本", page_one["raw_text"])
        self.assertTrue(page_one["manually_edited"])
        self.assertEqual([2], [page["page_number"] for page in corrected["pages"]])
        self.assertIn("人工修订文本", corrected["full_text"])
        self.assertIn("校正：识别文本-vertical-rtl", corrected["full_text"])
        self.assertEqual("ocr_ready", self.store.load(task_id)["status"])

    def test_rejects_correction_for_page_without_ocr(self):
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1])
        self.workflow.run_ocr(task_id, [1])
        with self.assertRaises(WorkflowStateError):
            self.workflow.queue_correction(task_id, [2])

    def test_manual_correction_draft_becomes_document_text(self):
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1])
        self.workflow.run_ocr(task_id, [1])
        self.workflow.update_ocr_text(task_id, [{"page_number": 1, "raw_text": "人工修订原文"}])
        self.workflow.queue_correction(task_id, [1])
        self.workflow.run_correction(task_id, [1])
        generated = self.workflow.result(task_id, "correction")["pages"][0]
        self.assertEqual("校正：人工修订原文", generated["corrected_text"])

        saved = self.workflow.update_corrected_text(task_id, [{"page_number": 1, "corrected_text": "人工最终定稿"}])
        self.assertTrue(saved["pages"][0]["manually_edited"])
        self.assertIn("人工最终定稿", self.workflow.document_text(task_id))


if __name__ == "__main__":
    unittest.main()
