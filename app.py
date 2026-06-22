from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
from io import BytesIO

import pandas as pd
import streamlit as st

from src.block_cleaner import mark_repeated_headers_footers
from src.bilingual_pairer import pair_chunks
from src.chunker import build_chunks
from src.coverage_validator import validate_coverage
from src.file_loader import load_uploaded_file
from src.highlight_renderer import render_highlighted_document
from src.regulation_checker import review_regulations
from src.regulation_detector import detect_regulations
from src.report_generator import (
    build_final_report,
    ensure_output_dir,
    save_csv,
    save_final_report,
    save_json,
)
from src.section_parser import parse_sections
from src.terminology_checker import check_terminology
from src.text_extractor import extract_document
from src.translation_checker import check_translations


OUTPUT_DIR = Path("outputs")
PAIR_STATUSES = [
    "paired", "uncertain", "missing_english", "missing_chinese",
    "standalone", "unpaired",
]

st.set_page_config(page_title="Bilingual Document Review Assistant", page_icon="🔎", layout="wide")


def build_coverage_rows(
    docs,
    detected_pairs,
    reviewed_pairs,
    unpaired_rows,
    skipped_rows,
    analyses_by_file,
    options,
):
    """Compatibility summary used by the original project tests and reports."""
    page_rows: list[dict] = []
    section_rows: list[dict] = []
    for doc in docs:
        sections: dict[str, dict] = {}
        for block in doc.blocks:
            section_id = block.section_id or "Unsectioned"
            item = sections.setdefault(section_id, {
                "file name": doc.file_name,
                "section": section_id,
                "total blocks": 0,
                "paired blocks": 0,
                "unpaired blocks": 0,
            })
            item["total blocks"] += 1
        analysis = analyses_by_file.get(doc.file_name)
        if analysis:
            for block_id, pair_id in analysis.block_to_pair.items():
                block = next((value for value in doc.blocks if value.block_id == block_id), None)
                if block:
                    sections.setdefault(block.section_id or "Unsectioned", {
                        "file name": doc.file_name, "section": block.section_id or "Unsectioned",
                        "total blocks": 0, "paired blocks": 0, "unpaired blocks": 0,
                    })["paired blocks"] += 1
        for row in unpaired_rows:
            if row.get("file name") != doc.file_name:
                continue
            section_id = row.get("section_id") or "Unsectioned"
            sections.setdefault(section_id, {
                "file name": doc.file_name, "section": section_id,
                "total blocks": 0, "paired blocks": 0, "unpaired blocks": 0,
            })["unpaired blocks"] += 1
        for item in sections.values():
            if item["unpaired blocks"] and item["paired blocks"]:
                item["status"] = "Partial coverage"
            elif item["unpaired blocks"]:
                item["status"] = "Unpaired content"
            elif item["paired blocks"]:
                item["status"] = "Covered"
            else:
                item["status"] = "Not reviewed"
            section_rows.append(item)
    return page_rows, section_rows


def initialise_state() -> None:
    defaults = {
        "api_key": "",
        "base_url": "",
        "model": "gpt-4o-mini",
        "document_name": "",
        "raw_blocks": [],
        "blocks": [],
        "chunks": [],
        "pairs": [],
        "reviewed_pairs": [],
        "block_statuses": [],
        "coverage_df": pd.DataFrame(),
        "coverage_summary": {},
        "translation_findings": [],
        "terminology_findings": [],
        "regulation_references": [],
        "regulation_review": [],
        "pairing_warnings": [],
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)
    ensure_output_dir(OUTPUT_DIR)


def api_settings() -> tuple[str, str, str]:
    return (
        st.session_state["api_key"],
        st.session_state["model"],
        st.session_state["base_url"],
    )


def require_blocks() -> bool:
    if not st.session_state["blocks"]:
        st.warning("Extract, clean, and section a document first.")
        return False
    return True


def require_pairs() -> bool:
    if not st.session_state["reviewed_pairs"]:
        st.warning("Run AI pairing first. Only confirmed pairs are checked.")
        return False
    return True


