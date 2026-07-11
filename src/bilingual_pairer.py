from __future__ import annotations

from dataclasses import dataclass
import re

from src.ai_client import AIClient
from src.chinese_to_english_pairing import (
    heading_reference_translation,
    semantic_similarity,
    weighted_pair_score,
)
from src.schemas import (
    BilingualPair,
    BlockType,
    ExtractedBlock,
    Language,
    PairStatus,
    PairValidationResponse,
)
from src.utils import (
    CHINESE_RE,
    chunks,
    extract_references,
    normalize_text,
    read_prompt,
    stable_id,
)

ENGLISH_RE = re.compile(r"[A-Za-z]")
HTML_TABLE_TAG_RE = re.compile(r"</?(?:td|tr|th)(?:\s+[^>]*)?>", re.I)
TABLE_DELIMITER_RE = re.compile(r"\s*\|\s*|\t+")
DATE_CELL_RE = re.compile(r"\b\d{4}[-/]\d{1,2}[-/]\d{1,2}\b")
REVISION_CELL_RE = re.compile(r"[A-Z]")
ALLOWED_CHINESE_SIDE_LATIN_RE = re.compile(
    r"\b(?:[A-Z]{2,8}\d*|QSP\d{3,6}|WI\d{3,6}|ISO[-\s]?\d{3,6}|"
    r"YY/?T?\s*\d{3,6}|21\s*CFR(?:\s+Part)?\s*\d+|EU|MDR|MDD|"
    r"[IVX]{1,5}\s*[a-z]?)\b"
)
NO_NORMAL_PAIRING_CLASSES = {
    "regulatory_matrix",
    "organization_chart_or_structure",
    "table_of_contents",
    "approval_table",
    "document_metadata",
}
EN_ONLY_ALLOWED_CLASSES = {
    "definition_table",
    "regulatory_references",
    "regulatory_matrix",
    "procedure_reference",
}


@dataclass(frozen=True)
class AlignmentUnit:
    chinese: str
    english: str
    unit_index: int
    machine_translation: str = ""


def _clean_alignment_text(text: str | None) -> str:
    """Normalize alignment-unit text and remove table extraction artefacts.

    This mirrors the useful cleanup from the pasted line-based processor, but keeps it
    local to pairing so the original extracted block text is still preserved elsewhere.
    """
    if not text:
        return ""
    text = HTML_TABLE_TAG_RE.sub(" ", text)
    return normalize_text(text)


def _clean_chinese_side(text: str | None) -> str:
    """Keep Chinese source text Chinese, allowing only abbreviations/codes."""
    text = _clean_alignment_text(text)
    if not text:
        return ""

    def keep_allowed(match: re.Match[str]) -> str:
        span = match.group(0)
        allowed = [item.group(0) for item in ALLOWED_CHINESE_SIDE_LATIN_RE.finditer(span)]
        return f" {' '.join(allowed)} " if allowed else " "

    text = re.sub(r"[A-Za-z][A-Za-z0-9'’./&() -]*", keep_allowed, text)
    text = re.sub(r"\s+([，。；：、（）])", r"\1", text)
    text = re.sub(r"([（])\s+", r"\1", text)
    return _clean_alignment_text(text)


def _clean_english_side(text: str | None) -> str:
    """Keep existing English text English-only for display/review matching."""
    text = _clean_alignment_text(text)
    if not text:
        return ""
    text = CHINESE_RE.sub(" ", text)
    text = re.sub(r"[，。；：、（）【】《》]", " ", text)
    return _clean_alignment_text(text)


def _language_counts(text: str) -> tuple[int, int]:
    return len(CHINESE_RE.findall(text)), len(ENGLISH_RE.findall(text))


def _is_code_like_cell(text: str) -> bool:
    stripped = normalize_text(text)
    if not stripped:
        return True
    if extract_references(stripped) and len(stripped) <= 24:
        return True
    return bool(re.fullmatch(r"[\d\s./():;,_-]+", stripped))


def _is_structural_table_cell(text: str) -> bool:
    stripped = normalize_text(text)
    if not stripped:
        return True
    if REVISION_CELL_RE.fullmatch(stripped):
        return True
    if DATE_CELL_RE.fullmatch(stripped):
        return True
    return _is_code_like_cell(stripped)


def _is_change_history_structural_cell(text: str) -> bool:
    compact = re.sub(r"[\s:：/|_-]+", "", normalize_text(text)).lower()
    return (
        _is_structural_table_cell(text)
        or compact in {"版本revision", "revrevision", "revision"}
        or compact in {"生效日期effectivedate", "effectivedate"}
    )


def _split_table_cells(text: str) -> list[str]:
    if "|" not in text and "\t" not in text:
        return []
    return [
        _clean_alignment_text(cell)
        for cell in TABLE_DELIMITER_RE.split(text.strip().strip("|"))
        if _clean_alignment_text(cell)
    ]


