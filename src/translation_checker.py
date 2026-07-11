from __future__ import annotations

from pathlib import Path
import re

from src.ai_client import AIClient
from src.schemas import (
    BilingualPair,
    PairStatus,
    RegulatoryFinding,
    ReviewBatchResponse,
    Severity,
    TermLocation,
    TerminologyIssue,
    TranslationFinding,
)
from src.utils import chunks, extract_references, read_prompt, stable_id


def deterministic_translation_checks(
    pairs: list[BilingualPair],
) -> list[TranslationFinding]:
    """Conservative checks on confirmed prose pairs only.

    Missing/uncertain content belongs in manual review and never becomes a translation
    finding. Numeric clause comparisons are intentionally left to semantic AI review.
    """
    findings: list[TranslationFinding] = []
    for pair in pairs:
        if (
            pair.pair_status != PairStatus.confirmed
            or not pair.should_check_translation
        ):
            continue
        if (
            pair.chinese_block_id
            and pair.chinese_block_id == pair.english_block_id
        ) or len(set(pair.source_block_ids)) == 1:
            # A mixed table/source block can contain a shared identifier only once.
            # The identifier cannot be attributed to one language reliably, so a
            # language-specific reference comparison would create a false mismatch.
            continue
        refs_zh = {
            ref
            for ref in extract_references(pair.chinese_text)
            if any(char.isalpha() for char in ref)
        }
        refs_en = {
            ref
            for ref in extract_references(pair.english_text)
            if any(char.isalpha() for char in ref)
        }
        if refs_zh != refs_en and (refs_zh or refs_en):
            findings.append(
                TranslationFinding(
                    finding_id=stable_id("TF", pair.pair_id, "reference"),
                    pair_id=pair.pair_id,
                    page=pair.page,
                    section=pair.section,
                    chinese_text=pair.chinese_text,
                    english_text=pair.english_text,
                    issue_type="Wrong section/clause or procedure reference",
                    severity=Severity.major,
                    explanation=(
                        "The detected standards, clauses, or procedure identifiers differ "
                        f"between languages: Chinese={sorted(refs_zh)}, English={sorted(refs_en)}."
                    ),
                    confidence=0.9,
                    needs_manual_review=True,
                )
            )
    return findings


_ALLOWED_BATCH_REGULATORY_DECISIONS = {
    "potential conflict",
    "confirmed conflict",
    "manual review required",
}
_FORBIDDEN_COVERAGE_CLAIM_RE = re.compile(
    r"\b(?:missing evidence|no evidence|overall compliance|document-wide compliance|"
    r"compliant|partially compliant|not applicable)\b",
    re.IGNORECASE,
)
_DOCUMENT_SCOPE_RE = re.compile(
    r"\b(?:the|this|entire|overall)\s+(?:quality\s+)?(?:document|manual)\b"
    r"|\b(?:document|manual)[ -]?wide\b|\boverall\b|\bcoverage\b",
    re.IGNORECASE,
)
_REGULATORY_ABSENCE_RE = re.compile(
    r"\b(?:absent|absence|missing|omits?|omitted|lacks?|nowhere|everywhere|"
    r"throughout|no\s+evidence)\b",
    re.IGNORECASE,
)
_CFR_GROUP_RE = re.compile(
    r"\b21\s+CFR\s+Parts?\s+"
    r"(\d{3}(?:\.\d+)?(?:\s*(?:,|and|&|/)\s*\d{3}(?:\.\d+)?)*)",
    re.IGNORECASE,
)
_CFR_SINGLE_RE = re.compile(
    r"\b21\s+CFR(?:\s+Part)?\s+(\d{3}(?:\.\d+)?)",
    re.IGNORECASE,
)
_PART_GROUP_RE = re.compile(
    r"\bParts?\s+"
    r"(\d{3}(?:\.\d+)?(?:\s*(?:,|and|&|/)\s*\d{3}(?:\.\d+)?)*)",
    re.IGNORECASE,
)
_ARTICLE_GROUP_RE = re.compile(
    r"\bArticles?\s+"
    r"(\d+[A-Za-z]?(?:\([A-Za-z0-9]+\))*"
    r"(?:\s*(?:,|and|&)\s*\d+[A-Za-z]?(?:\([A-Za-z0-9]+\))*)*)",
    re.IGNORECASE,
)
_ANNEX_GROUP_RE = re.compile(
    r"\bAnnex(?:es)?\s+"
    r"((?:[IVXLCDM]+|\d+)(?:\s*(?:,|and|&)\s*(?:[IVXLCDM]+|\d+))*)",
    re.IGNORECASE,
)
_SECTION_CLAUSE_GROUP_RE = re.compile(
    r"\b(Sections?|Clauses?)\s+"
    r"(\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*"
    r"(?:\s*(?:,|and|&)\s*\d+(?:\.\d+)*(?:\([A-Za-z0-9]+\))*)*)",
    re.IGNORECASE,
)
_SECTION_SYMBOL_RE = re.compile(
    r"§+\s*(\d+(?:\.\d+)+(?:\([A-Za-z0-9]+\))*)",
    re.IGNORECASE,
)
_BARE_DECIMAL_RE = re.compile(
    r"\b(\d+(?:\.\d+)+(?:\([A-Za-z0-9]+\))*)",
    re.IGNORECASE,
)
_PAIR_ISO_CLAUSE_RE = re.compile(
    r"\bISO\s*[- ]?\s*\d+(?:[- ]\d+)?(?:\s*[:：-]\s*(?:19|20)\d{2})?"
    r"\s+(?:clause\s+)?\d+(?:\.\d+)+",
    re.IGNORECASE,
)


