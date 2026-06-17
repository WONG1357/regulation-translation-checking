from __future__ import annotations

import json
import os
import re
from typing import Any

from .llm_client import LLMConfig, call_llm_json, get_llm_config
from .terminology_review import STANDARD_TERMS
from .utils import BilingualPair, normalize_text


MODAL_MAP = {
    "应": ["shall", "must", "should"],
    "必须": ["must", "shall"],
    "不得": ["shall not", "must not", "may not"],
    "可": ["may", "can"],
    "宜": ["should"],
}


def review_translation_pairs(
    pairs: list[BilingualPair],
    use_llm: bool = False,
    model: str = "gpt-4o-mini",
) -> tuple[list[dict[str, Any]], list[str]]:
    issues = deterministic_translation_checks(pairs)
    warnings: list[str] = []
    if use_llm:
        config = get_llm_config(model)
        if not config.api_key:
            warnings.append(f"{config.provider} API key not found. API translation review was skipped.")
        else:
            issues.extend(llm_translation_review(pairs, config))
    return _dedupe_issues(issues), warnings


def deterministic_translation_checks(pairs: list[BilingualPair]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for pair in pairs:
        zh = pair.chinese_text
        en = pair.english_text
        if not zh or not en:
            continue

        for cn_term, standard in STANDARD_TERMS.items():
            if cn_term in zh and not re.search(re.escape(standard), en, re.I):
                issues.append(_issue(pair, "inconsistent terminology", f"Chinese term '{cn_term}' is not translated using the recommended wording '{standard}'.", "Minor", _replace_or_append(en, standard), "Medium", "Deterministic check"))

        for modal_cn, allowed in MODAL_MAP.items():
            if modal_cn in zh and not any(modal in en.lower() for modal in allowed):
                severity = "Major" if modal_cn in {"应", "必须", "不得"} else "Minor"
                issues.append(_issue(pair, "incorrect modal verb", f"Chinese modal '{modal_cn}' usually requires one of: {', '.join(allowed)}. The English may weaken or change the obligation.", severity, en, "Medium", "Deterministic check"))

        if re.search(r"不|不得|禁止|无须|不应", zh) and not re.search(r"\b(no|not|non|without|shall not|must not|prohibit|forbid)\b", en, re.I):
            issues.append(_issue(pair, "missing information", "Chinese source contains a negative requirement, but the English does not clearly preserve the negative meaning.", "Major", en, "Medium", "Deterministic check"))

        if len(en.split()) < max(3, len(re.findall(r"[\u4e00-\u9fff]", zh)) * 0.12):
            issues.append(_issue(pair, "missing information", "English translation is much shorter than the Chinese source and may omit content.", "Major", en, "Low", "Deterministic check"))
        if len(en.split()) > max(30, len(re.findall(r"[\u4e00-\u9fff]", zh)) * 2.2):
            issues.append(_issue(pair, "extra information", "English translation is much longer than the Chinese source and may add content not present in Chinese.", "Minor", en, "Low", "Deterministic check"))
    return issues


def llm_translation_review(pairs: list[BilingualPair], config: LLMConfig) -> list[dict[str, Any]]:
    all_issues: list[dict[str, Any]] = []
    for pair in pairs:
        prompt = {
            "task": "Review Chinese-to-English translation for a medical-device regulatory/quality-management document. Chinese is controlling.",
            "requirements": [
                "Only report substantive issues; avoid trivial wording differences.",
                "Classify severity as Critical, Major, or Minor.",
                "Explain the issue and suggest corrected English.",
                "Return JSON array only.",
            ],
            "pair": {
                "location": pair.location,
                "chinese": pair.chinese_text,
                "english": pair.english_text,
            },
        }
        try:
            parsed = call_llm_json(
                config,
                [
                    {"role": "system", "content": "You are a bilingual regulatory translation reviewer for medical device quality systems."},
                    {"role": "user", "content": json.dumps(prompt, ensure_ascii=False)},
                ],
                expected="array",
            )
        except Exception:
            continue
        for item in parsed if isinstance(parsed, list) else []:
            all_issues.append({
                "page number or section": pair.location,
                "Chinese source text": pair.chinese_text,
                "existing English translation": pair.english_text,
                "issue type": item.get("issue_type", "translation accuracy"),
                "explanation of the problem": item.get("explanation", ""),
                "severity": item.get("severity", "Major"),
                "suggested corrected English wording": item.get("suggested_corrected_english", pair.english_text),
                "confidence level": item.get("confidence", "Medium"),
                "review source": f"{config.provider} API",
            })
    return all_issues


def _issue(pair: BilingualPair, issue_type: str, explanation: str, severity: str, suggestion: str, confidence: str, source: str) -> dict[str, Any]:
    return {
        "page number or section": pair.location,
        "Chinese source text": pair.chinese_text,
        "existing English translation": pair.english_text,
        "issue type": issue_type,
        "explanation of the problem": explanation,
        "severity": severity,
        "suggested corrected English wording": suggestion,
        "confidence level": confidence,
        "review source": source,
    }


def _replace_or_append(english: str, standard: str) -> str:
    return english if standard.lower() in english.lower() else f"{english} [Use term: {standard}]"


def _get_openai_key() -> str | None:
    return get_llm_config().api_key


def _extract_json(content: str) -> str:
    match = re.search(r"```(?:json)?\s*(.*?)```", content, re.S)
    return match.group(1).strip() if match else content.strip()


def _dedupe_issues(issues: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str]] = set()
    unique: list[dict[str, Any]] = []
    for issue in issues:
        key = (
            normalize_text(str(issue.get("page number or section", ""))),
            normalize_text(str(issue.get("Chinese source text", "")))[:80],
            normalize_text(str(issue.get("issue type", ""))),
        )
        if key not in seen:
            seen.add(key)
            unique.append(issue)
    return unique