def _split_compact_bilingual_piece(piece: str) -> tuple[str, str]:
    """Split a mixed one-line label such as "0.3 范围 Scope" or "Purpose / 目的"."""
    piece = _clean_alignment_text(piece)
    chinese_count, english_count = _language_counts(piece)
    if not chinese_count or not english_count:
        return "", ""

    bilingual_sequence = re.match(
        r"^(?P<chinese>.*[\u3400-\u9fff][^A-Za-z]{0,8})\s+"
        r"(?P<english>[A-Za-z][A-Za-z0-9'’/(),&;:.\-\s]+)$",
        piece,
    )
    if bilingual_sequence:
        english = bilingual_sequence.group("english")
        if len(re.findall(r"[A-Za-z]+", english)) >= 3:
            return _clean_chinese_side(bilingual_sequence.group("chinese")), _clean_english_side(
                english
            )

    spans = [
        match
        for match in re.finditer(
            r"[A-Za-z][A-Za-z'’/-]*(?:\s+[A-Za-z][A-Za-z'’/-]*)+",
            piece,
        )
        if len(ENGLISH_RE.findall(match.group(0))) >= 8
    ]
    if spans:
        english = " ".join(match.group(0).strip() for match in spans)
        chinese = piece
        for match in reversed(spans):
            chinese = chinese[: match.start()] + " " + chinese[match.end() :]
        return _clean_chinese_side(chinese), _clean_english_side(english)

    heading_translation = heading_reference_translation(piece)
    if heading_translation:
        chinese = "".join(
            match.group(0) for match in re.finditer(r"[\u3400-\u9fff、/]+", piece)
        )
        return _clean_chinese_side(chinese), _clean_english_side(heading_translation)

    compact_transition = re.match(
        r"^\s*(?:\d+(?:\.\d+)*\s*)?(?P<chinese>[\u3400-\u9fff、/（）()]+)"
        r"(?P<english>[A-Za-z][A-Za-z0-9'’/(),&;:.\-\s]*)\s*$",
        piece,
    )
    if compact_transition:
        return _clean_chinese_side(compact_transition.group("chinese")), _clean_english_side(
            compact_transition.group("english")
        )

    # The pasted processor also split on wide spacing, slash, or dash for compact
    # bilingual labels. Keep this as a fallback only, so prose with punctuation is not
    # over-split.
    parts = [
        _clean_alignment_text(part)
        for part in re.split(r"\s{2,}|/\s*|-\s*", piece)
        if _clean_alignment_text(part)
    ]
    chinese_parts: list[str] = []
    english_parts: list[str] = []
    for part in parts:
        ch_count, en_count = _language_counts(part)
        if ch_count and not en_count:
            chinese_parts.append(part)
        elif en_count and not ch_count:
            english_parts.append(part)
    if chinese_parts and english_parts:
        return _clean_chinese_side(" ".join(chinese_parts)), _clean_english_side(
            " ".join(english_parts)
        )
    return "", ""


def _translation_for_unit(
    machine_translation: str,
    unit_count: int,
    unit_index: int,
) -> str:
    machine_translation = _clean_alignment_text(machine_translation)
    if not machine_translation:
        return ""
    parts = [
        _clean_english_side(part)
        for part in re.split(r"\s*\|\s*|\n+", machine_translation)
        if _clean_english_side(part)
    ]
    if len(parts) == unit_count:
        return parts[unit_index]
    return machine_translation if unit_count == 1 else ""


def _unit_from_mixed_piece(piece: str, unit_index: int) -> AlignmentUnit | None:
    chinese, english = _split_compact_bilingual_piece(piece)
    if not chinese or not english:
        return None
    return AlignmentUnit(chinese, english, unit_index)


def _alignment_units_from_pieces(
    pieces: list[str],
    *,
    content_class: str,
) -> list[AlignmentUnit]:
    units: list[AlignmentUnit] = []
    pending_chinese: str | None = None
    pending_english: str | None = None
    for piece in pieces:
        piece = _clean_alignment_text(piece)
        if not piece:
            continue
        if content_class == "change_history" and _is_change_history_structural_cell(piece):
            continue
        if content_class != "change_history" and _is_structural_table_cell(piece):
            continue

        mixed_unit = _unit_from_mixed_piece(piece, len(units))
        if mixed_unit:
            units.append(mixed_unit)
            pending_chinese = None
            pending_english = None
            continue

        chinese_count, english_count = _language_counts(piece)
        if chinese_count and not english_count:
            if pending_english:
                units.append(
                    AlignmentUnit(
                        _clean_chinese_side(piece),
                        _clean_english_side(pending_english),
                        len(units),
                    )
                )
                pending_english = None
            else:
                pending_chinese = piece
            continue
        if english_count and not chinese_count:
            if pending_chinese:
                units.append(
                    AlignmentUnit(
                        _clean_chinese_side(pending_chinese),
                        _clean_english_side(piece),
                        len(units),
                    )
                )
                pending_chinese = None
            else:
                pending_english = piece
    return units


