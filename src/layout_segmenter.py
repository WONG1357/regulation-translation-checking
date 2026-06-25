from __future__ import annotations

import re
from collections import Counter, defaultdict

from rapidfuzz.fuzz import ratio

from src.schemas import BlockType, ExtractedBlock, SourceType
from src.utils import extract_section, language_of, normalize_text, stable_id

HEADER_MARKERS = (
    "文件编号 doc no",
    "文件版本 doc rev",
    "页次 page no",
)
REVISION_RE = re.compile(r"^\s*([A-Z])\s*\|")
DATE_RE = re.compile(
    r"\b(?:\d{1,2}[-/](?:[A-Za-z]{3}|\d{1,2})[-/]\d{4}|\d{4}[-/]\d{1,2}[-/]\d{1,2})\b"
)
REFERENCE_CODE_RE = re.compile(
    r"\b(?:QSP\d{4}|WI\d{3,5}|21\s*CFR|820\.\d+|ISO\s*\d+|"
    r"\d+(?:\.\d+){1,3}(?:\.[a-z]\)?)?)\b",
    re.I,
)
STANDALONE_LOCATOR_RE = re.compile(r"^\s*\d+(?:\.\d+)*\s*$")
NUMERIC_SECTION_RE = re.compile(r"^\d+(?:\.\d+)*$")


def _is_repeated_furniture(block: ExtractedBlock, page_count: int) -> bool:
    lower = block.text.lower()
    compact = re.sub(r"\s+", "", lower)
    real_section = bool(extract_section(block.text)) and bool(
        re.search(r"[A-Za-z\u3400-\u9fff]", block.text)
    )
    marker = any(token in lower for token in HEADER_MARKERS)
    marker = marker or any(
        token in compact
        for token in (
            "文件编号docno",
            "文件版本docrev",
            "页次pageno",
            "文件名称documentname",
        )
    )
    if real_section and not marker:
        return False
    visual = block.block_type in {BlockType.header, BlockType.footer}
    top_or_bottom = bool(
        block.bbox
        and (block.bbox[3] <= 135 or block.bbox[1] >= 790)
        and page_count > 2
    )
    return marker or top_or_bottom or (visual and page_count > 2)


def _split_mixed_lines(block: ExtractedBlock) -> list[ExtractedBlock]:
    lines = [normalize_text(line) for line in re.split(r"[\n\r]+", block.text) if line.strip()]
    if len(lines) <= 1:
        if block.source != SourceType.docx:
            block.reading_order *= 100
        return [block]
    grouped: list[tuple[str, object]] = []
    for line in lines:
        line_language = language_of(line)
        starts_new_unit = bool(extract_section(line)) or line.startswith(("-", "•", "·"))
        if (
            grouped
            and grouped[-1][1] == line_language
            and line_language in {"zh", "en"}
            and not starts_new_unit
        ):
            grouped[-1] = (f"{grouped[-1][0]} {line}", line_language)
        else:
            grouped.append((line, line_language))
    result: list[ExtractedBlock] = []
    for index, (line, line_language) in enumerate(grouped):
        result.append(
            block.model_copy(
                update={
                    "block_id": stable_id("seg", block.block_id, index, line),
                    "text": line,
                    "language": line_language,
                    "reading_order": block.reading_order * 100 + index,
                }
            )
        )
    return result


def _deduplicate(blocks: list[ExtractedBlock]) -> list[ExtractedBlock]:
    by_page: dict[int, list[ExtractedBlock]] = defaultdict(list)
    for block in blocks:
        by_page[block.page].append(block)
    retained: list[ExtractedBlock] = []
    for page_blocks in by_page.values():
        page_blocks.sort(key=lambda b: (b.reading_order, b.bbox[1] if b.bbox else 0))
        for block in page_blocks:
            duplicate = False
            for prior in retained[-30:]:
                if prior.page != block.page:
                    continue
                if ratio(prior.text, block.text) >= 96:
                    if block.block_type == BlockType.table_row:
                        prior.ignored = True
                    else:
                        duplicate = True
                    break
            if not duplicate:
                retained.append(block)
    return retained


