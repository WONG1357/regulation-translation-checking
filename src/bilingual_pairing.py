from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

from .block_classification import classify_document_blocks
from .section_detection import (
    SectionSegment,
    build_section_segments,
    parse_section_heading,
    section_sort_key,
)
from .utils import (
    BilingualPair,
    DocumentResult,
    TextBlock,
    chinese_char_count,
    classify_language,
    confidence_from_score,
    english_word_count,
    normalize_text,
    strip_leading_clause_number,
)


SPLIT_PATTERNS = [
    re.compile(r"(.+?[\u3400-\u9fff].+?)\s*/\s*(.+?[A-Za-z].*)"),
    re.compile(r"(.+?[\u3400-\u9fff].+?)\s*\|\s*(.+?[A-Za-z].*)"),
    re.compile(r"(.+?[\u3400-\u9fff].+?)\s{2,}(.+?[A-Za-z].*)"),
    re.compile(r"(.+?[\u3400-\u9fff][\u3400-\u9fff\s，。；：、（）()0-9.\-]*)\s+([A-Za-z].*)"),
    re.compile(r"(.+?[\u3400-\u9fff][\u3400-\u9fff\s，。；：、（）()0-9.\-]*)([A-Z][A-Za-z][A-Za-z0-9 ,;:()/&.\-].*)"),
    re.compile(r"([A-Za-z][A-Za-z0-9 ,;:()/&.\-]+?)\s+(.+?[\u3400-\u9fff].*)"),
]
BULLET_RE = re.compile(r"^\s*(?:[-•●▪◦]|[(（]?\d+[.)、）]|[A-Za-z][.)])\s*")
SENTENCE_END_RE = re.compile(r"[。！？.!?；;：:]$|[。！？.!?；;：:][”’'\")]$")
METADATA_RE = re.compile(
    r"(?:文件编号|文件名称|文件版本|页次|生效日期|批准|审核|编写|"
    r"\bdoc(?:ument)?\s*(?:no|name|rev)|\bpage\s*(?:no|number)|"
    r"\beffective\s*date|\bprepared\s*by|\bapproved\s*by)",
    re.I,
)
PAGE_NUMBER_RE = re.compile(
    r"^\s*(?:第\s*)?\d+\s*(?:页(?:共\s*\d+\s*页)?|/\s*\d+|of\s+\d+)?\s*$",
    re.I,
)
MIXED_SHORT_TERM_MAX_CHARS = 90


@dataclass
class PairingOptions:
    review_start_section: str | float = "2.0"
    include_headings: bool = False
    include_revision_history: bool = False
    include_definitions: bool = False
    include_clause_matrix: bool = False
    include_tables_after_start: bool = True
    include_headers_footers: bool = False


@dataclass
class MergedGroup:
    group_id: str
    language: str
    blocks: list[TextBlock]
    segment_id: str | None = None
    section_id: str | None = None

    @property
    def text(self) -> str:
        return normalize_text(" ".join(block.text for block in self.blocks))


@dataclass
class PairingAnalysis:
    pairs: list[BilingualPair] = field(default_factory=list)
    groups: list[MergedGroup] = field(default_factory=list)
    block_to_group: dict[str, str] = field(default_factory=dict)
    block_to_pair: dict[str, str] = field(default_factory=dict)
    block_status: dict[str, str] = field(default_factory=dict)
    block_reason: dict[str, str] = field(default_factory=dict)
    segments: list[SectionSegment] = field(default_factory=list)
    block_to_segment: dict[str, str] = field(default_factory=dict)


def build_document_summary(doc: DocumentResult, pairs: list[BilingualPair]) -> dict[str, object]:
    languages = Counter(classify_language(block.text) for block in doc.blocks)
    return {
        "file name": doc.file_name,
        "file type": doc.file_type.upper(),
        "detected languages": ", ".join(lang for lang, count in languages.items() if count),
        "Chinese blocks": languages["Chinese"],
        "English blocks": languages["English"],
        "mixed bilingual blocks": languages["Mixed Chinese-English"],
        "neutral blocks": languages["Neutral"],
        "likely bilingual pairs": len(pairs),
        "document title": doc.metadata.get("title"),
        "document number": doc.metadata.get("document_number"),
        "revision": doc.metadata.get("revision"),
        "page count": doc.metadata.get("page_count"),
    }