def alignment_units_from_text(
    text: str,
    *,
    content_class: str = "bilingual_prose",
    machine_translation: str = "",
) -> list[AlignmentUnit]:
    text = _clean_alignment_text(text)
    if not text:
        return []
    if "|" in text or "\t" in text:
        pieces = _split_table_cells(text)
    elif "\n" in text:
        pieces = [piece for piece in re.split(r"\n+", text) if _clean_alignment_text(piece)]
    else:
        unit = _unit_from_mixed_piece(text, 0)
        pieces = [] if unit else [text]
        units = [unit] if unit else _alignment_units_from_pieces(pieces, content_class=content_class)
        return [
            AlignmentUnit(
                item.chinese,
                item.english,
                item.unit_index,
                _translation_for_unit(machine_translation, len(units), item.unit_index),
            )
            for item in units
        ]

    units = _alignment_units_from_pieces(pieces, content_class=content_class)
    return [
        AlignmentUnit(
            item.chinese,
            item.english,
            item.unit_index,
            _translation_for_unit(machine_translation, len(units), item.unit_index),
        )
        for item in units
    ]


def _split_delimited_table_pair(text: str) -> tuple[str, str]:
    """Extract likely Chinese/English cells from delimiter-style table rows.

    The pasted logic treated pipe/tab-delimited rows as table alignment units. Here we
    adapt that idea to existing PDF table-row blocks and ignore clause/procedure code
    cells so regulatory matrix rows do not become noisy prose pairs.
    """
    cells = _split_table_cells(text)
    if len(cells) < 2:
        return "", ""

    best: tuple[int, int, int] | None = None
    for ch_index, chinese_cell in enumerate(cells):
        ch_count, ch_en_count = _language_counts(chinese_cell)
        if not ch_count or _is_code_like_cell(chinese_cell):
            continue
        for en_index, english_cell in enumerate(cells):
            en_ch_count, en_count = _language_counts(english_cell)
            if en_index == ch_index or en_ch_count or not en_count or _is_code_like_cell(english_cell):
                continue
            distance = abs(ch_index - en_index)
            score = 2 if distance == 1 else 1
            if best is None or score > best[0] or (
                score == best[0] and distance < abs(best[1] - best[2])
            ):
                best = (score, ch_index, en_index)
    if best:
        _, ch_index, en_index = best
        return _clean_chinese_side(cells[ch_index]), _clean_english_side(cells[en_index])

    # Some cells themselves contain compact bilingual text.
    for cell in cells:
        chinese, english = _split_compact_bilingual_piece(cell)
        if chinese and english:
            return chinese, english
    return "", ""


def split_mixed_text(text: str) -> tuple[str, str]:
    """Split a bilingual heading/table row while preserving clause codes and labels."""
    units = alignment_units_from_text(text)
    if units:
        return units[0].chinese, units[0].english

    text = _clean_alignment_text(text)
    table_chinese, table_english = _split_delimited_table_pair(text)
    if table_chinese and table_english:
        return table_chinese, table_english

    pieces = [piece.strip() for piece in re.split(r"\s*\|\s*|\n+", text) if piece.strip()]
    chinese_parts: list[str] = []
    english_parts: list[str] = []
    for piece in pieces:
        piece = _clean_alignment_text(piece)
        chinese_count, english_count = _language_counts(piece)
        if chinese_count and not english_count:
            chinese_parts.append(_clean_chinese_side(piece))
            continue
        if english_count and not chinese_count:
            english_parts.append(_clean_english_side(piece))
            continue
        if not chinese_count or not english_count:
            continue

        # Collect every multi-word English span. This handles change-history rows whose
        # Chinese and English bullets alternate several times inside one table cell.
        chinese, english = _split_compact_bilingual_piece(piece)
        if chinese and english:
            chinese_parts.append(chinese)
            english_parts.append(english)

    return _clean_chinese_side(" ".join(chinese_parts)), _clean_english_side(
        " ".join(english_parts)
    )


def _eligible_for_translation_check(block: ExtractedBlock) -> bool:
    if (
        block.ignored
        or block.content_class == "reference_table"
        or block.content_class in NO_NORMAL_PAIRING_CLASSES
    ):
        return False
    if block.block_type in {
        BlockType.header,
        BlockType.footer,
        BlockType.reference_table,
    }:
        return False
    text = block.text.strip()
    if len(text) < 4 or re.fullmatch(r"[\d\s./():-]+", text):
        return False
    return True


