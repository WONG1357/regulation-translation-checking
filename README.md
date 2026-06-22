# Bilingual Chinese-English Document Review Assistant

A Streamlit application for extracting, pairing, highlighting, and reviewing bilingual Chinese-English quality and regulatory documents.

## Install and run

```bash
pip install -r requirements.txt
streamlit run app.py
```

Open the local Streamlit URL shown in the terminal.

## API configuration

In **Upload & Settings**, enter:

- an AI API key (password field);
- an optional OpenAI-compatible base URL;
- the model name supported by that API.

The API key is kept only in `st.session_state`. It is not printed or written to report files.

## Workflow

1. Upload a PDF, DOCX, or TXT bilingual document.
2. Extract document blocks. PDF blocks retain page and bounding-box data; DOCX tables become table-row blocks.
3. Clean and section the document. Repeated headers and footers are marked but retained.
4. Build chunks using section, table, and size boundaries.
5. Run AI semantic pairing using only supplied block IDs.
6. Review coverage and optionally change/delete candidate pairs.
7. View Chinese and English pair members with matching highlight colours. Unpaired text remains plain.
8. Run translation, terminology, and regulation reviews.
9. Export JSON, CSV, and HTML reports.

Only confirmed paired text is sent to translation checking. Unpaired content remains visible and unattended; it does not block the workflow.

## Output files

The app creates `outputs/` automatically:

- `extracted_blocks.json`: all initially extracted blocks.
- `sectioned_blocks.json`: blocks after header/footer marking and section assignment.
- `chunks.json`: AI chunks with block IDs and context.
- `ai_pairs_raw.json`: validated raw AI pairing output.
- `reviewed_pairs.json`: optional user-reviewed pair list, or the raw list if unchanged.
- `coverage_report.csv`: one accounting row per extracted block.
- `translation_issues.csv` / `.json`: paired-text translation findings.
- `terminology_consistency.csv` / `.json`: document-wide terminology findings.
- `regulation_references.csv` / `.json`: detected regulation and standard references.
- `regulation_review.csv` / `.json`: cautious consistency review.
- `final_report.html`: summary, findings, and the highlighted document view.

## Limitations

- Scanned/image-only PDFs require OCR, which is not included.
- PDF reading order and irregular table reconstruction depend on the source PDF structure.
- AI pairing and review are advisory and require qualified human judgment.
- Regulatory verification is limited without official source text. The app instructs AI not to invent requirements and to report when full verification is unavailable.
- Long documents may require many API requests and can encounter provider token or rate limits.
