from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz import fuzz

from .utils import BilingualPair, TextBlock, contains_chinese, normalize_text


STANDARD_TERMS: dict[str, str] = {
    "质量管理体系": "Quality Management System",
    "质量手册": "Quality Manual",
    "管理者代表": "Management Representative",
    "文件控制": "Document Control",
    "纠正和预防措施": "Corrective and Preventive Action",
    "纠正措施": "Corrective Action",
    "预防措施": "Preventive Action",
    "不合格品": "nonconforming product",
    "医疗器械": "medical device",
    "法规要求": "regulatory requirements",
    "设计和开发": "design and development",
    "生产": "production",
    "采购": "purchasing",
    "监控和测量": "monitoring and measurement",
    "管理评审": "management review",
    "内部审核": "internal audit",
    "风险管理": "risk management",
    "顾客反馈": "customer feedback",
    "可追溯性": "traceability",
}


def review_terminology(blocks: list[TextBlock], pairs: list[BilingualPair]) -> list[dict[str, object]]:
    issues: list[dict[str, object]] = []
    term_observations: dict[str, list[dict[str, str]]] = defaultdict(list)

    candidate_terms = set(STANDARD_TERMS) | extract_repeated_chinese_terms(blocks)
    for term in candidate_terms:
        for pair in pairs:
            if term in pair.chinese_text:
                translation = infer_translation_fragment(term, pair.english_text)
                if translation:
                    term_observations[term].append({
                        "translation": translation,
                        "location": pair.location,
                        "english": pair.english_text,
                    })

    for term, observations in term_observations.items():
        translations = [obs["translation"] for obs in observations]
        normalized = defaultdict(list)
        for translation in translations:
            normalized[_normalize_en_term(translation)].append(translation)
        standard = STANDARD_TERMS.get(term) or _choose_recommended_translation(translations)
        standard_key = _normalize_en_term(standard)
        variant_keys = list(normalized)

        inconsistent = len(variant_keys) > 1
        deviates_from_standard = standard_key not in variant_keys and term in STANDARD_TERMS
        fuzzy_low = any(fuzz.token_set_ratio(key, standard_key) < 72 for key in variant_keys) if standard else False

        if inconsistent or deviates_from_standard or fuzzy_low:
            examples = "; ".join(obs["location"] for obs in observations[:3])
            issues.append({
                "Chinese term": term,
                "English translations found": "; ".join(sorted(set(translations))),
                "number of occurrences": len(observations),
                "example locations": examples,
                "recommended standard English translation": standard,
                "explanation": "The same Chinese quality/regulatory term appears with different or non-standard English wording. Use one controlled translation unless context clearly requires otherwise.",
            })
    return issues


def extract_repeated_chinese_terms(blocks: list[TextBlock]) -> set[str]:
    counts: defaultdict[str, int] = defaultdict(int)
    for block in blocks:
        if not contains_chinese(block.text):
            continue
        for token in re.findall(r"[\u4e00-\u9fff]{3,10}", block.text):
            if len(token) < 3:
                continue
            if any(stop in token for stop in ("公司", "文件", "以及", "进行", "应当")) and len(token) <= 4:
                continue
            counts[token] += 1
    return {term for term, count in counts.items() if count >= 3}


def infer_translation_fragment(term: str, english_text: str) -> str | None:
    standard = STANDARD_TERMS.get(term)
    clean = normalize_text(english_text)
    if not clean:
        return None
    if standard and re.search(re.escape(standard), clean, re.I):
        return standard
    noun_phrases = re.findall(r"\b[A-Za-z][A-Za-z\-]*(?:\s+(?:and\s+)?[A-Za-z][A-Za-z\-]*){0,5}\b", clean)
    if not noun_phrases:
        return clean[:80]
    if standard:
        return max(noun_phrases, key=lambda phrase: fuzz.token_set_ratio(phrase.lower(), standard.lower()))
    return max(noun_phrases, key=len)


def _normalize_en_term(term: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", term.lower()).strip()


def _choose_recommended_translation(translations: list[str]) -> str:
    return max(set(translations), key=translations.count) if translations else ""