def _looks_like_reference_mapping(chinese: str, english: str) -> bool:
    references = extract_references(english)
    if len(references) >= 2:
        return True
    if references and len(chinese) < 120 and not re.search(r"[。；;]", chinese):
        return True
    return False


def _looks_like_short_label_or_name(chinese: str, english: str) -> bool:
    chinese_chars = len(CHINESE_RE.findall(chinese))
    english_words = len(re.findall(r"[A-Za-z]+", english))
    return (
        chinese_chars <= 18
        and english_words <= 10
        and not re.search(r"[。；;！？!?]", chinese)
    )


def _same_revision(chinese: ExtractedBlock, english: ExtractedBlock) -> bool:
    if chinese.content_class != "change_history" and english.content_class != "change_history":
        return True
    return bool(
        chinese.revision_id
        and english.revision_id
        and chinese.revision_id == english.revision_id
    )


def _candidate_allowed(chinese: ExtractedBlock, english: ExtractedBlock) -> bool:
    if chinese.ignored or english.ignored:
        return False
    if (
        chinese.content_class in NO_NORMAL_PAIRING_CLASSES
        or english.content_class in NO_NORMAL_PAIRING_CLASSES
    ):
        return False
    if abs(chinese.page - english.page) > 2:
        return False
    if not _same_revision(chinese, english):
        return False
    if chinese.content_class == "reference_table" or english.content_class == "reference_table":
        return False
    if chinese.block_type == BlockType.heading and english.block_type not in {
        BlockType.heading,
        BlockType.paragraph,
    }:
        return False
    if chinese.table_id and english.table_id and chinese.table_id != english.table_id:
        return False
    return True


def _structural_alignment_score(chinese: ExtractedBlock, english: ExtractedBlock) -> float:
    """Score line/table adjacency inspired by the pasted alignment-unit processor."""
    if not _candidate_allowed(chinese, english):
        return 0.0
    score = 0.0
    if chinese.page == english.page:
        score += 0.25
    elif abs(chinese.page - english.page) == 1:
        score += 0.08
    if chinese.section and chinese.section == english.section:
        score += 0.20
    if chinese.table_id and chinese.table_id == english.table_id:
        score += 0.25
        if chinese.row_index is not None and chinese.row_index == english.row_index:
            score += 0.20
        if (
            chinese.col_index is not None
            and english.col_index is not None
            and abs(chinese.col_index - english.col_index) == 1
        ):
            score += 0.10
    order_gap = abs(chinese.reading_order - english.reading_order)
    if chinese.page == english.page and order_gap <= 2:
        score += 0.25
    elif chinese.page == english.page and order_gap <= 8:
        score += 0.15
    if chinese.bbox and english.bbox and chinese.page == english.page:
        chinese_mid = (chinese.bbox[1] + chinese.bbox[3]) / 2
        english_mid = (english.bbox[1] + english.bbox[3]) / 2
        page_height = max(chinese.bbox[3], english.bbox[3], 1)
        if abs(chinese_mid - english_mid) / page_height <= 0.035:
            score += 0.15
    return min(score, 1.0)


def _structural_candidate_score(
    chinese: ExtractedBlock,
    english: ExtractedBlock,
    *,
    confirmed_threshold: float,
    uncertain_threshold: float,
) -> tuple[float, float] | None:
    structural = _structural_alignment_score(chinese, english)
    if structural < 0.70:
        return None
    # Adjacent-line/table evidence is useful for surfacing candidates, but it is not
    # enough to confirm meaning. Cap below the confirmed threshold so AI/manual review
    # still decides whether this line-order candidate is a real translation pair.
    score = max(
        uncertain_threshold,
        min(confirmed_threshold - 0.01, 0.60 + 0.18 * structural),
    )
    return score, structural


def _join_blocks_text(blocks: list[ExtractedBlock]) -> str:
    return _clean_alignment_text(" ".join(block.text for block in blocks))


def _join_translations(blocks: list[ExtractedBlock], translations: dict[str, str]) -> str:
    return _clean_alignment_text(
        " ".join(translations.get(block.block_id, "") for block in blocks)
    )


def _merge_bbox(blocks: list[ExtractedBlock]) -> tuple[float, float, float, float] | None:
    boxes = [block.bbox for block in blocks if block.bbox]
    if not boxes:
        return None
    return (
        min(box[0] for box in boxes),
        min(box[1] for box in boxes),
        max(box[2] for box in boxes),
        max(box[3] for box in boxes),
    )


def _synthetic_group_block(blocks: list[ExtractedBlock], language: Language) -> ExtractedBlock:
    first = blocks[0]
    return first.model_copy(
        update={
            "block_id": stable_id("grp", *(block.block_id for block in blocks)),
            "language": language,
            "text": _join_blocks_text(blocks),
            "bbox": _merge_bbox(blocks),
            "reading_order": first.reading_order,
        }
    )


