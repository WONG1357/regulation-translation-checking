from __future__ import annotations

import re
from dataclasses import dataclass
from itertools import zip_longest

from .utils import TextBlock, normalize_text


SECTION_HEADING_RE = re.compile(
    r"^\s*(?P<number>\d+(?:\.\d+){1,3})"
    r"(?:\s+|[、．):：-]\s*)"
    r"(?P<title>\S.*)?$"
)
REVISION_REFERENCE_RE = re.compile(
    r"\b(?:section|clause|procedure|revision|rev\.?|amend(?:ed|ment)?|"
    r"add(?:ed|ition)?|delete(?:d)?|replace(?:d)?|change(?:d)?|"
    r"supporting|subsequent|existing|into|from|to)\b",
    re.I,
)


@dataclass(frozen=True)
class DetectedSection:
    section_id: str
    title: str
    heading: str
    key: tuple[int, ...]


@dataclass
class SectionSegment:
    segment_id: str
    file_name: str
    section_id: str | None
    section_title: str
    page_number: int | None
    start_order: int
    end_order: int
    block_ids: list[str]


def parse_section_heading(text: str | None) -> DetectedSection | None:
    clean = normalize_text(text or "")
    match = SECTION_HEADING_RE.match(clean)
    if not match:
        return None
    section_id = match.group("number")
    return DetectedSection(
        section_id=section_id,
        title=normalize_text(match.group("title") or ""),
        heading=clean,
        key=section_sort_key(section_id),
    )


def is_section_heading_block(block: TextBlock) -> DetectedSection | None:
    """Return a section only when the block is credible as a logical heading."""
    detected = parse_section_heading(block.text)
    if not detected:
        return None
    is_table_content = block.table_index is not None or block.extraction_source == "table"
    if not is_table_content:
        return detected

    # Tables frequently contain revision-history references such as
    # "8.2.3 into Supporting Procedure..." that are not document headings.
    title = detected.title
    if REVISION_REFERENCE_RE.search(title):
        return None
    has_chinese = bool(re.search(r"[\u3400-\u9fff]", title))
    has_english = bool(re.search(r"[A-Za-z]", title))
    if not (has_chinese and has_english):
        return None
    if len(title) > 120:
        return None
    return detected


def section_sort_key(value: str | float | int | None) -> tuple[int, ...]:
    if value is None:
        return ()
    match = re.match(r"^\s*(\d+(?:\.\d+)*)", str(value))
    if not match:
        return ()
    return tuple(int(part) for part in match.group(1).split("."))


def compare_sections(left: str | float | int | None, right: str | float | int | None) -> int:
    left_key = section_sort_key(left)
    right_key = section_sort_key(right)
    for left_part, right_part in zip_longest(left_key, right_key, fillvalue=0):
        if left_part < right_part:
            return -1
        if left_part > right_part:
            return 1
    return 0


def section_at_or_after(section_id: str | None, start: str | float | int | None) -> bool:
    return bool(section_sort_key(section_id)) and compare_sections(section_id, start) >= 0


def assign_sections(blocks: list[TextBlock]) -> None:
    """Assign the nearest preceding numbered heading to every block in reading order."""
    active: DetectedSection | None = None
    for block in sorted(blocks, key=lambda item: item.order):
        detected = is_section_heading_block(block)
        if not detected and block.section_heading:
            detected = parse_section_heading(block.section_heading)
        if detected:
            active = detected
            if is_section_heading_block(block):
                block.block_type = "heading"
        if active:
            block.section_id = active.section_id
            block.section_title = active.title
            block.section_heading = active.heading
        else:
            block.section_id = None
            block.section_title = ""
            block.section_heading = None


def build_section_segments(blocks: list[TextBlock]) -> list[SectionSegment]:
    """Build continuous section ranges, splitting at page or section changes."""
    segments: list[SectionSegment] = []
    current: SectionSegment | None = None
    for block in sorted(blocks, key=lambda item: item.order):
        key = (block.section_id, block.page_number)
        current_key = (current.section_id, current.page_number) if current else None
        if current is None or key != current_key:
            current = SectionSegment(
                segment_id=f"{block.file_name}:segment:{len(segments) + 1}",
                file_name=block.file_name,
                section_id=block.section_id,
                section_title=block.section_title,
                page_number=block.page_number,
                start_order=block.order,
                end_order=block.order,
                block_ids=[],
            )
            segments.append(current)
        current.block_ids.append(block.block_id)
        current.end_order = block.order
    return segments
