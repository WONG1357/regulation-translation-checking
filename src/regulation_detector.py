from __future__ import annotations

import re
from dataclasses import dataclass

from src.ai_client import AIClient
from src.schemas import DetectedRegulation, ExtractedBlock
from src.schemas import RegulationSelectionResponse
from src.utils import compact_context, read_prompt


@dataclass(frozen=True)
class RegulationPattern:
    name: str
    aliases: tuple[str, ...]
    pattern: re.Pattern[str]
    version_pattern: re.Pattern[str] | None = None


PATTERNS = (
    RegulationPattern(
        "ISO 13485",
        ("ISO-13485", "ISO13485"),
        re.compile(r"\b(?:BS\s+EN\s+)?ISO[-\s]?13485\b", re.I),
        re.compile(r"ISO[-\s]?13485\s*[:：-]?\s*(20\d{2})", re.I),
    ),
    RegulationPattern(
        "BS EN ISO 13485",
        ("EN ISO 13485",),
        re.compile(r"\bBS\s+EN\s+ISO\s*[- ]?13485\b", re.I),
        re.compile(r"BS\s+EN\s+ISO\s*13485\s*[:：-]?\s*(20\d{2})", re.I),
    ),
    RegulationPattern(
        "EU MDR Regulation (EU) 2017/745",
        ("EU MDR", "MDR 2017/745"),
        re.compile(r"\bEU\s+MDR\b|Regulation\s*\(EU\)\s*2017/745", re.I),
        re.compile(r"(2017/745)", re.I),
    ),
    RegulationPattern(
        "EU MDD 93/42/EEC",
        ("EU MDD", "MDD"),
        re.compile(r"\bEU\s+MDD\b|(?:Directive\s*)?93/42/EEC", re.I),
        re.compile(r"(93/42/EEC)", re.I),
    ),
    RegulationPattern(
        "21 CFR Part 820",
        ("21 CFR 820", "Quality System Regulation", "QSR"),
        re.compile(r"\b21\s+CFR(?:\s+Part)?\s*820\b|Quality System Regulations?", re.I),
    ),
    RegulationPattern(
        "Canadian Medical Devices Regulations",
        ("Canadian MDR", "CMDCAS"),
        re.compile(r"\bCanadian\s+MDR\b|\bCMDCAS\b|Canadian Medical Devices", re.I),
    ),
    RegulationPattern(
        "China Medical Device Regulations",
        ("China Medical Devices Act", "医疗器械监督管理条例", "医疗器械生产质量管理规范"),
        re.compile(
            r"China Medical Devices Act|医疗器械监督管理条例|医疗器械生产质量管理规范|国务院令第?\s*\d+\s*号",
            re.I,
        ),
    ),
    RegulationPattern(
        "YY/T 0287",
        ("YYT 0287",),
        re.compile(r"YY\s*/?\s*T\s*0287", re.I),
    ),
    RegulationPattern(
        "YY 0033",
        ("YY0033", "无菌医疗器械生产管理规范"),
        re.compile(r"YY\s*0033|无菌医疗器械生产管理规范", re.I),
    ),
    RegulationPattern(
        "Hong Kong Medical Device Administrative Control System",
        ("MDACS", "GN-02"),
        re.compile(r"\bMDACS\b|\bGN-0?2\b|醫療儀器的規管|医疗仪器的规管", re.I),
    ),
    RegulationPattern(
        "Korea Medical Devices Act",
        ("MFDS Medical Devices Act",),
        re.compile(r"\bMFDS\b.*Medical Devices Act|Korea.*Medical Devices Act", re.I),
    ),
)


def detect_regulations(blocks: list[ExtractedBlock]) -> list[DetectedRegulation]:
    detected: dict[str, DetectedRegulation] = {}
    for block in blocks:
        if block.ignored:
            continue
        for spec in PATTERNS:
            match = spec.pattern.search(block.text)
            if not match:
                continue
            version = "unknown"
            if spec.version_pattern:
                version_match = spec.version_pattern.search(block.text)
                if version_match:
                    version = version_match.group(1)
            confidence = 0.98 if spec.name.lower() in block.text.lower() else 0.9
            existing = detected.get(spec.name)
            candidate = DetectedRegulation(
                name=spec.name,
                version=version,
                evidence_text=compact_context(block.text, 420),
                page=block.page,
                section=block.section,
                confidence=confidence,
                aliases=list(spec.aliases),
            )
            if not existing or candidate.confidence > existing.confidence:
                detected[spec.name] = candidate
            elif existing.version == "unknown" and version != "unknown":
                existing.version = version
    return sorted(detected.values(), key=lambda item: (item.page, item.name))


def select_primary_regulation(
    regulations: list[DetectedRegulation],
    blocks: list[ExtractedBlock],
    client: AIClient | None = None,
    *,
    prompt_path: str = "prompts/select_target_regulation.md",
) -> tuple[list[DetectedRegulation], str | None]:
    """Return the one regulation most likely to be the governing review target.

    AI is used when available because the strongest match depends on document type,
    evidence context, and whether references are primary standards or market-specific
    supporting references. Dry-run falls back to a deterministic quality-manual ranking.
    """
    if len(regulations) <= 1:
        return regulations, None

    if client:
        prompt = read_prompt(prompt_path)
        evidence_blocks = [
            {
                "block_id": block.block_id,
                "page": block.page,
                "section": block.section,
                "block_type": block.block_type,
                "text": compact_context(block.text, 520),
            }
            for block in blocks
            if not block.ignored
            and (
                "quality manual" in block.text.lower()
                or "质量手册" in block.text
                or "quality management system" in block.text.lower()
                or "质量管理体系" in block.text
                or any(reg.name.lower() in block.text.lower() for reg in regulations)
                or any(
                    alias.lower() in block.text.lower()
                    for reg in regulations
                    for alias in reg.aliases
                )
            )
        ][:40]
        payload = {
            "detected_regulations": [
                reg.model_dump(mode="json") for reg in regulations
            ],
            "document_evidence_blocks": evidence_blocks,
            "selection_rule": (
                "Select exactly one regulation/standard that is most likely the primary "
                "review target for this uploaded document. Prefer a QMS standard when "
                "the document is a quality manual; treat market regulations as secondary "
                "unless the document scope clearly indicates they are the primary target."
            ),
        }
        response = client.request_json(prompt, payload, RegulationSelectionResponse)
        selected = next(
            (
                reg
                for reg in regulations
                if reg.name == response.selected_name
                or response.selected_name.lower() in {
                    reg.name.lower(),
                    *(alias.lower() for alias in reg.aliases),
                }
            ),
            None,
        )
        if selected:
            selected.confidence = min(1.0, max(selected.confidence, response.confidence))
            selected.evidence_text = (
                f"{selected.evidence_text}\n\nAI target-selection reason: {response.reason}"
            )
            return [selected], response.reason

    priority = [
        "ISO 13485",
        "BS EN ISO 13485",
        "YY/T 0287",
        "21 CFR Part 820",
        "EU MDR Regulation (EU) 2017/745",
        "EU MDD 93/42/EEC",
    ]
    selected = sorted(
        regulations,
        key=lambda reg: (
            priority.index(reg.name) if reg.name in priority else len(priority),
            reg.page,
            reg.name,
        ),
    )[0]
    reason = (
        "AI target regulation selection was unavailable; deterministic fallback selected "
        f"{selected.name} as the most likely primary QMS review target."
    )
    selected.evidence_text = f"{selected.evidence_text}\n\n{reason}"
    return [selected], reason