def _compatible_group_member(previous: ExtractedBlock, current: ExtractedBlock) -> bool:
    if current.language != previous.language:
        return False
    if current.page != previous.page:
        return False
    if (current.section or "") != (previous.section or ""):
        return False
    if current.content_class != previous.content_class:
        return False
    if current.revision_id != previous.revision_id:
        return False
    if current.block_type in {BlockType.heading, BlockType.header, BlockType.footer}:
        return False
    if previous.block_type in {BlockType.heading, BlockType.header, BlockType.footer}:
        return False
    if current.block_type != previous.block_type:
        return False
    if current.table_id and previous.table_id and current.table_id != previous.table_id:
        return False
    if current.reading_order - previous.reading_order > 4:
        return False
    return True


def _language_runs(blocks: list[ExtractedBlock]) -> list[list[ExtractedBlock]]:
    runs: list[list[ExtractedBlock]] = []
    for block in blocks:
        if block.language not in {Language.zh, Language.en}:
            continue
        if not _eligible_for_translation_check(block):
            continue
        if not runs or not _compatible_group_member(runs[-1][-1], block):
            runs.append([block])
        else:
            runs[-1].append(block)
    return runs


def _consecutive_run_pair_allowed(
    left: list[ExtractedBlock], right: list[ExtractedBlock]
) -> bool:
    if left[0].language == right[0].language:
        return False
    if len(left) == 1 and len(right) == 1:
        return False
    if left[-1].page != right[0].page:
        return False
    if (left[-1].section or "") != (right[0].section or ""):
        return False
    if right[0].reading_order - left[-1].reading_order > 6:
        return False
    if left[-1].content_class != right[0].content_class:
        return False
    if left[-1].revision_id != right[0].revision_id:
        return False
    left_chars = len(CHINESE_RE.findall(_join_blocks_text(left)))
    right_words = len(re.findall(r"[A-Za-z]+", _join_blocks_text(right)))
    if left[0].language == Language.zh:
        return left_chars >= 20 and right_words >= 20
    return right_words >= 20 and left_chars >= 20


def _pair_from_consecutive_runs(
    chinese_blocks: list[ExtractedBlock],
    english_blocks: list[ExtractedBlock],
    translations: dict[str, str],
    *,
    confirmed_threshold: float,
    uncertain_threshold: float,
) -> BilingualPair | None:
    machine_translation = _join_translations(chinese_blocks, translations)
    if not machine_translation:
        return None
    chinese_group = _synthetic_group_block(chinese_blocks, Language.zh)
    english_group = _synthetic_group_block(english_blocks, Language.en)
    score, semantic, components = weighted_pair_score(
        chinese_group, english_group, machine_translation
    )
    adjacency_bonus = (
        0.15 if english_blocks[0].reading_order > chinese_blocks[-1].reading_order else 0.08
    )
    score = min(1.0, score + adjacency_bonus)
    if score < uncertain_threshold:
        return None
    status = PairStatus.confirmed if score >= confirmed_threshold else PairStatus.uncertain
    source_ids = [block.block_id for block in chinese_blocks + english_blocks]
    reason = (
        "Consecutive same-section paragraph/table-row runs were paired as one logical "
        "bilingual paragraph; "
        f"translation semantic={components['semantic']:.2f}, "
        f"entities={components['entities']:.2f}, page={components['page']:.2f}, "
        f"section={components['section']:.2f}, length={components['length']:.2f}, "
        f"layout={components['layout']:.2f}, adjacency_bonus={adjacency_bonus:.2f}"
    )
    return BilingualPair(
        pair_id=stable_id("pair_group", *source_ids),
        page=min(chinese_blocks[0].page, english_blocks[0].page),
        section=chinese_blocks[0].section or english_blocks[0].section,
        block_type=chinese_blocks[0].block_type,
        chinese_block_id=chinese_blocks[0].block_id,
        english_block_id=english_blocks[0].block_id,
        chinese_text=_clean_chinese_side(chinese_group.text),
        machine_translated_english=_clean_english_side(machine_translation),
        english_text=_clean_english_side(english_group.text),
        semantic_similarity=semantic,
        final_pair_score=score,
        pair_confidence=score,
        pair_status=status,
        pairing_method="consecutive_paragraph_group",
        should_check_translation=(
            status == PairStatus.confirmed
            and not _looks_like_reference_mapping(chinese_group.text, english_group.text)
        ),
        pairing_reason=reason,
        needs_manual_review=status != PairStatus.confirmed,
        source_block_ids=source_ids,
        revision_id=chinese_blocks[0].revision_id,
        effective_date=chinese_blocks[0].effective_date,
    )


