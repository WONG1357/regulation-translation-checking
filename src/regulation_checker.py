from __future__ import annotations

import json
from typing import Any

from .ai_client import call_openai_compatible


def review_regulations(
    references: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    api_key: str,
    model: str,
    base_url: str = "",
) -> list[dict[str, Any]]:
    if not references:
        return []
    prompt = f"""Review possible consistency between the document statements and detected regulation references.
Do not invent regulatory requirements and do not rely on unsupported memory.
If official text is unavailable, use consistency_result "Unable to verify" and say:
"Unable to verify fully because official regulation text is not available."
Allowed results: Consistent, Possibly inconsistent, Inconsistent, Outdated reference, Unable to verify.
Return a JSON array with:
regulation_name, clause_or_topic, document_page, document_section, document_statement,
regulatory_expectation, consistency_result, explanation, suggested_action, evidence_available.
References: {json.dumps(references, ensure_ascii=False)}
Paired document text: {json.dumps(pairs, ensure_ascii=False)}"""
    result = call_openai_compatible(
        api_key, model,
        [{"role": "system", "content": "You are a cautious regulatory consistency reviewer."},
         {"role": "user", "content": prompt}],
        base_url,
    )
    return result if isinstance(result, list) else result.get("findings", [])
