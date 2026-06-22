from __future__ import annotations

from collections import Counter
from typing import Any

import pandas as pd


def validate_coverage(
    blocks: list[dict[str, Any]], block_statuses: list[dict[str, Any]]
) -> tuple[pd.DataFrame, dict[str, int]]:
    status_map = {item["block_id"]: item for item in block_statuses}
    rows: list[dict[str, Any]] = []
    for block in sorted(blocks, key=lambda item: item["order"]):
        if block["block_type"] == "header_footer":
            status, pair_id = "header_footer", None
        else:
            item = status_map.get(block["block_id"], {})
            status, pair_id = item.get("status", "unpaired"), item.get("pair_id")
        rows.append({
            "block_id": block["block_id"],
            "page": block["page"],
            "section": block.get("section"),
            "text": block["text"],
            "language": block["language"],
            "block_type": block["block_type"],
            "status": status,
            "pair_id": pair_id,
        })
    counts = Counter(row["status"] for row in rows)
    summary = {
        "total blocks": len(rows),
        "paired blocks": counts["paired"],
        "unpaired blocks": counts["unpaired"],
        "uncertain blocks": counts["uncertain"],
        "missing English": counts["missing_english"],
        "missing Chinese": counts["missing_chinese"],
        "standalone": counts["standalone"],
        "header/footer ignored": counts["header_footer"],
    }
    return pd.DataFrame(rows), summary
