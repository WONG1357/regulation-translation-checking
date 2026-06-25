from __future__ import annotations

import math
import re
from collections import Counter
from difflib import SequenceMatcher

from rapidfuzz.fuzz import token_set_ratio

from src.ai_client import AIClient
from src.schemas import ChineseTranslationResponse, ExtractedBlock
from src.utils import chunks, extract_references, normalize_text

HEADING_TRANSLATIONS = {
    "目录": "Table of Contents",
    "目的": "Purpose",
    "范围": "Scope",
    "参考文件": "References Document",
    "质量管理体系标准": "Quality Management System Specification",
    "适用法规": "Applicable Regulations",
    "定义/简写": "Definitions and Abbreviations",
    "定义简写": "Definitions and Abbreviations",
    "分发控制": "Distribution Control",
    "质量管理体系": "Quality Management System",
    "管理职责": "Management Responsibility",
    "资源管理": "Resource Management",
    "产品实现": "Product Realization",
    "测量、分析和改进": "Measurement, Analysis and Improvement",
    "测量分析和改进": "Measurement, Analysis and Improvement",
    "公司简介": "Company History",
    "更改历史记录": "History of Change",
    "文件控制": "Control of Documents",
    "记录控制": "Control of Records",
    "设计和开发": "Design and Development",
    "风险管理": "Risk Management",
    "纠正措施": "Corrective Action",
    "预防措施": "Preventive Action",
}

TRANSLATION_PROMPT = """Translate the Chinese-language content in each supplied document
block into faithful, literal professional English for bilingual matching. A layout block may
also contain an existing English translation; ignore that existing English and translate only
the Chinese content. Preserve names, dates, clause numbers, procedure codes, obligation
strength, bullets, and ordering. Do not explain, summarize, or improve the source. Return JSON
only with one item per block_id."""

TOKEN_RE = re.compile(r"[a-z0-9]+(?:[./:-][a-z0-9]+)*", re.I)
ENTITY_RE = re.compile(
    r"\b(?:QSP\d{4}|WI\d{3,5}|ISO[-\s]?\d+|21\s+CFR(?:\s+Part)?\s*\d+|"
    r"EU\s+(?:MDR|MDD)|YY/?T?\s*\d+|[A-Z]{2,6}|\d+(?:\.\d+)+(?:\.[a-z]\)?)?)\b",
    re.I,
)