def identify_bilingual_pairs(doc: DocumentResult, include_headers_footers: bool = False) -> list[BilingualPair]:
    return analyze_bilingual_pairing(
        doc,
        PairingOptions(include_headers_footers=include_headers_footers),
    ).pairs


def analyze_bilingual_pairing(
    doc: DocumentResult,
    options: PairingOptions | None = None,
) -> PairingAnalysis:
    """Pair in reading order: Chinese group -> closest following English group."""
    options = options or PairingOptions()
    classify_document_blocks(doc, options.review_start_section)
    analysis = PairingAnalysis()
    ordered = sorted(doc.blocks, key=lambda block: block.order)
    analysis.segments = build_section_segments(ordered)
    for segment in analysis.segments:
        for block_id in segment.block_ids:
            analysis.block_to_segment[block_id] = segment.segment_id
    eligible: list[TextBlock] = []
    for block in ordered:
        classification = block.classification
        if classification == "header_footer" and not options.include_headers_footers:
            analysis.block_status[block.block_id] = "ignored header-footer"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification in {"heading", "section_title"} and not options.include_headings:
            analysis.block_status[block.block_id] = "ignored heading"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "document_metadata":
            analysis.block_status[block.block_id] = "ignored document metadata"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "page_number":
            analysis.block_status[block.block_id] = "ignored page number"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "image_or_visual":
            analysis.block_status[block.block_id] = "ignored image or visual"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if (
            block.ignore_reason
            and "before configured review start" in block.ignore_reason
            and classification in {"main_chinese_paragraph", "main_english_translation", "neutral", "unknown"}
        ):
            analysis.block_status[block.block_id] = "ignored before review start"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "table_of_contents":
            analysis.block_status[block.block_id] = "ignored table of contents"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "revision_history" and not options.include_revision_history:
            analysis.block_status[block.block_id] = "ignored revision history"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "definitions_abbreviation" and not options.include_definitions:
            analysis.block_status[block.block_id] = "ignored definitions"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "regulation_reference":
            analysis.block_status[block.block_id] = "ignored regulation reference"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if classification == "clause_matrix" and not options.include_clause_matrix:
            analysis.block_status[block.block_id] = "ignored clause matrix"
            analysis.block_reason[block.block_id] = block.ignore_reason
            continue
        if block.table_index is not None and not options.include_tables_after_start:
            analysis.block_status[block.block_id] = "ignored table content"
            analysis.block_reason[block.block_id] = "Table review disabled by user setting."
            continue
        if (
            block.detected_language == "Mixed Chinese-English"
            and len(block.text) <= MIXED_SHORT_TERM_MAX_CHARS
            and not options.include_headings
        ):
            analysis.block_status[block.block_id] = "ignored mixed short term"
            analysis.block_reason[block.block_id] = "Short mixed bilingual heading/term excluded from paragraph review."
            continue
        if classification in {"main_chinese_paragraph", "main_english_translation"}:
            eligible.append(block)
        elif classification in {"heading", "section_title"} and options.include_headings:
            eligible.append(block)
        elif classification == "header_footer" and options.include_headers_footers:
            eligible.append(block)
        elif block.detected_language == "Mixed Chinese-English":
            eligible.append(block)
        elif classification in {"revision_history", "definitions_abbreviation", "clause_matrix"}:
            eligible.append(block)
        else:
            analysis.block_status[block.block_id] = classification
            analysis.block_reason[block.block_id] = block.ignore_reason or "Not a main bilingual paragraph candidate."

    groups = _build_groups(eligible, doc.file_name, analysis.block_to_segment)
    analysis.groups = groups
    for group in groups:
        for block in group.blocks:
            analysis.block_to_group[block.block_id] = group.group_id

    pair_number = _recover_parallel_language_runs(doc, analysis, groups, 0)
    index = 0
    while index < len(groups):
        group = groups[index]
        if _group_is_paired(analysis, group):
            index += 1
            continue
        if group.language == "Mixed Chinese-English":
            pair_number += 1
            pair = _split_group_pair(doc, group, pair_number)
            if pair:
                analysis.pairs.append(pair)
                _mark_pair(analysis, pair, group.blocks)
            else:
                for block in group.blocks:
                    analysis.block_status[block.block_id] = "mixed"
                    analysis.block_reason[block.block_id] = "Mixed bilingual block could not be split confidently; needs review."
            index += 1
            continue
        if group.language != "Chinese":
            index += 1
            continue

        next_index = index + 1
        skipped_neutral: list[MergedGroup] = []
        while (
            next_index < len(groups)
            and groups[next_index].language == "Neutral"
            and _groups_share_pairing_scope(group, groups[next_index])
        ):
            skipped_neutral.append(groups[next_index])
            next_index += 1
        if (
            next_index < len(groups)
            and groups[next_index].language == "English"
            and _groups_share_pairing_scope(group, groups[next_index])
        ):
            english_group = groups[next_index]
            if _strong_evidence_not_translation(group, english_group):
                index += 1
                continue
            pair_number += 1
            pair = _make_following_pair(
                doc,
                group,
                english_group,
                pair_number,
                bool(skipped_neutral),
            )
            analysis.pairs.append(pair)
            _mark_pair(analysis, pair, group.blocks + english_group.blocks)
            index = next_index + 1
            continue
        index += 1

    for block in ordered:
        if block.block_id in analysis.block_status:
            continue
        language = block.detected_language or classify_language(block.text)
        if language == "Neutral":
            analysis.block_status[block.block_id] = "neutral"
            analysis.block_reason[block.block_id] = "Numeric, code, date, punctuation, or other language-neutral content."
        else:
            analysis.block_status[block.block_id] = "unpaired"
            if language == "Chinese":
                reason = "No suitable English block immediately followed this Chinese block/group."
            elif language == "English":
                reason = "No unpaired Chinese block/group immediately preceded this English block."
            else:
                reason = "Mixed bilingual block could not be split confidently; needs review."
            analysis.block_reason[block.block_id] = reason
    return analysis