def _pair_from_alignment_unit(
    block: ExtractedBlock,
    unit: AlignmentUnit,
    *,
    confirmed_threshold: float,
) -> BilingualPair | None:
    chinese, english = unit.chinese, unit.english
    for date_value in filter(None, (block.effective_date,)):
        chinese = chinese.replace(date_value, " ")
        english = english.replace(date_value, " ")
    chinese = _clean_chinese_side(chinese)
    english = _clean_english_side(english)
    if not chinese or not english:
        return None
    heading_translation = heading_reference_translation(chinese)
    if block.content_class in {"reference_table", "regulatory_references"}:
        method = "table_row"
        score = 1.0
        semantic = 1.0
        should_check = False
        reason = f"Bilingual content is contained in one {block.content_class} row."
    elif block.block_type == BlockType.heading and heading_translation:
        method = "heading_glossary"
        semantic = semantic_similarity(heading_translation, english)
        score = max(0.90, semantic)
        should_check = False
        reason = "Known bilingual heading matched by the heading glossary."
    else:
        method = "table_row" if block.table_id else "translated_chinese_similarity"
        reference = unit.machine_translation or heading_translation or ""
        semantic = semantic_similarity(reference, english)
        # Same layout block is strong structural evidence, but a prose pair is not sent
        # downstream unless it also has a usable translation comparison.
        score = max(0.84, semantic) if reference else 0.74
        should_check = (
            bool(reference)
            and _eligible_for_translation_check(block)
            and not _looks_like_reference_mapping(chinese, english)
            and not _looks_like_short_label_or_name(chinese, english)
        )
        reason = "Chinese and English were extracted from the same logical layout block."
    status = (
        PairStatus.confirmed if score >= confirmed_threshold else PairStatus.uncertain
    )
    return BilingualPair(
        pair_id=f"{stable_id('pair', block.block_id)}_{unit.unit_index:03d}",
        page=block.page,
        section=block.section,
        block_type=block.block_type,
        chinese_block_id=block.block_id,
        english_block_id=block.block_id,
        chinese_text=chinese,
        machine_translated_english=_clean_english_side(
            unit.machine_translation or heading_translation or ""
        ),
        english_text=english,
        semantic_similarity=semantic,
        final_pair_score=score,
        pair_confidence=score,
        pair_status=status,
        pairing_method=method,
        should_check_translation=should_check and status == PairStatus.confirmed,
        pairing_reason=reason,
        needs_manual_review=status != PairStatus.confirmed,
        source_block_ids=[block.block_id],
        revision_id=block.revision_id,
        effective_date=block.effective_date,
    )


def _pairs_from_same_block(
    block: ExtractedBlock,
    machine_translation: str,
    *,
    confirmed_threshold: float,
) -> list[BilingualPair]:
    if block.ignored:
        return []
    if block.content_class in NO_NORMAL_PAIRING_CLASSES:
        return []
    units = alignment_units_from_text(
        block.text,
        content_class=block.content_class,
        machine_translation=machine_translation,
    )
    pairs: list[BilingualPair] = []
    for unit in units:
        pair = _pair_from_alignment_unit(
            block,
            unit,
            confirmed_threshold=confirmed_threshold,
        )
        if pair:
            pairs.append(pair)
    return pairs


