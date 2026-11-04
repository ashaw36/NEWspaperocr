"""可插拔文字纠错策略层。

定位：版面/阅读顺序/文章聚合属于结构层；本模块只做文字级软后处理，
在 AI 聚合产出之后、写入 corrected.json 之前应用，不改结构语义。

默认策略只做「繁体→繁体」的 OCR 错字修复，绝不做繁→简转换，
以忠实保留民国报纸原文用字。若将来需要简体输出，应另行注册
opt-in 策略（例如 ``t2s``），不得改动默认 ``conservative`` 行为。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Type


# ---------------------------------------------------------------------------
# 接口
# ---------------------------------------------------------------------------


class BaseCorrector(ABC):
    """文字纠错器接口：只接收纯文本，返回纠错后文本。"""

    @property
    @abstractmethod
    def name(self) -> str:
        """策略注册名，与 task.options.correction_mode 对应。"""

    @abstractmethod
    def correct(self, text: str) -> str:
        """对单段文本做纠错。不得改变非替换目标的字符。"""


# ---------------------------------------------------------------------------
# 注册表 / 工厂
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Type[BaseCorrector]] = {}


def register_corrector(cls: Type[BaseCorrector]) -> Type[BaseCorrector]:
    """类装饰器：按 `name` 属性注册（实例化后读取）。"""
    instance_name = cls().name
    _REGISTRY[instance_name] = cls
    return cls


def registered_correctors() -> List[str]:
    return sorted(_REGISTRY.keys())


def get_corrector(name: str) -> BaseCorrector:
    """按策略名取纠错器实例。``none`` 不在注册表内，由调用方跳过。"""
    key = (name or "").strip().lower()
    if key not in _REGISTRY:
        known = ", ".join(registered_correctors()) or "(empty)"
        raise ValueError(f"Unknown correction_mode={name!r}; known: {known}")
    return _REGISTRY[key]()


# ---------------------------------------------------------------------------
# 保守策略
# ---------------------------------------------------------------------------

# 繁体→繁体 OCR 误识修复。只放「几乎不会误伤、字形相近」的高确定条目。
# 不处理异体字（如 説/說）；不确定的一律不放。宁可少、不可错。
# 不做任何简繁转换：正确繁体与纯简体输入均应原样保留。
_OCR_SAFE_REPLACEMENTS: Dict[str, str] = {
    # 「組織」常见误识
    "租酸": "組織",
    "粗織": "組織",
    "組辆": "組織",
    # 双字/专名字形相近误识
    "委目": "委員",
    "活勤": "活動",
    "老申銀": "老申報",
    "大公服": "大公報",
    "停利": "停刊",
}


def _apply_mapping(text: str, mapping: Dict[str, str]) -> str:
    """按键长优先做确定替换，避免短键吞掉长词。"""
    if not text or not mapping:
        return text
    # 长词优先，防止多字词被短键拆开替换后结果不一致
    for src in sorted(mapping.keys(), key=len, reverse=True):
        dst = mapping[src]
        if src != dst and src in text:
            text = text.replace(src, dst)
    return text


@register_corrector
class ConservativeCorrector(BaseCorrector):
    """保守纠错：仅繁体保形的 OCR 确定替换。

    - 不做繁→简（简体需求请另行注册 opt-in 策略，如 ``t2s``）
    - 不猜字、不增删、不改语义、不改异体字
    - 未知字原样保留
    - ``correct`` 对已是目标形的文本幂等
    """

    @property
    def name(self) -> str:
        return "conservative"

    def correct(self, text: str) -> str:
        if not text:
            return text
        return _apply_mapping(text, _OCR_SAFE_REPLACEMENTS)


def apply_page_correction(page: Dict, corrector: BaseCorrector) -> Dict:
    """对聚合页结果的文字字段做原地纠错（不碰结构字段 / corrections 审计）。"""
    corrected_text = page.get("corrected_text")
    if isinstance(corrected_text, str):
        page["corrected_text"] = corrector.correct(corrected_text)

    articles: Iterable = page.get("articles") or []
    for article in articles:
        if not isinstance(article, dict):
            continue
        for key in ("title", "subtitle", "body"):
            value = article.get(key)
            if isinstance(value, str):
                article[key] = corrector.correct(value)
    return page