def _recover_parallel_language_runs(
    doc: DocumentResult,
    analysis: PairingAnalysis,
    groups: list[MergedGroup],
    pair_number: int,
) -> int:
    """Recover common PDF column order: Chinese run followed by matching English run."""
    index = 0
    while index < len(groups):
        first = groups[index]
        if first.language != "Chinese" or _group_is_paired(analysis, first):
            index += 1
            continue
        chinese_run: list[MergedGroup] = []
        cursor = index
        while (
            cursor < len(groups)
            and groups[cursor].language == "Chinese"
            and groups[cursor].segment_id == first.segment_id
            and not _group_is_paired(analysis, groups[cursor])
            and len(chinese_run) < 8
        ):
            chinese_run.append(groups[cursor])
            cursor += 1
        english_run: list[MergedGroup] = []
        while (
            cursor < len(groups)
            and groups[cursor].language == "English"
            and groups[cursor].segment_id == first.segment_id
            and not _group_is_paired(analysis, groups[cursor])
            and len(english_run) < 8
        ):
            english_run.append(groups[cursor])
            cursor += 1
        if len(chinese_run) >= 2 and len(chinese_run) == len(english_run):
            for chinese, english in zip(chinese_run, english_run):
                if _strong_evidence_not_translation(chinese, english):
                    continue
                pair_number += 1
                pair = _make_following_pair(doc, chinese, english, pair_number, False)
                pair.confidence_score = min(pair.confidence_score, 0.72)
                pair.confidence = confidence_from_score(pair.confidence_score)
                pair.pairing_reason = "section-local parallel Chinese/English run"
                analysis.pairs.append(pair)
                _mark_pair(analysis, pair, chinese.blocks + english.blocks)
            index = cursor
            continue
        index += 1
    return pair_number


def _group_is_paired(analysis: PairingAnalysis, group: MergedGroup) -> bool:
    return any(block.block_id in analysis.block_to_pair for block in group.blocks)


