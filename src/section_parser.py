from __future__ import annotations

import re
from typing import Any


SECTION_RE = re.compile(
    r"^\s*((?:\d+(?:\.\d+)+)(?:\.[A-Za-z])?[.)]?|(?:\d+(?:\.\d+)*)\.[A-Za-z]\))\s*(.*)"
)


def parse_sections(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    current_section: str | None = None
    current_heading: str | None = None
    for block in sorted(blocks, key=lambda item: item["order"]):
        match = SECTION_RE.match(block["text"])
        if match:
            current_section = match.group(1).rstrip(".)")
            current_heading = block["text"]
            block["section"] = current_section
            block["heading"] = current_heading
            if block["block_type"] != "header_footer":
                block["block_type"] = "heading"
        else:
            block["section"] = block.get("section") or current_section
            block["heading"] = block.get("heading") or current_heading
    return blocks