def _merge_adjacent_paragraph_fragments(
    blocks: list[ExtractedBlock],
) -> list[ExtractedBlock]:
    merged: list[ExtractedBlock] = []
    for block in blocks:
        if not merged:
            merged.append(block)
            continue
        previous = merged[-1]
        vertical_gap = (
            block.bbox[1] - previous.bbox[3]
            if block.bbox and previous.bbox
            else 0
        )
        compatible = (
            not block.ignored
            and not previous.ignored
            and block.source != SourceType.docx
            and previous.source != SourceType.docx
            and block.page == previous.page
            and block.section == previous.section
            and block.block_type == previous.block_type == BlockType.paragraph
            and block.language == previous.language
            and block.language in {"zh", "en"}
            and not block.text.startswith(("-", "•", "·"))
            and vertical_gap <= 18
        )
        if compatible:
            text = normalize_text(f"{previous.text} {block.text}")
            previous.text = text
            previous.block_id = stable_id(
                "merged", previous.block_id, block.block_id, text
            )
            if previous.bbox and block.bbox:
                previous.bbox = (
                    min(previous.bbox[0], block.bbox[0]),
                    min(previous.bbox[1], block.bbox[1]),
                    max(previous.bbox[2], block.bbox[2]),
                    max(previous.bbox[3], block.bbox[3]),
                )
            previous.confidence = min(previous.confidence, block.confidence)
        else:
            merged.append(block)
    return merged


def _is_reference_table_row(text: str) -> bool:
    if "|" not in text:
        return False
    cells = [cell.strip() for cell in text.split("|") if cell.strip()]
    if len(cells) < 3:
        return False
    code_cells = sum(
        bool(REFERENCE_CODE_RE.search(cell)) and len(cell) < 100 for cell in cells
    )
    prose_chars = len(re.findall(r"[A-Za-z\u3400-\u9fff]", text))
    code_count = len(REFERENCE_CODE_RE.findall(text))
    return code_cells >= 2 or (code_count >= 3 and prose_chars < 280)


def _is_standalone_locator(text: str) -> bool:
    """Return True for TOC/page-number/clause-number fragments with no prose."""
    return bool(STANDALONE_LOCATOR_RE.fullmatch(text))


def _section_parts(section: str | None) -> tuple[int, ...] | None:
    if not section or not NUMERIC_SECTION_RE.fullmatch(section):
        return None
    return tuple(int(part) for part in section.split("."))


def _is_plausible_next_section(previous: str | None, candidate: str | None) -> bool:
    """Gate OCR/PDF section guesses using a monotonic section tree.

    Example: after 2.1, the next new section can be 2.1.1, 2.2, or 3/3.0.
    Random OCR/table fragments such as 8.2 or 5.4 are rejected until the document
    actually reaches the intervening section path.
    """
    if not candidate:
        return False
    if previous is None:
        return True
    previous_parts = _section_parts(previous)
    candidate_parts = _section_parts(candidate)
    if not previous_parts or not candidate_parts:
        return True
    if candidate_parts == previous_parts:
        return True
    if (
        len(candidate_parts) == len(previous_parts) + 1
        and candidate_parts[:-1] == previous_parts
        and candidate_parts[-1] == 1
    ):
        return True
    if (
        len(candidate_parts) == len(previous_parts)
        and candidate_parts[:-1] == previous_parts[:-1]
        and candidate_parts[-1] == previous_parts[-1] + 1
    ):
        return True
    if len(candidate_parts) < len(previous_parts):
        depth = len(candidate_parts)
        if (
            candidate_parts[:-1] == previous_parts[: depth - 1]
            and candidate_parts[-1] == previous_parts[depth - 1] + 1
        ):
            return True
    if (
        candidate_parts[0] == previous_parts[0] + 1
        and all(part == 0 for part in candidate_parts[1:])
    ):
        return True
    if len(candidate_parts) == 1 and candidate_parts[0] == previous_parts[0] + 1:
        return True
    return False


