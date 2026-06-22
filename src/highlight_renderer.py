from __future__ import annotations

import html
from collections import defaultdict
from typing import Any


PALETTE = [
    "#FFF1B8", "#D9F7BE", "#BAE7FF", "#EFDBFF", "#FFD6E7",
    "#D6E4FF", "#B5F5EC", "#FFE7BA", "#E6FFFB", "#F4FFB8",
    "#F9F0FF", "#E6F4FF", "#FFF0F6", "#FCFFE6", "#FFFBE6",
    "#F0F5FF", "#E8F5E9", "#FCE4EC", "#E0F2F1", "#FFF3E0",
]


def pair_colour_map(pairs: list[dict[str, Any]]) -> dict[str, str]:
    return {pair["pair_id"]: PALETTE[index % len(PALETTE)] for index, pair in enumerate(pairs)}


def render_highlighted_document(
    blocks: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    block_statuses: list[dict[str, Any]],
    show_headers: bool = False,
) -> str:
    colours = pair_colour_map(pairs)
    status_map = {item["block_id"]: item for item in block_statuses}
    pair_labels = {pair["pair_id"]: f"Pair {index:03d}" for index, pair in enumerate(pairs, start=1)}
    pages: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for block in sorted(blocks, key=lambda item: item["order"]):
        if block["block_type"] == "header_footer" and not show_headers:
            continue
        pages[int(block.get("page") or 1)].append(block)

    output = ['<div class="bilingual-document">']
    for page, page_blocks in pages.items():
        output.append(f'<section class="doc-page"><h3>Page {page}</h3>')
        for block in page_blocks:
            item = status_map.get(block["block_id"], {})
            status = item.get("status", "unpaired")
            pair_id = item.get("pair_id")
            styles = ["padding:10px 12px", "margin:7px 0", "border-radius:8px", "line-height:1.55"]
            label = ""
            if pair_id in colours:
                styles.append(f"background:{colours[pair_id]}")
                label = f'<span class="pair-label">{html.escape(pair_labels.get(pair_id, pair_id))}</span>'
            if status == "uncertain":
                styles.append("border:2px dashed #8c8c8c")
            elif status == "missing_english":
                styles.append("border:2px solid #ff7875")
            elif status == "missing_chinese":
                styles.append("border:2px solid #ffa940")
            else:
                styles.append("border:1px solid transparent")
            output.append(
                f'<div id="{html.escape(block["block_id"])}" style="{";".join(styles)}">'
                f'{label}<div>{html.escape(block["text"])}</div>'
                f'<small style="color:#666">{html.escape(block["block_id"])} · '
                f'{html.escape(str(block.get("section") or "No section"))}</small></div>'
            )
        output.append("</section>")
    output.append("</div>")
    return "\n".join(output)
