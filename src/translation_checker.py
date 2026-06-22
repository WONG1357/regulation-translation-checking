from __future__ import annotations

import json
from typing import Any, Callable

from .ai_client import call_openai_compatible


def check_translations(
    pairs: list[dict[str, Any]],
    block_by_id: dict[str, dict[str, Any]],
    api_key: str,
    model: str,
    base_url: str = "",
    progress: Callable[[int, int], None] | None = None,
) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    confirmed = [pair for pair in pairs if pair.get("status", "paired") == "paired"]
    for index, pair in enumerate(confirmed, start=1):
        first_id = (pair.get("chinese_block_ids") or pair.get("english_block_ids") or [""])[0]
        block = block_by_id.get(first_id, {})
        prompt = f"""Evaluate this Chinese-English translation pair. Chinese is controlling.
Check missing/added meaning, mistranslation, grammar, professional wording, and medical-device/QMS terminology.
Return one JSON object only with keys:
pair_id, accuracy_result (pass/issue/uncertain), issue_type
(mistranslation/missing_meaning/added_meaning/grammar/terminology/style/none),
severity (Critical/Major/Minor/Suggestion/None), explanation, recommended_translation.
Pair: {json.dumps(pair, ensure_ascii=False)}"""
        result = call_openai_compatible(
            api_key, model,
            [{"role": "system", "content": "You are a bilingual quality and regulatory translation reviewer."},
             {"role": "user", "content": prompt}],
            base_url,
        )
        findings.append({
            "pair_id": pair["pair_id"],
            "page": block.get("page"),
            "section": block.get("section"),
            "chinese_text": pair.get("chinese_text", ""),
            "english_text": pair.get("english_text", ""),
            "accuracy_result": result.get("accuracy_result", "uncertain"),
            "issue_type": result.get("issue_type", "none"),
            "severity": result.get("severity", "None"),
            "explanation": result.get("explanation", ""),
            "recommended_translation": result.get("recommended_translation", ""),
        })
        if progress:
            progress(index, len(confirmed))
    return findings
