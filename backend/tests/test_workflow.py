import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from layout_engine import LayoutEngine
from task_store import TaskStore
from workflow import DocumentWorkflow, WorkflowStateError
from ocr_engine import OCREngine, assess_quality, prepare_crop_for_ocr
from ai_service import AIInsufficientBalanceError


class FakeOCR:
    backend = "fake-ocr"

    def recognize(self, image, direction):
        return {
            "full_text": f"识别文本-{direction}",
            "confidence": 0.9,
            "text_blocks": [],
        }

    def recognize_whole_page(self, image, direction="vertical-rtl"):
        return {
            "blocks": [],
            "full_text": f"整页-{direction}",
            "total_blocks": 0,
            "confidence": 0.9,
            "quality": {"status": "pass", "score": 0.9, "flags": []},
            "engine": self.backend,
        }


class ColumnOrderFakeOCR:
    """模拟竖排裁剪旋转后的 OCR：按旋转图中从左到右返回块（对应原图上→下）。"""

    backend = "fake-column-ocr"

    def recognize(self, image, direction):
        height, width = image.shape[:2]
        # 旋转后水平图：左=原上、右=原下。故意乱序喂入，引擎侧应再按水平排序。
        raw_blocks = [
            {
                "block_id": 1,
                "text": "下",
                "confidence": 0.95,
                "bbox": [
                    [width * 0.7, height * 0.2],
                    [width * 0.9, height * 0.2],
                    [width * 0.9, height * 0.8],
                    [width * 0.7, height * 0.8],
                ],
            },
            {
                "block_id": 2,
                "text": "上",
                "confidence": 0.95,
                "bbox": [
                    [width * 0.1, height * 0.2],
                    [width * 0.3, height * 0.2],
                    [width * 0.3, height * 0.8],
                    [width * 0.1, height * 0.8],
                ],
            },
        ]
        # 与 OCREngine.recognize 一致：竖排已旋转，按 horizontal-ltr 排
        sort_dir = "horizontal-ltr" if direction == "vertical-rtl" else direction

        def center(block):
            points = block["bbox"]
            return (
                sum(p[0] for p in points) / len(points),
                sum(p[1] for p in points) / len(points),
            )

        if sort_dir == "vertical-rtl":
            ordered = sorted(raw_blocks, key=lambda b: (-center(b)[0], center(b)[1]))
        else:
            ordered = sorted(raw_blocks, key=lambda b: (center(b)[1], center(b)[0]))
        for index, block in enumerate(ordered, 1):
            block["reading_order"] = index
        full_text = "\n".join(block["text"] for block in ordered)
        return {
            "full_text": full_text,
            "confidence": 0.95,
            "text_blocks": ordered,
            "total_blocks": len(ordered),
            "quality": {"status": "pass", "score": 0.95, "flags": []},
            "engine": self.backend,
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
        self.assertTrue(
            all(region["label"] == "advertisement" for region in result["regions"])
        )

    def test_normalizes_user_regions(self):
        regions = self.engine.normalize_regions(
            [
                {
                    "id": "r1",
                    "order": "2",
                    "label": "body",
                    "article_id": "article-a",
                    "direction": "vertical-rtl",
                    "bbox": {"x": -0.1, "y": 0.2, "width": 1.4, "height": 0.5},
                }
            ]
        )
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

    def test_wholepage_bbox_maps_from_rotate_90_cw(self):
        # Original H=100; rotated point (xr=10, yr=30) → original (30, 90)
        mapped = OCREngine._map_bbox_from_rotate_90_cw([[10.0, 30.0]], orig_h=100)
        self.assertEqual([[30.0, 90.0]], mapped)
        # Top-left of original (0,0) → after 90CW ≈ (H, 0) in continuous map;
        # inverse of (xr=H, yr=0) recovers (0, 0).
        mapped_origin = OCREngine._map_bbox_from_rotate_90_cw(
            [[100.0, 0.0]], orig_h=100
        )
        self.assertEqual([[0.0, 0.0]], mapped_origin)

    def test_map_blocks_to_layout_regions_orders_vertical_rtl(self):
        # Page 100x100; right column region then left; blocks intentionally shuffled.
        layout_regions = [
            {
                "id": "right",
                "order": 1,
                "label": "body",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "bbox": {"x": 0.5, "y": 0.0, "width": 0.5, "height": 1.0},
            },
            {
                "id": "left",
                "order": 2,
                "label": "body",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "bbox": {"x": 0.0, "y": 0.0, "width": 0.5, "height": 1.0},
            },
        ]
        blocks = [
            {
                "block_id": 1,
                "text": "右下",
                "confidence": 0.9,
                "bbox": [[70, 70], [80, 70], [80, 80], [70, 80]],
            },
            {
                "block_id": 2,
                "text": "左上",
                "confidence": 0.9,
                "bbox": [[10, 10], [20, 10], [20, 20], [10, 20]],
            },
            {
                "block_id": 3,
                "text": "右上",
                "confidence": 0.9,
                "bbox": [[70, 10], [80, 10], [80, 20], [70, 20]],
            },
            {
                "block_id": 4,
                "text": "左下",
                "confidence": 0.9,
                "bbox": [[10, 70], [20, 70], [20, 80], [10, 80]],
            },
        ]
        mapped = DocumentWorkflow._map_blocks_to_layout_regions(
            blocks, layout_regions, page_width=100, page_height=100,
            page_direction="vertical-rtl",
        )
        by_id = {region["region_id"]: region for region in mapped}
        self.assertEqual(["右上", "右下"], [b["text"] for b in by_id["right"]["text_blocks"]])
        self.assertEqual(["左上", "左下"], [b["text"] for b in by_id["left"]["text_blocks"]])
        self.assertEqual("右上\n右下", by_id["right"]["raw_text"])
        self.assertEqual("a1", by_id["right"]["article_id"])

    def test_unhit_block_assigns_to_nearest_region(self):
        layout_regions = [
            {
                "id": "r1",
                "order": 1,
                "label": "body",
                "article_id": "a1",
                "direction": "horizontal-ltr",
                "bbox": {"x": 0.0, "y": 0.0, "width": 0.4, "height": 0.4},
            }
        ]
        # Center (90,90) is outside the region; nearest is still r1.
        blocks = [
            {
                "block_id": 1,
                "text": "外",
                "confidence": 0.8,
                "bbox": [[85, 85], [95, 85], [95, 95], [85, 95]],
            }
        ]
        mapped = DocumentWorkflow._map_blocks_to_layout_regions(
            blocks, layout_regions, 100, 100, "horizontal-ltr"
        )
        self.assertEqual(1, len(mapped))
        self.assertEqual(["外"], [b["text"] for b in mapped[0]["text_blocks"]])
        self.assertEqual("r1", blocks[0]["region_id"])

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
        self.assertEqual(
            [[1.0, 2.0], [11.0, 2.0], [11.0, 12.0], [1.0, 12.0]], blocks[0]["bbox"]
        )

    def test_paddle_v3_result_accepts_rectangle_boxes(self):
        engine = OCREngine.__new__(OCREngine)
        blocks = engine._paddle_v3_blocks(
            [
                {
                    "rec_boxes": [[2, 3, 18, 24]],
                    "rec_texts": ["报纸"],
                    "rec_scores": [0.8],
                }
            ]
        )

        self.assertEqual(
            [[2.0, 3.0], [18.0, 3.0], [18.0, 24.0], [2.0, 24.0]], blocks[0]["bbox"]
        )


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
                "regions": [
                    {
                        "id": f"r{number}",
                        "order": 1,
                        "label": "body",
                        "article_id": f"article-{number}",
                        "direction": "vertical-rtl",
                        "bbox": {"x": 0.1, "y": 0.1, "width": 0.8, "height": 0.8},
                    }
                ],
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

        result = self.workflow.update_ocr_text(
            task_id, [{"page_number": 1, "raw_text": "人工修订文本"}]
        )
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
        self.workflow.update_ocr_text(
            task_id, [{"page_number": 1, "raw_text": "人工修订原文"}]
        )
        self.workflow.queue_correction(task_id, [1])
        self.workflow.run_correction(task_id, [1])
        generated = self.workflow.result(task_id, "correction")["pages"][0]
        self.assertEqual("校正：人工修订原文", generated["corrected_text"])

        saved = self.workflow.update_corrected_text(
            task_id, [{"page_number": 1, "corrected_text": "人工最终定稿"}]
        )
        self.assertTrue(saved["pages"][0]["manually_edited"])
        self.assertIn("人工最终定稿", self.workflow.document_text(task_id))

    def test_failed_ai_correction_keeps_ocr_text_available(self):
        class BalanceLimitedAI(FakeAI):
            def correct_page(self, page_number, regions, page_text=""):
                raise AIInsufficientBalanceError("AI 服务账户余额不足")

        self.workflow.ai = BalanceLimitedAI()
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1])
        self.workflow.run_ocr(task_id, [1])
        self.workflow.queue_correction(task_id, [1])
        self.workflow.run_correction(task_id, [1])

        failed_task = self.store.load(task_id)
        ocr_result = self.workflow.result(task_id, "ocr")
        self.assertEqual("failed", failed_task["status"])
        self.assertEqual("correction", failed_task["stage"])
        self.assertIn("余额不足", failed_task["error"]["message"])
        self.assertEqual([1], failed_task["ocr"]["completed_pages"])
        self.assertTrue(ocr_result["full_text"])
        self.assertTrue((self.store.task_dir(task_id) / "raw.txt").exists())

    def test_columnwise_vertical_region_reads_top_to_bottom(self):
        """单列竖排：旋转后 OCR 块按上→下排序。"""
        self.workflow.ocr = ColumnOrderFakeOCR()
        self.task["options"]["ocr_mode"] = "columnwise"
        self.store.save(self.task)
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1])
        self.workflow.run_columnwise_ocr(task_id, [1])
        result = self.workflow.result(task_id, "ocr")
        region = result["pages"][0]["regions"][0]
        self.assertEqual("上\n下", region["raw_text"])
        self.assertEqual(
            ["上", "下"], [block["text"] for block in region["text_blocks"]]
        )
        self.assertEqual("columnwise-regions", result["pages"][0]["structure_source"])
        self.assertEqual("columnwise", self.store.load(task_id)["ocr"]["mode"])

    def test_columnwise_joins_regions_by_order_right_to_left(self):
        """多列按 region.order（右→左）拼接；栏内各自上→下。"""
        self.workflow.ocr = ColumnOrderFakeOCR()
        self.task["options"]["ocr_mode"] = "columnwise"
        self.task["pages"][0]["layout"]["regions"] = [
            {
                "id": "right",
                "order": 1,
                "label": "body",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "bbox": {"x": 0.55, "y": 0.1, "width": 0.35, "height": 0.8},
            },
            {
                "id": "left",
                "order": 2,
                "label": "body",
                "article_id": "a1",
                "direction": "vertical-rtl",
                "bbox": {"x": 0.1, "y": 0.1, "width": 0.35, "height": 0.8},
            },
        ]
        self.store.save(self.task)
        task_id = self.task["id"]
        self.workflow.queue_ocr(task_id, [1])
        self.workflow.run_columnwise_ocr(task_id, [1])
        result = self.workflow.result(task_id, "ocr")
        page = result["pages"][0]
        by_id = {region["region_id"]: region for region in page["regions"]}
        self.assertEqual("上\n下", by_id["right"]["raw_text"])
        self.assertEqual("上\n下", by_id["left"]["raw_text"])
        self.assertEqual("上\n下\n\n上\n下", page["raw_text"])
        self.assertEqual(
            ["right", "left"], [region["region_id"] for region in page["regions"]]
        )

    def test_map_crop_blocks_to_page_undoes_vertical_rotation(self):
        # Crop at (10, 20), size 40x100; rotated point (xr=10, yr=30) → crop (30, 90)
        # → page (40, 110)
        blocks = [
            {
                "text": "字",
                "confidence": 0.9,
                "bbox": [[10.0, 30.0], [12.0, 30.0], [12.0, 40.0], [10.0, 40.0]],
            }
        ]
        mapped = DocumentWorkflow._map_crop_blocks_to_page(
            blocks,
            {"x": 10, "y": 20, "width": 40, "height": 100},
            "vertical-rtl",
        )
        self.assertEqual(
            [[40.0, 110.0], [40.0, 108.0], [50.0, 108.0], [50.0, 110.0]],
            mapped[0]["bbox"],
        )


if __name__ == "__main__":
    unittest.main()