def require_api() -> bool:
    key, model, _ = api_settings()
    if not key.strip():
        st.error("Enter an API key in Upload & Settings.")
        return False
    if not model.strip():
        st.error("Enter an AI model name in Upload & Settings.")
        return False
    return True


def reset_downstream() -> None:
    for key, value in {
        "chunks": [], "pairs": [], "reviewed_pairs": [], "block_statuses": [],
        "coverage_df": pd.DataFrame(), "coverage_summary": {},
        "translation_findings": [], "terminology_findings": [],
        "regulation_references": [], "regulation_review": [], "pairing_warnings": [],
    }.items():
        st.session_state[key] = value


def status_rows_from_pairs(pairs: list[dict]) -> list[dict]:
    existing = {row["block_id"]: dict(row) for row in st.session_state["block_statuses"]}
    paired_ids: dict[str, str] = {}
    for pair in pairs:
        if pair.get("status") not in {"paired", "uncertain"}:
            continue
        for block_id in pair.get("chinese_block_ids", []) + pair.get("english_block_ids", []):
            paired_ids[block_id] = pair["pair_id"]
    for block in st.session_state["blocks"]:
        block_id = block["block_id"]
        if block["block_type"] == "header_footer":
            existing[block_id] = {"block_id": block_id, "status": "header_footer", "pair_id": None}
        elif block_id in paired_ids:
            pair = next(item for item in pairs if item["pair_id"] == paired_ids[block_id])
            existing[block_id] = {
                "block_id": block_id,
                "status": pair.get("status", "paired"),
                "pair_id": paired_ids[block_id],
            }
        elif existing.get(block_id, {}).get("pair_id"):
            existing[block_id] = {"block_id": block_id, "status": "unpaired", "pair_id": None}
        else:
            existing.setdefault(block_id, {"block_id": block_id, "status": "unpaired", "pair_id": None})
    return list(existing.values())


def render_upload_tab() -> None:
    st.subheader("Upload & Settings")
    left, right = st.columns([1.15, 1])
    with left:
        uploaded = st.file_uploader("Bilingual document", type=["pdf", "docx", "txt"])
        st.checkbox(
            "Include repeated headers and footers in AI pairing",
            value=False,
            key="include_headers",
            help="They always remain in extracted_blocks.json. The default is to exclude them from pairing.",
        )
        if st.button("1. Extract document", type="primary", use_container_width=True):
            try:
                name, data = load_uploaded_file(uploaded)
                with st.spinner("Extracting paragraphs, headings, and table rows…"):
                    blocks = extract_document(name, data)
                st.session_state["document_name"] = name
                st.session_state["raw_blocks"] = blocks
                st.session_state["blocks"] = blocks
                reset_downstream()
                save_json("extracted_blocks.json", blocks, OUTPUT_DIR)
                st.success(f"Extracted {len(blocks)} blocks from {name}.")
            except Exception as exc:
                st.error(f"Extraction failed: {exc}")
        if st.button("2. Clean and section document", use_container_width=True):
            if not st.session_state["raw_blocks"]:
                st.warning("Extract a document first.")
            else:
                blocks = [dict(item) for item in st.session_state["raw_blocks"]]
                blocks = mark_repeated_headers_footers(blocks)
                blocks = parse_sections(blocks)
                chunks = build_chunks(blocks, st.session_state["include_headers"])
                st.session_state["blocks"] = blocks
                st.session_state["chunks"] = chunks
                reset_downstream()
                st.session_state["chunks"] = chunks
                save_json("sectioned_blocks.json", blocks, OUTPUT_DIR)
                save_json("chunks.json", chunks, OUTPUT_DIR)
                st.success(f"Created {len(chunks)} AI chunks without using page boundaries as sections.")
    with right:
        st.text_input(
            "AI API key",
            type="password",
            key="api_key",
            help="Kept only in Streamlit session_state. It is never written to output files.",
        )
        st.text_input(
            "OpenAI-compatible base URL (optional)",
            key="base_url",
            placeholder="https://api.openai.com/v1",
        )
        st.text_input("AI model", key="model", placeholder="gpt-4o-mini")
        st.info(
            "Python extracts and tracks every block. AI performs semantic pairing. "
            "The reviewer remains advisory: uncertain and unpaired content is preserved, not forced."
        )

    if st.session_state["blocks"]:
        header_count = sum(b["block_type"] == "header_footer" for b in st.session_state["blocks"])
        table_count = sum(b["block_type"] == "table_row" for b in st.session_state["blocks"])
        c1, c2, c3 = st.columns(3)
        c1.metric("Extracted blocks", len(st.session_state["blocks"]))
        c2.metric("Table rows", table_count)
        c3.metric("Headers/footers marked", header_count)