def _detect_toc_pages(blocks: list[ExtractedBlock]) -> set[int]:
    """Detect table-of-contents pages, including noisy PyMuPDF split blocks."""
    by_page: dict[int, list[ExtractedBlock]] = defaultdict(list)
    for block in blocks:
        by_page[block.page].append(block)

    pages: set[int] = set()
    for page, page_blocks in by_page.items():
        page_text = " ".join(block.text for block in page_blocks).lower()
        compact = re.sub(r"\s+", "", page_text)
        page_lines = [
            normalize_text(line)
            for block in page_blocks
            for line in re.split(r"[\n\r]+", block.text)
            if normalize_text(line)
        ]
        has_toc_title = any(
            len(block.text) < 140
            and (
                block.text.strip().lower() == "table of contents"
                or re.sub(r"\s+", "", block.text.lower())
                in {"0.1目录tableofcontents", "目录tableofcontents"}
                or re.search(r"^\s*0\.1\s*目录", block.text)
            )
            for block in page_blocks
        )
        has_toc_header = (
            "章节chapter" in compact
            and "标题titles" in compact
            and ("页码page" in compact or "page" in page_text)
        )
        locator_count = sum(_is_standalone_locator(line) for line in page_lines)
        bilingual_label_count = sum(
            bool(re.search(r"[\u3400-\u9fff]", line) and re.search(r"[A-Za-z]", line))
            for line in page_lines
        )
        long_prose_count = sum(
            len(line) > 150 or bool(re.search(r"[。；;]", line))
            for line in page_lines
            if not _is_standalone_locator(line)
        )
        if has_toc_title or has_toc_header or (
            locator_count >= 8 and bilingual_label_count >= 6 and "cover page" in page_text
        ) or (
            locator_count >= 3 and bilingual_label_count >= 3 and long_prose_count == 0
        ):
            pages.add(page)
    return pages


def _detect_change_history_pages(blocks: list[ExtractedBlock]) -> set[int]:
    revision_pages = {
        block.page
        for block in blocks
        if REVISION_RE.match(block.text) and DATE_RE.search(block.text)
    }
    first_revision_page = min(revision_pages) if revision_pages else None
    explicit_change_pages = {
        block.page
        for block in blocks
        if len(block.text) < 100
        and (first_revision_page is None or block.page <= first_revision_page)
        and (
            block.text.strip().lower().startswith("history of change")
            or block.text.strip().startswith("更改历史记录")
        )
    }
    explicit_change_pages.update(revision_pages)
    contents_pages = _detect_toc_pages(blocks)
    change_history_pages = set(explicit_change_pages)
    if explicit_change_pages:
        start_page = min(explicit_change_pages)
        end_candidates = [page for page in contents_pages if page > start_page]
        end_page = min(end_candidates) - 1 if end_candidates else max(explicit_change_pages)
        change_history_pages.update(range(start_page, end_page + 1))
    return change_history_pages


def _detect_reference_pages(blocks: list[ExtractedBlock]) -> set[int]:
    rows_by_page: Counter[int] = Counter()
    for block in blocks:
        if block.source == SourceType.docx:
            continue
        if block.block_type == BlockType.table_row and _is_reference_table_row(block.text):
            rows_by_page[block.page] += 1
    return {page for page, row_count in rows_by_page.items() if row_count >= 3}


def _classify_special_content(blocks: list[ExtractedBlock]) -> None:
    non_docx_blocks = [block for block in blocks if block.source != SourceType.docx]
    toc_pages = _detect_toc_pages(non_docx_blocks)
    for block in blocks:
        if (
            block.source != SourceType.docx
            and block.page in toc_pages
            and block.block_type not in {
            BlockType.header,
            BlockType.footer,
            }
        ):
            block.content_class = "table_of_contents"
            block.ignored = True

    change_history_pages = _detect_change_history_pages(non_docx_blocks)

    current_revision: str | None = None
    reference_rows_by_page: Counter[int] = Counter()
    for block in sorted(blocks, key=lambda item: (item.page, item.reading_order)):
        if block.content_class == "table_of_contents":
            continue
        if (
            block.source != SourceType.docx
            and block.page in change_history_pages
            and block.block_type in {
            BlockType.table_row,
            BlockType.paragraph,
            }
        ):
            revision_match = REVISION_RE.match(block.text)
            if revision_match:
                current_revision = revision_match.group(1)
            if current_revision:
                block.revision_id = current_revision
                block.block_type = BlockType.change_history
                block.content_class = "change_history"
                date_match = DATE_RE.search(block.text)
                if date_match:
                    block.effective_date = date_match.group(0)
            continue
        if (
            block.source != SourceType.docx
            and block.block_type == BlockType.table_row
            and _is_reference_table_row(block.text)
        ):
            block.block_type = BlockType.reference_table
            block.content_class = "reference_table"
            reference_rows_by_page[block.page] += 1
            continue

    reference_pages = {
        page for page, row_count in reference_rows_by_page.items() if row_count >= 3
    }
    for block in blocks:
        if (
            block.source != SourceType.docx
            and block.page in reference_pages
            and block.block_type not in {
            BlockType.header,
            BlockType.footer,
            }
        ):
            block.content_class = "reference_table"
            if block.block_type in {
                BlockType.table_row,
                BlockType.table_cell,
                BlockType.paragraph,
            }:
                block.block_type = BlockType.reference_table


