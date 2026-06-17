from __future__ import annotations

import re

from .utils import TextBlock, contains_chinese, contains_english


REGULATION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("ISO 13485", re.compile(r"\b(?:BS\s+EN\s+)?ISO\s*13485(?::\d{4})?\b", re.I)),
    ("BS EN ISO 13485", re.compile(r"\bBS\s+EN\s+ISO\s*13485(?::\d{4})?\b", re.I)),
    ("EU MDD 93/42/EEC", re.compile(r"\b(?:MDD|93/42/EEC|Directive\s+93/42/EEC)\b", re.I)),
    ("EU MDR Regulation (EU) 2017/745", re.compile(r"\b(?:MDR|Regulation\s*\(EU\)\s*2017/745|2017/745)\b", re.I)),
    ("21 CFR Part 820", re.compile(r"\b21\s*CFR\s*(?:Part\s*)?820\b", re.I)),
    ("Canadian MDR", re.compile(r"\b(?:Canadian\s+MDR|SOR/98-282|Medical\s+Devices\s+Regulations)\b", re.I)),
    ("YY/T 0287", re.compile(r"\bYY/T\s*0287(?:[-:]\d{4})?\b", re.I)),
    ("YY0033", re.compile(r"\bYY\s*0033(?:[-:]\d{4})?\b", re.I)),
    ("China medical device regulations", re.compile(r"(?:医疗器械监督管理条例|医疗器械注册|中国.*医疗器械|NMPA|国家药监局)", re.I)),
]


def detect_regulatory_references(blocks: list[TextBlock]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    seen: set[tuple[str, str, str]] = set()
    for block in blocks:
        for standard_name, pattern in REGULATION_PATTERNS:
            for match in pattern.finditer(block.text):
                language = _language_of_reference(block.text)
                key = (standard_name, match.group(0), block.location_label())
                if key in seen:
                    continue
                seen.add(key)
                rows.append({
                    "regulation / standard name": standard_name,
                    "document number": match.group(0),
                    "section where it appears": block.location_label(),
                    "language": language,
                    "context": block.text,
                })
    return rows


def _language_of_reference(text: str) -> str:
    if contains_chinese(text) and contains_english(text):
        return "Chinese and English"
    if contains_chinese(text):
        return "Chinese"
    if contains_english(text):
        return "English"
    return "Unknown"
