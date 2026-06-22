from __future__ import annotations

import re
from typing import Any


PATTERNS = [
    ("BS EN ISO 13485", r"\bBS\s+EN\s+ISO\s*13485(?::\d{4})?\b"),
    ("ISO 13485", r"\bISO\s*13485(?::\d{4})?\b"),
    ("EU MDD 93/42/EEC", r"\b(?:MDD|93/42/EEC|Directive\s+93/42/EEC)\b"),
    ("EU MDR Regulation (EU) 2017/745", r"\b(?:MDR|Regulation\s*\(EU\)\s*2017/745|2017/745)\b"),
    ("21 CFR Part 820", r"\b21\s*CFR\s*(?:Part\s*)?820\b"),
    ("Canadian MDR", r"\b(?:Canadian\s+MDR|SOR/98-282|Medical\s+Devices\s+Regulations)\b"),
    ("CMDCAS", r"\bCMDCAS\b"),
    ("YY/T 0287", r"\bYY/T\s*0287(?:[-:]\d{4})?\b"),
    ("YY0033", r"\bYY\s*0033(?:[-:]\d{4})?\b"),
    ("China medical device regulations", r"(?:医疗器械监督管理条例|NMPA|国家药监局)"),
]


def detect_regulations(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for block in blocks:
        for name, pattern in PATTERNS:
            for match in re.finditer(pattern, block["text"], re.I):
                wording = match.group(0)
                year_match = re.search(r"(19|20)\d{2}", wording)
                outdated = bool(re.search(r"\bMDD\b|93/42/EEC|CMDCAS", wording, re.I))
                findings.append({
                    "regulation_name": name,
                    "version/year": year_match.group(0) if year_match else "",
                    "page": block["page"],
                    "section": block.get("section"),
                    "exact_document_wording": wording,
                    "surrounding_context": block["text"],
                    "reference_status": "possibly outdated" if outdated else "not determined",
                })
    return findings