def render_extraction_tab() -> None:
    st.subheader("Extraction Preview")
    if not st.session_state["blocks"]:
        st.info("Extract a document to inspect every captured block.")
        return
    blocks = st.session_state["blocks"]
    pages = sorted({int(item.get("page") or 1) for item in blocks})
    selected_pages = st.multiselect("Pages", pages, default=pages[: min(5, len(pages))])
    block_types = sorted({item["block_type"] for item in blocks})
    selected_types = st.multiselect("Block types", block_types, default=block_types)
    rows = [
        item for item in blocks
        if int(item.get("page") or 1) in selected_pages and item["block_type"] in selected_types
    ]
    st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True, height=560)
    if st.session_state["chunks"]:
        with st.expander(f"Chunk preview ({len(st.session_state['chunks'])} chunks)"):
            st.json(st.session_state["chunks"][:3], expanded=False)


def render_pairing_tab() -> None:
    st.subheader("AI Pairing")
    if st.button("3. Run AI pairing", type="primary"):
        if require_blocks() and require_api():
            try:
                chunks = st.session_state["chunks"] or build_chunks(
                    st.session_state["blocks"], st.session_state.get("include_headers", False)
                )
                st.session_state["chunks"] = chunks
                save_json("chunks.json", chunks, OUTPUT_DIR)
                progress = st.progress(0, text="Pairing document chunks…")
                key, model, base_url = api_settings()
                result = pair_chunks(
                    chunks, key, model, base_url,
                    lambda done, total: progress.progress(
                        done / max(total, 1), text=f"Paired {done} of {total} chunks"
                    ),
                )
                progress.empty()
                st.session_state["pairs"] = result["pairs"]
                st.session_state["reviewed_pairs"] = [dict(item) for item in result["pairs"]]
                st.session_state["block_statuses"] = result["block_statuses"]
                st.session_state["pairing_warnings"] = result["warnings"]
                coverage_df, summary = validate_coverage(
                    st.session_state["blocks"], result["block_statuses"]
                )
                st.session_state["coverage_df"] = coverage_df
                st.session_state["coverage_summary"] = summary
                save_json("ai_pairs_raw.json", result, OUTPUT_DIR)
                save_json("reviewed_pairs.json", result["pairs"], OUTPUT_DIR)
                save_csv("coverage_report.csv", coverage_df, OUTPUT_DIR)
                st.success(f"AI returned {len(result['pairs'])} candidate pairs.")
            except Exception as exc:
                st.error(f"AI pairing failed: {exc}")

    if st.session_state["pairing_warnings"]:
        with st.expander(f"Pairing warnings ({len(st.session_state['pairing_warnings'])})"):
            for warning in st.session_state["pairing_warnings"]:
                st.warning(warning)

    summary = st.session_state["coverage_summary"]
    if summary:
        columns = st.columns(4)
        for index, (label, value) in enumerate(summary.items()):
            columns[index % 4].metric(label.title(), value)

    pairs = st.session_state["reviewed_pairs"]
    if not pairs:
        st.info("Run pairing to view and optionally review candidate pairs.")
        return
    confidence_limit = st.slider("Maximum confidence to show", 0.0, 1.0, 1.0, 0.05)
    status_filter = st.multiselect("Statuses", PAIR_STATUSES, default=PAIR_STATUSES)
    visible = [
        item for item in pairs
        if float(item.get("confidence", 0)) <= confidence_limit
        and item.get("status", "paired") in status_filter
    ]
    editor_rows = [{
        "keep": True,
        "pair_id": item["pair_id"],
        "status": item.get("status", "paired"),
        "confidence": item.get("confidence", 0),
        "chinese_text": item.get("chinese_text", ""),
        "english_text": item.get("english_text", ""),
        "pairing_reason": item.get("pairing_reason", ""),
    } for item in visible]
    edited = st.data_editor(
        pd.DataFrame(editor_rows),
        use_container_width=True,
        hide_index=True,
        disabled=["pair_id", "confidence", "chinese_text", "english_text", "pairing_reason"],
        column_config={
            "status": st.column_config.SelectboxColumn("status", options=PAIR_STATUSES),
            "keep": st.column_config.CheckboxColumn("keep"),
        },
        key="pair_editor",
    )
    if st.button("Save optional pair review"):
        changes = {row["pair_id"]: row for row in edited.to_dict("records")}
        reviewed: list[dict] = []
        for pair in pairs:
            change = changes.get(pair["pair_id"])
            if change and not change["keep"]:
                continue
            updated = dict(pair)
            if change:
                updated["status"] = change["status"]
            reviewed.append(updated)
        st.session_state["reviewed_pairs"] = reviewed
        st.session_state["block_statuses"] = status_rows_from_pairs(reviewed)
        coverage_df, summary = validate_coverage(
            st.session_state["blocks"], st.session_state["block_statuses"]
        )
        st.session_state["coverage_df"] = coverage_df
        st.session_state["coverage_summary"] = summary
        save_json("reviewed_pairs.json", reviewed, OUTPUT_DIR)
        save_csv("coverage_report.csv", coverage_df, OUTPUT_DIR)
        st.success("Pair review saved. Deleted pairs are returned to unattended/unpaired status.")

    if not st.session_state["coverage_df"].empty:
        with st.expander("Full block coverage report"):
            st.dataframe(st.session_state["coverage_df"], use_container_width=True, hide_index=True)


