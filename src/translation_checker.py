from __future__ import annotations

from pathlib import Path

from src.ai_client import AIClient
from src.schemas import (
    BilingualPair,
    PairStatus,
    ReviewBatchResponse,
    Severity,
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


def ai_review_pairs(
    pairs: list[BilingualPair],
    regulations: list[dict],
    client: AIClient,
    *,
    batch_size: int = 6,
    prompt_path: str | Path = "prompts/translation_check.md",
) -> ReviewBatchResponse:
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
        combined.translation_findings.extend(response.translation_findings)
        combined.regulatory_findings.extend(response.regulatory_findings)
        combined.terminology_issues.extend(response.terminology_issues)
    return combined
