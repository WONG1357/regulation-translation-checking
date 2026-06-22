from __future__ import annotations

import json
from typing import Any

from .ai_client import call_openai_compatible


def check_terminology(
    pairs: list[dict[str, Any]], api_key: str, model: str, base_url: str = ""
) -> list[dict[str, Any]]:
    confirmed = [pair for pair in pairs if pair.get("status", "paired") == "paired"]
    if not confirmed:
        return []
    prompt = f"""Build a global Chinese-English terminology consistency review from these confirmed pairs.
Check QMS/regulatory terms, company names, role titles, abbreviations, procedure names and regulation names.
Return a JSON array. Each object must contain:
chinese_term, english_variants_found, recommended_translation, locations, severity, explanation, suggested_action.
Only report terms supported by the supplied text. Pairs:
{json.dumps(confirmed, ensure_ascii=False)}"""
    result = call_openai_compatible(
        api_key, model,
        [{"role": "system", "content": "You are a medical-device terminology consistency reviewer."},
         {"role": "user", "content": prompt}],
        base_url,
    )
    return result if isinstance(result, list) else result.get("findings", [])
