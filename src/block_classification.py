from __future__ import annotations

import re

from .section_detection import assign_sections, parse_section_heading, section_at_or_after
from .utils import DocumentResult, TextBlock, classify_language, normalize_text


CLASSIFICATIONS = {
    "main_chinese_paragraph",
    "main_english_translation",
    "heading",
    "section_title",
    "table_of_contents",
    "revision_history",
    "definitions_abbreviation",
    "regulation_reference",
    "clause_matrix",
    "header_footer",
    "document_metadata",
    "page_number",
    "image_or_visual",
    "neutral",
    "unknown",
}

PAGE_NUMBER_RE = re.compile(r"^\s*(?:第\s*)?\d+\s*(?:页(?:\s*共\s*\d+\s*页)?|/\s*\d+|of\s+\d+)?\s*$", re.I)
METADATA_RE = re.compile(
    r"(?:文件编号|文件名称|文件版本|版本号|修订号|生效日期|批准|审核|编写|签名|"
    r"\bdoc(?:ument)?\s*(?:no|name|number)|\brevision\b|\brev(?:\.|\s*[:：])"
    r"|\beffective\s*date|\bprepared\s*by|\bapproved\s*by|\bsignature)",
    re.I,
)
SECTION_PATTERNS = (
    ("table_of_contents", r"目录|table\s+of\s+contents|^\s*contents\s*$"),
    ("revision_history", r"更改历史|修订历史|版本历史|revision\s+history|history\s+of\s+change"),
    ("definitions_abbreviation", r"定义|简写|缩写|definitions?|abbreviations?"),
    ("regulation_reference", r"参考文件|引用文件|法规参考|reference\s+documents?|normative\s+references?"),
    ("clause_matrix", r"条款矩阵|clause\s+matrix|对照表|correlation\s+matrix"),
)


def classify_document_blocks(doc: DocumentResult, review_start_section: str | float = "2.0") -> None:
    """Attach deterministic language, source, classification, and ignore reason to every block."""
    ordered = sorted(doc.blocks, key=lambda block: block.order)
    assign_sections(ordered)
    first_start_order = _first_review_start_order(ordered, review_start_section)
    for block in ordered:
        block.detected_language = classify_language(block.text)
        block.extraction_source = _extraction_source(block)
        block.classification, block.ignore_reason = classify_block(
            block,
            review_start_section=review_start_section,
            first_start_order=first_start_order,
        )


def classify_block(
    block: TextBlock,
    review_start_section: str | float = "2.0",
    first_start_order: int | None = None,
) -> tuple[str, str]:
    text = normalize_text(block.text)
    language = block.detected_language or classify_language(text)
    section_text = normalize_text(block.section_heading or "")

    if block.block_type == "image_or_visual":
        return "image_or_visual", "Image, logo, organization chart, or other non-text visual is excluded from API review."
    if block.is_repeated_header_footer or block.block_type in {"header", "footer"}:
        return "header_footer", "Repeated page header or footer is excluded from API review."
    if PAGE_NUMBER_RE.fullmatch(text):
        return "page_number", "Standalone page number is excluded from API review."
    if METADATA_RE.search(text):
        return "document_metadata", "Document metadata, banner, revision, or signature content is excluded from API review."

    section_category = _section_category(section_text or text)
    if section_category:
        return section_category, _category_reason(section_category)

    if block.block_type == "heading":
        classification = "section_title" if _section_number(text) is not None else "heading"
        return classification, "Heading or section title is excluded from API paragraph review."

    section_no = block.section_id or _section_number(section_text)
    before_start = (
        (section_no is not None and not section_at_or_after(section_no, review_start_section))
        or (first_start_order is not None and block.order < first_start_order)
    )
    if before_start:
        return _language_candidate(language), (
            f"Content occurs before configured review start section {review_start_section}; "
            "it remains extracted and visible for debugging."
        )

    if language == "Chinese":
        return "main_chinese_paragraph", ""
    if language == "English":
        return "main_english_translation", ""
    if language == "Neutral":
        return "neutral", "Language-neutral content is not a bilingual paragraph candidate."
    if language == "Mixed Chinese-English":
        return "unknown", "Mixed bilingual text requires deterministic same-block splitting before review."
    return "unknown", "Text could not be deterministically classified."


def is_main_candidate(block: TextBlock) -> bool:
    return block.classification in {"main_chinese_paragraph", "main_english_translation"} and not block.ignore_reason


def _first_review_start_order(blocks: list[TextBlock], review_start_section: str | float) -> int | None:
    candidates = [
        block.order
        for block in blocks
        if block.block_type == "heading"
        and (detected := parse_section_heading(block.text))
        and section_at_or_after(detected.section_id, review_start_section)
    ]
    return min(candidates) if candidates else None


def _extraction_source(block: TextBlock) -> str:
    if block.extraction_source and block.extraction_source != "unknown":
        return block.extraction_source
    if block.block_type in {"paragraph", "table_cell", "header", "footer", "image_or_visual"}:
        return {
            "table_cell": "table",
            "image_or_visual": "unknown",
        }.get(block.block_type, block.block_type)
    return "unknown"


def _section_category(text: str) -> str | None:
    value = normalize_text(text).lower()
    for classification, pattern in SECTION_PATTERNS:
        if re.search(pattern, value, re.I):
            return classification
    return None


def _category_reason(classification: str) -> str:
    labels = {
        "table_of_contents": "Table of contents is excluded from API review.",
        "revision_history": "Revision history is excluded from API review.",
        "definitions_abbreviation": "Definitions and abbreviations are excluded from API review.",
        "regulation_reference": "Reference document section is excluded from API review.",
        "clause_matrix": "Clause matrix is excluded from API review.",
    }
    return labels[classification]


def _language_candidate(language: str) -> str:
    if language == "Chinese":
        return "main_chinese_paragraph"
    if language == "English":
        return "main_english_translation"
    if language == "Neutral":
        return "neutral"
    return "unknown"


def _section_number(text: str | None) -> str | None:
    if not text:
        return None
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", text)
    if not match:
        return None
    try:
        return match.group(1)
    except (ValueError, AttributeError):
        return None