def _authoritative_pair(
    pair_id: str,
    allowed_pairs: dict[str, BilingualPair],
    finding_type: str,
) -> BilingualPair:
    try:
        return allowed_pairs[pair_id]
    except KeyError as exc:
        raise ValueError(
            f"{finding_type} contains unknown pair ID: {pair_id}"
        ) from exc


def _validated_evidence_pairs(
    evidence_pair_ids: list[str],
    source_block_ids: list[str],
    allowed_pairs: dict[str, BilingualPair],
    finding_type: str,
) -> list[BilingualPair]:
    if not evidence_pair_ids:
        raise ValueError(f"{finding_type} requires at least one evidence pair ID.")
    pairs = [
        _authoritative_pair(pair_id, allowed_pairs, finding_type)
        for pair_id in dict.fromkeys(evidence_pair_ids)
    ]
    allowed_sources = {
        source_id for pair in pairs for source_id in pair.source_block_ids
    }
    if not source_block_ids:
        raise ValueError(f"{finding_type} requires at least one source block ID.")
    unknown_sources = sorted(set(source_block_ids) - allowed_sources)
    if unknown_sources:
        raise ValueError(
            f"{finding_type} contains unknown source block ID: "
            + ", ".join(unknown_sources)
        )
    return pairs


def _authoritative_evidence_quote(
    quote: str,
    pairs: list[BilingualPair],
    finding_type: str,
) -> str:
    quote = quote.strip()
    if not quote:
        raise ValueError(f"{finding_type} requires an exact source evidence quote.")
    quote_key = quote.casefold()
    for pair in pairs:
        for source_text in (pair.chinese_text, pair.english_text):
            start = source_text.casefold().find(quote_key)
            if start >= 0:
                return source_text[start : start + len(quote)]
    raise ValueError(
        f"{finding_type} evidence quote is not present in its authoritative pair."
    )


def _normalize_translation_finding(
    finding: TranslationFinding,
    allowed_pairs: dict[str, BilingualPair],
) -> TranslationFinding:
    pair = _authoritative_pair(
        finding.pair_id, allowed_pairs, "Translation finding"
    )
    evidence_quote = _authoritative_evidence_quote(
        finding.evidence_quote, [pair], "Translation finding"
    )
    finding_id = stable_id(
        "TF",
        pair.pair_id,
        finding.issue_type.strip().lower(),
        evidence_quote.casefold(),
    )
    return finding.model_copy(
        update={
            "finding_id": finding_id,
            "page": pair.page,
            "section": pair.section,
            "chinese_text": pair.chinese_text,
            "english_text": pair.english_text,
            "evidence_quote": evidence_quote,
            "needs_manual_review": True,
        }
    )


