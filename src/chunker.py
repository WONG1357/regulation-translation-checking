from __future__ import annotations

from typing import Any

from .section_parser import build_section_segments, section_at_or_after


def build_chunks(
    blocks: list[dict[str, Any]],
    include_headers: bool = False,
    max_characters: int = 12000,
    review_start_section: str | None = None,
) -> list[dict[str, Any]]:
    """Pack logical page/section segments into size-limited AI chunks.

    Small neighboring sections may share a chunk. Oversized sections may span
    multiple chunks. Page boundaries alone never define the AI scope.
    """
    segments = [
        segment for segment in build_section_segments(blocks, include_headers)
        if section_at_or_after(segment.get("section_id"), review_start_section)
    ]
    chunks: list[dict[str, Any]] = []
    current_blocks: list[dict[str, Any]] = []
    current_segments: list[dict[str, Any]] = []
    current_size = 0

    def flush() -> None:
        nonlocal current_blocks, current_segments, current_size
        if not current_blocks:
            return
        number = len(chunks) + 1
        pages = [int(item.get("page") or 1) for item in current_blocks]
        sections = [item.get("section") for item in current_blocks if item.get("section")]
        segment_ids = list(dict.fromkeys(item["section_segment_id"] for item in current_blocks))
        chunks.append({
            "chunk_id": f"chunk_{number:03d}",
            "page_range": [min(pages), max(pages)],
            "section_range": [sections[0], sections[-1]] if sections else [None, None],
            "section_ids": list(dict.fromkeys(sections)),
            "segment_ids": segment_ids,
            "segments": [{
                "segment_id": segment["segment_id"],
                "section_id": segment.get("section_id"),
                "section_title": segment.get("section_title"),
                "page_start": segment["page_start"],
                "page_end": segment["page_end"],
                "continued_from_previous_page": segment["continued_from_previous_page"],
            } for segment in current_segments if segment["segment_id"] in segment_ids],
            "block_ids": [item["block_id"] for item in current_blocks],
            "blocks": [{
                "block_id": item["block_id"],
                "text": item["text"],
                "language": item["language"],
                "block_type": item["block_type"],
                "page": item["page"],
                "section": item.get("section"),
                "section_title": item.get("section_title"),
                "section_segment_id": item.get("section_segment_id"),
                "section_type": item.get("section_type"),
                "section_category": item.get("section_category"),
            } for item in current_blocks],
            "block_text": "\n".join(
                f'{item["block_id"]} [{item.get("section") or "front matter"} | '
                f'{item.get("section_segment_id")}]: {item["text"]}'
                for item in current_blocks
            ),
            "nearby_heading_context": next(
                (item.get("heading") for item in reversed(current_blocks) if item.get("heading")), None
            ),
        })
        current_blocks, current_segments, current_size = [], [], 0

    for segment in segments:
        segment_blocks = segment["blocks"]
        for block in segment_blocks:
            size = len(block.get("text", "")) + 80
            if current_blocks and current_size + size > max_characters:
                flush()
            if not current_segments or current_segments[-1]["segment_id"] != segment["segment_id"]:
                current_segments.append(segment)
            current_blocks.append(block)
            current_size += size
    flush()
    return chunks