def render_highlight_tab() -> None:
    st.subheader("Highlighted Pair Viewer")
    if not require_blocks():
        return
    show_headers = st.toggle("Show repeated headers and footers", value=False)
    html_view = render_highlighted_document(
        st.session_state["blocks"],
        st.session_state["reviewed_pairs"],
        st.session_state["block_statuses"],
        show_headers,
    )
    st.markdown(
        """<style>
        .doc-page{border-top:3px solid #d9e2ec;margin:24px 0;padding-top:8px}
        .pair-label{font-size:11px;font-weight:700;float:right;color:#445}
        </style>""",
        unsafe_allow_html=True,
    )
    st.markdown(html_view, unsafe_allow_html=True)
    pairs = st.session_state["reviewed_pairs"]
    if pairs:
        st.divider()
        st.caption("Pair details")
        for pair in pairs:
            with st.expander(
                f"{pair['pair_id']} · {pair.get('status', 'paired')} · confidence {pair.get('confidence', 0):.2f}"
            ):
                st.write({
                    "Chinese": pair.get("chinese_text", ""),
                    "English": pair.get("english_text", ""),
                    "Chinese block IDs": pair.get("chinese_block_ids", []),
                    "English block IDs": pair.get("english_block_ids", []),
                    "Pairing reason": pair.get("pairing_reason", ""),
                })