def _build_groups(
    blocks: list[TextBlock],
    file_name: str,
    block_to_segment: dict[str, str],
) -> list[MergedGroup]:
    groups: list[MergedGroup] = []
    for block in blocks:
        language = classify_language(block.text)
        if (
            groups
            and language in {"Chinese", "English"}
            and groups[-1].language == language
            and groups[-1].segment_id == block_to_segment.get(block.block_id)
            and _should_merge_continuation(groups[-1].blocks[-1], block, language)
        ):
            groups[-1].blocks.append(block)
            continue
        group = MergedGroup(
            group_id=f"{file_name}:group:{len(groups) + 1}",
            language=language,
            blocks=[block],
            segment_id=block_to_segment.get(block.block_id),
            section_id=block.section_id,
        )
        groups.append(group)
    return groups


def _should_merge_continuation(previous: TextBlock, current: TextBlock, language: str) -> bool:
    if previous.page_number and current.page_number and previous.page_number != current.page_number:
        return False
    if previous.section_heading != current.section_heading and current.block_type == "heading":
        return False
    if previous.table_index is not None or current.table_index is not None:
        # Preserve row/cell boundaries. Wrapped text within a detected cell is
        # already returned as one cell block by the extractor.
        return (
            previous.table_index == current.table_index
            and previous.row_index == current.row_index
            and previous.cell_index == current.cell_index
        )
    if current.block_type == "heading":
        return False
    if BULLET_RE.match(current.text):
        return False
    if BULLET_RE.match(previous.text) and SENTENCE_END_RE.search(previous.text):
        return False

    if previous.bbox and current.bbox:
        vertical_gap = current.bbox[1] - previous.bbox[3]
        indent_gap = abs(current.bbox[0] - previous.bbox[0])
        if vertical_gap < -2 or vertical_gap > 22 or indent_gap > 24:
            return False
        if not SENTENCE_END_RE.search(previous.text):
            return True
        # A completed sentence may still wrap into a paragraph continuation,
        # but require very tight alignment.
        return vertical_gap <= 8 and indent_gap <= 6

    # DOCX/TXT paragraphs are already paragraph-level; only join obvious
    # extraction fragments without final punctuation.
    return not SENTENCE_END_RE.search(previous.text) and len(previous.text) < (90 if language == "English" else 55)


def _groups_share_pairing_scope(chinese: MergedGroup, following: MergedGroup) -> bool:
    if chinese.segment_id == following.segment_id:
        return True
    if not chinese.section_id or chinese.section_id != following.section_id:
        return False
    previous = chinese.blocks[-1]
    current = following.blocks[0]
    return (
        previous.page_number is not None
        and current.page_number is not None
        and current.page_number == previous.page_number + 1
    )


def split_same_block_pair(block: TextBlock) -> BilingualPair | None:
    group = MergedGroup(
        f"{block.file_name}:group:{block.order}",
        "Mixed Chinese-English",
        [block],
        section_id=block.section_id,
    )
    return _split_group_pair(
        DocumentResult(block.file_name, block.file_type, [block], [], {}),
        group,
        block.order + 1,
    )


def _split_group_pair(doc: DocumentResult, group: MergedGroup, pair_number: int) -> BilingualPair | None:
    text = group.text
    for pattern in SPLIT_PATTERNS:
        match = pattern.fullmatch(text)
        if not match:
            continue
        first, second = normalize_text(match.group(1)), normalize_text(match.group(2))
        zh, en = (first, second) if chinese_char_count(first) >= chinese_char_count(second) else (second, first)
        if chinese_char_count(zh) < 2 or english_word_count(en) < 1:
            continue
        block_ids = [block.block_id for block in group.blocks]
        first_block = group.blocks[0]
        return BilingualPair(
            pair_id=f"{doc.file_name}:pair:{pair_number}",
            file_name=doc.file_name,
            chinese_text=strip_leading_clause_number(zh),
            english_text=strip_leading_clause_number(en),
            confidence="High",
            confidence_score=0.94,
            pairing_reason="same mixed bilingual line",
            location=first_block.location_label(),
            page_number=first_block.page_number,
            section_heading=first_block.section_heading,
            chinese_block_id=block_ids[0],
            english_block_id=block_ids[0],
            chinese_block_ids=block_ids,
            english_block_ids=block_ids,
            merged_group_id=group.group_id,
        )
    return None