def pair_blocks(
    blocks: list[ExtractedBlock],
    translations: dict[str, str],
    *,
    confirmed_threshold: float = 0.82,
    uncertain_threshold: float = 0.68,
) -> list[BilingualPair]:
    """Pair primarily by translated-Chinese-to-original-English similarity."""
    active = [block for block in blocks if block.text]
    pairs: list[BilingualPair] = []
    consumed: set[str] = set()

    # Same-row bilingual headings and table rows are reconstructed before cross-block search.
    for block in active:
        if block.content_class in NO_NORMAL_PAIRING_CLASSES:
            continue
        if not CHINESE_RE.search(block.text) or not re.search(r"[A-Za-z]", block.text):
            continue
        same_block_pairs = _pairs_from_same_block(
            block,
            translations.get(block.block_id, ""),
            confirmed_threshold=confirmed_threshold,
        )
        if same_block_pairs:
            pairs.extend(same_block_pairs)
            consumed.add(block.block_id)

    # Consecutive Chinese rows followed by consecutive English rows often represent one
    # visual paragraph split by PDF table extraction. Pair these runs as a whole before
    # one-to-one matching, otherwise each short row looks like a missing translation.
    run_candidates: list[tuple[float, BilingualPair]] = []
    unconsumed_active = [block for block in active if block.block_id not in consumed]
    runs = _language_runs(unconsumed_active)
    for left, right in zip(runs, runs[1:], strict=False):
        if not _consecutive_run_pair_allowed(left, right):
            continue
        chinese_run, english_run = (
            (left, right) if left[0].language == Language.zh else (right, left)
        )
        pair = _pair_from_consecutive_runs(
            chinese_run,
            english_run,
            translations,
            confirmed_threshold=confirmed_threshold,
            uncertain_threshold=uncertain_threshold,
        )
        if pair:
            run_candidates.append((pair.final_pair_score, pair))
    run_candidates.sort(key=lambda item: item[0], reverse=True)
    for _, pair in run_candidates:
        if any(block_id in consumed for block_id in pair.source_block_ids):
            continue
        pairs.append(pair)
        consumed.update(pair.source_block_ids)

    chinese_blocks = [
        block
        for block in active
        if block.block_id not in consumed and block.language == Language.zh
    ]
    english_blocks = [
        block
        for block in active
        if block.block_id not in consumed and block.language == Language.en
    ]

    candidates: list[
        tuple[float, float, str, ExtractedBlock, ExtractedBlock, dict[str, float]]
    ] = []
    for chinese in chinese_blocks:
        machine_translation = translations.get(chinese.block_id, "")
        heading_translation = heading_reference_translation(chinese.text)
        if not machine_translation and heading_translation:
            machine_translation = heading_translation
        for english in english_blocks:
            if not _candidate_allowed(chinese, english):
                continue
            method = "translated_chinese_similarity"
            if machine_translation:
                english_for_score = english.model_copy(
                    update={"text": _clean_english_side(english.text)}
                )
                score, semantic, components = weighted_pair_score(
                    chinese, english_for_score, machine_translation
                )
            else:
                score = 0.0
                semantic = 0.0
                components = {
                    "semantic": 0.0,
                    "entities": 0.0,
                    "page": 0.0,
                    "section": 0.0,
                    "length": 0.0,
                    "layout": 0.0,
                }
            structural_candidate = _structural_candidate_score(
                chinese,
                english,
                confirmed_threshold=confirmed_threshold,
                uncertain_threshold=uncertain_threshold,
            )
            if structural_candidate:
                structural_score, structural = structural_candidate
                components["structural"] = structural
                if score < uncertain_threshold:
                    score = structural_score
                    method = "layout_adjacency_candidate"
            if machine_translation and chinese.block_type == BlockType.heading and heading_translation:
                # Headings are short, so lexical semantic scores are noisier.
                heading_similarity = semantic_similarity(
                    heading_translation, _clean_english_side(english.text)
                )
                score = max(score, 0.88 * heading_similarity + 0.12)
                semantic = max(semantic, heading_similarity)
                components["semantic"] = semantic
                method = "heading_glossary"
            if score >= uncertain_threshold:
                candidates.append((score, semantic, method, chinese, english, components))

    candidates.sort(key=lambda item: item[0], reverse=True)
    used_chinese: set[str] = set()
    used_english: set[str] = set()
    for score, semantic, method, chinese, english, components in candidates:
        if chinese.block_id in used_chinese or english.block_id in used_english:
            continue
        used_chinese.add(chinese.block_id)
        used_english.add(english.block_id)
        consumed.update((chinese.block_id, english.block_id))
        status = (
            PairStatus.confirmed
            if score >= confirmed_threshold
            else PairStatus.uncertain
        )
        is_heading = chinese.block_type == BlockType.heading
        reason = (
            f"translation semantic={components['semantic']:.2f}, "
            f"entities={components['entities']:.2f}, page={components['page']:.2f}, "
            f"section={components['section']:.2f}, length={components['length']:.2f}, "
            f"layout={components['layout']:.2f}"
        )
        if "structural" in components:
            reason = f"{reason}, structural_adjacency={components['structural']:.2f}"
        should_check = (
            status == PairStatus.confirmed
            and not is_heading
            and _eligible_for_translation_check(chinese)
            and _eligible_for_translation_check(english)
            and not _looks_like_short_label_or_name(chinese.text, english.text)
            and not _looks_like_reference_mapping(chinese.text, english.text)
        )
        pairs.append(
            BilingualPair(
                pair_id=stable_id("pair", chinese.block_id, english.block_id),
                page=min(chinese.page, english.page),
                section=chinese.section or english.section,
                block_type=chinese.block_type,
                chinese_block_id=chinese.block_id,
                english_block_id=english.block_id,
                chinese_text=_clean_chinese_side(chinese.text),
                machine_translated_english=_clean_alignment_text(
                    translations.get(chinese.block_id, "")
                    or heading_reference_translation(chinese.text)
                    or ""
                ),
                english_text=_clean_english_side(english.text),
                semantic_similarity=semantic,
                final_pair_score=score,
                pair_confidence=score,
                pair_status=status,
                pairing_method=method,
                should_check_translation=should_check,
                pairing_reason=reason,
                needs_manual_review=status != PairStatus.confirmed,
                source_block_ids=[chinese.block_id, english.block_id],
                revision_id=chinese.revision_id,
                effective_date=chinese.effective_date,
            )
        )

    for block in active:
        if block.block_id in consumed:
            continue
        if block.language == Language.zh:
            status = PairStatus.missing_english
            chinese_text, english_text, unpaired_text = _clean_chinese_side(block.text), "", ""
        elif block.language == Language.en:
            if block.content_class in EN_ONLY_ALLOWED_CLASSES:
                status = PairStatus.unpaired
                chinese_text, english_text, unpaired_text = (
                    "",
                    "",
                    _clean_english_side(block.text),
                )
            else:
                status = PairStatus.missing_chinese
                chinese_text, english_text, unpaired_text = (
                    "",
                    _clean_english_side(block.text),
                    "",
                )
        else:
            status = PairStatus.unpaired
            chinese_text, english_text, unpaired_text = "", "", block.text
        no_translation_required = (
            block.ignored
            or block.content_class in EN_ONLY_ALLOWED_CLASSES
            or block.content_class in NO_NORMAL_PAIRING_CLASSES
        )
        reason = (
            f"Block classified as {block.content_class}; normal bilingual pairing is not required."
            if no_translation_required
            else "No candidate met the strict translated-Chinese similarity threshold."
        )
        pairs.append(
            BilingualPair(
                pair_id=stable_id("pair", block.block_id, status),
                page=block.page,
                section=block.section,
                block_type=block.block_type,
                chinese_block_id=block.block_id if chinese_text else None,
                english_block_id=block.block_id if english_text else None,
                chinese_text=chinese_text,
                machine_translated_english=_clean_english_side(
                    translations.get(block.block_id, "")
                ),
                english_text=english_text,
                unpaired_text=unpaired_text,
                semantic_similarity=0.0,
                final_pair_score=0.0,
                pair_confidence=0.0,
                pair_status=status,
                pairing_method="translated_chinese_similarity",
                should_check_translation=False,
                pairing_reason=reason,
                needs_manual_review=not no_translation_required,
                source_block_ids=[block.block_id],
                revision_id=block.revision_id,
                effective_date=block.effective_date,
            )
        )
    order_by_block = {block.block_id: index for index, block in enumerate(active)}

    def pair_sort_key(pair: BilingualPair) -> tuple[int, int, str]:
        source_orders = [
            order_by_block[block_id]
            for block_id in pair.source_block_ids
            if block_id in order_by_block
        ]
        return (
            pair.page,
            min(source_orders) if source_orders else 10**9,
            pair.pair_id,
        )

    return sorted(pairs, key=pair_sort_key)


