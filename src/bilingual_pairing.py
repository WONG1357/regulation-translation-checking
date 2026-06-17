from __future__ import annotations

import re
from collections import Counter

from .utils import (
    BilingualPair,
    DocumentResult,
    TextBlock,
    chinese_char_count,
    classify_language,
    confidence_from_score,
    contains_chinese,
    contains_english,
    english_word_count,
    normalize_text,
)


SPLIT_PATTERNS = [
    re.compile(r"(.+?[\u3400-\u9fff].+?)\s*/\s*(.+?[A-Za-z].*)"),
    re.compile(r"(.+?[\u3400-\u9fff].+?)\s*\|\s*(.+?[A-Za-z].*)"),
    re.compile(r"(.+?[\u3400-\u9fff].+?)\s{2,}(.+?[A-Za-z].*)"),
]


def build_document_summary(doc: DocumentResult, pairs: list[BilingualPair]) -> dict[str, object]:
    languages = Counter(classify_language(block.text) for block in doc.blocks)
    return {
        "file name": doc.file_name,
        "file type": doc.file_type.upper(),
        "detected languages": ", ".join(lang for lang, count in languages.items() if count),
        "Chinese blocks": sum(1 for block in doc.blocks if contains_chinese(block.text)),
        "English blocks": sum(1 for block in doc.blocks if contains_english(block.text)),
        "likely bilingual pairs": len(pairs),
        "document title": doc.metadata.get("title"),
        "document number": doc.metadata.get("document_number"),
        "revision": doc.metadata.get("revision"),
        "page count": doc.metadata.get("page_count"),
    }


def identify_bilingual_pairs(doc: DocumentResult) -> list[BilingualPair]:
    pairs: list[BilingualPair] = []
    used_english_ids: set[str] = set()

    for block in doc.blocks:
        same_block = split_same_block_pair(block)
        if same_block:
            pairs.append(same_block)
            continue

    chinese_blocks = [b for b in doc.blocks if contains_chinese(b.text)]
    english_blocks = [b for b in doc.blocks if contains_english(b.text)]
    same_block_ids = {p.chinese_block_id for p in pairs if p.chinese_block_id}

    for zh in chinese_blocks:
        if zh.block_id in same_block_ids and contains_english(zh.text):
            continue
        candidates = [
            en for en in english_blocks
            if en.block_id not in used_english_ids
            and en.block_id != zh.block_id
            and abs(en.order - zh.order) <= 4
        ]
        if not candidates:
            continue
        scored = [(en, *_candidate_score(zh, en)) for en in candidates]
        best_en, score, reason = max(scored, key=lambda item: item[1])
        if score < 0.25:
            continue
        used_english_ids.add(best_en.block_id)
        pairs.append(
            BilingualPair(
                pair_id=f"{doc.file_name}:pair:{len(pairs) + 1}",
                file_name=doc.file_name,
                chinese_text=normalize_text(zh.text),
                english_text=normalize_text(best_en.text),
                confidence=confidence_from_score(score),
                confidence_score=round(score, 2),
                pairing_reason=reason,
                location=zh.location_label(),
                page_number=zh.page_number or best_en.page_number,
                section_heading=zh.section_heading or best_en.section_heading,
                chinese_block_id=zh.block_id,
                english_block_id=best_en.block_id,
            )
        )

    return pairs


def split_same_block_pair(block: TextBlock) -> BilingualPair | None:
    if not (contains_chinese(block.text) and contains_english(block.text)):
        return None
    for pattern in SPLIT_PATTERNS:
        match = pattern.match(block.text)
        if match:
            zh, en = match.group(1), match.group(2)
            if chinese_char_count(zh) >= 2 and english_word_count(en) >= 1:
                return BilingualPair(
                    pair_id=f"{block.file_name}:same:{block.order}",
                    file_name=block.file_name,
                    chinese_text=normalize_text(zh),
                    english_text=normalize_text(en),
                    confidence="High",
                    confidence_score=0.9,
                    pairing_reason=f"Chinese and English found in the same {block.block_type}",
                    location=block.location_label(),
                    page_number=block.page_number,
                    section_heading=block.section_heading,
                    chinese_block_id=block.block_id,
                    english_block_id=block.block_id,
                )
    return None


def _candidate_score(zh: TextBlock, en: TextBlock) -> tuple[float, str]:
    score = 0.15
    reasons: list[str] = []
    distance = abs(en.order - zh.order)
    score += max(0.0, 0.35 - distance * 0.08)
    reasons.append(f"nearby paragraph distance {distance}")

    if zh.page_number and en.page_number and zh.page_number == en.page_number:
        score += 0.2
        reasons.append("same page")
    if zh.section_heading and en.section_heading and zh.section_heading == en.section_heading:
        score += 0.15
        reasons.append("same section")
    if zh.table_index is not None and zh.table_index == en.table_index:
        score += 0.25
        reasons.append("same table")
        if zh.row_index is not None and zh.row_index == en.row_index:
            score += 0.2
            reasons.append("same table row")
    length_ratio = min(chinese_char_count(zh.text) * 2.0, english_word_count(en.text) * 6.0) / max(chinese_char_count(zh.text) * 2.0, english_word_count(en.text) * 6.0, 1)
    score += length_ratio * 0.15
    return min(score, 0.98), ", ".join(reasons)
