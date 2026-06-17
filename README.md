# Bilingual Chinese-English Regulatory Review App

This Streamlit app reviews bilingual Chinese-English regulatory and quality management documents, with Chinese treated as the controlling source text.

## Features

- Upload one or more `DOCX`, `PDF`, or `TXT` bilingual documents.
- Optionally upload reference regulation documents for wording comparison.
- Extract DOCX paragraphs and tables.
- Extract PDF text page by page and warn when pages appear scanned or image-based.
- Detect Chinese blocks, English blocks, and likely bilingual pairs.
- Assign high, medium, or low confidence to detected Chinese-English pairs.
- Run deterministic checks for terminology, modal verbs, missing negative meaning, and length mismatch.
- Use a configurable API provider to assist Part C bilingual pair detection and paragraph-level translation review.
- Detect common medical-device regulations and standards such as ISO 13485, EU MDR, EU MDD, 21 CFR Part 820, YY/T 0287, and others.
- Export Excel and Word reports.

## Project Structure

```text
app.py
requirements.txt
README.md
src/
  extractors.py
  bilingual_pairing.py
  translation_review.py
  terminology_review.py
  regulation_detection.py
  reference_comparison.py
  export_report.py
  utils.py
```

The extraction layer is intentionally separated from review logic so `XLSX` extraction can be added later by creating a spreadsheet extractor that returns the same `DocumentResult` and `TextBlock` structures.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

## API Configuration

You can choose **DeepSeek**, **OpenAI**, **OpenAI-compatible**, or **Anthropic** in the app sidebar. Enter the provider key in the password field. DeepSeek is prefilled with `https://api.deepseek.com` and works through the OpenAI-compatible path.

Alternatively, set an API key in the environment before launching Streamlit:

```bash
export LLM_API_PROVIDER="OpenAI"
export LLM_API_KEY="your_api_key"
streamlit run app.py
```

For DeepSeek:

```bash
export LLM_API_PROVIDER="DeepSeek"
export DEEPSEEK_API_KEY="your_deepseek_key"
export LLM_MODEL="deepseek-v4-flash"
streamlit run app.py
```

You can also add the key to Streamlit secrets:

```toml
# .streamlit/secrets.toml
LLM_API_KEY = "your_api_key"
```

The sidebar option **Use API for Part C bilingual pair detection** asks the selected provider to identify Chinese-English pairs for the Part C table. The option **Use API for paragraph translation review** sends the detected pairs to the selected provider and returns one row per pair, including OK rows and issue rows. Issue rows are also merged into the Translation Issue Report.

Version 1 reads keys from the sidebar, Streamlit secrets, or environment variables such as `LLM_API_KEY`, `DEEPSEEK_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY`. The API layers are isolated in `src/llm_client.py`, `src/api_pairing.py`, `src/paragraph_api_review.py`, and `src/reference_comparison.py`.

## Notes and Limitations

- Pairing is heuristic and should be reviewed by a human.
- PDF table structure is not reconstructed in version 1.
- OCR is not included. If PDF pages have no extractable text, the app warns that OCR may be required.
- LLM findings are advisory and should be verified by qualified regulatory/quality personnel.
