from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

from src.schemas import DetectedRegulation, ExtractedBlock, RegulationEvidence
from src.utils import compact_context

ReferenceType = Literal["standard", "regulation", "guidance", "program"]


@dataclass(frozen=True)
class RegulationPattern:
    name: str
    aliases: tuple[str, ...]
    reference_type: ReferenceType
    pattern: re.Pattern[str]
    version_pattern: re.Pattern[str] | None = None


@dataclass(frozen=True)
class EvidenceCandidate:
    evidence: RegulationEvidence
    confidence: float
    source_priority: int
    source_order: int


YEAR_VERSION = re.compile(r"[:：-]\s*((?:19|20)\d{2})\b", re.I)

PATTERNS = (
    RegulationPattern(
        "ISO 13485",
        ("ISO-13485", "ISO13485", "EN ISO 13485", "BS EN ISO 13485"),
        "standard",
        re.compile(
            r"\b(?:(?:BS\s+EN|EN|BS)\s+)?ISO\s*[- ]?\s*13485"
            r"(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "ISO 14971",
        ("ISO-14971", "ISO14971", "EN ISO 14971"),
        "standard",
        re.compile(
            r"\b(?:EN\s+)?ISO\s*[- ]?\s*14971"
            r"(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "ISO 62366-1",
        (
            "IEC 62366-1",
            "EN IEC 62366-1",
            "BS EN 62366-1",
            "ISO-62366-1",
        ),
        "standard",
        re.compile(
            r"\b(?:(?:BS\s+)?EN(?:\s+IEC)?|IEC|ISO)\s*[- ]?\s*62366"
            r"\s*[-‐‑–— ]\s*1"
            r"(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "ISO/TR 20416",
        ("ISO TR 20416", "ISO-TR 20416"),
        "guidance",
        re.compile(
            r"\bISO\s*/?\s*TR\s*[- ]?\s*20416"
            r"(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "ISO 14155",
        ("ISO-14155", "ISO14155", "EN ISO 14155"),
        "standard",
        re.compile(
            r"\b(?:EN\s+)?ISO\s*[- ]?\s*14155"
            r"(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "EU MDR Regulation (EU) 2017/745",
        ("EU MDR", "MDR 2017/745", "Regulation (EU) 2017/745"),
        "regulation",
        re.compile(
            r"(?:\bEU\s+MDR\s+)?Regulation\s*\(EU\)\s*(?:No\.?\s*)?2017/745\b"
            r"|\bMDR\s+2017/745\b|\bEU\s+MDR\b",
            re.I,
        ),
        re.compile(r"(2017/745)", re.I),
    ),
    RegulationPattern(
        "EU MDD 93/42/EEC",
        ("EU MDD", "MDD", "Directive 93/42/EEC"),
        "regulation",
        re.compile(
            r"(?:\bEU\s+MDD\s+)?(?:Directive\s*)?93/42/EEC\b"
            r"|\bMDD\s+93/42/EEC\b|\bEU\s+MDD\b",
            re.I,
        ),
        re.compile(r"(93/42/EEC)", re.I),
    ),
    RegulationPattern(
        "21 CFR Part 807",
        ("21 CFR 807", "21 CFR Part 807"),
        "regulation",
        re.compile(
            r"\b21\s+CFR\s+(?:Parts?\s*)?"
            r"(?:807\s*(?:and|&|/)\s*820|820\s*(?:and|&|/)\s*807)\b"
            r"|\b21\s+CFR(?:\s+Part)?\s*807(?:\.\d+)?\b",
            re.I,
        ),
    ),
    RegulationPattern(
        "21 CFR Part 820",
        ("21 CFR 820", "Quality System Regulation", "QSR"),
        "regulation",
        re.compile(
            r"\b21\s+CFR\s+(?:Parts?\s*)?"
            r"(?:807\s*(?:and|&|/)\s*820|820\s*(?:and|&|/)\s*807)\b"
            r"|\b21\s+CFR(?:\s+Part)?\s*820(?:\.\d+)?\b"
            r"|\bQuality System Regulations?\b|\bQSR\b",
            re.I,
        ),
    ),
    RegulationPattern(
        "Canadian Medical Devices Regulations",
        ("Canadian MDR", "SOR/98-282"),
        "regulation",
        re.compile(
            r"\bCanadian Medical Devices(?: Regulations?)?\b(?:\s*\(?SOR/98-282\)?)?"
            r"|\bSOR/98-282\b|\bCanadian\s+MDR\b",
            re.I,
        ),
        re.compile(r"(SOR/98-282)", re.I),
    ),
    RegulationPattern(
        "Canadian Medical Devices Regulations",
        ("CMDCAS",),
        "program",
        re.compile(r"\bCMDCAS\b", re.I),
    ),
    RegulationPattern(
        "China Medical Device Regulations",
        (
            "China Medical Devices Act",
            "医疗器械监督管理条例",
            "医疗器械生产质量管理规范",
        ),
        "regulation",
        re.compile(
            r"医疗器械监督管理条例(?:[（(]\s*国务院令第?\s*\d+\s*号\s*[）)])?"
            r"|医疗器械生产质量管理规范"
            r"|\bChina Medical Devices Act\b"
            r"|\bRegulations? (?:on|for) the Supervision and Administration of Medical Devices\b"
            r"(?:\s*\(State Council (?:Order|Decree) No\.?\s*\d+\))?"
            r"|国务院令第?\s*\d+\s*号",
            re.I,
        ),
        re.compile(
            r"(?:国务院令第?\s*|State Council (?:Order|Decree) No\.?\s*)"
            r"(\d+)(?:\s*号)?",
            re.I,
        ),
    ),
    RegulationPattern(
        "YY/T 0033",
        ("YYT 0033", "YY 0033", "无菌医疗器械生产管理规范"),
        "standard",
        re.compile(
            r"YY\s*/?\s*T?\s*0033(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b"
            r"|无菌医疗器械生产管理规范",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "YY/T 0287",
        ("YYT 0287", "YY 0287"),
        "standard",
        re.compile(
            r"YY\s*/?\s*T?\s*0287(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "YY/T 0316",
        ("YYT 0316", "YY 0316"),
        "standard",
        re.compile(
            r"YY\s*/?\s*T?\s*0316(?:\s*[:：-]\s*(?:(?:19|20)\d{2}))?\b",
            re.I,
        ),
        YEAR_VERSION,
    ),
    RegulationPattern(
        "Hong Kong MDACS",
        ("MDACS", "Medical Device Administrative Control System"),
        "program",
        re.compile(
            r"(?:\bHong Kong\s+)?\bMedical Device Administrative Control System\b"
            r"(?:\s*\(MDACS\))?|\bMDACS\b|醫療儀器行政管理制度|医疗器械行政管理制度"
            r"|醫療儀器的規管|医疗仪器的规管",
            re.I,
        ),
    ),
    RegulationPattern(
        "Hong Kong GN guidance",
        ("MDACS GN", "GN guidance"),
        "guidance",
        re.compile(r"\bGN[-\s]?\d{1,2}(?:[-/]\d+)?\b", re.I),
        re.compile(r"\b(GN[-\s]?\d{1,2}(?:[-/]\d+)?)\b", re.I),
    ),
    RegulationPattern(
        "MDCG guidance",
        ("MDCG",),
        "guidance",
        re.compile(r"\bMDCG(?:\s+\d{4}[-/]\d+(?:\s+Rev\.?\s*\d+)?)?\b", re.I),
        re.compile(r"\bMDCG\s+(\d{4}[-/]\d+(?:\s+Rev\.?\s*\d+)?)\b", re.I),
    ),
    RegulationPattern(
        "MEDDEV guidance",
        ("MEDDEV",),
        "guidance",
        re.compile(
            r"\bMEDDEV(?:\s+\d+(?:\.\d+)?(?:/|[-‐‑–—])\d+"
            r"(?:\s+rev\.?\s*\d+)?)?\b",
            re.I,
        ),
        re.compile(
            r"\bMEDDEV\s+(\d+(?:\.\d+)?(?:/|[-‐‑–—])\d+"
            r"(?:\s+rev\.?\s*\d+)?)\b",
            re.I,
        ),
    ),
    RegulationPattern(
        "FDA UDI/GUDID",
        ("FDA UDI", "UDI", "GUDID", "Unique Device Identification System"),
        "program",
        re.compile(
            r"\b(?:FDA\s+)?(?:Unique\s+Device\s+Identification(?:\s+System)?"
            r"|UDI(?:\s*/\s*GUDID)?|GUDID)\b",
            re.I,
        ),
    ),
    RegulationPattern(
        "Korea Medical Devices Act",
        ("MFDS Medical Devices Act",),
        "regulation",
        re.compile(r"\bMFDS\b.*?Medical Devices Act|\bKorea.*?Medical Devices Act", re.I),
    ),
)

PROVISION_PATTERNS = (
    re.compile(
        r"\b21\s+CFR(?:\s+Part)?\s+(?:§+\s*)?\d{3}\.\d+"
        r"(?:\([A-Za-z0-9]+\))*",
        re.I,
    ),
    re.compile(r"§+\s*\d{3}\.\d+(?:\([A-Za-z0-9]+\))*", re.I),
    re.compile(
        r"\bArticles?\s+\d+[A-Za-z]?(?:\([A-Za-z0-9]+\))*"
        r"(?:\s*(?:,|and)\s*\d+[A-Za-z]?(?:\([A-Za-z0-9]+\))*)*",
        re.I,
    ),
    re.compile(
        r"\bAnnex(?:es)?\s+[IVXLCDM]+(?:\s*(?:,|and)\s*[IVXLCDM]+)*\b",
        re.I,
    ),
    re.compile(
        r"\bClauses?\s+\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*"
        r"(?:\s*(?:,|and)\s*\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*)*",
        re.I,
    ),
)


def _extract_version(spec: RegulationPattern, citation: str) -> str:
    if spec.version_pattern is None:
        return "unknown"
    match = spec.version_pattern.search(citation)
    return match.group(1).strip() if match else "unknown"


def _expand_provision(text: str) -> list[str]:
    normalized = " ".join(text.split())
    grouped = re.fullmatch(
        r"(Articles?|Annex(?:es)?|Sections?|Clauses?)\s+(.+)",
        normalized,
        re.I,
    )
    if not grouped:
        return [normalized]
    prefix = grouped.group(1).casefold()
    singular = {
        "article": "Article",
        "articles": "Article",
        "annex": "Annex",
        "annexes": "Annex",
        "section": "Section",
        "sections": "Section",
        "clause": "Clause",
        "clauses": "Clause",
    }[prefix]
    token_pattern = (
        r"\b[IVXLCDM]+\b"
        if singular == "Annex"
        else r"\d+(?:\.\d+)*[A-Za-z]?(?:\([A-Za-z0-9]+\))*"
    )
    return [f"{singular} {token}" for token in re.findall(token_pattern, grouped.group(2), re.I)]


def _provision_matches(evidence_text: str) -> list[tuple[int, int, list[str]]]:
    matches: list[tuple[int, int, str]] = []
    for pattern in PROVISION_PATTERNS:
        matches.extend(
            (match.start(), match.end(), match.group(0).strip())
            for match in pattern.finditer(evidence_text)
        )
    matches.sort(key=lambda item: (item[0], -(item[1] - item[0])))

    provisions: list[tuple[int, int, list[str]]] = []
    selected_ranges: list[tuple[int, int]] = []
    seen: set[str] = set()
    for start, end, text in matches:
        if any(start >= selected_start and end <= selected_end for selected_start, selected_end in selected_ranges):
            continue
        expanded = _expand_provision(text)
        key = "\x1f".join(item.casefold() for item in expanded)
        if key in seen:
            continue
        provisions.append((start, end, expanded))
        selected_ranges.append((start, end))
        seen.add(key)
    return provisions


def _span_distance(start: int, end: int, other_start: int, other_end: int) -> int:
    if end <= other_start:
        return other_start - end
    if start >= other_end:
        return start - other_end
    return 0


def _provisions_for_match(
    evidence_text: str,
    match: re.Match[str],
    regulation_spans: list[tuple[int, int]],
) -> list[str]:
    provisions: list[str] = []
    seen: set[str] = set()
    current_span = (match.start(), match.end())
    for start, end, expanded in _provision_matches(evidence_text):
        distances = [
            _span_distance(start, end, regulation_start, regulation_end)
            for regulation_start, regulation_end in regulation_spans
        ]
        current_distance = _span_distance(start, end, *current_span)
        if current_distance != min(distances, default=current_distance):
            continue
        for provision in expanded:
            key = provision.casefold()
            if key not in seen:
                provisions.append(provision)
                seen.add(key)
    return provisions


def _evidence_context(block: ExtractedBlock) -> str:
    context = [part for part in (block.context_before, block.text, block.context_after) if part]
    return compact_context("\n".join(context), 1200)


def _source_priority(block: ExtractedBlock) -> int:
    block_type = getattr(block.block_type, "value", block.block_type)
    return 0 if block_type == "change_history" else 1


def detect_regulations(blocks: list[ExtractedBlock]) -> list[DetectedRegulation]:
    candidates_by_name: dict[str, list[EvidenceCandidate]] = {}
    aliases_by_name: dict[str, set[str]] = {}
    for spec in PATTERNS:
        aliases_by_name.setdefault(spec.name, set()).update(spec.aliases)
    seen_mentions: set[tuple[str, str, int, int]] = set()
    source_order = 0

    for block in blocks:
        if block.ignored:
            continue
        block_matches = [
            (spec, match)
            for spec in PATTERNS
            for match in spec.pattern.finditer(block.text)
        ]
        regulation_spans = sorted({(match.start(), match.end()) for _, match in block_matches})
        for spec, match in block_matches:
            mention_key = (spec.name, block.block_id, match.start(), match.end())
            if mention_key in seen_mentions:
                continue
            seen_mentions.add(mention_key)
            citation = match.group(0).strip()
            version = _extract_version(spec, citation)
            evidence = RegulationEvidence(
                exact_citation=citation,
                reference_type=spec.reference_type,
                version=version,
                cited_provisions=_provisions_for_match(
                    block.text, match, regulation_spans
                ),
                source_block_id=block.block_id,
                page=block.page,
                company_document_section=block.section,
                evidence_text=block.text,
                evidence_context=_evidence_context(block),
            )
            confidence = 0.98 if spec.name.casefold() in citation.casefold() else 0.94
            candidates_by_name.setdefault(spec.name, []).append(
                EvidenceCandidate(
                    evidence=evidence,
                    confidence=confidence,
                    source_priority=_source_priority(block),
                    source_order=source_order,
                )
            )
            source_order += 1

    detected: list[DetectedRegulation] = []
    for name, candidates in candidates_by_name.items():
        representative = max(
            candidates,
            key=lambda candidate: (
                candidate.source_priority,
                candidate.evidence.version != "unknown",
                candidate.confidence,
                -candidate.source_order,
            ),
        )
        evidence = representative.evidence
        detected.append(
            DetectedRegulation(
                name=name,
                version=evidence.version,
                evidence_text=evidence.evidence_text,
                page=evidence.page,
                section=evidence.company_document_section,
                confidence=representative.confidence,
                aliases=sorted(aliases_by_name[name]),
                evidence=[candidate.evidence for candidate in candidates],
            )
        )
    return sorted(detected, key=lambda item: (item.page, item.name))
