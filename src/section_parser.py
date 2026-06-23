from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any


# Supports 0.1, 1.0, 3.2.11, 7.5.9.b), 7.5.9 b), and optional trailing punctuation.
NUMBERED_SECTION_RE = re.compile(
    r"^\s*"
    r"(?P<number>\d+(?:\.\d+)+(?:\s*\.\s*[A-Za-z]|\s+[A-Za-z](?=\s*[.)]))?)"
    r"\s*(?P<closing>[.)、：:]?)"
    r"\s*(?P<title>.*)$"
)
APPENDIX_RE = re.compile(
    r"^\s*(?P<label>appendix|annex|附录|附件)\s*"
    r"(?P<number>[A-Za-z0-9一二三四五六七八九十]*)"
    r"\s*[-—:：.]?\s*(?P<title>.*)$",
    re.I,
)

CATEGORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("revision_history", re.compile(r"修订历史|更改历史|版本历史|revision\s+history|history\s+of\s+change", re.I)),
    ("definitions_abbreviations", re.compile(r"定义|术语|简写|缩写|definitions?|terms?\s+and\s+definitions?|abbreviations?", re.I)),
    ("regulation_references", re.compile(r"适用法规|法规引用|规范性引用|references?|applicable\s+regulations?|regulatory\s+references?", re.I)),
    ("table_of_contents", re.compile(r"目录|table\s+of\s+contents|contents", re.I)),
    ("scope", re.compile(r"范围|适用范围|\bscope\b", re.I)),
    ("responsibilities", re.compile(r"职责|责任|responsibilit(?:y|ies)", re.I)),
    ("procedure", re.compile(r"程序|过程|方法|procedure|process|method", re.I)),
    ("records", re.compile(r"记录|records?", re.I)),
]


@dataclass(frozen=True)
class SectionMatch:
    section_id: str
    title: str
    heading: str
    section_type: str
    level: int
    category: str


def section_order_key(section_id: str | None) -> tuple:
    """Sort numbered sections numerically; appendices follow numbered content."""
    clean = (section_id or "").strip()
    if not clean:
        return (0,)
    if re.match(r"^(appendix|annex|附录|附件)", clean, re.I):
        suffix = re.sub(r"^(appendix|annex|附录|附件)\s*", "", clean, flags=re.I)
        return (2, suffix.casefold())
    parts: list[tuple[int, int | str]] = []
    for part in clean.rstrip(".)").split("."):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.casefold()))
    return (1, *parts)


def section_at_or_after(section_id: str | None, review_start: str | None) -> bool:
    if not review_start or not review_start.strip():
        return True
    if not section_id:
        return False
    return section_order_key(section_id) >= section_order_key(review_start)


def is_valid_next_section(current_id: str | None, candidate_id: str) -> bool:
    """Enforce a sequential numeric section hierarchy.

    The document must begin at 0.1. From 0.1 the only valid next headings are
    0.2 (next sibling), 1.0 (next major section), or 0.1.1 (first child).
    The same sibling/major/first-child rule is applied throughout the document.
    """
    if current_id is None:
        return candidate_id == "0.1"
    if not re.fullmatch(r"\d+(?:\.\d+)+", current_id):
        return False
    if not re.fullmatch(r"\d+(?:\.\d+)+", candidate_id):
        return False

    current = [int(part) for part in current_id.split(".")]
    candidate = [int(part) for part in candidate_id.split(".")]

    # First child, e.g. 0.1 -> 0.1.1 or 4.2 -> 4.2.1.
    if candidate == current + [1]:
        return True

    # Next sibling at the same depth, e.g. 0.1 -> 0.2 or 4.2.1 -> 4.2.2.
    if len(candidate) == len(current):
        if candidate[:-1] == current[:-1] and candidate[-1] == current[-1] + 1:
            return True

    # Move up to the next sibling of any ancestor, e.g. 4.2.3 -> 4.3.
    for depth in range(len(current) - 1, 1, -1):
        ancestor = current[:depth]
        expected = ancestor[:-1] + [ancestor[-1] + 1]
        if candidate == expected:
            return True

    # Next major section always begins at .0, e.g. 0.1 -> 1.0.
    if len(candidate) == 2 and candidate == [current[0] + 1, 0]:
        return True
    return False


