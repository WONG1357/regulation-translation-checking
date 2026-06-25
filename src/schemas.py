from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class Severity(str, Enum):
    critical = "Critical"
    major = "Major"
    minor = "Minor"
    observation = "Observation"


class BlockType(str, Enum):
    heading = "heading"
    paragraph = "paragraph"
    table_row = "table_row"
    table_cell = "table_cell"
    reference_table = "reference_table"
    change_history = "change_history"
    bullet = "bullet"
    footer = "footer"
    header = "header"
    image = "image"
    unknown = "unknown"


class Language(str, Enum):
    zh = "zh"
    en = "en"
    mixed = "mixed"
    unknown = "unknown"


class PairStatus(str, Enum):
    confirmed = "confirmed"
    uncertain = "uncertain"
    missing_chinese = "missing_chinese"
    missing_english = "missing_english"
    unpaired = "unpaired"


class SourceType(str, Enum):
    text_extraction = "text_extraction"
    ocr = "ocr"
    docx = "docx"


class ExtractedBlock(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    block_id: str
    page: int = Field(ge=1)
    section: str | None = None
    block_type: BlockType = BlockType.unknown
    language: Language = Language.unknown
    text: str
    bbox: tuple[float, float, float, float] | None = None
    source: SourceType = SourceType.text_extraction
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    font_size: float | None = None
    reading_order: int = 0
    table_id: str | None = None
    row_index: int | None = None
    col_index: int | None = None
    context_before: str | None = None
    context_after: str | None = None
    ignored: bool = False
    warnings: list[str] = Field(default_factory=list)
    content_class: str = "bilingual_prose"
    revision_id: str | None = None
    effective_date: str | None = None
    raw_page: int | None = None
    section_level: int | None = None
    is_preserved_heading: bool = False

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        lines = [
            " ".join(line.replace("\x00", " ").split()).strip()
            for line in value.splitlines()
        ]
        return "\n".join(line for line in lines if line).strip()


class BilingualPair(BaseModel):
    model_config = ConfigDict(use_enum_values=True)

    pair_id: str
    page: int = Field(ge=1)
    section: str | None = None
    block_type: BlockType = BlockType.paragraph
    chinese_block_id: str | None = None
    english_block_id: str | None = None
    chinese_text: str = ""
    machine_translated_english: str = ""
    english_text: str = ""
    unpaired_text: str = ""
    semantic_similarity: float = Field(default=0.0, ge=0.0, le=1.0)
    final_pair_score: float = Field(default=0.0, ge=0.0, le=1.0)
    pair_confidence: float = Field(ge=0.0, le=1.0)
    pairing_method: str = "translated_chinese_similarity"
    pairing_reason: str
    pair_status: PairStatus
    should_check_translation: bool = False
    needs_manual_review: bool = False
    ai_validated: bool = False
    source_block_ids: list[str] = Field(default_factory=list)
    revision_id: str | None = None
    effective_date: str | None = None

    @property
    def status(self) -> str:
        """Backward-compatible read alias used by older display code."""
        return self.pair_status


class DetectedRegulation(BaseModel):
    name: str
    version: str = "unknown"
    evidence_text: str
    page: int
    section: str | None = None
    confidence: float = Field(ge=0.0, le=1.0)
    aliases: list[str] = Field(default_factory=list)


class TranslationFinding(BaseModel):
    finding_id: str
    page: int
    section: str | None = None
    chinese_text: str
    english_text: str
    issue_type: str
    severity: Severity
    explanation: str
    suggested_english: str = ""
    suggested_chinese: str = ""
    confidence: float = Field(ge=0.0, le=1.0)
    needs_manual_review: bool = False
    pair_id: str | None = None


class RegulatoryFinding(BaseModel):
    finding_id: str
    regulation: str
    clause_or_topic: str = ""
    page: int
    section: str | None = None
    chinese_text: str = ""
    english_text: str = ""
    issue: str
    severity: Severity
    explanation: str = ""
    recommendation: str
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    manual_review_required: bool = True
    decision: str = ""
    requirement_summary: str = ""
    gap_or_concern: str = ""
    manual_review_reason: str = ""


class TermLocation(BaseModel):
    page: int
    section: str | None = None
    text: str


class TerminologyIssue(BaseModel):
    term_id: str
    chinese_term: str
    english_variants: list[str]
    preferred_english: str
    locations: list[TermLocation]
    issue: str
    severity: Severity
    recommendation: str


class GlossaryEntry(BaseModel):
    chinese_term: str
    preferred_english: str
    alternative_english_terms: list[str] = Field(default_factory=list)
    frequency: int = 0
    locations: list[TermLocation] = Field(default_factory=list)


class PairValidationItem(BaseModel):
    pair_id: str
    is_correct_pair: bool
    confidence: float = Field(ge=0.0, le=1.0)
    reason: str
    pair_type: Literal[
        "exact_meaning",
        "partial_match",
        "wrong_pair",
        "heading_pair",
        "table_reference",
        "uncertain",
    ]
    should_check_translation: bool


class PairValidationResponse(BaseModel):
    items: list[PairValidationItem]


class ChineseTranslationItem(BaseModel):
    block_id: str
    translated_english: str


class ChineseTranslationResponse(BaseModel):
    items: list[ChineseTranslationItem]


class RegulationSelectionResponse(BaseModel):
    selected_name: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    alternative_names_considered: list[str] = Field(default_factory=list)


class ReviewBatchResponse(BaseModel):
    translation_findings: list[TranslationFinding] = Field(default_factory=list)
    regulatory_findings: list[RegulatoryFinding] = Field(default_factory=list)
    terminology_issues: list[TerminologyIssue] = Field(default_factory=list)


class ProcessingSettings(BaseModel):
    include_headers_footers: bool = False
    ocr_fallback: bool = True
    review_regulations: bool = True
    review_terminology: bool = True
    severity_threshold: Severity = Severity.observation
    batch_size: int = Field(default=6, ge=1, le=20)
    confirmed_pair_threshold: float = Field(default=0.82, ge=0.70, le=0.98)
    uncertain_pair_threshold: float = Field(default=0.68, ge=0.45, le=0.90)
    dry_run: bool = False
    ai_provider: str = "DeepSeek"
    ai_model: str = "deepseek-v4-flash"
    ai_base_url: str | None = None
    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    max_pages: int | None = None


class DocumentMetadata(BaseModel):
    filename: str
    file_type: str
    page_count: int
    processed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    warnings: list[str] = Field(default_factory=list)


class ProcessingResult(BaseModel):
    metadata: DocumentMetadata
    settings: ProcessingSettings
    blocks: list[ExtractedBlock]
    pairs: list[BilingualPair]
    regulations: list[DetectedRegulation]
    translation_findings: list[TranslationFinding] = Field(default_factory=list)
    regulatory_findings: list[RegulatoryFinding] = Field(default_factory=list)
    terminology_issues: list[TerminologyIssue] = Field(default_factory=list)
    glossary: list[GlossaryEntry] = Field(default_factory=list)
    prompts_used: dict[str, str] = Field(default_factory=dict)
    token_usage: dict[str, int] = Field(default_factory=dict)
    processing_warnings: list[str] = Field(default_factory=list)

    @property
    def unpaired_blocks(self) -> list[ExtractedBlock]:
        paired = {
            block_id
            for pair in self.pairs
            for block_id in (pair.chinese_block_id, pair.english_block_id)
            if block_id
        }
        return [b for b in self.blocks if not b.ignored and b.block_id not in paired]

    def export_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")


class AIConfig(BaseModel):
    provider: str = "OpenAI"
    model: str
    api_key: str
    base_url: str | None = None
    cache_dir: Path = Path(".cache/ai")
    timeout_seconds: float = 90.0
    max_retries: int = 2
