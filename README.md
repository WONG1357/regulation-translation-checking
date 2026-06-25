# Bilingual Translation and Regulatory Consistency Checker

A Streamlit application for preliminary Chinese-English translation, terminology, and regulatory consistency review of medical-device QMS documents.

## Features

- DOCX-only ingestion for the bilingual Quality Manual workflow.
- Word-native extraction that preserves body order, paragraphs, tables, rendered page
  markers, and TOC-derived section/page hints.
- Small-block segmentation rather than page-level pairing.
- Chinese-to-English machine translation before semantic pair matching.
- Strict configurable confirmed/uncertain thresholds, with no forced low-score pairing.
- Special handling for bilingual headings, change-history revisions, and reference matrices.
- AI validation of uncertain pairs only.
- A second AI stage for translation equivalence and regulatory observations.
- Regulation detection from the uploaded document.
- Document-wide bilingual glossary and terminology consistency checks.
- One downloadable DOCX review report.
- Dry-run mode for extraction and pairing without an API key.

## Run

```bash
uv sync --extra dev
uv run streamlit run app/streamlit_app.py
```

PDF and OCR processing are intentionally disabled in the current workflow. Use the DOCX
source file so the app can rely on Word paragraph/table structure instead of lossy PDF
layout reconstruction.

## AI configuration

The UI supports DeepSeek, OpenAI, and generic OpenAI-compatible endpoints. For DeepSeek,
select `DeepSeek`, use model `deepseek-v4-flash`, and keep the API base URL as
`https://api.deepseek.com`. API keys are entered into a password field and are not written
to disk. AI responses are requested as JSON, validated with Pydantic, retried on invalid
output, and cached in `.cache/ai/` by prompt/input hash.

Dry-run mode does not machine-translate prose, so it confirms only stable same-row and
heading-glossary pairs. Other content is preserved for manual review rather than force-paired.

## Project structure

```text
app/                    Streamlit UI
src/                    Extraction, pairing, checking, and reporting modules
prompts/                Versioned AI prompts
outputs/                Generated DOCX review report
tests/                  Unit tests
```

## Important limitation

Only `outputs/review_report.docx` is generated for the user. This tool produces AI-assisted
observations. It does not determine compliance, certification, or legal acceptability. Every
final decision must be made by qualified regulatory and quality professionals.