def parse_section_heading(text: str, block_type: str = "paragraph") -> SectionMatch | None:
    """Return a section heading only when the block plausibly begins a new section."""
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean or block_type == "header_footer":
        return None

    appendix = APPENDIX_RE.match(clean)
    if appendix:
        number = appendix.group("number").strip()
        label = appendix.group("label")
        section_id = f"{label.title()} {number}".strip()
        title = appendix.group("title").strip()
        return SectionMatch(
            section_id=section_id,
            title=title,
            heading=clean,
            section_type="appendix",
            level=1,
            category=classify_section_category(clean, "appendix"),
        )

    match = NUMBERED_SECTION_RE.match(clean)
    if not match:
        return None
    raw_number = re.sub(r"\s+([A-Za-z])$", r".\1", match.group("number").strip())
    number = re.sub(r"\s+", "", raw_number)
    number = re.sub(r"\.([A-Za-z])$", lambda value: f".{value.group(1).lower()}", number)
    title = match.group("title").strip()

    # A long table row or sentence beginning with a clause reference is usually content,
    # not a heading. Existing extractor heading hints remain authoritative.
    heading_hint = block_type == "heading"
    if not heading_hint and ("|" in clean or len(clean) > 240):
        return None
    if not heading_hint and not title:
        return None

    numeric_parts = re.findall(r"\d+", number)
    alpha_suffix = bool(re.search(r"\.[a-z]$", number, re.I))
    level = len(numeric_parts) + (1 if alpha_suffix else 0)
    return SectionMatch(
        section_id=number,
        title=title,
        heading=clean,
        section_type="numbered",
        level=level,
        category=classify_section_category(clean, "numbered"),
    )


def classify_section_category(heading: str, section_type: str = "numbered") -> str:
    if section_type == "appendix":
        return "appendix"
    for category, pattern in CATEGORY_PATTERNS:
        if pattern.search(heading or ""):
            return category
    return "main_content"


def parse_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Assign logical sections in reading order, allowing sections to cross pages."""
    current: SectionMatch | None = None
    for block in sorted(blocks, key=lambda item: item["order"]):
        match = parse_section_heading(block.get("text", ""), block.get("block_type", "paragraph"))
        if match and is_valid_next_section(
            current.section_id if current else None,
            match.section_id,
        ):
            current = match
            block["section"] = match.section_id
            block["heading"] = match.heading
            block["section_title"] = match.title
            block["section_type"] = match.section_type
            block["section_level"] = match.level
            block["section_category"] = match.category
            if block["block_type"] != "header_footer":
                block["block_type"] = "heading"
            continue

        if match:
            block["section_candidate_rejected"] = match.section_id
            block["section_rejection_reason"] = (
                "Invalid section sequence. "
                f"Expected a valid sibling, next major section, or first child after "
                f"{current.section_id if current else 'document start 0.1'}."
            )
            if block.get("block_type") == "heading":
                block["block_type"] = "paragraph"

        # No page reset: the active logical section continues onto following pages.
        if current:
            block["section"] = current.section_id
            block["heading"] = current.heading
            block["section_title"] = current.title
            block["section_type"] = current.section_type
            block["section_level"] = current.level
            block["section_category"] = current.category
        else:
            block["section"] = None
            block["heading"] = None
            block["section_title"] = block.get("section_title") or ""
            block["section_type"] = block.get("section_type") or "front_matter"
            block["section_level"] = block.get("section_level") or 0
            block["section_category"] = block.get("section_category") or "front_matter"
    return assign_section_segments(blocks)


def assign_section_segments(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Create page+section continuous segments while retaining section continuity."""
    segment_number = 0
    previous_key: tuple[int, str | None] | None = None
    for block in sorted(blocks, key=lambda item: item["order"]):
        key = (int(block.get("page") or 1), block.get("section"))
        if key != previous_key:
            segment_number += 1
            previous_key = key
        block["section_segment_id"] = f"segment_{segment_number:04d}"
    return blocks


def build_section_segments(
    blocks: list[dict[str, Any]], include_headers: bool = False
) -> list[dict[str, Any]]:
    segments: list[dict[str, Any]] = []
    current_id: str | None = None
    current: list[dict[str, Any]] = []

    def flush() -> None:
        nonlocal current
        if not current:
            return
        first, last = current[0], current[-1]
        segments.append({
            "segment_id": first["section_segment_id"],
            "section_id": first.get("section"),
            "section_title": first.get("section_title", ""),
            "section_category": first.get("section_category", "front_matter"),
            "page_start": int(first.get("page") or 1),
            "page_end": int(last.get("page") or 1),
            "order_start": first["order"],
            "order_end": last["order"],
            "block_ids": [item["block_id"] for item in current],
            "blocks": list(current),
            "continued_from_previous_page": bool(
                segments
                and segments[-1].get("section_id") == first.get("section")
                and segments[-1].get("page_end") != int(first.get("page") or 1)
            ),
        })
        current = []

    for block in sorted(blocks, key=lambda item: item["order"]):
        if block.get("block_type") == "header_footer" and not include_headers:
            continue
        segment_id = block.get("section_segment_id")
        if current and segment_id != current_id:
            flush()
        current_id = segment_id
        current.append(block)
    flush()
    return segments
