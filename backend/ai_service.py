"""Optional vision and language model services for layout, correction and research."""

from __future__ import annotations

import base64
import io
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


class AIInsufficientBalanceError(AIResponseError):
    pass


class AIService:
    def __init__(self):
        load_dotenv()
        self.backend, self.model, self.vision_model, self.client, self.error = "unavailable", None, None, None, None
        provider = os.getenv("AI_PROVIDER", "").strip().lower()
        if provider in {"deepseek", "deepseek-chat", "deepseek-reasoner"} or (not provider and os.getenv("DEEPSEEK_API_KEY")):
            self._init_openai_compatible(
                "deepseek",
                os.getenv("DEEPSEEK_API_KEY"),
                os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
                os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
            )
            self.vision_model = os.getenv("DEEPSEEK_VISION_MODEL", "deepseek-flash")
        elif provider == "anthropic" or (not provider and os.getenv("ANTHROPIC_API_KEY")):
            try:
                from anthropic import Anthropic
                self.client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
                self.backend = "anthropic"
                self.model = os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-20250514")
                self.vision_model = self.model
            except Exception as error:
                self.error = str(error)
        elif provider == "openai" or (not provider and os.getenv("OPENAI_API_KEY")):
            self._init_openai_compatible(
                "openai",
                os.getenv("OPENAI_API_KEY"),
                os.getenv("OPENAI_MODEL", "gpt-4o"),
                os.getenv("OPENAI_BASE_URL"),
            )
            self.vision_model = os.getenv("OPENAI_VISION_MODEL", self.model)

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
        return self.available and bool(self.vision_model)

    def health(self) -> Dict:
        return {"available": self.available, "backend": self.backend, "model": self.model, "vision": self.supports_vision, "error": self.error}

    def enrich_layout(self, image_path: str | Path, layout: Dict) -> Dict:
        prompt = f"""Analyze the attached historical Chinese newspaper page. Image evidence is primary.
Return one JSON object with layout_type, reading_direction and regions. Coordinates must be normalized 0..1.
Create tight, non-overlapping regions for distinct visual units. Keep every ordinary vertical text column separate;
do not merge neighboring columns. Split masthead, date/publication details, headline, contents panel and body columns.
Use right-to-left column reading order, top-to-bottom within each vertical column. Do not assign the whole page to one
article: use a new article_id when a clear headline or visual divider starts a new item; otherwise use a shared ID only
for continuous article columns. Allowed labels: masthead, title, subtitle, body, caption, metadata, advertisement,
ignore. Allowed directions: vertical-rtl, horizontal-ltr. Return at most 24 regions. Include id, order, label,
article_id, direction, bbox, confidence and notes for every region.

Computer-vision proposal for reference only:
{json.dumps(layout, ensure_ascii=False)}

Return {{"layout_type":"vertical-columns|mixed|grid|horizontal-rows","reading_direction":"vertical-rtl|horizontal-ltr","regions":[...]}}"""
        return self._vision_json(image_path, prompt, max_tokens=6000)

    def transcribe_region(self, image_path: str | Path, region: Dict, page_number: int) -> Dict:
        prompt = f"""Transcribe only this crop from page {page_number} of a historical traditional-Chinese newspaper.
Read the image directly. Preserve traditional characters, historical spelling, punctuation and line/column order.
Do not modernize, paraphrase, repair based on general knowledge or invent text outside the crop.
The crop label is {region.get('label')} and direction is {region.get('direction')}.
Return JSON only: {{"text":"verbatim transcription","uncertain":"characters or short spans you cannot read","confidence":0.0}}.
Use □ for an unreadable individual character. If the crop is not text, return an empty text string."""
        result = self._vision_json(image_path, prompt, max_tokens=2200)
        result["text"] = str(result.get("text", "")).strip()
        result["uncertain"] = str(result.get("uncertain", "")).strip()
        try:
            result["confidence"] = min(1.0, max(0.0, float(result.get("confidence", 0.0))))
        except (TypeError, ValueError):
            result["confidence"] = 0.0
        return result

    def compose_page(self, page_number: int, regions: List[Dict], page_text: str = "") -> Dict:
        prompt = f"""Compose the verified visual transcriptions of page {page_number} into readable historical newspaper text.
Preserve every source character and traditional form. Do not add text not present in region transcriptions. Use region order
and article_id to combine columns. Keep unresolved □ and list uncertainty rather than guessing. Return JSON only with
corrected_text, articles (id,title,text), corrections (region_id,original,corrected,reason,confidence), and warnings.

Region evidence:
{json.dumps(regions, ensure_ascii=False)}

Local OCR is a secondary candidate only; use it to flag conflicts, not overwrite clear visual readings:
{page_text}"""
        return self._text_json(prompt, max_tokens=5000)

    def correct_page(self, page_number: int, regions: List[Dict], page_text: str = "", page_image: str | Path | None = None) -> Dict:
        compact = [{
            "region_id": region["region_id"], "order": region["order"], "label": region["label"],
            "article_id": region["article_id"], "direction": region["direction"],
            "raw_text": region.get("raw_text", ""), "confidence": region.get("confidence", 0),
            "quality": region.get("quality", {}),
        } for region in regions]
        prompt = f"""Proofread OCR from page {page_number} of a historical traditional-Chinese newspaper.
Use the page image as the primary evidence and the OCR text only as a draft. Use region order, labels, article grouping
and semantics. Correct only characters supported by the image or strong context; preserve historical wording, traditional
characters, names and uncertainty. Never silently modernize the text. Return JSON only with corrected_text, articles
(id, title, text), corrections (region_id, original, corrected, reason, confidence), and warnings.

OCR regions:
{json.dumps(compact, ensure_ascii=False)}

Page OCR draft after any human edits (use it as a transcription hint, not as unquestionable truth):
{page_text}"""
        if page_image and self.supports_vision:
            try:
                result = self._vision_json(page_image, prompt, max_tokens=6000)
                result.setdefault("transcription_mode", "vision")
                return result
            except AIInsufficientBalanceError:
                raise
            except Exception as error:
                # Text correction remains a safe fallback when the vision
                # provider is unavailable or rejects a large page image.
                result = self._text_json(prompt, max_tokens=5000)
                result.setdefault("warnings", []).append("视觉校正调用失败，已回退到文本语义校正；请复核低置信度区域。")
                result["transcription_mode"] = "text-fallback"
                return result
        result = self._text_json(prompt, max_tokens=5000)
        result.setdefault("transcription_mode", "text")
        return result

    def summarize_document(self, text: str, instruction: str = "") -> Dict:
        prompt = f"""请分析下面这份中国历史报纸的 OCR 转录内容，并且所有面向用户的分析文字必须使用简体中文。
无论原文或用户要求使用何种语言，summary、key_points、people、organizations、places、dates、topics 和
uncertainties 中的内容都必须用简体中文表达；仅在引用原文、专有名词或无法翻译的人名地名时保留原文。
只返回包含 summary、key_points、people、organizations、places、dates、topics、uncertainties 字段的 JSON。
区分原文明确记载的事实与分析判断，不得补造信息。用户关注重点：{instruction or '整体概述'}。

报纸转录内容：
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

    def _vision_json(self, image_path: str | Path, prompt: str, max_tokens: int = 5000) -> Dict:
        self._require_client()
        path = Path(image_path)
        media_type, encoded = self._encode_vision_image(path, max_dimension=2200 if "Transcribe only this crop" in prompt else 1800)
        prompt = f"{prompt}\nReturn json only as a single JSON object."
        if self.backend == "anthropic":
            response = self._call_provider(lambda: self.client.messages.create(model=self.model, max_tokens=max_tokens, messages=[{
                "role": "user", "content": [
                    {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": encoded}},
                    {"type": "text", "text": prompt},
                ]
            }]))
            content = response.content[0].text
        else:
            options = {
                "model": self.vision_model or self.model,
                "messages": [{"role": "user", "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{encoded}"}},
                ]}],
            }
            options["max_tokens"] = max_tokens
            if self.backend == "deepseek":
                options["response_format"] = {"type": "json_object"}
                options["extra_body"] = {"thinking": {"type": "disabled"}}
            try:
                response = self._call_provider(lambda: self.client.chat.completions.create(**options))
            except AIInsufficientBalanceError:
                raise
            except Exception:
                if self.backend != "deepseek":
                    raise
                options.pop("response_format", None)
                options.pop("extra_body", None)
                response = self._call_provider(lambda: self.client.chat.completions.create(**options))
            content = response.choices[0].message.content
        if not isinstance(content, str) or not content.strip():
            raise AIResponseError("The vision model returned an empty response")
        return self._parse_json(content, model=self.vision_model or self.model)

    def _encode_vision_image(self, path: Path, max_dimension: int = 2400) -> tuple[str, str]:
        """Bound image dimensions/bytes before sending a page to a vision model."""
        try:
            from PIL import Image
            with Image.open(path) as image:
                image = image.convert("RGB")
                # Avoid shrinking small text crops; enlarge to a useful reading
                # size when the source crop is low-resolution.
                scale = min(2.0, max_dimension / max(image.size))
                if abs(scale - 1.0) > 0.03:
                    image = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS)
                buffer = io.BytesIO()
                image.save(buffer, format="JPEG", quality=82, optimize=True)
                return "image/jpeg", base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            media_type = mimetypes.guess_type(path.name)[0] or "image/png"
            return media_type, base64.b64encode(path.read_bytes()).decode("ascii")

    def _text_json(self, prompt: str, max_tokens: int) -> Dict:
        self._require_client()
        if self.backend == "anthropic":
            response = self._call_provider(lambda: self.client.messages.create(model=self.model, max_tokens=max_tokens, messages=[{"role": "user", "content": prompt}]))
            content = response.content[0].text
        else:
            response = self._call_provider(lambda: self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
                response_format={"type": "json_object"},
            ))
            content = response.choices[0].message.content
        return self._parse_json(content, model=self.model)

    def _call_provider(self, request):
        try:
            return request()
        except Exception as error:
            response = getattr(error, "response", None)
            status_code = getattr(error, "status_code", None) or getattr(response, "status_code", None)
            body = getattr(error, "body", None)
            details = body.get("error", body) if isinstance(body, dict) else {}
            provider_message = details.get("message", "") if isinstance(details, dict) else ""
            error_code = details.get("code") if isinstance(details, dict) else None
            error_text = f"{provider_message} {error}"
            if status_code == 402 or error_code == "insufficient_balance_error" or "insufficient balance" in error_text.lower():
                request_id = details.get("request_id") if isinstance(details, dict) else None
                request_id = request_id or getattr(error, "request_id", None)
                if not request_id:
                    match = re.search(r"request[_ ]?id\s*[:=]\s*([A-Za-z0-9-]+)", error_text, re.IGNORECASE)
                    request_id = match.group(1) if match else None
                message = "AI 服务账户余额不足。请为当前 API 账户充值，或切换到余额充足的 AI 服务后重试。"
                if request_id:
                    message += f"请求编号：{request_id}。"
                raise AIInsufficientBalanceError(message) from error
            raise

    def _require_client(self):
        if not self.available:
            raise AIUnavailableError("Configure DEEPSEEK_API_KEY, ANTHROPIC_API_KEY or OPENAI_API_KEY to enable AI stages")

    def _parse_json(self, content: str, model: str | None = None) -> Dict:
        cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip(), flags=re.IGNORECASE)
        try:
            result = json.loads(cleaned)
        except json.JSONDecodeError as error:
            # Vision models sometimes add a short sentence around an otherwise
            # valid JSON object even when the prompt requests JSON only.
            start, end = cleaned.find("{"), cleaned.rfind("}")
            if start < 0 or end <= start:
                raise AIResponseError(f"Model did not return valid JSON: {error}") from error
            try:
                result = json.loads(cleaned[start:end + 1])
            except json.JSONDecodeError:
                raise AIResponseError(f"Model did not return valid JSON: {error}") from error
        if not isinstance(result, dict):
            raise AIResponseError("Model response must be a JSON object")
        result["ai_backend"], result["ai_model"] = self.backend, model or self.model
        return result
