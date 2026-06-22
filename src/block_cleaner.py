from __future__ import annotations

from collections import defaultdict
import re
from typing import Any


def mark_repeated_headers_footers(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Mark repeated edge-of-page text without deleting it."""
    normalized_pages: dict[str, set[int]] = defaultdict(set)
    page_orders: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in blocks:
        page_orders[int(block.get("page") or 1)].append(block)
        key = _normalise(block["text"])
        if key:
            normalized_pages[key].add(int(block.get("page") or 1))

    page_count = max(page_orders, default=1)
    threshold = max(2, min(3, page_count))
    for page_blocks in page_orders.values():
        ordered = sorted(page_blocks, key=lambda item: item["order"])
        edge_ids = {item["block_id"] for item in ordered[:2] + ordered[-2:]}
        for block in ordered:
            key = _normalise(block["text"])
            repeated = len(normalized_pages.get(key, set())) >= threshold
            page_number_only = bool(re.fullmatch(r"(?:page\s*)?\d+(?:\s*(?:/|of)\s*\d+)?", key, re.I))
            if block["block_id"] in edge_ids and (repeated or page_number_only):
                block["block_type"] = "header_footer"
    return blocks


def _normalise(text: str) -> str:
    text = re.sub(r"\d+", "#", text.lower())
    return re.sub(r"\s+", " ", text).strip()