def segment_blocks(
    raw_blocks: list[ExtractedBlock],
    *,
    include_headers_footers: bool = False,
) -> list[ExtractedBlock]:
    """Normalize, split, classify, section-tag, and preserve all logical blocks."""
    if not raw_blocks:
        return []
    page_count = max(block.page for block in raw_blocks)
    expanded: list[ExtractedBlock] = []

    ordered = sorted(
        raw_blocks,
        key=lambda b: (
            b.page,
            b.bbox[1] if b.bbox else b.reading_order,
            b.bbox[0] if b.bbox else 0,
            b.reading_order,
        ),
    )
    toc_pages = _detect_toc_pages(ordered)
    non_docx_ordered = [block for block in ordered if block.source != SourceType.docx]
    change_history_pages = _detect_change_history_pages(non_docx_ordered)
    reference_pages = _detect_reference_pages(non_docx_ordered)
    for block in ordered:
        if not block.text:
            continue
        if block.page in toc_pages and block.block_type not in {
            BlockType.header,
            BlockType.footer,
        }:
            block.ignored = True
            block.content_class = "table_of_contents"
        if _is_repeated_furniture(block, page_count):
            block.ignored = not include_headers_footers
            if block.block_type not in {BlockType.header, BlockType.footer}:
                block.block_type = BlockType.header
        if (
            block.source != SourceType.docx
            and block.page in change_history_pages
            and block.block_type in {
            BlockType.heading,
            BlockType.paragraph,
            BlockType.table_row,
            }
        ):
            block.content_class = "change_history"
        if (
            block.source != SourceType.docx
            and block.page in reference_pages
            and block.block_type not in {
            BlockType.header,
            BlockType.footer,
            }
        ):
            block.content_class = "reference_table"
            if block.block_type in {
                BlockType.table_row,
                BlockType.table_cell,
                BlockType.paragraph,
            }:
                block.block_type = BlockType.reference_table
        if (
            extract_section(block.text)
            and not block.ignored
            and block.block_type in {BlockType.header, BlockType.footer}
        ):
            block.block_type = BlockType.heading
        expanded.extend(_split_mixed_lines(block))

    blocks = _merge_adjacent_paragraph_fragments(_deduplicate(expanded))
    _classify_special_content(blocks)
    active_section: str | None = None
    for index, block in enumerate(blocks):
        preserved_section = block.section
        section = extract_section(block.text)
        top_level_single_number = bool(section and re.fullmatch(r"\d+", section))
        standalone_section_number = bool(
            not section and _is_standalone_locator(block.text) and "." in block.text
        )
        if (
            block.source == SourceType.docx
            and preserved_section
            and block.content_class
            not in {"change_history", "reference_table", "table_of_contents"}
        ):
            active_section = preserved_section
            block.section = active_section
        elif standalone_section_number and block.content_class not in {
            "reference_table",
            "change_history",
            "table_of_contents",
        }:
            possible_section = block.text.strip()
            if (
                not block.ignored
                and active_section is not None
                and _is_plausible_next_section(active_section, possible_section)
            ):
                active_section = possible_section
            block.ignored = True
            block.content_class = "locator"
            block.section = active_section
        elif (
            section
            and not block.ignored
            and block.content_class
            not in {"change_history", "reference_table", "table_of_contents"}
            and block.block_type
            in {BlockType.heading, BlockType.table_row, BlockType.paragraph}
            and (not top_level_single_number or block.block_type == BlockType.heading)
            and _is_plausible_next_section(active_section, section)
        ):
            active_section = section
            block.section = active_section
        elif not block.ignored and active_section:
            block.section = active_section
        if block.text.startswith(("-", "•", "·")):
            block.block_type = BlockType.bullet
        block.language = language_of(block.text)
        if index:
            block.context_before = blocks[index - 1].text
        if index + 1 < len(blocks):
            block.context_after = blocks[index + 1].text
    return blocks
