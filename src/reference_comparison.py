from __future__ import annotations

import json
import re

from rapidfuzz import fuzz, process

from .llm_client import call_llm_json, format_api_error, get_llm_config, is_authentication_error
from .utils import BilingualPair, DocumentResult, TextBlock, contains_english, normalize_text


def compare_with_references(
    pairs: list[BilingualPair],
    reference_docs: list[DocumentResult],
    use_llm: bool = False,
    model: str = "gpt-4o-mini",
) -> tuple[list[dict[str, object]], list[str]]:
    if not reference_docs:
        return [], ["Reference comparison not performed because no reference regulation documents were uploaded."]

    reference_blocks = [
        block for doc in reference_docs for block in doc.blocks
        if contains_english(block.text) and len(block.text) > 30
    ]
    if not reference_blocks:
        return [], ["Reference documents were uploaded, but no usable English reference text was extracted."]

    rows: list[dict[str, object]] = []
    choices = {block.block_id: block.text for block in reference_blocks}
    for pair in pairs:
        if len(pair.english_text) < 25:
            continue
        match = process.extractOne(pair.english_text, choices, scorer=fuzz.token_set_ratio)
        if not match:
            continue
        _text, score, block_id = match
        ref_block = next(block for block in reference_blocks if block.block_id == block_id)
        if score >= 65:
            mismatch = score < 82
            rows.append({
                "bilingual document location": pair.location,
                "Chinese source text": pair.chinese_text,
                "English wording in bilingual document": pair.english_text,
                "matched reference document": ref_block.file_name,
                "reference location": ref_block.location_label(),
                "similarity score": round(score, 1),
                "possible issue": "Possible mismatch or weakened regulatory meaning" if mismatch else "Likely aligned",
                "reference wording": normalize_text(ref_block.text),
                "suggested improved wording": normalize_text(ref_block.text) if mismatch else "",
                "comparison method": "deterministic fuzzy match",
            })
    if use_llm:
        rows, llm_warnings = _enrich_reference_rows_with_llm(rows, model=model)
        return rows, llm_warnings
    return rows, []


def _enrich_reference_rows_with_llm(rows: list[dict[str, object]], model: str) -> tuple[list[dict[str, object]], list[str]]:
    config = get_llm_config(model)
    if not config.api_key:
        return rows, [f"{config.provider} API key not found. Reference comparison used deterministic fuzzy matching only."]

    warnings: list[str] = []
    for row in rows:
        if row.get("possible issue") != "Possible mismatch or weakened regulatory meaning":
            continue
        payload = {
            "task": "Compare regulatory English wording in a bilingual document against a reference regulation. Chinese source is controlling.",
            "chinese_source": row.get("Chinese source text"),
            "bilingual_english": row.get("English wording in bilingual document"),
            "reference_english": row.get("reference wording"),
            "return_json_keys": ["assessment", "explanation", "suggested_improved_wording", "confidence"],
        }
        try:
            parsed = call_llm_json(
                config,
                [
                    {"role": "system", "content": "You compare medical-device regulatory wording for meaning, obligation strength, and terminology."},
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                expected="object",
            )
        except Exception as exc:
            warnings.append(f"API reference comparison failed: {format_api_error(config.provider, exc)}")
            if is_authentication_error(exc):
                break
            continue
        row["possible issue"] = parsed.get("assessment", row["possible issue"])
        row["LLM explanation"] = parsed.get("explanation", "")
        row["suggested improved wording"] = parsed.get("suggested_improved_wording", row.get("suggested improved wording", ""))
        row["LLM confidence"] = parsed.get("confidence", "")
        row["comparison method"] = f"deterministic fuzzy match + {config.provider} semantic comparison"
    return rows, warnings


def _extract_json(content: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    return match.group(1).strip() if match else content.strip()
