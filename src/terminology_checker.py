from __future__ import annotations

import re
from collections import Counter, defaultdict

from src.schemas import (
    BilingualPair,
    GlossaryEntry,
    PairStatus,
    Severity,
    TermLocation,
    TerminologyIssue,
)
from src.utils import stable_id


PREFERRED_TERMS = {
    "质量管理体系": "Quality Management System",
    "质量手册": "Quality Manual",
    "管理者代表": "Management Representative",
    "文件控制": "Control of Documents",
    "记录控制": "Control of Records",
    "医疗器械文档": "Medical Device File",
    "设计和开发": "Design and Development",
    "风险管理": "Risk Management",
    "纠正措施": "Corrective Action",
    "预防措施": "Preventive Action",
    "不合格品": "Nonconforming Product",
    "供应商纠正措施报告": "Supplier Corrective Action Report",
    "法规符合性负责人": "Person Responsible for Regulatory Compliance",
    "法規符合性負責人": "Person Responsible for Regulatory Compliance",
    "监控和测量": "Monitoring and Measurement",
}


def _english_candidate(chinese_term: str, english_text: str) -> str | None:
    preferred = PREFERRED_TERMS[chinese_term]
    if preferred.lower() in english_text.lower():
        return preferred
    phrase_candidates = re.findall(
        r"(?:[A-Z][A-Za-z/-]*(?:\s+|$)){1,7}", english_text
    )
    if not phrase_candidates:
        return None
    return max((p.strip() for p in phrase_candidates), key=len, default=None)


def check_terminology(
    pairs: list[BilingualPair],
) -> tuple[list[TerminologyIssue], list[GlossaryEntry]]:
    variants: dict[str, Counter[str]] = defaultdict(Counter)
    locations: dict[str, list[TermLocation]] = defaultdict(list)
    evidence_pair_ids: dict[str, list[str]] = defaultdict(list)
    source_block_ids: dict[str, set[str]] = defaultdict(set)
    for pair in pairs:
        if (
            pair.pair_status != PairStatus.confirmed
            or not pair.chinese_text
            or not pair.english_text
        ):
            continue
        for chinese, preferred in PREFERRED_TERMS.items():
            if chinese not in pair.chinese_text:
                continue
            candidate = _english_candidate(chinese, pair.english_text)
            if candidate:
                variants[chinese][candidate] += 1
            locations[chinese].append(
                TermLocation(
                    page=pair.page,
                    section=pair.section,
                    text=f"{pair.chinese_text} / {pair.english_text}",
                )
            )
            evidence_pair_ids[chinese].append(pair.pair_id)
            source_block_ids[chinese].update(pair.source_block_ids)

    issues: list[TerminologyIssue] = []
    glossary: list[GlossaryEntry] = []
    for chinese, preferred in PREFERRED_TERMS.items():
        found = variants.get(chinese, Counter())
        locs = locations.get(chinese, [])
        if not locs:
            continue
        alternatives = [variant for variant in found if variant.lower() != preferred.lower()]
        glossary.append(
            GlossaryEntry(
                chinese_term=chinese,
                preferred_english=preferred,
                alternative_english_terms=alternatives,
                frequency=len(locs),
                locations=locs[:10],
            )
        )
        if len(found) > 1 or alternatives:
            issues.append(
                TerminologyIssue(
                    term_id=stable_id("TERM", chinese),
                    chinese_term=chinese,
                    english_variants=list(found),
                    preferred_english=preferred,
                    locations=locs[:10],
                    issue="Inconsistent English translation",
                    severity=Severity.minor,
                    recommendation=f'Use "{preferred}" consistently unless context requires otherwise.',
                    evidence_pair_ids=list(dict.fromkeys(evidence_pair_ids[chinese])),
                    source_block_ids=sorted(source_block_ids[chinese]),
                )
            )
    return issues, glossary
