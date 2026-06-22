from __future__ import annotations

import json
import re
from typing import Any

from .llm_client import (
    LLMAuthenticationError,
    LLMConfig,
    call_llm_json,
    format_api_error,
    get_llm_config,
    is_authentication_error,
    is_configuration_error,
)
from .utils import BilingualPair, normalize_text


def review_paragraph_pairs_with_api(
    pairs: list[BilingualPair],
    model: str,
    batch_size: int = 8,
    config: LLMConfig | None = None,
    progress_callback=None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Call the configured LLM API to review detected bilingual paragraph pairs.

    This returns one row per reviewed pair, including "OK" rows. Translation
    issue tables can then filter to rows where the model found a problem.
    """
    warnings: list[str] = []
    config = config or get_llm_config(model)
    if not config.api_key:
        return [], [f"{config.provider} API key not found. Paragraph API processing was skipped."]
    if not pairs:
        return [], ["No bilingual paragraph pairs were available for API processing."]

    rows: list[dict[str, Any]] = []
    total = len(pairs)
    for start in range(0, len(pairs), batch_size):
        batch = pairs[start : start + batch_size]
        payload = {
            "task": "Review bilingual Chinese-English regulatory/quality-management paragraph pairs. Chinese is the controlling source.",
            "rules": [
                "Return one JSON object for every input pair, even if no issue is found.",
                "Do not over-report trivial style differences.",
                "Compare the Chinese controlling meaning against the English translation in plain language.",
                "Flag wrong meaning, missing information, extra information, weakened regulatory obligation, wrong modal verbs, terminology inconsistency, and unclear English.",
                "Severity must be Critical, Major, Minor, or None.",
                "Confidence must be High, Medium, or Low.",
            ],
            "output_schema": {
                "pair_id": "string",
                "status": "OK or Issue",
                "comparison_summary": "plain-language comparison of Chinese source meaning and English translation meaning",
                "issue_type": "string",
                "severity": "Critical, Major, Minor, or None",
                "explanation": "string",
                "suggested_corrected_english": "string",
                "confidence": "High, Medium, or Low",
            },
            "pairs": [
                {
                    "pair_id": pair.pair_id,
                    "location": pair.location,
                    "chinese_source": pair.chinese_text,
                    "english_translation": pair.english_text,
                }
                for pair in batch
            ],
        }
        try:
            parsed = call_llm_json(
                config,
                [
                    {
                        "role": "system",
                        "content": "You are a bilingual reviewer for medical-device regulatory and quality-management documents.",
                    },
                    {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
                ],
                expected="array",
            )
        except Exception as exc:
            warning = f"API paragraph review failed: {format_api_error(config.provider, exc)}"
            if warning not in warnings:
                warnings.append(warning)
            if is_authentication_error(exc) or is_configuration_error(exc):
                break
            continue

        by_pair_id = {pair.pair_id: pair for pair in batch}
        for item in parsed if isinstance(parsed, list) else []:
            pair = by_pair_id.get(str(item.get("pair_id")))
            if not pair:
                continue
            rows.append(
                {
                    "pair_id": pair.pair_id,
                    "location": pair.location,
                    "Chinese source text": pair.chinese_text,
                    "existing English translation": pair.english_text,
                    "API status": item.get("status", "Issue"),
                    "comparison summary": item.get("comparison_summary", ""),
                    "issue type": item.get("issue_type", ""),
                    "severity": item.get("severity", "None"),
                    "explanation of the problem": item.get("explanation", ""),
                    "suggested corrected English wording": item.get("suggested_corrected_english", pair.english_text),
                    "confidence level": item.get("confidence", "Medium"),
                    "provider": config.provider,
                    "model": config.model,
                }
            )
        if progress_callback:
            progress_callback(min(start + len(batch), total), total)
    return rows, warnings


def api_rows_to_translation_issues(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for row in rows:
        status = str(row.get("API status", "")).lower()
        severity = str(row.get("severity", "None"))
        if status == "ok" or severity.lower() == "none":
            continue
        issues.append(
            {
                "page number or section": row.get("location", ""),
                "Chinese source text": row.get("Chinese source text", ""),
                "existing English translation": row.get("existing English translation", ""),
                "comparison summary": row.get("comparison summary", ""),
                "issue type": row.get("issue type", "translation accuracy"),
                "explanation of the problem": row.get("explanation of the problem", ""),
                "severity": severity,
                "suggested corrected English wording": row.get("suggested corrected English wording", ""),
                "confidence level": row.get("confidence level", "Medium"),
                "review source": f"{row.get('provider', 'API')} API",
            }
        )
    return issues


def _extract_json(content: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    return normalize_text(match.group(1)) if match else normalize_text(content)
