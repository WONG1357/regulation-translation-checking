from __future__ import annotations

from typing import Any


def build_chunks(
    blocks: list[dict[str, Any]],
    include_headers: bool = False,
    max_characters: int = 12000,
) -> list[dict[str, Any]]:
    eligible = [
        block for block in sorted(blocks, key=lambda item: item["order"])
        if include_headers or block["block_type"] != "header_footer"
    ]
    chunks: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = []
    current_size = 0

    def flush() -> None:
        nonlocal current, current_size
        if not current:
            return
        number = len(chunks) + 1
        pages = [int(item.get("page") or 1) for item in current]
        sections = [item.get("section") for item in current if item.get("section")]
        chunks.append({
            "chunk_id": f"chunk_{number:03d}",
            "page_range": [min(pages), max(pages)],
            "section_range": [sections[0], sections[-1]] if sections else [None, None],
            "block_ids": [item["block_id"] for item in current],
            "blocks": [
                {
                    "block_id": item["block_id"],
                    "text": item["text"],
                    "language": item["language"],
                    "block_type": item["block_type"],
                    "page": item["page"],
                    "section": item.get("section"),
                }
                for item in current
            ],
            "block_text": "\n".join(f'{item["block_id"]}: {item["text"]}' for item in current),
            "nearby_heading_context": next(
                (item.get("heading") for item in reversed(current) if item.get("heading")), None
            ),
        })
        current = []
        current_size = 0

    for block in eligible:
        size = len(block["text"]) + 50
        boundary = current and (
            block.get("section") != current[-1].get("section")
            or block.get("table_id") != current[-1].get("table_id")
        )
        if current and (current_size + size > max_characters or (boundary and current_size > max_characters // 2)):
            flush()
        current.append(block)
        current_size += size
    flush()
    return chunks