def _make_following_pair(
    doc: DocumentResult,
    chinese: MergedGroup,
    english: MergedGroup,
    pair_number: int,
    skipped_neutral: bool,
) -> BilingualPair:
    zh_first = chinese.blocks[0]
    en_first = english.blocks[0]
    score = 0.78
    reasons = ["Chinese block immediately followed by English block"]
    if skipped_neutral:
        score -= 0.14
        reasons[0] = "uncertain but nearest following English block"
    if len(chinese.blocks) > 1 or len(english.blocks) > 1:
        score += 0.04
        reasons.append("paragraph continuation merged")
        if any(BULLET_RE.match(block.text) for block in chinese.blocks + english.blocks):
            reasons[-1] = "bullet continuation merged"
    if zh_first.page_number and zh_first.page_number == en_first.page_number:
        score += 0.06
    if zh_first.bbox and en_first.bbox and abs(zh_first.bbox[0] - en_first.bbox[0]) <= 18:
        score += 0.05
    if zh_first.table_index is not None and zh_first.table_index == en_first.table_index:
        if zh_first.row_index == en_first.row_index and zh_first.cell_index == en_first.cell_index:
            score = max(score, 0.96)
            reasons = ["same table cell"]
        elif zh_first.row_index == en_first.row_index:
            score = max(score, 0.94)
            reasons = ["same table row"]
        elif en_first.row_index == (zh_first.row_index or 0) + 1:
            score = max(score, 0.88)
            reasons = ["adjacent table rows"]
    return BilingualPair(
        pair_id=f"{doc.file_name}:pair:{pair_number}",
        file_name=doc.file_name,
        chinese_text=strip_leading_clause_number(chinese.text),
        english_text=strip_leading_clause_number(english.text),
        confidence=confidence_from_score(min(score, 0.98)),
        confidence_score=round(min(score, 0.98), 2),
        pairing_reason=", ".join(reasons),
        location=zh_first.location_label(),
        page_number=zh_first.page_number or en_first.page_number,
        section_heading=zh_first.section_heading or en_first.section_heading,
        chinese_block_id=chinese.blocks[0].block_id,
        english_block_id=english.blocks[0].block_id,
        chinese_block_ids=[block.block_id for block in chinese.blocks],
        english_block_ids=[block.block_id for block in english.blocks],
        merged_group_id=f"{chinese.group_id} + {english.group_id}",
    )


def _strong_evidence_not_translation(chinese: MergedGroup, english: MergedGroup) -> bool:
    zh = chinese.blocks[0]
    en = english.blocks[0]
    if zh.page_number and en.page_number and en.page_number - zh.page_number > 1:
        return True
    if zh.table_index is not None or en.table_index is not None:
        if zh.table_index != en.table_index:
            return True
        if zh.row_index is not None and en.row_index is not None and abs(en.row_index - zh.row_index) > 1:
            return True
    return False


def _mark_pair(analysis: PairingAnalysis, pair: BilingualPair, blocks: list[TextBlock]) -> None:
    status = "mixed" if pair.chinese_block_ids == pair.english_block_ids else "paired"
    for block in blocks:
        analysis.block_to_pair[block.block_id] = pair.pair_id
        analysis.block_status[block.block_id] = status
        analysis.block_reason[block.block_id] = pair.pairing_reason


def section_number(text: str | None) -> tuple[int, ...] | None:
    if not text:
        return None
    detected = parse_section_heading(text)
    key = detected.key if detected else section_sort_key(text)
    return key or None


def classify_section_category(text: str | None) -> str:
    value = normalize_text(text or "").lower()
    patterns = {
        "revision_history": r"更改历史|修订历史|revision history|history of change",
        "table_of_contents": r"目录|table of contents|contents",
        "purpose": r"目的|purpose",
        "scope": r"范围|scope",
        "references": r"参考文件|引用文件|reference document|references",
        "definitions": r"定义|简写|缩写|definition|abbreviation",
        "distribution_control": r"分发|distribution control",
        "clause_matrix": r"条款矩阵|clause matrix|对照表",
        "company_history": r"公司历史|company history",
    }
    for category, pattern in patterns.items():
        if re.search(pattern, value, re.I):
            return category
    return "main_body"
