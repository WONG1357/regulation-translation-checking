from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import Any, Iterable


SUPPORTED_EXTENSIONS = {"docx", "pdf", "txt"}
MAX_FILE_SIZE_MB = 50


@dataclass
class TextBlock:
    block_id: str
    file_name: str
    file_type: str
    text: str
    block_type: str
    order: int
    page_number: int | None = None
    section_heading: str | None = None
    section_id: str | None = None
    section_title: str = ""
    paragraph_number: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None
    bbox: tuple[float, float, float, float] | None = None
    bbox_normalized: tuple[float, float, float, float] | None = None
    is_repeated_header_footer: bool = False
    detected_language: str = ""
    extraction_source: str = "unknown"
    classification: str = "unknown"
    ignore_reason: str = ""

    def location_label(self) -> str:
        parts: list[str] = []
        if self.page_number:
            parts.append(f"Page {self.page_number}")
        if self.section_heading:
            parts.append(f"Section: {self.section_heading}")
        if self.paragraph_number:
            parts.append(f"Para {self.paragraph_number}")
        if self.table_index is not None:
            table = f"Table {self.table_index + 1}"
            if self.row_index is not None:
                table += f", row {self.row_index + 1}"
            if self.cell_index is not None:
                table += f", cell {self.cell_index + 1}"
            parts.append(table)
        return " | ".join(parts) if parts else f"Block {self.order + 1}"


@dataclass
class DocumentResult:
    file_name: str
    file_type: str
    blocks: list[TextBlock]
    warnings: list[str]
    metadata: dict[str, Any]


@dataclass
class BilingualPair:
    pair_id: str
    file_name: str
    chinese_text: str
    english_text: str
    confidence: str
    confidence_score: float
    pairing_reason: str
    location: str
    page_number: int | None = None
    section_heading: str | None = None
    chinese_block_id: str | None = None
    english_block_id: str | None = None
    chinese_block_ids: list[str] | None = None
    english_block_ids: list[str] | None = None
    merged_group_id: str | None = None


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def strip_leading_clause_number(text: str) -> str:
    """Remove a leading clause/list marker without removing meaningful in-sentence numbers."""
    clean = normalize_text(text)
    clean = re.sub(
        r"^\s*(?:"
        r"\d+(?:\.\d+)+(?:[.)、：:]|\s+)?"
        r"|[(（]?\d+[)）.、]\s*"
        r")",
        "",
        clean,
        count=1,
    )
    return clean.strip()


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def contains_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def chinese_char_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text or ""))


def english_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z\-]*", text or ""))


def classify_language(text: str) -> str:
    """Classify by meaningful character ratios, with codes/numbers kept neutral."""
    text = text or ""
    zh_count = chinese_char_count(text)
    latin_count = len(re.findall(r"[A-Za-z]", text))
    word_count = english_word_count(text)
    meaningful = zh_count + latin_count
    if meaningful == 0:
        return "Neutral"

    zh_ratio = zh_count / meaningful
    en_ratio = latin_count / meaningful
    if zh_count >= 2 and word_count >= 1 and zh_ratio >= 0.18 and en_ratio >= 0.18:
        return "Mixed Chinese-English"
    if zh_count >= 2 and (zh_ratio >= 0.65 or word_count <= 1):
        return "Chinese"
    if word_count >= 1 and (en_ratio >= 0.65 or zh_count <= 1):
        return "English"
    if zh_count and latin_count:
        return "Mixed Chinese-English"
    return "Neutral"


def confidence_from_score(score: float) -> str:
    if score >= 0.75:
        return "High"
    if score >= 0.45:
        return "Medium"
    return "Low"


def text_preview(text: str, limit: int = 180) -> str:
    clean = normalize_text(text)
    return clean if len(clean) <= limit else clean[: limit - 1] + "…"


def dataclasses_to_records(items: Iterable[Any]) -> list[dict[str, Any]]:
    return [asdict(item) if hasattr(item, "__dataclass_fields__") else dict(item) for item in items]


def safe_sheet_name(name: str) -> str:
    cleaned = re.sub(r"[\[\]\*:/\\?]", "_", name)[:31]
    return cleaned or "Sheet"
