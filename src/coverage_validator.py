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


def build_page_coverage(
    blocks: list[dict[str, Any]], block_statuses: list[dict[str, Any]]
) -> pd.DataFrame:
    status_map = {item["block_id"]: item for item in block_statuses}
    rows: list[dict[str, Any]] = []
    pages = sorted({int(item.get("page") or 1) for item in blocks})
    for page in pages:
        page_blocks = [item for item in blocks if int(item.get("page") or 1) == page]
        meaningful = [item for item in page_blocks if item["block_type"] != "header_footer"]
        statuses = [status_map.get(item["block_id"], {}).get("status", "unpaired") for item in meaningful]
        pairs = {
            status_map.get(item["block_id"], {}).get("pair_id")
            for item in meaningful
            if status_map.get(item["block_id"], {}).get("pair_id")
        }
        unpaired = sum(status in {"unpaired", "uncertain", "missing_english", "missing_chinese"} for status in statuses)
        accounted = sum(status in {
            "paired", "standalone", "uncertain", "missing_english", "missing_chinese", "unpaired"
        } for status in statuses)
        if meaningful and accounted == 0:
            state = "Possibly skipped"
        elif unpaired and pairs:
            state = "Partial coverage"
        elif unpaired:
            state = "Unpaired content"
        else:
            state = "Covered"
        rows.append({
            "page_number": page,
            "sections_detected_on_page": ", ".join(dict.fromkeys(
                str(item.get("section") or "front_matter") for item in meaningful
            )),
            "extracted_blocks": len(page_blocks),
            "pairs": len(pairs),
            "unpaired_blocks": unpaired,
            "status": state,
        })
    return pd.DataFrame(rows)


def build_section_coverage(
    blocks: list[dict[str, Any]], block_statuses: list[dict[str, Any]]
) -> pd.DataFrame:
    status_map = {item["block_id"]: item for item in block_statuses}
    section_ids = list(dict.fromkeys(item.get("section") or "front_matter" for item in blocks))
    rows: list[dict[str, Any]] = []
    for section_id in section_ids:
        section_blocks = [
            item for item in blocks
            if (item.get("section") or "front_matter") == section_id
            and item["block_type"] != "header_footer"
        ]
        if not section_blocks:
            continue
        zh = [item for item in section_blocks if item.get("language") == "zh"]
        en = [item for item in section_blocks if item.get("language") == "en"]
        pairs = {
            status_map.get(item["block_id"], {}).get("pair_id")
            for item in section_blocks
            if status_map.get(item["block_id"], {}).get("pair_id")
        }
        unpaired_zh = sum(
            status_map.get(item["block_id"], {}).get("status", "unpaired") != "paired" for item in zh
        )
        unpaired_en = sum(
            status_map.get(item["block_id"], {}).get("status", "unpaired") != "paired" for item in en
        )
        if pairs and not (unpaired_zh or unpaired_en):
            state, reason = "Covered", ""
        elif pairs:
            state, reason = "Partial coverage", "Some Chinese or English blocks remain unpaired."
        elif zh or en:
            state, reason = "Unpaired content", "Meaningful language blocks have no confirmed bilingual pair."
        else:
            state, reason = "No bilingual main content", ""
        pages = [int(item.get("page") or 1) for item in section_blocks]
        rows.append({
            "section_id": section_id,
            "section_title": section_blocks[0].get("section_title", ""),
            "page_start": min(pages),
            "page_end": max(pages),
            "extracted_blocks": len(section_blocks),
            "Chinese main blocks": len(zh),
            "English translation blocks": len(en),
            "bilingual_pairs": len(pairs),
            "unpaired Chinese blocks": unpaired_zh,
            "unpaired English blocks": unpaired_en,
            "status": state,
            "failure reason": reason,
        })
    return pd.DataFrame(rows)
