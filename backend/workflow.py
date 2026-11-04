"""Stateful, reviewable newspaper recognition workflow."""

from __future__ import annotations

import inspect
import json
import traceback
from difflib import SequenceMatcher
from pathlib import Path
from typing import Callable, Dict, List

import cv2

from aggregation_quality import OK_THRESHOLD, score_aggregation
from ai_service import AIService
from column_segmenter import segment_columns
from correction import apply_page_correction, get_corrector
from image_io import read_image, write_image
from layout_engine import LayoutEngine
from ocr_engine import OCREngine, assess_quality, prepare_crop_for_ocr
from pdf_processor import PDFProcessor
from task_store import TaskStore, utc_now

# LLM 聚合非确定性兜底：最多重试次数（含首次）。
AGGREGATE_MAX_ATTEMPTS = 3
AGGREGATE_RETRY_HINT = (
    "上次聚合质量不佳，请更严格按列从右到左、栏内从上到下排序，"
    "标题应为完整短语，避免截取以「之」「、」「，」等结尾的悬空片段，"
    "正文应连贯成段而非单字碎片。"
)


class WorkflowStateError(RuntimeError):
    pass


class DocumentWorkflow:
    def __init__(self, store: TaskStore, ocr: OCREngine, ai: AIService):
        self.store, self.ocr, self.ai = store, ocr, ai
        self.layout = LayoutEngine()

    def analyze_layout(
        self, task_id: str, max_pages_override: int | None = None
    ) -> None:
        try:
            task = self.store.load(task_id)
            task.update(status="layout_running", stage="layout", error=None)
            self.store.save(task)
            task_dir = self.store.task_dir(task_id)
            processor = PDFProcessor(dpi=int(task["options"].get("dpi", 180)))
            document_page_count = processor.page_count(task["source_path"])
            requested_limit = max_pages_override or task["options"].get("max_pages")
            if requested_limit is None and not task["options"].get("layout_expanded"):
                requested_limit = 1
            pages = processor.render_document(
                task["source_path"],
                task_dir / "pages",
                max_pages=requested_limit or None,
            )
            task["document_page_count"] = document_page_count
            task["progress"] = {
                "current": 0,
                "total": len(pages),
                "message": "正在分析页面结构",
            }
            self.store.save(task)

            existing_pages = {
                page["page_number"]: page for page in task.get("pages", [])
            }
            planned = []
            warnings = []
            use_ai = bool(task["options"].get("ai_layout", True)) and getattr(
                self.ai, "supports_vision", False
            )
            layout_ai_success = 0
            layout_ai_failed = 0
            for index, page in enumerate(pages, 1):
                image = read_image(page["path"])
                prior_layout = existing_pages.get(page["page_number"], {}).get("layout")
                proposal = prior_layout or self.layout.propose(
                    image, page["page_number"]
                )
                if use_ai and (
                    prior_layout is None
                    or prior_layout.get("source") != "user-reviewed"
                ):
                    try:
                        enriched = self.ai.enrich_layout(page["path"], proposal)
                        enriched["regions"] = self.layout.normalize_regions(
                            enriched.get("regions", proposal["regions"])
                        )
                        proposal = enriched
                        proposal["source"] = "ai+computer-vision"
                        layout_ai_success += 1
                    except Exception as error:
                        layout_ai_failed += 1
                        warnings.append(
                            f"Page {page['page_number']} AI layout review failed: {error}"
                        )
                page_record = {
                    "page_number": page["page_number"],
                    "width": page["width"],
                    "height": page["height"],
                    "image_url": f"/api/tasks/{task_id}/pages/{page['page_number']}/image",
                    "layout": proposal,
                }
                planned.append(page_record)
                task["pages"] = planned
                task["progress"] = {
                    "current": index,
                    "total": len(pages),
                    "message": f"已分析第 {index}/{len(pages)} 页",
                }
                self.store.save(task)

            task.update(
                pages=planned,
                status="awaiting_layout_review",
                stage="layout",
                confirmed=False,
                warnings=warnings,
                progress={
                    "current": len(pages),
                    "total": len(pages),
                    "message": "请检查并确认 OCR 窗口",
                },
            )
            task["layout_quality"] = {
                "mode": (
                    "vision-reviewed"
                    if layout_ai_success
                    else "computer-vision-fallback"
                ),
                "vision_succeeded": layout_ai_success,
                "vision_failed": layout_ai_failed,
            }
            if max_pages_override:
                task["options"]["layout_expanded"] = True
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "layout", error)

    def expand_layout(self, task_id: str) -> None:
        task = self.store.load(task_id)
        if task.get("status") in {
            "layout_running",
            "ocr_running",
            "correction_running",
        }:
            raise WorkflowStateError("The task is currently running")
        total = int(task.get("document_page_count") or 1)
        task["options"]["layout_expanded"] = True
        task["options"]["layout_target_pages"] = total
        return self.store.save(task)

    def save_layout(self, task_id: str, page_updates: List[Dict]) -> Dict:
        task = self.store.load(task_id)
        if task["status"] in {"layout_running", "ocr_running", "correction_running"}:
            raise WorkflowStateError("The task is currently running")
        updates = {int(page["page_number"]): page for page in page_updates}
        for page in task.get("pages", []):
            incoming = updates.get(page["page_number"])
            if not incoming:
                continue
            page["layout"]["regions"] = self.layout.normalize_regions(
                incoming.get("regions", [])
            )
            page["layout"]["source"] = "user-reviewed"
        task.update(
            status="awaiting_layout_review", stage="layout", confirmed=False, error=None
        )
        return self.store.save(task)

    def queue_ocr(self, task_id: str, page_numbers: List[int] | None = None) -> Dict:
        task = self.store.load(task_id)
        if not task.get("pages"):
            raise WorkflowStateError("Layout analysis is not complete")
        if task["status"] in {"layout_running", "ocr_running", "correction_running"}:
            raise WorkflowStateError("The task is currently running")
        available = {page["page_number"] for page in task["pages"]}
        requested = sorted(set(page_numbers or available))
        if not requested or not set(requested).issubset(available):
            raise WorkflowStateError("OCR page selection is invalid")
        ocr_mode = task.get("options", {}).get("ocr_mode", "regions")
        task.update(
            status="ocr_queued",
            stage="ocr",
            confirmed=True,
            error=None,
            ocr_request={"page_numbers": requested, "ocr_mode": ocr_mode},
        )
        return self.store.save(task)

    def run_ocr(self, task_id: str, page_numbers: List[int] | None = None) -> None:
        task = self.store.load(task_id)
        ocr_mode = task.get("options", {}).get("ocr_mode", "regions")
        if ocr_mode == "columnwise":
            return self.run_columnwise_ocr(task_id, page_numbers)
        if ocr_mode == "wholepage":
            return self.run_wholepage_ocr(task_id, page_numbers)
        try:
            task = self.store.load(task_id)
            requested = sorted(
                set(
                    page_numbers
                    or task.get("ocr_request", {}).get("page_numbers")
                    or [page["page_number"] for page in task["pages"]]
                )
            )
            selected_pages = [
                page for page in task["pages"] if page["page_number"] in requested
            ]
            task.update(status="ocr_running", stage="ocr", error=None)
            regions_total = sum(
                1
                for page in selected_pages
                for region in page["layout"]["regions"]
                if region["label"] != "ignore"
            )
            task["progress"] = {
                "current": 0,
                "total": regions_total,
                "message": "正在识别已确认的 OCR 窗口",
            }
            self.store.save(task)

            result_path = self.store.task_dir(task_id) / "ocr.json"
            previous = (
                self._read_json(task_id, "ocr.json")
                if result_path.exists()
                else {"pages": []}
            )
            page_results = {
                page["page_number"]: page for page in previous.get("pages", [])
            }
            completed = 0
            crops_dir = self.store.task_dir(task_id) / "crops"
            crops_dir.mkdir(exist_ok=True)
            for page in selected_pages:
                image_path = (
                    self.store.task_dir(task_id)
                    / "pages"
                    / f"page_{page['page_number']:03d}.png"
                )
                image = read_image(image_path)
                if image is None:
                    raise RuntimeError(
                        f"Cannot load rendered page {page['page_number']}"
                    )
                page_regions = []
                for region in sorted(
                    page["layout"]["regions"], key=lambda item: item["order"]
                ):
                    if region["label"] == "ignore":
                        continue
                    crop, pixel_box = self._crop(image, region["bbox"])
                    prepared = prepare_crop_for_ocr(crop, region["direction"])
                    crop_path = (
                        crops_dir / f"p{page['page_number']:03d}_{region['id']}.png"
                    )
                    if not write_image(crop_path, crop):
                        raise RuntimeError(f"Cannot save OCR crop: {crop_path.name}")
                    recognition = self.ocr.recognize(prepared, region["direction"])
                    visual = None
                    vision_error = None
                    if getattr(self.ai, "supports_vision", False) and hasattr(
                        self.ai, "transcribe_region"
                    ):
                        try:
                            visual = self.ai.transcribe_region(
                                crop_path, region, page["page_number"]
                            )
                        except Exception as error:
                            vision_error = str(error)
                    visual_text = visual["text"] if visual else ""
                    chosen_text = (
                        visual_text if visual_text else recognition["full_text"]
                    )
                    disagreements = (
                        self._texts_disagree(visual_text, recognition["full_text"])
                        if visual_text
                        else False
                    )
                    quality = recognition.get(
                        "quality",
                        {
                            "status": "unknown",
                            "score": recognition["confidence"],
                            "flags": [],
                        },
                    )
                    if visual and visual.get("text"):
                        visual_confidence = float(visual.get("confidence") or 0)
                        quality = {
                            "status": (
                                "needs_review"
                                if visual.get("uncertain") or disagreements
                                else ("check" if visual_confidence < 0.75 else "pass")
                            ),
                            "score": round(visual_confidence, 4),
                            "flags": (
                                ["vision-uncertain"] if visual.get("uncertain") else []
                            )
                            + (["ocr-disagreement"] if disagreements else []),
                        }
                    page_regions.append(
                        {
                            "region_id": region["id"],
                            "order": region["order"],
                            "label": region["label"],
                            "article_id": region["article_id"],
                            "direction": region["direction"],
                            "bbox": region["bbox"],
                            "pixel_bbox": pixel_box,
                            "raw_text": recognition["full_text"],
                            "visual_text": visual["text"] if visual else "",
                            "final_region_text": chosen_text,
                            "visual_confidence": (
                                visual.get("confidence") if visual else None
                            ),
                            "visual_uncertain": (
                                visual.get("uncertain", "") if visual else ""
                            ),
                            "vision_error": vision_error,
                            "confidence": recognition["confidence"],
                            "quality": quality,
                            "text_blocks": recognition["text_blocks"],
                            "crop_url": f"/api/tasks/{task_id}/crops/{crop_path.name}",
                        }
                    )
                    completed += 1
                    task["progress"] = {
                        "current": completed,
                        "total": regions_total,
                        "message": f"正在识别第 {page['page_number']} 页窗口 {region['order']}",
                    }
                    self.store.save(task)
                page_text = "\n\n".join(
                    item["raw_text"] for item in page_regions if item["raw_text"]
                )
                visual_page_text = "\n\n".join(
                    item["final_region_text"]
                    for item in sorted(page_regions, key=lambda item: item["order"])
                    if item["final_region_text"]
                )
                page_results[page["page_number"]] = {
                    "page_number": page["page_number"],
                    "regions": page_regions,
                    "raw_text": page_text,
                    "visual_text": visual_page_text,
                }
                result = self._save_ocr_result(task_id, list(page_results.values()))
                task["ocr"] = {
                    "pages": len(result["pages"]),
                    "regions": sum(len(item["regions"]) for item in result["pages"]),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                }
                self.store.save(task)

            result = self._save_ocr_result(task_id, list(page_results.values()))
            visual_regions = sum(
                1
                for page in result["pages"]
                for region in page["regions"]
                if region.get("visual_text")
            )
            vision_failures = sum(
                1
                for page in result["pages"]
                for region in page["regions"]
                if region.get("vision_error")
            )
            task.update(
                status="ocr_ready",
                stage="ocr",
                ocr={
                    "pages": len(result["pages"]),
                    "regions": sum(len(item["regions"]) for item in result["pages"]),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                },
                recognition_quality={
                    "vision_regions": visual_regions,
                    "vision_failures": vision_failures,
                    "mode": (
                        "vision-primary-with-local-crosscheck"
                        if visual_regions
                        else "local-ocr-fallback"
                    ),
                },
                progress={
                    "current": regions_total,
                    "total": regions_total,
                    "message": "识别完成，可查看视觉转录与本地 OCR 对照",
                },
            )
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "ocr", error)

    def run_wholepage_ocr(
        self, task_id: str, page_numbers: List[int] | None = None
    ) -> None:
        """整页 OCR + 视觉版面映射（或投影分栏回退）+ AI 文章聚合。"""
        try:
            task = self.store.load(task_id)
            requested = sorted(
                set(
                    page_numbers
                    or task.get("ocr_request", {}).get("page_numbers")
                    or [page["page_number"] for page in task["pages"]]
                )
            )
            selected_pages = [
                page for page in task["pages"] if page["page_number"] in requested
            ]
            direction = task.get("options", {}).get("reading_direction") or (
                selected_pages[0]
                .get("layout", {})
                .get("reading_direction", "vertical-rtl")
                if selected_pages
                else "vertical-rtl"
            )
            task["options"]["mode"] = "wholepage"
            task.update(status="ocr_running", stage="ocr", error=None)
            task["progress"] = {
                "current": 0,
                "total": len(selected_pages),
                "message": "正在进行整页识别",
            }
            self.store.save(task)

            result_path = self.store.task_dir(task_id) / "ocr.json"
            previous = (
                self._read_json(task_id, "ocr.json")
                if result_path.exists()
                else {"pages": []}
            )
            page_results = {
                page["page_number"]: page for page in previous.get("pages", [])
            }
            corrected_path = self.store.task_dir(task_id) / "corrected.json"
            previous_corrected = (
                self._read_json(task_id, "corrected.json")
                if corrected_path.exists()
                else {"pages": []}
            )
            corrected_by_page = {
                page["page_number"]: page
                for page in previous_corrected.get("pages", [])
            }
            ai_aggregated = 0
            layout_mapped_pages = 0

            for index, page in enumerate(selected_pages, 1):
                image_path = (
                    self.store.task_dir(task_id)
                    / "pages"
                    / f"page_{page['page_number']:03d}.png"
                )
                image = read_image(image_path)
                if image is None:
                    raise RuntimeError(
                        f"Cannot load rendered page {page['page_number']}"
                    )

                page_direction = (
                    page.get("layout", {}).get("reading_direction") or direction
                )
                recognition = self.ocr.recognize_whole_page(image, page_direction)
                blocks = recognition["blocks"]
                page_h, page_w = image.shape[:2]
                layout_regions = list((page.get("layout") or {}).get("regions") or [])

                columns: List[Dict] = []
                structure_source = "columns"
                if layout_regions:
                    mapped_regions = self._map_blocks_to_layout_regions(
                        blocks, layout_regions, page_w, page_h, page_direction
                    )
                    structure_source = "layout-regions"
                    layout_mapped_pages += 1
                else:
                    columns = segment_columns(image, blocks, page_direction)
                    mapped_regions = self._regions_from_columns(
                        blocks, columns, page_direction, page["page_number"]
                    )

                ordered_raw = (
                    "\n\n".join(
                        region["raw_text"]
                        for region in mapped_regions
                        if region.get("raw_text")
                    )
                    or recognition["full_text"]
                )

                page_record = {
                    "page_number": page["page_number"],
                    "blocks": blocks,
                    "columns": columns,
                    "structure_source": structure_source,
                    "raw_text": ordered_raw,
                    "confidence": recognition["confidence"],
                    "quality": recognition.get("quality"),
                    "regions": mapped_regions,
                }
                page_results[page["page_number"]] = page_record

                if self.ai.available:
                    try:
                        if structure_source == "layout-regions":
                            aggregated = self._aggregate_with_retry(
                                self.ai.aggregate_by_regions,
                                page["page_number"],
                                mapped_regions,
                                page_image=image_path,
                                direction=page_direction,
                            )
                        else:
                            aggregated = self._aggregate_with_retry(
                                self.ai.aggregate_whole_page,
                                page["page_number"],
                                blocks,
                                columns,
                                page_image=image_path,
                                direction=page_direction,
                            )
                        aggregated["page_number"] = page["page_number"]
                        corrected_by_page[page["page_number"]] = (
                            self._apply_pluggable_correction(task, aggregated)
                        )
                        ai_aggregated += 1
                    except Exception as error:
                        task.setdefault("warnings", [])
                        if isinstance(task["warnings"], list):
                            task["warnings"].append(
                                f"第 {page['page_number']} 页 AI 聚合失败，已保留整页原文: {error}"
                            )

                result = self._save_ocr_result(task_id, list(page_results.values()))
                if corrected_by_page:
                    self._save_corrected_result(
                        task_id, list(corrected_by_page.values()), result
                    )

                task["ocr"] = {
                    "pages": len(result["pages"]),
                    "regions": sum(
                        len(item.get("regions") or []) for item in result["pages"]
                    ),
                    "blocks": sum(
                        len(item.get("blocks") or []) for item in result["pages"]
                    ),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                    "mode": "wholepage",
                }
                task["progress"] = {
                    "current": index,
                    "total": len(selected_pages),
                    "message": f"已完成整页识别 {index}/{len(selected_pages)} 页",
                }
                self.store.save(task)

            result = self._save_ocr_result(task_id, list(page_results.values()))
            if corrected_by_page:
                corrected = self._save_corrected_result(
                    task_id, list(corrected_by_page.values()), result
                )
                task["correction"] = {
                    "completed_pages": [
                        page["page_number"] for page in corrected["pages"]
                    ],
                    "result_url": f"/api/tasks/{task_id}/correction",
                }

            if ai_aggregated and layout_mapped_pages:
                quality_mode = "wholepage+layout-regions+ai"
            elif ai_aggregated:
                quality_mode = "wholepage+ai-aggregate"
            elif layout_mapped_pages:
                quality_mode = "wholepage+layout-regions"
            else:
                quality_mode = "wholepage-raw"

            task.update(
                status="ocr_ready",
                stage="ocr",
                ocr={
                    "pages": len(result["pages"]),
                    "regions": sum(
                        len(item.get("regions") or []) for item in result["pages"]
                    ),
                    "blocks": sum(
                        len(item.get("blocks") or []) for item in result["pages"]
                    ),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                    "mode": "wholepage",
                },
                recognition_quality={
                    "mode": quality_mode,
                    "ai_aggregated_pages": ai_aggregated,
                    "layout_mapped_pages": layout_mapped_pages,
                },
                progress={
                    "current": len(selected_pages),
                    "total": len(selected_pages),
                    "message": (
                        "整页识别与 AI 文章聚合完成"
                        if ai_aggregated
                        else "整页识别完成（未配置 AI，已输出全覆盖原文）"
                    ),
                },
            )
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "ocr", error)

    def run_columnwise_ocr(
        self, task_id: str, page_numbers: List[int] | None = None
    ) -> None:
        """逐列旋转 OCR：按视觉 region bbox 裁剪后单独 OCR，保证栏内阅读顺序。

        文字只信 RapidOCR；视觉仅提供 region 边界。无 layout regions 时回退整页路径。
        """
        try:
            task = self.store.load(task_id)
            requested = sorted(
                set(
                    page_numbers
                    or task.get("ocr_request", {}).get("page_numbers")
                    or [page["page_number"] for page in task["pages"]]
                )
            )
            selected_pages = [
                page for page in task["pages"] if page["page_number"] in requested
            ]
            direction = task.get("options", {}).get("reading_direction") or (
                selected_pages[0]
                .get("layout", {})
                .get("reading_direction", "vertical-rtl")
                if selected_pages
                else "vertical-rtl"
            )
            task["options"]["mode"] = "columnwise"
            task.update(status="ocr_running", stage="ocr", error=None)
            task["progress"] = {
                "current": 0,
                "total": len(selected_pages),
                "message": "正在进行逐列旋转识别",
            }
            self.store.save(task)

            result_path = self.store.task_dir(task_id) / "ocr.json"
            previous = (
                self._read_json(task_id, "ocr.json")
                if result_path.exists()
                else {"pages": []}
            )
            page_results = {
                page["page_number"]: page for page in previous.get("pages", [])
            }
            corrected_path = self.store.task_dir(task_id) / "corrected.json"
            previous_corrected = (
                self._read_json(task_id, "corrected.json")
                if corrected_path.exists()
                else {"pages": []}
            )
            corrected_by_page = {
                page["page_number"]: page
                for page in previous_corrected.get("pages", [])
            }
            ai_aggregated = 0
            columnwise_pages = 0
            fallback_pages = 0
            crops_dir = self.store.task_dir(task_id) / "crops"
            crops_dir.mkdir(exist_ok=True)

            for index, page in enumerate(selected_pages, 1):
                image_path = (
                    self.store.task_dir(task_id)
                    / "pages"
                    / f"page_{page['page_number']:03d}.png"
                )
                image = read_image(image_path)
                if image is None:
                    raise RuntimeError(
                        f"Cannot load rendered page {page['page_number']}"
                    )

                page_direction = (
                    page.get("layout", {}).get("reading_direction") or direction
                )
                layout_regions = [
                    region
                    for region in list((page.get("layout") or {}).get("regions") or [])
                    if region.get("label") != "ignore"
                ]

                if not layout_regions:
                    # 无视觉分区：回退整页 OCR + 投影分栏
                    fallback_pages += 1
                    recognition = self.ocr.recognize_whole_page(image, page_direction)
                    blocks = recognition["blocks"]
                    columns = segment_columns(image, blocks, page_direction)
                    mapped_regions = self._regions_from_columns(
                        blocks, columns, page_direction, page["page_number"]
                    )
                    ordered_raw = (
                        "\n\n".join(
                            region["raw_text"]
                            for region in mapped_regions
                            if region.get("raw_text")
                        )
                        or recognition["full_text"]
                    )
                    structure_source = "columns"
                    page_record = {
                        "page_number": page["page_number"],
                        "blocks": blocks,
                        "columns": columns,
                        "structure_source": structure_source,
                        "raw_text": ordered_raw,
                        "confidence": recognition["confidence"],
                        "quality": recognition.get("quality"),
                        "regions": mapped_regions,
                    }
                    if self.ai.available:
                        try:
                            aggregated = self._aggregate_with_retry(
                                self.ai.aggregate_whole_page,
                                page["page_number"],
                                blocks,
                                columns,
                                page_image=image_path,
                                direction=page_direction,
                            )
                            aggregated["page_number"] = page["page_number"]
                            corrected_by_page[page["page_number"]] = (
                                self._apply_pluggable_correction(task, aggregated)
                            )
                            ai_aggregated += 1
                        except Exception as error:
                            task.setdefault("warnings", [])
                            if isinstance(task["warnings"], list):
                                task["warnings"].append(
                                    f"第 {page['page_number']} 页 AI 聚合失败，已保留整页原文: {error}"
                                )
                else:
                    columnwise_pages += 1
                    mapped_regions = self._ocr_regions_columnwise(
                        image,
                        layout_regions,
                        page_direction,
                        crops_dir,
                        task_id,
                        page["page_number"],
                    )
                    blocks = [
                        block
                        for region in mapped_regions
                        for block in (region.get("text_blocks") or [])
                    ]
                    for block_id, block in enumerate(blocks, 1):
                        block["block_id"] = block_id
                        block["reading_order"] = block_id
                    ordered_raw = "\n\n".join(
                        region["raw_text"]
                        for region in mapped_regions
                        if region.get("raw_text")
                    )
                    confidences = [
                        float(region.get("confidence") or 0)
                        for region in mapped_regions
                        if region.get("text_blocks")
                    ]
                    page_confidence = (
                        sum(confidences) / len(confidences) if confidences else 0.0
                    )
                    page_record = {
                        "page_number": page["page_number"],
                        "blocks": blocks,
                        "columns": [],
                        "structure_source": "columnwise-regions",
                        "raw_text": ordered_raw,
                        "confidence": page_confidence,
                        "quality": assess_quality(
                            ordered_raw, page_confidence, len(blocks)
                        ),
                        "regions": mapped_regions,
                    }
                    if self.ai.available:
                        try:
                            aggregated = self._aggregate_with_retry(
                                self.ai.aggregate_by_regions,
                                page["page_number"],
                                mapped_regions,
                                page_image=image_path,
                                direction=page_direction,
                            )
                            aggregated["page_number"] = page["page_number"]
                            corrected_by_page[page["page_number"]] = (
                                self._apply_pluggable_correction(task, aggregated)
                            )
                            ai_aggregated += 1
                        except Exception as error:
                            task.setdefault("warnings", [])
                            if isinstance(task["warnings"], list):
                                task["warnings"].append(
                                    f"第 {page['page_number']} 页 AI 聚合失败，已保留逐列原文: {error}"
                                )

                page_results[page["page_number"]] = page_record
                result = self._save_ocr_result(task_id, list(page_results.values()))
                if corrected_by_page:
                    self._save_corrected_result(
                        task_id, list(corrected_by_page.values()), result
                    )

                task["ocr"] = {
                    "pages": len(result["pages"]),
                    "regions": sum(
                        len(item.get("regions") or []) for item in result["pages"]
                    ),
                    "blocks": sum(
                        len(item.get("blocks") or []) for item in result["pages"]
                    ),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                    "mode": "columnwise",
                }
                task["progress"] = {
                    "current": index,
                    "total": len(selected_pages),
                    "message": f"已完成逐列识别 {index}/{len(selected_pages)} 页",
                }
                self.store.save(task)

            result = self._save_ocr_result(task_id, list(page_results.values()))
            if corrected_by_page:
                corrected = self._save_corrected_result(
                    task_id, list(corrected_by_page.values()), result
                )
                task["correction"] = {
                    "completed_pages": [
                        page["page_number"] for page in corrected["pages"]
                    ],
                    "result_url": f"/api/tasks/{task_id}/correction",
                }

            if ai_aggregated and columnwise_pages:
                quality_mode = "columnwise+layout-regions+ai"
            elif columnwise_pages:
                quality_mode = "columnwise+layout-regions"
            elif ai_aggregated:
                quality_mode = "columnwise-fallback+ai-aggregate"
            else:
                quality_mode = "columnwise-fallback-raw"

            task.update(
                status="ocr_ready",
                stage="ocr",
                ocr={
                    "pages": len(result["pages"]),
                    "regions": sum(
                        len(item.get("regions") or []) for item in result["pages"]
                    ),
                    "blocks": sum(
                        len(item.get("blocks") or []) for item in result["pages"]
                    ),
                    "completed_pages": [
                        item["page_number"] for item in result["pages"]
                    ],
                    "requested_pages": requested,
                    "result_url": f"/api/tasks/{task_id}/ocr",
                    "mode": "columnwise",
                },
                recognition_quality={
                    "mode": quality_mode,
                    "ai_aggregated_pages": ai_aggregated,
                    "columnwise_pages": columnwise_pages,
                    "fallback_pages": fallback_pages,
                },
                progress={
                    "current": len(selected_pages),
                    "total": len(selected_pages),
                    "message": (
                        "逐列识别与 AI 文章聚合完成"
                        if ai_aggregated
                        else "逐列识别完成（未配置 AI，已输出栏内有序原文）"
                    ),
                },
            )
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "ocr", error)

    def _ocr_regions_columnwise(
        self,
        image,
        layout_regions: List[Dict],
        page_direction: str,
        crops_dir: Path,
        task_id: str,
        page_number: int,
    ) -> List[Dict]:
        """对每个视觉 region 单独裁剪、旋转 OCR；不调用视觉转录。"""
        mapped: List[Dict] = []
        for index, region in enumerate(
            sorted(layout_regions, key=lambda item: int(item.get("order") or 0)), 1
        ):
            region_id = str(region.get("id") or f"r{index}")
            direction = region.get("direction") or page_direction
            crop, pixel_box = self._crop(image, region["bbox"])
            prepared = prepare_crop_for_ocr(crop, direction)
            crop_path = crops_dir / f"p{page_number:03d}_{region_id}.png"
            write_image(crop_path, crop)
            recognition = self.ocr.recognize(prepared, direction)
            page_blocks = self._map_crop_blocks_to_page(
                recognition.get("text_blocks") or [], pixel_box, direction
            )
            for reading_index, block in enumerate(page_blocks, 1):
                block["region_id"] = region_id
                block["region_reading_order"] = reading_index
            text = recognition.get("full_text") or ""
            mapped.append(
                {
                    "region_id": region_id,
                    "order": int(region.get("order") or index),
                    "label": region.get("label") or "body",
                    "article_id": region.get("article_id") or f"article-{region_id}",
                    "direction": direction,
                    "bbox": region.get("bbox"),
                    "pixel_bbox": pixel_box,
                    "raw_text": text,
                    "final_region_text": text,
                    "confidence": recognition.get("confidence") or 0.0,
                    "quality": recognition.get("quality"),
                    "text_blocks": page_blocks,
                    "crop_url": f"/api/tasks/{task_id}/crops/{crop_path.name}",
                }
            )
        return mapped

    @staticmethod
    def _map_crop_blocks_to_page(
        blocks: List[Dict], pixel_box: Dict, direction: str
    ) -> List[Dict]:
        """把裁剪（及竖排旋转）坐标系下的 bbox 映射回整页像素坐标。"""
        ox = int(pixel_box["x"])
        oy = int(pixel_box["y"])
        crop_h = int(pixel_box["height"])
        mapped: List[Dict] = []
        for block in blocks:
            bbox = block.get("bbox") or []
            if direction == "vertical-rtl" and bbox:
                bbox = OCREngine._map_bbox_from_rotate_90_cw(bbox, crop_h)
            page_bbox = [[float(point[0]) + ox, float(point[1]) + oy] for point in bbox]
            mapped.append({**block, "bbox": page_bbox})
        return mapped

    @staticmethod
    def _block_center_xy(bbox) -> tuple[float, float]:
        if isinstance(bbox, dict):
            return (
                float(bbox["x"]) + float(bbox["width"]) / 2.0,
                float(bbox["y"]) + float(bbox["height"]) / 2.0,
            )
        xs = [float(point[0]) for point in bbox]
        ys = [float(point[1]) for point in bbox]
        return sum(xs) / len(xs), sum(ys) / len(ys)

    @staticmethod
    def _point_in_norm_bbox(nx: float, ny: float, bbox: Dict) -> bool:
        x0 = float(bbox["x"])
        y0 = float(bbox["y"])
        x1 = x0 + float(bbox["width"])
        y1 = y0 + float(bbox["height"])
        return x0 <= nx <= x1 and y0 <= ny <= y1

    @classmethod
    def _sort_blocks_by_direction(
        cls, blocks: List[Dict], direction: str
    ) -> List[Dict]:
        def sort_key(block: Dict):
            cx, cy = cls._block_center_xy(block.get("bbox") or [[0, 0]])
            if direction == "vertical-rtl":
                return (-cx, cy)
            return (cy, cx)

        return sorted(blocks, key=sort_key)

    @classmethod
    def _map_blocks_to_layout_regions(
        cls,
        blocks: List[Dict],
        layout_regions: List[Dict],
        page_width: int,
        page_height: int,
        page_direction: str,
    ) -> List[Dict]:
        """把整页 OCR blocks 映射到视觉版面 regions，并按阅读方向排序拼文本。"""
        width = max(float(page_width), 1.0)
        height = max(float(page_height), 1.0)
        buckets: Dict[str, List[Dict]] = {
            str(region.get("id") or f"r{index}"): []
            for index, region in enumerate(layout_regions, 1)
        }
        region_by_id = {
            str(region.get("id") or f"r{index}"): region
            for index, region in enumerate(layout_regions, 1)
        }
        loose_blocks: List[Dict] = []

        for block in blocks:
            cx, cy = cls._block_center_xy(block.get("bbox") or [[0, 0]])
            nx, ny = cx / width, cy / height
            hit_id = None
            for region_id, region in region_by_id.items():
                if cls._point_in_norm_bbox(nx, ny, region["bbox"]):
                    hit_id = region_id
                    break
            if hit_id is not None:
                buckets[hit_id].append(block)
                block["region_id"] = hit_id
                continue

            # 未命中：归到最近 region；若无可用 region 则进 loose
            best_id = None
            best_dist = float("inf")
            for region_id, region in region_by_id.items():
                rcx, rcy = cls._block_center_xy(region["bbox"])
                dist = (nx - rcx) ** 2 + (ny - rcy) ** 2
                if dist < best_dist:
                    best_dist = dist
                    best_id = region_id
            if best_id is not None:
                buckets[best_id].append(block)
                block["region_id"] = best_id
            else:
                loose_blocks.append(block)
                block["region_id"] = "loose"

        mapped: List[Dict] = []
        for index, region in enumerate(layout_regions, 1):
            region_id = str(region.get("id") or f"r{index}")
            direction = region.get("direction") or page_direction
            ordered = cls._sort_blocks_by_direction(
                buckets.get(region_id, []), direction
            )
            for reading_index, block in enumerate(ordered, 1):
                block["region_reading_order"] = reading_index
            text = "\n".join(
                str(block.get("text") or "") for block in ordered if block.get("text")
            )
            confidence = (
                sum(float(block.get("confidence") or 0) for block in ordered)
                / len(ordered)
                if ordered
                else 0.0
            )
            mapped.append(
                {
                    "region_id": region_id,
                    "order": int(region.get("order") or index),
                    "label": region.get("label") or "body",
                    "article_id": region.get("article_id") or f"article-{region_id}",
                    "direction": direction,
                    "bbox": region.get("bbox"),
                    "raw_text": text,
                    "final_region_text": text,
                    "confidence": confidence,
                    "text_blocks": ordered,
                }
            )

        if loose_blocks:
            ordered_loose = cls._sort_blocks_by_direction(loose_blocks, page_direction)
            text = "\n".join(
                str(block.get("text") or "")
                for block in ordered_loose
                if block.get("text")
            )
            mapped.append(
                {
                    "region_id": "loose",
                    "order": max((r["order"] for r in mapped), default=0) + 1,
                    "label": "body",
                    "article_id": "loose",
                    "direction": page_direction,
                    "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "raw_text": text,
                    "final_region_text": text,
                    "confidence": (
                        sum(
                            float(block.get("confidence") or 0)
                            for block in ordered_loose
                        )
                        / len(ordered_loose)
                        if ordered_loose
                        else 0.0
                    ),
                    "text_blocks": ordered_loose,
                }
            )

        mapped.sort(key=lambda item: int(item.get("order") or 0))
        return mapped

    @classmethod
    def _regions_from_columns(
        cls,
        blocks: List[Dict],
        columns: List[Dict],
        page_direction: str,
        page_number: int,
    ) -> List[Dict]:
        """投影分栏回退：把带 column_index 的 blocks 收成伪 region 列表。"""
        if not columns:
            text = "\n".join(
                str(block.get("text") or "") for block in blocks if block.get("text")
            )
            return [
                {
                    "region_id": "wholepage",
                    "order": 1,
                    "label": "body",
                    "article_id": f"page-{page_number}",
                    "direction": page_direction,
                    "bbox": {"x": 0, "y": 0, "width": 1, "height": 1},
                    "raw_text": text,
                    "final_region_text": text,
                    "confidence": (
                        sum(float(b.get("confidence") or 0) for b in blocks)
                        / len(blocks)
                        if blocks
                        else 0.0
                    ),
                    "text_blocks": blocks,
                }
            ]

        by_column: Dict[int, List[Dict]] = {}
        for block in blocks:
            by_column.setdefault(int(block.get("column_index", 0)), []).append(block)

        regions: List[Dict] = []
        for column in columns:
            column_index = int(column.get("column_index", 0))
            col_blocks = cls._sort_blocks_by_direction(
                by_column.get(column_index, []), page_direction
            )
            text = "\n".join(
                str(block.get("text") or "")
                for block in col_blocks
                if block.get("text")
            )
            regions.append(
                {
                    "region_id": f"col-{column_index}",
                    "order": column_index + 1,
                    "label": "body",
                    "article_id": f"page-{page_number}",
                    "direction": page_direction,
                    "bbox": None,
                    "column_index": column_index,
                    "raw_text": text,
                    "final_region_text": text,
                    "confidence": (
                        sum(float(b.get("confidence") or 0) for b in col_blocks)
                        / len(col_blocks)
                        if col_blocks
                        else 0.0
                    ),
                    "text_blocks": col_blocks,
                }
            )
        return regions

    def queue_correction(
        self, task_id: str, page_numbers: List[int] | None = None
    ) -> Dict:
        if not self.ai.available:
            raise WorkflowStateError(
                "AI is not configured. Add an API key before semantic correction"
            )
        task = self.store.load(task_id)
        if task["status"] not in {"ocr_ready", "correction_ready"}:
            raise WorkflowStateError("OCR must finish before AI correction")
        raw = self._read_json(task_id, "ocr.json")
        available = {page["page_number"] for page in raw["pages"]}
        requested = sorted(set(page_numbers or available))
        if not requested or not set(requested).issubset(available):
            raise WorkflowStateError("Only pages with completed OCR can be corrected")
        task.update(
            status="correction_queued",
            stage="correction",
            error=None,
            correction_request={"page_numbers": requested},
        )
        return self.store.save(task)

    def run_correction(
        self, task_id: str, page_numbers: List[int] | None = None
    ) -> None:
        try:
            task = self.store.load(task_id)
            raw = self._read_json(task_id, "ocr.json")
            requested = sorted(
                set(
                    page_numbers
                    or task.get("correction_request", {}).get("page_numbers")
                    or [page["page_number"] for page in raw["pages"]]
                )
            )
            raw_pages = [
                page for page in raw["pages"] if page["page_number"] in requested
            ]
            corrected_path = self.store.task_dir(task_id) / "corrected.json"
            previous = (
                self._read_json(task_id, "corrected.json")
                if corrected_path.exists()
                else {"pages": []}
            )
            corrected_by_page = {
                page["page_number"]: page for page in previous.get("pages", [])
            }
            task.update(status="correction_running", stage="correction")
            task["progress"] = {
                "current": 0,
                "total": len(raw_pages),
                "message": "正在进行 AI 语义校正",
            }
            self.store.save(task)
            for index, page in enumerate(raw_pages, 1):
                page_image = (
                    self.store.task_dir(task_id)
                    / "pages"
                    / f"page_{page['page_number']:03d}.png"
                )
                if hasattr(self.ai, "compose_page") and any(
                    region.get("visual_text") for region in page["regions"]
                ):
                    corrected = self.ai.compose_page(
                        page["page_number"], page["regions"], page.get("raw_text", "")
                    )
                    corrected["transcription_mode"] = "vision-regions+text-compose"
                else:
                    try:
                        corrected = self.ai.correct_page(
                            page["page_number"],
                            page["regions"],
                            page.get("raw_text", ""),
                            page_image=page_image,
                        )
                    except TypeError:
                        corrected = self.ai.correct_page(
                            page["page_number"],
                            page["regions"],
                            page.get("raw_text", ""),
                        )
                corrected["page_number"] = page["page_number"]
                corrected_by_page[page["page_number"]] = (
                    self._apply_pluggable_correction(task, corrected)
                )
                result = self._save_corrected_result(
                    task_id, list(corrected_by_page.values()), raw
                )
                task["progress"] = {
                    "current": index,
                    "total": len(raw_pages),
                    "message": f"已校正第 {index}/{len(raw_pages)} 页",
                }
                self.store.save(task)
            result = self._save_corrected_result(
                task_id, list(corrected_by_page.values()), raw
            )
            task.update(
                status="correction_ready",
                stage="correction",
                correction={
                    "completed_pages": [
                        page["page_number"] for page in result["pages"]
                    ],
                    "result_url": f"/api/tasks/{task_id}/correction",
                },
                progress={
                    "current": len(raw_pages),
                    "total": len(raw_pages),
                    "message": "AI 语义校正完成",
                },
            )
            self.store.save(task)
        except Exception as error:
            self._fail(task_id, "correction", error)

    def result(self, task_id: str, kind: str) -> Dict:
        name = "corrected.json" if kind == "correction" else "ocr.json"
        return self._read_json(task_id, name)

    def update_ocr_text(self, task_id: str, page_updates: List[Dict]) -> Dict:
        result = self._read_json(task_id, "ocr.json")
        updates = {
            int(item["page_number"]): str(item.get("raw_text", ""))
            for item in page_updates
        }
        available = {page["page_number"] for page in result["pages"]}
        if not updates or not set(updates).issubset(available):
            raise WorkflowStateError("Only pages with completed OCR can be edited")
        for page in result["pages"]:
            if page["page_number"] in updates:
                page["raw_text"] = updates[page["page_number"]]
                page["manually_edited"] = True
        saved = self._save_ocr_result(task_id, result["pages"])
        corrected_path = self.store.task_dir(task_id) / "corrected.json"
        if corrected_path.exists():
            corrected = self._read_json(task_id, "corrected.json")
            remaining = [
                page
                for page in corrected.get("pages", [])
                if page["page_number"] not in updates
            ]
            self._save_corrected_result(task_id, remaining, saved)
            task = self.store.load(task_id)
            task.update(
                status="ocr_ready",
                stage="ocr",
                correction={
                    "completed_pages": [page["page_number"] for page in remaining],
                    "result_url": f"/api/tasks/{task_id}/correction",
                    "stale_pages": sorted(updates),
                },
            )
            self.store.save(task)
        return saved

    def update_corrected_text(self, task_id: str, page_updates: List[Dict]) -> Dict:
        raw = self._read_json(task_id, "ocr.json")
        result = self._read_json(task_id, "corrected.json")
        updates = {
            int(item["page_number"]): str(item.get("corrected_text", ""))
            for item in page_updates
        }
        available = {page["page_number"] for page in result.get("pages", [])}
        if not updates or not set(updates).issubset(available):
            raise WorkflowStateError(
                "Only pages with an AI correction draft can be edited"
            )
        for page in result["pages"]:
            if page["page_number"] in updates:
                page["corrected_text"] = updates[page["page_number"]]
                page["manually_edited"] = True
        saved = self._save_corrected_result(task_id, result["pages"], raw)
        task = self.store.load(task_id)
        task.update(
            status="correction_ready",
            stage="correction",
            correction={
                "completed_pages": [page["page_number"] for page in saved["pages"]],
                "result_url": f"/api/tasks/{task_id}/correction",
            },
        )
        self.store.save(task)
        return saved

    def document_text(self, task_id: str) -> str:
        task_dir = self.store.task_dir(task_id)
        corrected = task_dir / "corrected.txt"
        raw = task_dir / "raw.txt"
        path = corrected if corrected.exists() else raw
        if not path.exists():
            raise WorkflowStateError("No OCR text is available")
        return path.read_text(encoding="utf-8")

    def summarize(self, task_id: str, instruction: str) -> Dict:
        return self.ai.summarize_document(self.document_text(task_id), instruction)

    def answer(self, task_id: str, question: str) -> Dict:
        return self.ai.answer(self.document_text(task_id), question)

    def _crop(self, image, bbox: Dict):
        height, width = image.shape[:2]
        x1, y1 = int(bbox["x"] * width), int(bbox["y"] * height)
        x2, y2 = int((bbox["x"] + bbox["width"]) * width), int(
            (bbox["y"] + bbox["height"]) * height
        )
        pad = max(2, int(min(width, height) * 0.003))
        x1, y1, x2, y2 = (
            max(0, x1 - pad),
            max(0, y1 - pad),
            min(width, x2 + pad),
            min(height, y2 + pad),
        )
        if x2 <= x1 or y2 <= y1:
            raise ValueError("OCR region has an empty bounding box")
        return image[y1:y2, x1:x2], {
            "x": x1,
            "y": y1,
            "width": x2 - x1,
            "height": y2 - y1,
        }

    @staticmethod
    def _texts_disagree(left: str, right: str) -> bool:
        left_chars = "".join((left or "").split())
        right_chars = "".join((right or "").split())
        if not left_chars or not right_chars:
            return bool(left_chars or right_chars)
        if left_chars == right_chars:
            return False
        matcher = SequenceMatcher(None, left_chars, right_chars)
        return 1.0 - matcher.ratio() > 0.18

    def _write_json(self, task_id: str, name: str, value: Dict):
        path = self.store.task_dir(task_id) / name
        temp = path.with_suffix(path.suffix + ".tmp")
        temp.write_text(
            json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        temp.replace(path)

    def _save_ocr_result(self, task_id: str, pages: List[Dict]) -> Dict:
        ordered = sorted(pages, key=lambda page: page["page_number"])
        lines = []
        for page in ordered:
            lines.extend(
                [
                    f"========== Page {page['page_number']} ==========",
                    page.get("raw_text", ""),
                    "",
                ]
            )
        result = {
            "task_id": task_id,
            "engine": self.ocr.backend,
            "pages": ordered,
            "full_text": "\n".join(lines),
            "updated_at": utc_now(),
        }
        self._write_json(task_id, "ocr.json", result)
        (self.store.task_dir(task_id) / "raw.txt").write_text(
            result["full_text"], encoding="utf-8"
        )
        return result

    def _aggregate_with_retry(
        self,
        aggregate_fn: Callable[..., Dict],
        *args,
        max_attempts: int = AGGREGATE_MAX_ATTEMPTS,
        **kwargs,
    ) -> Dict:
        """对一次 LLM 聚合调用做质量校验 + 重试兜底。

        最多尝试 ``max_attempts`` 次；每次打分后保留最高分结果。
        全部不达标时不硬失败，返回得分最高的那次，并在 warnings 中说明。
        第 2 次起若聚合函数支持 ``hint``，追加排序/标题质量提示以引导重采样。
        """
        best_result: Dict | None = None
        best_quality: Dict | None = None
        attempts_used = 0

        for attempt in range(1, max_attempts + 1):
            attempts_used = attempt
            call_kwargs = dict(kwargs)
            if attempt > 1 and self._aggregate_fn_accepts_hint(aggregate_fn):
                call_kwargs["hint"] = AGGREGATE_RETRY_HINT
            result = aggregate_fn(*args, **call_kwargs)
            if not isinstance(result, dict):
                result = {"articles": [], "warnings": [f"聚合返回非 dict: {type(result)}"]}
            quality = score_aggregation(result)
            if best_result is None or quality["score"] > best_quality["score"]:
                best_result = result
                best_quality = quality
            if quality["ok"]:
                break

        assert best_result is not None and best_quality is not None
        warnings = list(best_result.get("warnings") or [])
        issues_preview = "; ".join(best_quality["issues"][:5]) or "无"
        if best_quality["ok"]:
            warnings.append(
                f"聚合质量校验: score={best_quality['score']:.2f} "
                f"ok=True threshold={OK_THRESHOLD} "
                f"attempts={attempts_used}/{max_attempts} "
                f"issues=[{issues_preview}]"
            )
        else:
            warnings.append(
                f"聚合质量未达标（已降级采用最高分结果）: "
                f"score={best_quality['score']:.2f} ok=False "
                f"threshold={OK_THRESHOLD} "
                f"attempts={attempts_used}/{max_attempts} "
                f"issues=[{issues_preview}]"
            )
        best_result["warnings"] = warnings
        return best_result

    @staticmethod
    def _aggregate_fn_accepts_hint(aggregate_fn: Callable[..., Dict]) -> bool:
        try:
            signature = inspect.signature(aggregate_fn)
        except (TypeError, ValueError):
            return True
        if any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in signature.parameters.values()
        ):
            return True
        return "hint" in signature.parameters

    def _apply_pluggable_correction(self, task: Dict, page_result: Dict) -> Dict:
        """文字级软后处理：AI 聚合/校正产出后、写 corrected.json 前。

        不改版面/阅读顺序/文章聚合等结构层语义，只替换文本字段。

        ``task["options"]["correction_mode"]`` 默认 ``"none"``（最小改动：
        保持既有流水线输出不变）。设为已注册策略名（如 ``"conservative"``）
        时启用；``"none"`` / 空 / off 跳过。
        """
        mode = str(
            (task.get("options") or {}).get("correction_mode") or "none"
        ).strip().lower()
        if mode in {"", "none", "off", "false", "0"}:
            return page_result
        return apply_page_correction(page_result, get_corrector(mode))

    def _save_corrected_result(
        self, task_id: str, pages: List[Dict], raw: Dict
    ) -> Dict:
        ordered = sorted(pages, key=lambda page: page["page_number"])
        corrected_by_page = {page["page_number"]: page for page in ordered}
        lines = []
        for raw_page in sorted(raw["pages"], key=lambda page: page["page_number"]):
            corrected_page = corrected_by_page.get(raw_page["page_number"])
            text = (
                corrected_page.get("corrected_text", raw_page.get("raw_text", ""))
                if corrected_page
                else raw_page.get("raw_text", "")
            )
            lines.extend(
                [f"========== Page {raw_page['page_number']} ==========", text, ""]
            )
        result = {
            "task_id": task_id,
            "pages": ordered,
            "full_text": "\n".join(lines),
            "generated_at": utc_now(),
        }
        self._write_json(task_id, "corrected.json", result)
        (self.store.task_dir(task_id) / "corrected.txt").write_text(
            result["full_text"], encoding="utf-8"
        )
        return result

    def _read_json(self, task_id: str, name: str) -> Dict:
        path = self.store.task_dir(task_id) / name
        if not path.exists():
            raise WorkflowStateError(f"Result is not available: {name}")
        return json.loads(path.read_text(encoding="utf-8"))

    def _fail(self, task_id: str, stage: str, error: Exception):
        try:
            task = self.store.load(task_id)
            task.update(
                status="failed",
                stage=stage,
                error={
                    "message": str(error),
                    "type": type(error).__name__,
                    "trace": traceback.format_exc(),
                },
            )
            self.store.save(task)
        except Exception:
            pass

    def generate_final_document(self, task_id: str, format: str = "markdown") -> str:
        """Generate a structured final document from OCR results.

        Args:
            task_id: Task identifier
            format: Output format ('markdown' or 'html')

        Returns:
            Path to generated document
        """
        from document_composer import DocumentComposer

        task = self.store.load(task_id)

        # Get OCR or corrected results
        corrected_path = self.store.task_dir(task_id) / "corrected.json"
        try:
            result = (
                self._read_json(task_id, "corrected.json")
                if corrected_path.exists()
                else self._read_json(task_id, "ocr.json")
            )
        except WorkflowStateError:
            result = self._read_json(task_id, "ocr.json")

        composer = DocumentComposer()
        ocr_mode = task.get("options", {}).get("ocr_mode", "regions")
        ai_articles = []
        for page in result.get("pages", []):
            ai_articles.extend(page.get("articles") or [])

        if ocr_mode in {"wholepage", "columnwise"} and ai_articles:
            content = composer.compose_from_ai_articles(ai_articles, task, fmt=format)
            extension = "html" if format == "html" else "md"
        elif format == "html":
            content = composer.compose_html(task, result["pages"])
            extension = "html"
        else:
            content = composer.compose_markdown(task, result["pages"])
            extension = "md"

        output_path = self.store.task_dir(task_id) / f"final_document.{extension}"
        output_path.write_text(content, encoding="utf-8")

        return str(output_path)

    def validate_quality(self, task_id: str) -> Dict:
        """Validate OCR quality and completeness.

        Args:
            task_id: Task identifier

        Returns:
            Validation report
        """
        from quality_validator import QualityValidator

        task = self.store.load(task_id)
        ocr_result_path = self.store.task_dir(task_id) / "ocr.json"
        task["ocr_result"] = (
            self._read_json(task_id, "ocr.json")
            if ocr_result_path.exists()
            else {"pages": []}
        )
        validator = QualityValidator(target_accuracy=0.95)

        return validator.validate_task(task)
