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
    paragraph_number: int | None = None
    table_index: int | None = None
    row_index: int | None = None
    cell_index: int | None = None

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


def normalize_text(text: str) -> str:
    text = text.replace("\u3000", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def contains_chinese(text: str) -> bool:
    return bool(re.search(r"[\u3400-\u9fff]", text or ""))


def contains_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def chinese_char_count(text: str) -> int:
    return len(re.findall(r"[\u3400-\u9fff]", text or ""))


def english_word_count(text: str) -> int:
    return len(re.findall(r"[A-Za-z][A-Za-z\-]*", text or ""))


def classify_language(text: str) -> str:
    has_zh = contains_chinese(text)
    has_en = contains_english(text)
    if has_zh and has_en:
        return "Chinese + English"
    if has_zh:
        return "Chinese"
    if has_en:
        return "English"
    return "Other/Unknown"


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
