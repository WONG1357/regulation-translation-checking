from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
from typing import Any

from .block_classification import classify_document_blocks
from .llm_client import LLMConfig, call_llm_json, format_api_error
from .section_detection import section_at_or_after, section_sort_key
from .utils import (
    BilingualPair,
    DocumentResult,
    TextBlock,
    confidence_from_score,
    normalize_text,
)


PROMPT_PATH = Path(__file__).resolve().parent.parent / "prompts" / "analyze_bilingual_section.md"
ALLOWED_CLASSIFICATIONS = {
    "chinese_source",
    "english_translation",
    "bilingual_mixed",
    "heading",
    "header_footer",
    "metadata",
    "table_content",
    "ignored",
    "unclear",
}


@dataclass
class SectionPackage:
    document_name: str
    section_id: str
    section_title: str
    page_start: int | None
    page_end: int | None
    blocks: list[dict[str, Any]]


@dataclass
class SectionAIResult:
    document_name: str
    section_id: str
    section_title: str
    page_start: int | None
    page_end: int | None
    status: str
    ai_processed: bool
    pairs: list[dict[str, Any]] = field(default_factory=list)
    block_audit: list[dict[str, Any]] = field(default_factory=list)
    translation_issues: list[dict[str, Any]] = field(default_factory=list)
    wording_consistency: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    failure_reason: str = ""
    missing_block_ids: list[str] = field(default_factory=list)
    unpaired_chinese_block_ids: list[str] = field(default_factory=list)
    unpaired_english_block_ids: list[str] = field(default_factory=list)


def build_section_packages(
    docs: list[DocumentResult],
    review_start_section: str | float = "2.0",
    include_tables: bool = True,
) -> list[SectionPackage]:
    packages: list[SectionPackage] = []
    for doc in docs:
        classify_document_blocks(doc, review_start_section)
        grouped: dict[str, list[TextBlock]] = {}
        for block in sorted(doc.blocks, key=lambda item: item.order):
            if not block.section_id or not section_at_or_after(block.section_id, review_start_section):
                continue
            if block.table_index is not None and not include_tables:
                continue
            grouped.setdefault(block.section_id, []).append(block)
        for section_id in sorted(grouped, key=section_sort_key):
            blocks = grouped[section_id]
            pages = [block.page_number for block in blocks if block.page_number is not None]
            packages.append(
                SectionPackage(
                    document_name=doc.file_name,
                    section_id=section_id,
                    section_title=next((block.section_title for block in blocks if block.section_title), ""),
                    page_start=min(pages) if pages else None,
                    page_end=max(pages) if pages else None,
                    blocks=[_block_payload(block) for block in blocks],
                )
            )
    return packages


