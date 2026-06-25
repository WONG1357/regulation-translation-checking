from __future__ import annotations

from pathlib import Path
from typing import Callable

from src.ai_client import AIClient
from src.bilingual_pairer import pair_blocks, validate_pairs_with_ai
from src.chinese_to_english_pairing import translate_chinese_blocks
from src.document_loader import load_document
from src.layout_segmenter import segment_blocks
from src.regulation_detector import detect_regulations, select_primary_regulation
from src.regulatory_checker import deterministic_regulatory_observations
from src.schemas import AIConfig, ProcessingResult, ProcessingSettings
from src.terminology_checker import check_terminology
from src.translation_checker import ai_review_pairs, deterministic_translation_checks
from src.utils import read_prompt

ProgressCallback = Callable[[str, float], None]


def process_document(
    path: str | Path,
    settings: ProcessingSettings,
    *,
    ai_config: AIConfig | None = None,
    progress: ProgressCallback | None = None,
) -> ProcessingResult:
    def update(message: str, amount: float):
        if progress:
            progress(message, amount)

    update("Loading and extracting document", 0.08)
    metadata, raw_blocks = load_document(
        path,
        ocr_fallback=settings.ocr_fallback,
        max_pages=None,
    )
    page_start = settings.page_start or 1
    if settings.page_end is not None:
        page_end = settings.page_end
    elif settings.max_pages is not None:
        page_end = page_start + settings.max_pages - 1
    else:
        page_end = None
    if page_end is not None and page_end < page_start:
        raise ValueError("Page range end must be greater than or equal to start.")
    if page_start > 1 or page_end is not None:
        raw_blocks = [
            block
            for block in raw_blocks
            if block.page >= page_start and (page_end is None or block.page <= page_end)
        ]
        if not raw_blocks:
            raise ValueError(
                f"No extractable DOCX content was found in page range {page_start}"
                + (f"-{page_end}." if page_end is not None else "+.")
            )
        unique_pages = sorted({block.page for block in raw_blocks})
        metadata = metadata.model_copy(
            update={
                "page_count": len(unique_pages),
                "warnings": metadata.warnings
                + [
                    "Processed selected page range "
                    f"{page_start}-{page_end if page_end is not None else 'end'}; "
                    f"{len(unique_pages)} page(s) contained extracted content."
                ],
            }
        )
    update("Segmenting layout into logical blocks", 0.22)
    blocks = segment_blocks(
        raw_blocks, include_headers_footers=settings.include_headers_footers
    )
    client: AIClient | None = None
    warnings: list[str] = []
    if not settings.dry_run:
        if not ai_config or not ai_config.api_key:
            raise ValueError("An API key is required unless dry-run mode is enabled.")
        client = AIClient(ai_config)
    else:
        warnings.append(
            "Dry-run mode: prose blocks are not machine-translated, so only stable "
            "same-row/heading matches can be confirmed."
        )

    update("Detecting regulations and selecting one target standard", 0.30)
    all_regulations = detect_regulations(blocks) if settings.review_regulations else []
    regulation_selection_reason: str | None = None
    regulations: list = []
    if settings.review_regulations:
        regulations, regulation_selection_reason = select_primary_regulation(
            all_regulations, blocks, client
        )
        if regulation_selection_reason:
            warnings.append(regulation_selection_reason)

    chinese_blocks = [
        block
        for block in blocks
        if not block.ignored and any("\u3400" <= char <= "\u9fff" for char in block.text)
    ]
    update("Translating Chinese blocks for semantic pairing", 0.40)
    translations = translate_chinese_blocks(
        chinese_blocks, client, batch_size=settings.batch_size
    )
    update("Pairing translated Chinese with original English", 0.56)
    pairs = pair_blocks(
        blocks,
        translations,
        confirmed_threshold=settings.confirmed_pair_threshold,
        uncertain_threshold=settings.uncertain_pair_threshold,
    )

    if client:
        update("AI stage 1: validating uncertain bilingual pairs", 0.66)
        pairs = validate_pairs_with_ai(
            pairs,
            blocks,
            client,
            batch_size=settings.batch_size,
        )

    update("Running conservative deterministic checks", 0.72)
    translation_findings = deterministic_translation_checks(pairs)
    regulatory_findings = (
        deterministic_regulatory_observations(pairs, regulations)
        if settings.review_regulations
        else []
    )
    terminology_issues, glossary = (
        check_terminology(pairs) if settings.review_terminology else ([], [])
    )

    if client:
        update("AI stage 2: reviewing confirmed bilingual prose", 0.80)
        response = ai_review_pairs(
            pairs,
            [reg.model_dump(mode="json") for reg in regulations],
            client,
            batch_size=settings.batch_size,
        )
        translation_findings.extend(response.translation_findings)
        regulatory_findings.extend(response.regulatory_findings)
        terminology_issues.extend(response.terminology_issues)

    update("Assembling result", 0.92)
    prompts = {
        "Pairing validation": read_prompt("prompts/pair_bilingual_blocks.md"),
        "Translation/regulatory/terminology review": read_prompt(
            "prompts/translation_check.md"
        ),
    }
    result = ProcessingResult(
        metadata=metadata,
        settings=settings,
        blocks=blocks,
        pairs=pairs,
        regulations=regulations,
        translation_findings=translation_findings,
        regulatory_findings=regulatory_findings,
        terminology_issues=terminology_issues,
        glossary=glossary,
        prompts_used=prompts,
        token_usage=client.token_usage if client else {},
        processing_warnings=warnings,
    )
    update("Processing complete", 1.0)
    return result