def render_translation_tab() -> None:
    st.subheader("Translation Check")
    st.caption("Only pairs with status “paired” are sent for translation checking.")
    if st.button("5. Run translation check", type="primary"):
        if require_pairs() and require_api():
            try:
                progress = st.progress(0, text="Reviewing confirmed translations…")
                key, model, base_url = api_settings()
                block_by_id = {item["block_id"]: item for item in st.session_state["blocks"]}
                findings = check_translations(
                    st.session_state["reviewed_pairs"], block_by_id, key, model, base_url,
                    lambda done, total: progress.progress(
                        done / max(total, 1), text=f"Reviewed {done} of {total} pairs"
                    ),
                )
                progress.empty()
                st.session_state["translation_findings"] = findings
                save_json("translation_issues.json", findings, OUTPUT_DIR)
                save_csv("translation_issues.csv", findings, OUTPUT_DIR)
                st.success(f"Reviewed {len(findings)} confirmed pairs.")
            except Exception as exc:
                st.error(f"Translation check failed: {exc}")
    if st.session_state["translation_findings"]:
        st.dataframe(pd.DataFrame(st.session_state["translation_findings"]), use_container_width=True, hide_index=True)


def render_terminology_tab() -> None:
    st.subheader("Terminology Consistency")
    if st.button("6. Run terminology check", type="primary"):
        if require_pairs() and require_api():
            try:
                key, model, base_url = api_settings()
                with st.spinner("Building a document-wide terminology table…"):
                    findings = check_terminology(
                        st.session_state["reviewed_pairs"], key, model, base_url
                    )
                st.session_state["terminology_findings"] = findings
                save_json("terminology_consistency.json", findings, OUTPUT_DIR)
                save_csv("terminology_consistency.csv", findings, OUTPUT_DIR)
                st.success(f"Terminology review produced {len(findings)} findings.")
            except Exception as exc:
                st.error(f"Terminology check failed: {exc}")
    if st.session_state["terminology_findings"]:
        st.dataframe(pd.DataFrame(st.session_state["terminology_findings"]), use_container_width=True, hide_index=True)


def render_regulation_tab() -> None:
    st.subheader("Regulation Review")
    if st.button("Detect regulation references"):
        if require_blocks():
            references = detect_regulations(st.session_state["blocks"])
            st.session_state["regulation_references"] = references
            save_json("regulation_references.json", references, OUTPUT_DIR)
            save_csv("regulation_references.csv", references, OUTPUT_DIR)
            st.success(f"Detected {len(references)} regulation or standard references.")
    if st.session_state["regulation_references"]:
        st.dataframe(pd.DataFrame(st.session_state["regulation_references"]), use_container_width=True, hide_index=True)
    if st.button("7. Run regulation review", type="primary"):
        if require_pairs() and require_api():
            try:
                references = st.session_state["regulation_references"] or detect_regulations(
                    st.session_state["blocks"]
                )
                st.session_state["regulation_references"] = references
                key, model, base_url = api_settings()
                with st.spinner("Reviewing references cautiously against available evidence…"):
                    findings = review_regulations(
                        references, st.session_state["reviewed_pairs"], key, model, base_url
                    )
                st.session_state["regulation_review"] = findings
                save_json("regulation_references.json", references, OUTPUT_DIR)
                save_csv("regulation_references.csv", references, OUTPUT_DIR)
                save_json("regulation_review.json", findings, OUTPUT_DIR)
                save_csv("regulation_review.csv", findings, OUTPUT_DIR)
                st.success(f"Regulation review produced {len(findings)} findings.")
            except Exception as exc:
                st.error(f"Regulation review failed: {exc}")
    if st.session_state["regulation_review"]:
        st.dataframe(pd.DataFrame(st.session_state["regulation_review"]), use_container_width=True, hide_index=True)
    st.warning(
        "Regulatory findings are advisory. Where official source text is unavailable, the app must return "
        "“Unable to verify fully because official regulation text is not available.”"
    )


def zip_outputs() -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        for path in sorted(OUTPUT_DIR.glob("*")):
            if path.is_file():
                archive.write(path, path.name)
    return buffer.getvalue()