def _normalized_reference(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _target_reference_names(target: dict) -> list[str]:
    names = [str(target.get("name", "")), *target.get("aliases", [])]
    selected_version = str(target.get("version", "unknown"))
    names.extend(
        str(evidence.get("exact_citation", ""))
        for evidence in target.get("evidence", [])
        if isinstance(evidence, dict)
        and str(evidence.get("version", "unknown")) == selected_version
    )
    return [name for name in names if name]


def _matches_selected_target(finding_name: str, target: dict) -> bool:
    finding_key = _normalized_reference(finding_name)
    version_key = _normalized_reference(str(target.get("version", "unknown")))
    for name in _target_reference_names(target):
        target_key = _normalized_reference(name)
        if finding_key == target_key:
            return True
        suffix = finding_key[len(target_key) :] if finding_key.startswith(target_key) else ""
        if version_key != "unknown" and suffix == version_key:
            return True
    return False


def _coordinated_values(value: str) -> list[str]:
    return [
        item.strip().casefold()
        for item in re.split(r"\s*(?:,|and|&|/)\s*", value, flags=re.IGNORECASE)
        if item.strip()
    ]


def _provision_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for match in _CFR_GROUP_RE.finditer(text):
        tokens.update(f"cfr:{value}" for value in _coordinated_values(match.group(1)))
    for match in _CFR_SINGLE_RE.finditer(text):
        tokens.add(f"cfr:{match.group(1).casefold()}")
    for match in _PART_GROUP_RE.finditer(text):
        tokens.update(f"part:{value}" for value in _coordinated_values(match.group(1)))
    for match in _ARTICLE_GROUP_RE.finditer(text):
        tokens.update(
            f"article:{value}" for value in _coordinated_values(match.group(1))
        )
    for match in _ANNEX_GROUP_RE.finditer(text):
        tokens.update(
            f"annex:{value}" for value in _coordinated_values(match.group(1))
        )
    for match in _SECTION_CLAUSE_GROUP_RE.finditer(text):
        prefix = "section" if match.group(1).casefold().startswith("section") else "clause"
        tokens.update(
            f"{prefix}:{value}" for value in _coordinated_values(match.group(2))
        )
    for match in _SECTION_SYMBOL_RE.finditer(text):
        tokens.add(f"section:{match.group(1).casefold()}")
    for match in _BARE_DECIMAL_RE.finditer(text):
        tokens.add(f"clause:{match.group(1).casefold()}")
    return tokens


def _target_and_pair_provisions(target: dict, pairs: list[BilingualPair]) -> set[str]:
    tokens: set[str] = set()
    for name in _target_reference_names(target):
        tokens.update(_provision_tokens(name))
    for evidence in target.get("evidence", []):
        if not isinstance(evidence, dict):
            continue
        for provision in evidence.get("cited_provisions", []):
            tokens.update(_provision_tokens(str(provision)))
    for pair in pairs:
        pair_text = " ".join(
            (
                pair.chinese_text,
                pair.english_text,
                pair.machine_translated_english,
                pair.unpaired_text,
            )
        )
        for pattern in (
            _CFR_GROUP_RE,
            _CFR_SINGLE_RE,
            _PART_GROUP_RE,
            _ARTICLE_GROUP_RE,
            _ANNEX_GROUP_RE,
            _SECTION_CLAUSE_GROUP_RE,
            _SECTION_SYMBOL_RE,
            _PAIR_ISO_CLAUSE_RE,
        ):
            for match in pattern.finditer(pair_text):
                if pattern is _SECTION_CLAUSE_GROUP_RE and match.group(
                    1
                ).casefold().startswith("section"):
                    continue
                tokens.update(_provision_tokens(match.group(0)))
    return tokens


def _normalize_regulatory_finding(
    finding: RegulatoryFinding,
    allowed_pairs: dict[str, BilingualPair],
    selected_target: dict | None,
) -> RegulatoryFinding:
    if selected_target is None:
        raise ValueError(
            "Regulatory findings require exactly one reviewer-selected regulatory target."
        )
    if not _matches_selected_target(finding.regulation, selected_target):
        raise ValueError(
            "Regulatory finding does not match the reviewer-selected target."
        )
    decision = re.sub(r"\s+", " ", finding.decision).strip().lower()
    claim_text = " ".join(
        (
            finding.decision,
            finding.issue,
            finding.explanation,
            finding.gap_or_concern,
            finding.manual_review_reason,
            finding.requirement_summary,
            finding.recommendation,
        )
    )
    if (
        decision not in _ALLOWED_BATCH_REGULATORY_DECISIONS
        or _FORBIDDEN_COVERAGE_CLAIM_RE.search(claim_text)
    ):
        raise ValueError(
            "AI batch findings may not make a document-wide coverage or compliance claim."
        )
    evidence_pairs = _validated_evidence_pairs(
        finding.evidence_pair_ids,
        finding.source_block_ids,
        allowed_pairs,
        "Regulatory finding",
    )
    decision_prefix = re.compile(
        rf"^Decision:\s*{re.escape(finding.decision.strip())}\s*[—:-]",
        re.IGNORECASE,
    )
    if (
        not decision_prefix.search(finding.issue)
        or not any(pair.pair_id in finding.issue for pair in evidence_pairs)
        or _DOCUMENT_SCOPE_RE.search(claim_text)
        or _REGULATORY_ABSENCE_RE.search(claim_text)
    ):
        raise ValueError(
            "AI regulatory findings must state pair-local scope and cite an evidence pair ID."
        )
    claimed_provisions = _provision_tokens(finding.clause_or_topic)
    supported_provisions = _target_and_pair_provisions(
        selected_target, evidence_pairs
    )
    if not claimed_provisions <= supported_provisions:
        raise ValueError(
            "Regulatory finding contains an unstated clause or provision."
        )
    pair = min(
        evidence_pairs,
        key=lambda item: (item.page, item.section or "", item.pair_id),
    )
    evidence_quote = _authoritative_evidence_quote(
        finding.evidence_quote, evidence_pairs, "Regulatory finding"
    )
    finding_id = stable_id(
        "RF",
        *sorted(finding.evidence_pair_ids),
        _normalized_reference(str(selected_target["name"])),
        *(sorted(claimed_provisions) or [decision]),
        evidence_quote.casefold(),
    )
    return finding.model_copy(
        update={
            "finding_id": finding_id,
            "regulation": str(selected_target["name"]),
            "page": pair.page,
            "section": pair.section,
            "chinese_text": pair.chinese_text,
            "english_text": pair.english_text,
            "evidence_quote": evidence_quote,
            "manual_review_required": True,
        }
    )


def _normalize_terminology_issue(
    issue: TerminologyIssue,
    allowed_pairs: dict[str, BilingualPair],
) -> TerminologyIssue:
    evidence_pairs = _validated_evidence_pairs(
        issue.evidence_pair_ids,
        issue.source_block_ids,
        allowed_pairs,
        "Terminology finding",
    )
    evidence_pairs.sort(key=lambda item: (item.page, item.section or "", item.pair_id))
    locations = [
        TermLocation(
            page=pair.page,
            section=pair.section,
            text=f"{pair.chinese_text} / {pair.english_text}",
        )
        for pair in evidence_pairs
    ]
    term_id = stable_id(
        "TERM",
        *sorted(issue.evidence_pair_ids),
        issue.chinese_term.strip().lower(),
    )
    severity = (
        Severity.minor
        if issue.severity in {Severity.critical, Severity.major}
        else issue.severity
    )
    return issue.model_copy(
        update={"term_id": term_id, "locations": locations, "severity": severity}
    )


def validate_and_normalize_review_response(
    response: ReviewBatchResponse,
    batch: list[BilingualPair],
    selected_target: dict | None = None,
) -> ReviewBatchResponse:
    """Fail closed on AI provenance and replace all quoted locations from source pairs."""
    allowed_pairs = {pair.pair_id: pair for pair in batch}
    translations = {
        finding.finding_id: finding
        for raw in response.translation_findings
        if (
            finding := _normalize_translation_finding(raw, allowed_pairs)
        )
    }
    regulations = {
        finding.finding_id: finding
        for raw in response.regulatory_findings
        if (
            finding := _normalize_regulatory_finding(
                raw, allowed_pairs, selected_target
            )
        )
    }
    terminology = {
        issue.term_id: issue
        for raw in response.terminology_issues
        if (issue := _normalize_terminology_issue(raw, allowed_pairs))
    }
    return ReviewBatchResponse(
        translation_findings=list(translations.values()),
        regulatory_findings=list(regulations.values()),
        terminology_issues=list(terminology.values()),
    )


def ai_review_pairs(
    pairs: list[BilingualPair],
    regulations: list[dict],
    client: AIClient,
    *,
    batch_size: int = 6,
    prompt_path: str | Path = "prompts/translation_check.md",
) -> ReviewBatchResponse:
    if len(regulations) > 1:
        raise ValueError("AI review accepts at most one reviewer-selected regulatory target.")
    selected_target = regulations[0] if regulations else None
    prompt = read_prompt(prompt_path)
    combined = ReviewBatchResponse()
    eligible = [
        pair
        for pair in pairs
        if pair.pair_status == PairStatus.confirmed and pair.should_check_translation
    ]
    for batch in chunks(eligible, batch_size):
        payload = {
            "detected_regulations": regulations,
            "pairs": [pair.model_dump(mode="json") for pair in batch],
        }
        response = client.request_json(prompt, payload, ReviewBatchResponse)
        normalized = validate_and_normalize_review_response(
            response, batch, selected_target
        )
        combined.translation_findings.extend(normalized.translation_findings)
        combined.regulatory_findings.extend(normalized.regulatory_findings)
        combined.terminology_issues.extend(normalized.terminology_issues)
    return ReviewBatchResponse(
        translation_findings=list(
            {item.finding_id: item for item in combined.translation_findings}.values()
        ),
        regulatory_findings=list(
            {item.finding_id: item for item in combined.regulatory_findings}.values()
        ),
        terminology_issues=list(
            {item.term_id: item for item in combined.terminology_issues}.values()
        ),
    )