def validate_pairs_with_ai(
    pairs: list[BilingualPair],
    blocks: list[ExtractedBlock],
    client: AIClient,
    *,
    batch_size: int = 8,
    prompt_path: str = "prompts/pair_bilingual_blocks.md",
) -> list[BilingualPair]:
    """Validate uncertain pairs only; AI cannot rescue unrelated low-score candidates."""
    prompt = read_prompt(prompt_path)
    pair_map = {pair.pair_id: pair.model_copy(deep=True) for pair in pairs}
    uncertain = [pair for pair in pairs if pair.pair_status == PairStatus.uncertain]

    for batch in chunks(uncertain, batch_size):
        payload = {
            "candidate_pairs": [
                {
                    **pair.model_dump(mode="json"),
                    "nearby_context": [
                        block.text
                        for block in blocks
                        if not block.ignored
                        and abs(block.page - pair.page) <= 1
                        and block.block_id not in pair.source_block_ids
                    ][:8],
                }
                for pair in batch
            ]
        }
        response = client.request_json(prompt, payload, PairValidationResponse)
        for item in response.items:
            pair = pair_map.get(item.pair_id)
            if not pair:
                continue
            pair.ai_validated = True
            pair.pairing_reason = item.reason
            pair.pair_confidence = item.confidence
            pair.pairing_method = "ai_validated"
            pair.should_check_translation = (
                item.is_correct_pair
                and item.confidence >= 0.80
                and item.should_check_translation
                and item.pair_type not in {"heading_pair", "table_reference"}
            )
            if item.is_correct_pair and item.confidence >= 0.80:
                pair.pair_status = PairStatus.confirmed
                pair.needs_manual_review = False
            else:
                pair.pair_status = PairStatus.uncertain
                pair.needs_manual_review = True
    order_by_block = {
        block.block_id: index
        for index, block in enumerate(block for block in blocks if not block.ignored)
    }

    def pair_sort_key(pair: BilingualPair) -> tuple[int, int, str]:
        source_orders = [
            order_by_block[block_id]
            for block_id in pair.source_block_ids
            if block_id in order_by_block
        ]
        return (
            pair.page,
            min(source_orders) if source_orders else 10**9,
            pair.pair_id,
        )

    return sorted(pair_map.values(), key=pair_sort_key)