def normalize_for_similarity(text: str) -> str:
    text = normalize_text(text).lower()
    text = re.sub(r"(?<=\w)\s+(?=\w)", " ", text)
    text = re.sub(r"[^a-z0-9\s./:-]", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def heading_reference_translation(text: str) -> str | None:
    chinese_chars = len(re.findall(r"[\u3400-\u9fff]", text))
    if len(text) > 90 or chinese_chars > 24 or re.search(r"[。；;！？!?]", text):
        return None
    cleaned = re.sub(r"^\s*(?:\d+\.)*\d+\s*", "", text)
    cleaned = re.sub(r"[\s：:]+", "", cleaned)
    for chinese, english in sorted(
        HEADING_TRANSLATIONS.items(), key=lambda item: len(item[0]), reverse=True
    ):
        if chinese.replace("、", "") in cleaned.replace("、", ""):
            return english
    return None


def translate_chinese_blocks(
    blocks: list[ExtractedBlock],
    client: AIClient | None,
    *,
    batch_size: int = 12,
) -> dict[str, str]:
    """Translate every Chinese-bearing block before candidate matching.

    In dry-run mode, only stable heading glossary translations are emitted. Prose is left
    untranslated and therefore cannot be force-paired by position.
    """
    translations: dict[str, str] = {}
    pending: list[ExtractedBlock] = []
    for block in blocks:
        heading_translation = heading_reference_translation(block.text)
        if block.block_type == "heading" and heading_translation:
            translations[block.block_id] = heading_translation
        elif block.content_class == "reference_table":
            translations[block.block_id] = ""
        else:
            pending.append(block)

    if client is None:
        return translations

    for batch in chunks(pending, batch_size):
        payload = {
            "blocks": [
                {
                    "block_id": block.block_id,
                    "page": block.page,
                    "section": block.section,
                    "block_type": block.block_type,
                    "revision_id": block.revision_id,
                    "chinese_text": block.text,
                }
                for block in batch
            ]
        }
        response = client.request_json(
            TRANSLATION_PROMPT, payload, ChineseTranslationResponse
        )
        returned = {item.block_id: item.translated_english for item in response.items}
        for block in batch:
            translations[block.block_id] = normalize_text(returned.get(block.block_id, ""))
    return translations


def semantic_similarity(machine_translation: str, english_text: str) -> float:
    left = normalize_for_similarity(machine_translation)
    right = normalize_for_similarity(english_text)
    if not left or not right:
        return 0.0
    token_score = token_set_ratio(left, right) / 100.0
    sequence_score = SequenceMatcher(None, left, right).ratio()
    left_tokens = Counter(TOKEN_RE.findall(left))
    right_tokens = Counter(TOKEN_RE.findall(right))
    overlap = sum((left_tokens & right_tokens).values())
    token_recall = overlap / max(sum(left_tokens.values()), 1)
    return min(1.0, 0.5 * token_score + 0.25 * sequence_score + 0.25 * token_recall)


def shared_entities_score(
    chinese_text: str, machine_translation: str, english_text: str
) -> float:
    source_entities = {
        match.upper()
        for match in ENTITY_RE.findall(f"{chinese_text} {machine_translation}")
    } | extract_references(chinese_text)
    target_entities = {
        match.upper() for match in ENTITY_RE.findall(english_text)
    } | extract_references(english_text)
    if not source_entities and not target_entities:
        return 0.5
    return len(source_entities & target_entities) / max(
        len(source_entities | target_entities), 1
    )


def page_proximity_score(chinese: ExtractedBlock, english: ExtractedBlock) -> float:
    gap = abs(chinese.page - english.page)
    return {0: 1.0, 1: 0.65, 2: 0.2}.get(gap, 0.0)


def section_score(chinese: ExtractedBlock, english: ExtractedBlock) -> float:
    if not chinese.section or not english.section:
        return 0.5
    return 1.0 if chinese.section == english.section else 0.0


def length_similarity_score(machine_translation: str, english_text: str) -> float:
    if not machine_translation or not english_text:
        return 0.0
    ratio = min(len(machine_translation), len(english_text)) / max(
        len(machine_translation), len(english_text)
    )
    return math.sqrt(ratio)


def layout_proximity_score(chinese: ExtractedBlock, english: ExtractedBlock) -> float:
    if chinese.table_id and chinese.table_id == english.table_id:
        if chinese.row_index == english.row_index:
            return 1.0
        if chinese.row_index is not None and english.row_index is not None:
            return max(0.0, 1.0 - abs(chinese.row_index - english.row_index) / 4)
    if chinese.page != english.page:
        return 0.2
    if not chinese.bbox or not english.bbox:
        order_gap = abs(chinese.reading_order - english.reading_order)
        return max(0.0, 1.0 - order_gap / 800)
    page_height = max(chinese.bbox[3], english.bbox[3], 1)
    vertical_gap = abs(
        (chinese.bbox[1] + chinese.bbox[3]) / 2
        - (english.bbox[1] + english.bbox[3]) / 2
    )
    return max(0.0, 1.0 - vertical_gap / page_height)


def weighted_pair_score(
    chinese: ExtractedBlock,
    english: ExtractedBlock,
    machine_translation: str,
) -> tuple[float, float, dict[str, float]]:
    semantic = semantic_similarity(machine_translation, english.text)
    components = {
        "semantic": semantic,
        "entities": shared_entities_score(
            chinese.text, machine_translation, english.text
        ),
        "page": page_proximity_score(chinese, english),
        "section": section_score(chinese, english),
        "length": length_similarity_score(machine_translation, english.text),
        "layout": layout_proximity_score(chinese, english),
    }
    score = (
        0.55 * components["semantic"]
        + 0.15 * components["entities"]
        + 0.10 * components["page"]
        + 0.10 * components["section"]
        + 0.05 * components["length"]
        + 0.05 * components["layout"]
    )
    return min(score, 1.0), semantic, components
