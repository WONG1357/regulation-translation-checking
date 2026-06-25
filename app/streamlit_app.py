from __future__ import annotations

import html
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.document_loader import save_uploaded_file  # noqa: E402
from src.pipeline import process_document  # noqa: E402
from src.regulatory_checker import build_regulatory_coverage_matrix  # noqa: E402
from src.report_generator import generate_report  # noqa: E402
from src.schemas import (  # noqa: E402
    AIConfig,
    PairStatus,
    ProcessingSettings,
    Severity,
)
from src.utils import severity_rank  # noqa: E402

st.set_page_config(
    page_title="Bilingual Regulatory Checker",
    page_icon="🩺",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
  :root { --ink:#19324a; --blue:#2e74b5; --line:#d7dee8; --surface:#f7f9fc; }
  .block-container { padding-top: 1.5rem; padding-bottom: 3rem; }
  h1, h2, h3 { color: var(--ink); }
  .app-kicker { color:#2e74b5; font-weight:700; letter-spacing:.08em; font-size:.78rem; }
  .pair-card { border:1px solid var(--line); border-left:6px solid #94a3b8;
    border-radius:10px; padding:14px 16px; margin:10px 0; background:white; }
  .pair-card.paired { border-left-color:#16a34a; background:#f0fdf4; }
  .pair-card.uncertain { border-left-color:#eab308; background:#fefce8; }
  .pair-card.missing { border-left-color:#f97316; background:#fff7ed; }
  .pair-card.unpaired { border-left-color:#94a3b8; background:#f8fafc; }
  .pair-card.mismatch { border-left-color:#dc2626; background:#fef2f2; }
  .pair-meta { color:#64748b; font-size:.78rem; margin-bottom:8px; }
  .lang-label { font-weight:700; color:#334155; font-size:.78rem; text-transform:uppercase; }
  .source-text { white-space:pre-wrap; line-height:1.55; font-size:.92rem; }
  .reg-chip { display:inline-block; padding:4px 9px; margin:3px; border-radius:999px;
    background:#e8f0f7; color:#19324a; font-size:.8rem; font-weight:600; }
  [data-testid="stMetric"] { background:#f7f9fc; border:1px solid #e2e8f0;
    padding:10px 14px; border-radius:10px; }
</style>
""",
    unsafe_allow_html=True,
)


def pair_card(pair, mismatch_pair_ids: set[str]) -> str:
    if pair.pair_id in mismatch_pair_ids:
        css_class = "mismatch"
    elif pair.pair_status == PairStatus.confirmed:
        css_class = "paired"
    elif pair.pair_status == PairStatus.uncertain:
        css_class = "uncertain"
    elif pair.pair_status in {
        PairStatus.missing_chinese,
        PairStatus.missing_english,
    }:
        css_class = "missing"
    else:
        css_class = "unpaired"
    return f"""
    <div class="pair-card {css_class}">
      <div class="pair-meta">
        Page {pair.page} · Section {html.escape(pair.section or "—")} ·
        {html.escape(str(pair.pair_status))} · confidence {pair.pair_confidence:.0%} ·
        semantic {pair.semantic_similarity:.0%}<br/>
        {html.escape(pair.pairing_reason)}
      </div>
      <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:18px">
        <div><div class="lang-label">中文</div>
          <div class="source-text">{html.escape(pair.chinese_text or "—")}</div></div>
        <div><div class="lang-label">Machine translation</div>
          <div class="source-text">{html.escape(pair.machine_translated_english or "—")}</div></div>
        <div><div class="lang-label">English</div>
          <div class="source-text">{html.escape(pair.english_text or pair.unpaired_text or "—")}</div></div>
      </div>
    </div>
    """


with st.sidebar:
    st.header("Review settings")
    uploaded = st.file_uploader("Upload DOCX", type=["docx"])
    provider = st.selectbox("AI provider", ["DeepSeek", "OpenAI", "OpenAI-compatible"])
    default_models = {
        "DeepSeek": "deepseek-v4-flash",
        "OpenAI": "gpt-4.1-mini",
        "OpenAI-compatible": "gpt-4.1-mini",
    }
    model = st.text_input("Model", value=default_models[provider])
    if provider == "DeepSeek":
        base_url = st.text_input("DeepSeek API base URL", value="https://api.deepseek.com")
    elif provider == "OpenAI-compatible":
        base_url = st.text_input("Compatible API base URL", placeholder="https://…/v1")
    else:
        base_url = ""
    api_key = st.text_input("API key", type="password")
    dry_run = st.toggle("Dry run (no AI calls)", value=not bool(api_key))
    st.divider()
    include_furniture = st.checkbox("Include headers/footers", value=False)
    review_regulations = st.checkbox("Review regulations", value=True)
    review_terminology = st.checkbox("Review terminology consistency", value=True)
    severity_threshold = st.selectbox(
        "Severity threshold",
        [severity.value for severity in Severity],
        index=3,
    )
    batch_size = st.slider("AI batch size", 1, 15, 6)
    confirmed_threshold = st.slider(
        "Confirmed pair threshold", 0.70, 0.98, 0.82, 0.01
    )
    uncertain_threshold = st.slider(
        "Uncertain pair threshold", 0.45, confirmed_threshold - 0.01, 0.68, 0.01
    )
    page_range_enabled = st.checkbox("Process selected page range", value=False)
    if page_range_enabled:
        page_start = st.number_input("Start page", min_value=1, value=1)
        page_end = st.number_input("End page", min_value=1, value=max(1, int(page_start)))
    else:
        page_start = None
        page_end = None
    process_clicked = st.button(
        "Process document", type="primary", width="stretch", disabled=not uploaded
    )

st.markdown('<div class="app-kicker">MEDICAL-DEVICE QMS REVIEW</div>', unsafe_allow_html=True)
st.title("Bilingual Translation and Regulatory Consistency Checker")
st.caption(
    "DOCX-native Chinese-English extraction, conservative AI review, and traceable DOCX reporting."
)

if not uploaded:
    st.info(
        "Upload the bilingual Quality Manual as a DOCX file. PDF/OCR processing is disabled "
        "so the app can use the Word document's real paragraph, table, section, and page structure."
    )

if process_clicked and uploaded:
    settings = ProcessingSettings(
        include_headers_footers=include_furniture,
        ocr_fallback=False,
        review_regulations=review_regulations,
        review_terminology=review_terminology,
        severity_threshold=Severity(severity_threshold),
        batch_size=batch_size,
        confirmed_pair_threshold=confirmed_threshold,
        uncertain_pair_threshold=uncertain_threshold,
        dry_run=dry_run,
        ai_provider=provider,
        ai_model=model,
        ai_base_url=base_url or None,
        page_start=int(page_start) if page_start else None,
        page_end=int(page_end) if page_end else None,
        max_pages=None,
    )
    status = st.status("Preparing review…", expanded=True)
    progress_bar = status.progress(0)

    def progress(message: str, amount: float):
        status.write(message)
        progress_bar.progress(amount)

    temporary_path = save_uploaded_file(uploaded.name, uploaded.getvalue())
    try:
        ai_config = None
        if not dry_run:
            ai_config = AIConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url or None,
            )
        result = process_document(
            temporary_path,
            settings,
            ai_config=ai_config,
            progress=progress,
        )
        output_dir = ROOT / "outputs"
        report_path = generate_report(
            result,
            output_dir / "review_report.docx",
            ai_model=model if not dry_run else "Dry run / deterministic checks",
        )
        st.session_state["review_result"] = result
        st.session_state["report_path"] = str(report_path)
        status.update(label="Review complete", state="complete", expanded=False)
    except Exception as exc:
        status.update(label="Processing failed", state="error", expanded=True)
        st.exception(exc)

result = st.session_state.get("review_result")
if result:
    counts = {
        "Pages": result.metadata.page_count,
        "Blocks": len(result.blocks),
        "Confirmed pairs": sum(
            pair.pair_status == PairStatus.confirmed for pair in result.pairs
        ),
        "Manual review": sum(
            pair.pair_status != PairStatus.confirmed for pair in result.pairs
        ),
        "Findings": len(result.translation_findings)
        + len(result.regulatory_findings)
        + len(result.terminology_issues),
    }
    columns = st.columns(len(counts))
    for column, (label, value) in zip(columns, counts.items()):
        column.metric(label, value)

    tabs = st.tabs(
        [
            "Document",
            "Detected regulations",
            "Bilingual pairs",
            "Regulation consistency",
            "Findings",
            "Unpaired / manual review",
            "Downloads",
        ]
    )
    with tabs[0]:
        st.subheader("Uploaded document summary")
        st.json(
            {
                "filename": result.metadata.filename,
                "type": result.metadata.file_type,
                "pages": result.metadata.page_count,
                "warnings": result.metadata.warnings + result.processing_warnings,
                "token_usage": result.token_usage,
            }
        )
        st.subheader("Detected document structure")
        structure = pd.DataFrame(
            [
                {
                    "page": block.page,
                    "raw_page": block.raw_page,
                    "section": block.section,
                    "section_level": block.section_level,
                    "type": block.block_type,
                    "content_class": block.content_class,
                    "preserved_heading": block.is_preserved_heading,
                    "ignored": block.ignored,
                    "language": block.language,
                    "source": block.source,
                    "confidence": block.confidence,
                    "text": block.text,
                }
                for block in result.blocks
                if not block.ignored
            ]
        )
        st.dataframe(structure, width="stretch", hide_index=True)

    with tabs[1]:
        if result.regulations:
            st.markdown(
                "".join(
                    f'<span class="reg-chip">{html.escape(reg.name)}</span>'
                    for reg in result.regulations
                ),
                unsafe_allow_html=True,
            )
            st.dataframe(
                pd.DataFrame([reg.model_dump() for reg in result.regulations]),
                width="stretch",
                hide_index=True,
            )
        else:
            st.info("No regulation references were detected.")

    with tabs[2]:
        status_filter = st.multiselect(
            "Pair status",
            [status.value for status in PairStatus],
            default=[status.value for status in PairStatus],
        )
        alignment_pairs = [
            pair
            for pair in result.pairs
            if pair.chinese_text and pair.pair_status in status_filter
        ]
        alignment_rows = [
            {
                "ID": index,
                "Page": pair.page,
                "Section": pair.section,
                "Status": pair.pair_status,
                "Confidence": round(pair.pair_confidence, 3),
                "Original Chinese": pair.chinese_text,
                "New English Translation": pair.machine_translated_english,
                "Existing English": pair.english_text,
                "Pairing reason": pair.pairing_reason,
            }
            for index, pair in enumerate(alignment_pairs, start=1)
        ]
        st.subheader("Chinese-first alignment units")
        st.caption(
            "This view follows the review worksheet shape: Chinese source text is "
            "extracted first, translated by AI, then matched to the closest existing "
            "English content. English-only leftovers are kept in the manual-review tab."
        )
        st.dataframe(
            pd.DataFrame(alignment_rows),
            width="stretch",
            hide_index=True,
        )
        show_cards = st.checkbox("Show highlighted side-by-side cards", value=False)
        mismatch_ids = {
            finding.pair_id
            for finding in result.translation_findings
            if finding.issue_type in {"Meaning mismatch", "Added meaning", "Regulatory concern"}
            and finding.pair_id
        }
        if show_cards:
            for pair in alignment_pairs[:300]:
                st.markdown(pair_card(pair, mismatch_ids), unsafe_allow_html=True)
            if len(alignment_pairs) > 300:
                st.caption(f"Showing the first 300 of {len(alignment_pairs)} pairs.")

    with tabs[3]:
        st.subheader("Selected-regulation coverage matrix")
        if result.regulations:
            selected = result.regulations[0]
            st.caption(
                "This view maps the selected international regulation/standard to the "
                "company document chapter/subsection evidence. It highlights missing or "
                "weakly supported topics and their severity. It is an AI-assisted "
                "preliminary mapping, not certification or legal advice."
            )
            st.markdown(
                f'<span class="reg-chip">Selected target: {html.escape(selected.name)}</span>',
                unsafe_allow_html=True,
            )
            coverage_rows = build_regulatory_coverage_matrix(
                result.pairs,
                result.regulations,
                result.regulatory_findings,
            )
            severity_filter = st.multiselect(
                "Coverage severity",
                ["Critical", "Major", "Minor", "Observation", "None"],
                default=["Critical", "Major", "Minor", "Observation", "None"],
            )
            decision_filter = st.multiselect(
                "Coverage decision",
                sorted({row["Coverage decision"] for row in coverage_rows}),
                default=sorted({row["Coverage decision"] for row in coverage_rows}),
            )
            shown_coverage = [
                row
                for row in coverage_rows
                if row["Severity"] in severity_filter
                and row["Coverage decision"] in decision_filter
            ]
            st.dataframe(
                pd.DataFrame(shown_coverage),
                width="stretch",
                hide_index=True,
            )
            missing_or_major = [
                row
                for row in coverage_rows
                if row["Severity"] in {"Critical", "Major"}
                or row["Coverage decision"] in {"Missing Evidence", "Confirmed Conflict"}
            ]
            if missing_or_major:
                st.subheader("Missing / high-severity regulatory topics")
                st.dataframe(
                    pd.DataFrame(missing_or_major),
                    width="stretch",
                    hide_index=True,
                )
        else:
            st.info("No selected regulation is available. Enable regulation review and reprocess the document.")

    with tabs[4]:
        threshold = severity_rank(severity_threshold)
        translation_rows = [
            finding.model_dump()
            for finding in result.translation_findings
            if severity_rank(finding.severity.value) >= threshold
        ]
        regulatory_rows = [
            finding.model_dump()
            for finding in result.regulatory_findings
            if severity_rank(finding.severity.value) >= threshold
        ]
        terminology_rows = [
            issue.model_dump()
            for issue in result.terminology_issues
            if severity_rank(issue.severity.value) >= threshold
        ]
        st.subheader("Translation equivalence")
        st.dataframe(pd.DataFrame(translation_rows), width="stretch", hide_index=True)
        st.subheader("Regulatory consistency")
        st.dataframe(pd.DataFrame(regulatory_rows), width="stretch", hide_index=True)
        st.subheader("Terminology consistency")
        st.dataframe(pd.DataFrame(terminology_rows), width="stretch", hide_index=True)

    with tabs[5]:
        manual = [
            pair.model_dump()
            for pair in result.pairs
            if pair.needs_manual_review or pair.pair_status != PairStatus.confirmed
        ]
        st.dataframe(pd.DataFrame(manual), width="stretch", hide_index=True)

    with tabs[6]:
        st.warning(
            "AI-assisted preliminary review only. Final decisions require qualified "
            "regulatory and quality professionals."
        )
        report_path = Path(st.session_state["report_path"])
        st.download_button(
            "Download Review Report (.docx)",
            report_path.read_bytes(),
            file_name="review_report.docx",
            mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            type="primary",
        )