def render_export_tab() -> None:
    st.subheader("Export Report")
    if st.button("8. Export reports", type="primary"):
        if not require_blocks():
            return
        try:
            pairs = st.session_state["reviewed_pairs"]
            statuses = st.session_state["block_statuses"]
            if not statuses:
                statuses = status_rows_from_pairs(pairs)
                st.session_state["block_statuses"] = statuses
            coverage_df, summary = validate_coverage(st.session_state["blocks"], statuses)
            st.session_state["coverage_df"] = coverage_df
            st.session_state["coverage_summary"] = summary

            save_json("extracted_blocks.json", st.session_state["raw_blocks"], OUTPUT_DIR)
            save_json("sectioned_blocks.json", st.session_state["blocks"], OUTPUT_DIR)
            save_json("chunks.json", st.session_state["chunks"], OUTPUT_DIR)
            save_json("ai_pairs_raw.json", {
                "pairs": st.session_state["pairs"],
                "block_statuses": statuses,
                "warnings": st.session_state["pairing_warnings"],
            }, OUTPUT_DIR)
            save_json("reviewed_pairs.json", pairs, OUTPUT_DIR)
            save_csv("coverage_report.csv", coverage_df, OUTPUT_DIR)
            save_json("translation_issues.json", st.session_state["translation_findings"], OUTPUT_DIR)
            save_csv("translation_issues.csv", st.session_state["translation_findings"], OUTPUT_DIR)
            save_json("terminology_consistency.json", st.session_state["terminology_findings"], OUTPUT_DIR)
            save_csv("terminology_consistency.csv", st.session_state["terminology_findings"], OUTPUT_DIR)
            save_json("regulation_references.json", st.session_state["regulation_references"], OUTPUT_DIR)
            save_csv("regulation_references.csv", st.session_state["regulation_references"], OUTPUT_DIR)
            save_json("regulation_review.json", st.session_state["regulation_review"], OUTPUT_DIR)
            save_csv("regulation_review.csv", st.session_state["regulation_review"], OUTPUT_DIR)
            report = build_final_report(
                st.session_state["document_name"],
                st.session_state["blocks"],
                pairs,
                statuses,
                summary,
                st.session_state["translation_findings"],
                st.session_state["terminology_findings"],
                st.session_state["regulation_references"],
                st.session_state["regulation_review"],
            )
            save_final_report(report, OUTPUT_DIR)
            st.session_state["final_report_html"] = report
            st.success("All JSON, CSV, and HTML reports were written to outputs/.")
        except Exception as exc:
            st.error(f"Report export failed: {exc}")

    report = st.session_state.get("final_report_html")
    if report:
        st.download_button(
            "Download final_report.html",
            report.encode("utf-8"),
            file_name="final_report.html",
            mime="text/html",
        )
        st.download_button(
            "Download all outputs (.zip)",
            zip_outputs(),
            file_name="bilingual_review_outputs.zip",
            mime="application/zip",
        )
    expected = [
        "extracted_blocks.json", "sectioned_blocks.json", "chunks.json",
        "ai_pairs_raw.json", "reviewed_pairs.json", "coverage_report.csv",
        "translation_issues.csv", "terminology_consistency.csv",
        "regulation_references.csv", "regulation_review.csv", "final_report.html",
    ]
    st.write("Required output artifacts")
    st.dataframe(pd.DataFrame({
        "file": expected,
        "ready": [(OUTPUT_DIR / name).exists() for name in expected],
    }), use_container_width=True, hide_index=True)


def main() -> None:
    initialise_state()
    st.title("Bilingual Chinese-English Document Review Assistant")
    st.caption(
        "Extract every document block, pair Chinese and English semantically, highlight matched text, "
        "and review translation, terminology, and regulatory consistency."
    )
    tabs = st.tabs([
        "1. Upload & Settings",
        "2. Extraction Preview",
        "3. AI Pairing",
        "4. Highlighted Pair Viewer",
        "5. Translation Check",
        "6. Terminology Consistency",
        "7. Regulation Review",
        "8. Export Report",
    ])
    renderers = [
        render_upload_tab, render_extraction_tab, render_pairing_tab, render_highlight_tab,
        render_translation_tab, render_terminology_tab, render_regulation_tab, render_export_tab,
    ]
    for tab, renderer in zip(tabs, renderers):
        with tab:
            renderer()


if __name__ == "__main__":
    main()
