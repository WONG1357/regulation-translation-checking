from __future__ import annotations

import json
from typing import Any, Callable

from .ai_client import call_openai_compatible


ALLOWED_STATUSES = {
    "paired", "missing_english", "missing_chinese", "standalone",
    "header_footer", "uncertain", "unpaired",
}


def pair_chunks(
    chunks: list[dict[str, Any]],
    api_key: str,
    model: str,
    base_url: str = "",
    progress: Callable[[int, int], None] | None = None,
) -> dict[str, Any]:
    all_pairs: list[dict[str, Any]] = []
    all_statuses: list[dict[str, Any]] = []
    warnings: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        result = _pair_chunk(chunk, api_key, model, base_url)
        valid_ids = set(chunk["block_ids"])
        pairs, statuses, chunk_warnings = validate_pairing_result(result, chunk["chunk_id"], valid_ids)
        all_pairs.extend(pairs)
        all_statuses.extend(statuses)
        warnings.extend(chunk_warnings)
        if progress:
            progress(index, len(chunks))
    return {"pairs": all_pairs, "block_statuses": all_statuses, "warnings": warnings}


def _pair_chunk(chunk: dict[str, Any], api_key: str, model: str, base_url: str) -> dict[str, Any]:
    schema = {
        "chunk_id": chunk["chunk_id"],
        "pairs": [{
            "pair_id": f'{chunk["chunk_id"]}_pair_001',
            "chinese_block_ids": ["existing_id"],
            "english_block_ids": ["existing_id"],
            "chinese_text": "verbatim source text",
            "english_text": "verbatim source text",
            "confidence": 0.9,
            "pairing_reason": "short reason",
            "status": "paired",
        }],
        "block_statuses": [{"block_id": "existing_id", "status": "paired", "pair_id": "pair id or null"}],
        "warnings": [],
    }
    prompt = f"""Pair Chinese source blocks with their corresponding English translations.
Use semantic meaning and document order. A pair may contain multiple blocks on either side.
Use ONLY supplied block IDs and copy text verbatim; never invent, rewrite, or omit document text.
Account for every block exactly once in block_statuses.
Allowed statuses: paired, missing_english, missing_chinese, standalone, header_footer, uncertain, unpaired.
Do not force unrelated text into a pair. Titles, codes, company names, abbreviations and regulation names may be standalone.
Return JSON only, shaped like:
{json.dumps(schema, ensure_ascii=False)}

Chunk:
{json.dumps(chunk, ensure_ascii=False)}"""
    return call_openai_compatible(
        api_key, model,
        [{"role": "system", "content": "You are a careful bilingual regulatory document pairing engine."},
         {"role": "user", "content": prompt}],
        base_url,
    )


def validate_pairing_result(
    result: dict[str, Any], chunk_id: str, valid_ids: set[str]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    if not isinstance(result, dict):
        raise ValueError(f"{chunk_id}: AI pairing result is not a JSON object.")
    warnings = [str(item) for item in result.get("warnings", [])]
    used_pair_ids: set[str] = set()
    pairs: list[dict[str, Any]] = []
    assigned: set[str] = set()
    for number, pair in enumerate(result.get("pairs", []), start=1):
        zh_ids = [value for value in pair.get("chinese_block_ids", []) if value in valid_ids]
        en_ids = [value for value in pair.get("english_block_ids", []) if value in valid_ids]
        if not zh_ids or not en_ids:
            warnings.append(f"{chunk_id}: discarded a pair with missing or unknown block IDs.")
            continue
        if set(zh_ids) & set(en_ids):
            warnings.append(f"{chunk_id}: discarded a pair that reused the same block on both sides.")
            continue
        pair_id = str(pair.get("pair_id") or f"{chunk_id}_pair_{number:03d}")
        if pair_id in used_pair_ids:
            pair_id = f"{chunk_id}_pair_{number:03d}"
        used_pair_ids.add(pair_id)
        clean = {
            **pair,
            "pair_id": pair_id,
            "chinese_block_ids": zh_ids,
            "english_block_ids": en_ids,
            "confidence": float(pair.get("confidence") or 0),
            "status": "paired" if pair.get("status") not in {"uncertain"} else "uncertain",
        }
        pairs.append(clean)
        assigned.update(zh_ids + en_ids)

    status_map: dict[str, dict[str, Any]] = {}
    for item in result.get("block_statuses", []):
        block_id = item.get("block_id")
        status = item.get("status")
        if block_id in valid_ids and status in ALLOWED_STATUSES:
            status_map[block_id] = {
                "block_id": block_id,
                "status": status,
                "pair_id": item.get("pair_id"),
            }
    pair_lookup = {
        block_id: (pair["pair_id"], pair.get("status", "paired"))
        for pair in pairs
        for block_id in pair["chinese_block_ids"] + pair["english_block_ids"]
    }
    for block_id in valid_ids:
        if block_id in pair_lookup:
            pair_id, pair_status = pair_lookup[block_id]
            status_map[block_id] = {
                "block_id": block_id,
                "status": pair_status,
                "pair_id": pair_id,
            }
        elif block_id not in status_map:
            status_map[block_id] = {"block_id": block_id, "status": "unpaired", "pair_id": None}
            warnings.append(f"{chunk_id}: {block_id} was omitted by AI and marked unpaired.")
    return pairs, list(status_map.values()), warnings
