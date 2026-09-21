"""Optional vision and language model services for layout, correction and research."""

from __future__ import annotations

import base64
import json
import mimetypes
import os
import re
from pathlib import Path
from typing import Dict, List

from dotenv import load_dotenv


class AIUnavailableError(RuntimeError):
    pass


class AIResponseError(RuntimeError):
    pass


class AIService:
    def __init__(self):
        load_dotenv()
        self.backend, self.model, self.client, self.error = "unavailable", None, None, None
        provider = os.getenv("AI_PROVIDER", "").strip().lower()
        if provider in {"deepseek", "deepseek-chat", "deepseek-reasoner"} or (not provider and os.getenv("DEEPSEEK_API_KEY")):
            self._init_openai_compatible(
                "deepseek",
                os.getenv("DEEPSEEK_API_KEY"),
                os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
        elif provider == "anthropic" or (not provider and os.getenv("ANTHROPIC_API_KEY")):
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
                self.backend = "anthropic"
                self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
            except Exception as error:
                self.error = str(error)
        elif provider == "openai" or (not provider and os.getenv("OPENAI_API_KEY")):
            self._init_openai_compatible(
                "openai",
                os.getenv("OPENAI_API_KEY"),
                os.getenv("OPENAI_MODEL", "gpt-4o"),
                os.getenv("OPENAI_BASE_URL"),
            )

    def _init_openai_compatible(self, backend: str, api_key: str | None, model: str, base_url: str | None) -> None:
        if not api_key:
            self.error = f"{backend.upper()} API key is not configured"
            return
        try:
            from openai import OpenAI
            options = {"api_key": api_key}
            if base_url:
                options["base_url"] = base_url.rstrip("/")
            self.client = OpenAI(**options)
            self.backend = backend
            self.model = model
        except Exception as error:
            self.error = str(error)

    @property
    def available(self) -> bool:
        return self.client is not None

    @property
    def supports_vision(self) -> bool:
        return self.available and self.backend != "deepseek"

    def health(self) -> Dict:
        return {"available": self.available, "backend": self.backend, "model": self.model, "vision": self.supports_vision, "error": self.error}

    def enrich_layout(self, image_path: str | Path, layout: Dict) -> Dict:
        prompt = f"""You are planning OCR windows for a historical Chinese newspaper page.
Review the image and computer-vision proposal. Return JSON only. Keep normalized coordinates between 0 and 1.
Correct missing, overlapping or badly split windows. Every region must contain id, order, label, article_id,
direction, bbox, confidence and notes. Allowed labels: masthead, title, subtitle, body, caption, metadata,
advertisement, ignore. Allowed directions: vertical-rtl, horizontal-ltr. Order must reflect historical reading
order. Group related title and body regions with article_id. Do not transcribe the page yet.

Proposal:
{json.dumps(layout, ensure_ascii=False)}

Return {{"layout_type":"...","reading_direction":"...","regions":[...]}}"""
        return self._vision_json(image_path, prompt)

    def correct_page(self, page_number: int, regions: List[Dict], page_text: str = "") -> Dict:
        compact = [{
            "region_id": region["region_id"], "order": region["order"], "label": region["label"],
            "article_id": region["article_id"], "direction": region["direction"],
            "raw_text": region.get("raw_text", ""), "confidence": region.get("confidence", 0),
        } for region in regions]
        prompt = f"""Proofread OCR from page {page_number} of a 1945 traditional-Chinese newspaper.
Use region order, labels, article grouping and semantics. Correct only likely OCR errors; preserve historical wording,
traditional characters, names and uncertainty. Never silently modernize the text. Return JSON only with corrected_text,
articles (id, title, text), corrections (region_id, original, corrected, reason, confidence), and warnings.

OCR regions:
{json.dumps(compact, ensure_ascii=False)}

Authoritative page text after any human edits:
{page_text}"""
        return self._text_json(prompt, max_tokens=5000)

    def summarize_document(self, text: str, instruction: str = "") -> Dict:
        prompt = f"""Analyze this OCR transcription of a historical Chinese newspaper. Return JSON only with summary,
key_points, people, organizations, places, dates, topics and uncertainties. Separate facts stated by the source from
interpretation. User focus: {instruction or 'general overview'}.

Document:
{text[:80000]}"""
        return self._text_json(prompt, max_tokens=3500)

    def answer(self, text: str, question: str) -> Dict:
        prompt = f"""Answer using only the historical newspaper transcription below. Quote short supporting passages and
identify page markers when available. State clearly when evidence is absent or OCR is uncertain. Return JSON only with
answer, evidence and uncertainties.

Question: {question}

Document:
{text[:80000]}"""
        return self._text_json(prompt, max_tokens=2500)

    def _vision_json(self, image_path: str | Path, prompt: str) -> Dict:
        self._require_client()
        if self.backend == "deepseek":
            raise AIUnavailableError("DeepSeek 文本模型不支持图片版面复核，请使用本地版面分析；OCR 后的语义校正、总结和问答仍可用")
        path = Path(image_path)
        media_type = mimetypes.guess_type(path.name)[0] or "image/png"
        encoded = base64.b64encode(path.read_bytes()).decode("ascii")
        if self.backend == "anthropic":
            response = self.client.messages.create(model=self.model, max_tokens=5000, messages=[{
                "role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}},
                    {"type": "text", "text": prompt},
                ]
            }])
            content = response.content[0].text
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
                ]}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
        return self._parse_json(content)

    def _text_json(self, prompt: str, max_tokens: int) -> Dict:
        self._require_client()
        if self.backend == "anthropic":
            response = self.client.messages.create(model=self.model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}])
            content = response.content[0].text
        else:
            response = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            )
            content = response.choices[0].message.content
        return self._parse_json(content)

    def _require_client(self):
        if not self.available:
            raise AIUnavailableError("Configure DEEPSEEK_API_KEY, ANTHROPIC_API_KEY or OPENAI_API_KEY to enable AI stages")

    def _parse_json(self, content: str) -> Dict:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as error:
            raise AIResponseError(f"Model did not return valid JSON: {error}") from error
        if not isinstance(result, dict):
            raise AIResponseError("Model response must be a JSON object")
        result["ai_backend"], result["ai_model"] = self.backend, self.model
        return result