def analyze_sections_with_ai(
    packages: list[SectionPackage],
    config: LLMConfig,
    progress_callback=None,
) -> list[SectionAIResult]:
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    results: list[SectionAIResult] = []
    total = len(packages)
    for index, package in enumerate(packages, 1):
        try:
            payload = call_llm_json(
                config,
                [
                    {"role": "system", "content": prompt},
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "instruction": "Analyze this complete logical section. No block limit or chunking is applied.",
                                "section": section_package_to_dict(package),
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                expected="object",
            )
            result = validate_section_response(package, payload)
        except Exception as exc:
            result = SectionAIResult(
                document_name=package.document_name,
                section_id=package.section_id,
                section_title=package.section_title,
                page_start=package.page_start,
                page_end=package.page_end,
                status="AI failed",
                ai_processed=True,
                failure_reason=format_api_error(config.provider, exc),
            )
        results.append(result)
        if progress_callback:
            progress_callback(index, total, package.section_id)
    return results


def validate_section_response(package: SectionPackage, payload: Any) -> SectionAIResult:
    result = SectionAIResult(
        document_name=package.document_name,
        section_id=package.section_id,
        section_title=package.section_title,
        page_start=package.page_start,
        page_end=package.page_end,
        status="OK",
        ai_processed=True,
    )
    if not isinstance(payload, dict):
        result.status = "AI failed"
        result.failure_reason = "AI response was not a JSON object."
        return result

    failures: list[str] = []
    if str(payload.get("section_id", "")) != package.section_id:
        failures.append("Response section ID does not match the input section.")
    if payload.get("page_start") != package.page_start or payload.get("page_end") != package.page_end:
        failures.append("Response did not preserve the section page range.")

    input_ids = [str(block["block_id"]) for block in package.blocks]
    input_id_set = set(input_ids)
    audit = payload.get("block_audit") if isinstance(payload.get("block_audit"), list) else []
    audit_ids = [str(item.get("block_id", "")) for item in audit if isinstance(item, dict)]
    result.missing_block_ids = sorted(input_id_set - set(audit_ids))
    duplicate_audit_ids = sorted({block_id for block_id in audit_ids if audit_ids.count(block_id) > 1})
    unknown_audit_ids = sorted(set(audit_ids) - input_id_set)
    if result.missing_block_ids:
        failures.append(f"Missing block IDs: {', '.join(result.missing_block_ids)}")
    if duplicate_audit_ids:
        failures.append(f"Duplicate block audit IDs: {', '.join(duplicate_audit_ids)}")
    if unknown_audit_ids:
        failures.append(f"Unknown block audit IDs: {', '.join(unknown_audit_ids)}")
    for item in audit:
        if isinstance(item, dict) and item.get("classification") not in ALLOWED_CLASSIFICATIONS:
            failures.append(f"Invalid classification for block {item.get('block_id')}.")
    result.block_audit = audit

    pairs = payload.get("pairs") if isinstance(payload.get("pairs"), list) else []
    pair_ids: set[str] = set()
    paired_block_ids: set[str] = set()
    valid_pairs: list[dict[str, Any]] = []
    for item in pairs:
        if not isinstance(item, dict):
            failures.append("A pair entry was not an object.")
            continue
        pair_id = str(item.get("pair_id", "")).strip()
        zh_ids = [str(value) for value in item.get("chinese_block_ids", [])]
        en_ids = [str(value) for value in item.get("english_block_ids", [])]
        if not pair_id or pair_id in pair_ids:
            failures.append("Pair IDs are missing or duplicated.")
            continue
        if not zh_ids or not en_ids or not normalize_text(str(item.get("chinese_text", ""))) or not normalize_text(str(item.get("english_text", ""))):
            failures.append(f"Pair {pair_id} is missing Chinese or English content.")
            continue
        unknown_pair_ids = (set(zh_ids) | set(en_ids)) - input_id_set
        if unknown_pair_ids:
            failures.append(f"Pair {pair_id} references unknown block IDs: {', '.join(sorted(unknown_pair_ids))}")
            continue
        pair_ids.add(pair_id)
        paired_block_ids.update(zh_ids)
        paired_block_ids.update(en_ids)
        valid_pairs.append(item)
    result.pairs = valid_pairs

    audit_by_id = {
        str(item.get("block_id")): item
        for item in audit
        if isinstance(item, dict) and item.get("block_id")
    }
    result.unpaired_chinese_block_ids = sorted(
        block_id for block_id, item in audit_by_id.items()
        if item.get("classification") == "chinese_source" and block_id not in paired_block_ids
    )
    result.unpaired_english_block_ids = sorted(
        block_id for block_id, item in audit_by_id.items()
        if item.get("classification") == "english_translation" and block_id not in paired_block_ids
    )
    if result.unpaired_chinese_block_ids or result.unpaired_english_block_ids:
        failures.append("Meaningful Chinese or English blocks remain unpaired.")

    issues = payload.get("translation_issues") if isinstance(payload.get("translation_issues"), list) else []
    result.translation_issues = [
        item for item in issues
        if isinstance(item, dict) and str(item.get("pair_id", "")) in pair_ids
    ]
    if len(result.translation_issues) != len(issues):
        failures.append("Translation issues reference unknown pair IDs.")
    result.wording_consistency = (
        payload.get("wording_consistency")
        if isinstance(payload.get("wording_consistency"), list)
        else []
    )
    result.warnings = [str(value) for value in payload.get("warnings", [])]
    if failures:
        result.status = "Needs review"
        result.failure_reason = "; ".join(dict.fromkeys(failures))
    elif not valid_pairs and not any(
        item.get("classification") in {"chinese_source", "english_translation", "bilingual_mixed"}
        for item in audit if isinstance(item, dict)
    ):
        result.status = "No main content"
    return result


def results_to_bilingual_pairs(
    results: list[SectionAIResult],
    block_by_id: dict[str, TextBlock],
) -> list[BilingualPair]:
    output: list[BilingualPair] = []
    seen: set[str] = set()
    for result in results:
        if result.status not in {"OK", "Needs review"}:
            continue
        for index, item in enumerate(result.pairs, 1):
            pair_id = str(item.get("pair_id") or f"{result.document_name}:{result.section_id}:pair:{index}")
            if pair_id in seen:
                pair_id = f"{result.document_name}:{result.section_id}:{pair_id}"
            seen.add(pair_id)
            zh_ids = [str(value) for value in item.get("chinese_block_ids", [])]
            en_ids = [str(value) for value in item.get("english_block_ids", [])]
            first = next((block_by_id.get(block_id) for block_id in zh_ids + en_ids if block_by_id.get(block_id)), None)
            confidence = str(item.get("confidence", "Medium"))
            score = {"High": 0.9, "Medium": 0.65, "Low": 0.35}.get(confidence, 0.65)
            output.append(
                BilingualPair(
                    pair_id=pair_id,
                    file_name=result.document_name,
                    chinese_text=normalize_text(str(item.get("chinese_text", ""))),
                    english_text=normalize_text(str(item.get("english_text", ""))),
                    confidence=confidence_from_score(score),
                    confidence_score=score,
                    pairing_reason=str(item.get("reason", "AI section analysis")),
                    location=first.location_label() if first else f"Section {result.section_id}",
                    page_number=first.page_number if first else result.page_start,
                    section_heading=f"{result.section_id} {result.section_title}".strip(),
                    chinese_block_id=zh_ids[0] if zh_ids else None,
                    english_block_id=en_ids[0] if en_ids else None,
                    chinese_block_ids=zh_ids,
                    english_block_ids=en_ids,
                )
            )
    return output


def translation_issue_rows(
    results: list[SectionAIResult],
    pairs: list[BilingualPair],
) -> list[dict[str, Any]]:
    pair_by_id = {pair.pair_id: pair for pair in pairs}
    rows: list[dict[str, Any]] = []
    for result in results:
        for item in result.translation_issues:
            pair = pair_by_id.get(str(item.get("pair_id", "")))
            if not pair or str(item.get("severity", "None")).lower() == "none":
                continue
            rows.append(
                {
                    "page number or section": pair.location,
                    "Chinese source text": pair.chinese_text,
                    "existing English translation": pair.english_text,
                    "issue type": item.get("issue_type", "translation accuracy"),
                    "explanation of the problem": item.get("explanation", ""),
                    "severity": item.get("severity", "Major"),
                    "suggested corrected English wording": item.get("suggested_corrected_english", pair.english_text),
                    "confidence level": item.get("confidence", "Medium"),
                    "review source": "Section AI review",
                }
            )
    return rows


def wording_consistency_rows(results: list[SectionAIResult]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for result in results:
        for item in result.wording_consistency:
            if not isinstance(item, dict) or str(item.get("severity", "None")).lower() == "none":
                continue
            rows.append(
                {
                    "section ID": result.section_id,
                    "section title": result.section_title,
                    "page range": _page_range(result.page_start, result.page_end),
                    "Chinese term": item.get("chinese_term", ""),
                    "English translations found": "; ".join(str(value) for value in item.get("english_variants", [])),
                    "recommended standard English translation": item.get("recommended_english", ""),
                    "explanation": item.get("explanation", ""),
                    "block IDs": ", ".join(str(value) for value in item.get("block_ids", [])),
                    "severity": item.get("severity", "Minor"),
                }
            )
    return rows


def build_section_ai_coverage(
    packages: list[SectionPackage],
    results: list[SectionAIResult],
) -> list[dict[str, Any]]:
    result_map = {(result.document_name, result.section_id): result for result in results}
    rows: list[dict[str, Any]] = []
    for package in packages:
        result = result_map.get((package.document_name, package.section_id))
        rows.append(
            {
                "document": package.document_name,
                "section_id": package.section_id,
                "section_title": package.section_title,
                "page_start": package.page_start,
                "page_end": package.page_end,
                "total_blocks": len(package.blocks),
                "AI processed": "Yes" if result else "No",
                "pairs": len(result.pairs) if result else 0,
                "unpaired Chinese": len(result.unpaired_chinese_block_ids) if result else 0,
                "unpaired English": len(result.unpaired_english_block_ids) if result else 0,
                "translation issues": len(result.translation_issues) if result else 0,
                "wording findings": len(result.wording_consistency) if result else 0,
                "status": result.status if result else "Not processed",
                "failure reason": result.failure_reason if result else "",
            }
        )
    return rows


def section_package_to_dict(package: SectionPackage) -> dict[str, Any]:
    return asdict(package)


def section_result_to_dict(result: SectionAIResult) -> dict[str, Any]:
    return asdict(result)


def _block_payload(block: TextBlock) -> dict[str, Any]:
    return {
        "block_id": block.block_id,
        "page_number": block.page_number,
        "order": block.order,
        "text": block.text,
        "detected_language": block.detected_language,
        "classification_hint": block.classification,
        "block_type": block.block_type,
        "table_index": block.table_index,
        "row_index": block.row_index,
        "cell_index": block.cell_index,
        "bbox": block.bbox,
        "ignore_reason": block.ignore_reason,
    }


def _page_range(start: int | None, end: int | None) -> str:
    if start == end:
        return str(start or "")
    return f"{start or ''}–{end or ''}"
