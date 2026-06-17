from __future__ import annotations

import pandas as pd
import re
import streamlit as st
from rapidfuzz import fuzz

from src.api_pairing import identify_bilingual_pairs_with_api
from src.bilingual_pairing import build_document_summary, identify_bilingual_pairs
from src.export_report import build_excel_report, build_word_report
from src.extractors import extract_uploaded_file
from src.llm_client import get_llm_config, provider_key_label
from src.paragraph_api_review import api_rows_to_translation_issues, review_paragraph_pairs_with_api
from src.reference_comparison import compare_with_references
from src.regulation_detection import detect_regulatory_references
from src.terminology_review import review_terminology
from src.translation_review import review_translation_pairs
from src.utils import BilingualPair, DocumentResult, TextBlock, dataclasses_to_records


st.set_page_config(
    page_title="Bilingual Regulatory Review",
    page_icon="📄",
    layout="wide",
)


def main() -> None:
    st.title("Bilingual Chinese-English Regulatory Document Review")
    st.caption("Chinese source text is treated as the controlling version for all review findings.")

    init_state()
    render_upload_section()

    docs: list[DocumentResult] = st.session_state["docs"]
    refs: list[DocumentResult] = st.session_state["refs"]
    if not docs:
        st.info("Upload one or more bilingual DOCX, PDF, or TXT documents to begin.")
        return

    with st.spinner("Analyzing documents..."):
        pairs_by_file: dict[str, list[BilingualPair]] = {}
        pairing_warnings: list[str] = []
        for doc in docs:
            deterministic_pairs = identify_bilingual_pairs(doc)
            if st.session_state["use_api_pairing"]:
                pairs, warnings = identify_bilingual_pairs_with_api(
                    doc,
                    deterministic_pairs,
                    model=st.session_state["model_name"],
                )
                pairs_by_file[doc.file_name] = pairs
                pairing_warnings.extend(warnings)
            else:
                pairs_by_file[doc.file_name] = deterministic_pairs
        all_pairs = [pair for pairs in pairs_by_file.values() for pair in pairs]
        all_blocks = [block for doc in docs for block in doc.blocks]
        selected_scope = selected_review_section_option(docs)
        paragraph_review_pairs = filter_paragraph_review_pairs(all_pairs, all_blocks, selected_scope)
        api_config = get_llm_config(st.session_state["model_name"])
        translation_issues, translation_warnings = review_translation_pairs(
            paragraph_review_pairs,
            use_llm=False,
            model=st.session_state["model_name"],
        )
        api_paragraph_rows: list[dict] = []
        api_paragraph_warnings: list[str] = []
        if st.session_state["use_paragraph_api"]:
            api_paragraph_rows, api_paragraph_warnings = review_paragraph_pairs_with_api(
                paragraph_review_pairs,
                model=st.session_state["model_name"],
                config=api_config,
            )
            translation_issues.extend(api_rows_to_translation_issues(api_paragraph_rows))
            translation_warnings.extend(api_paragraph_warnings)
        terminology_issues = review_terminology(all_blocks, all_pairs)
        regulatory_refs = detect_regulatory_references(all_blocks)
        reference_rows, reference_warnings = compare_with_references(
            all_pairs,
            refs,
            use_llm=st.session_state["use_reference_api"],
            model=st.session_state["model_name"],
        )

    render_summary(docs, pairs_by_file)
    render_pair_review(all_pairs, pairing_warnings)
    render_api_paragraph_review(api_paragraph_rows, api_paragraph_warnings, api_config.provider, api_config.model, len(paragraph_review_pairs), len(all_pairs), str(selected_scope["label"]))
    render_translation_report(translation_issues, translation_warnings, api_config.provider, st.session_state["use_paragraph_api"], len(paragraph_review_pairs), len(all_pairs), str(selected_scope["label"]))
    render_terminology_report(terminology_issues)
    render_regulatory_report(regulatory_refs)
    render_reference_comparison(reference_rows, reference_warnings)
    render_export(all_pairs, api_paragraph_rows, translation_issues, terminology_issues, regulatory_refs, reference_rows)


def init_state() -> None:
    st.session_state.setdefault("docs", [])
    st.session_state.setdefault("refs", [])
    st.session_state.setdefault("use_api_pairing", True)
    st.session_state.setdefault("use_paragraph_api", True)
    st.session_state.setdefault("use_reference_api", False)
    st.session_state.setdefault("api_provider", "DeepSeek")
    st.session_state.setdefault("api_key", "")
    st.session_state.setdefault("api_base_url", "https://api.deepseek.com")
    st.session_state.setdefault("model_name", "deepseek-v4-flash")
    st.session_state.setdefault("review_section_key", "__all_from_1__")


def render_upload_section() -> None:
    with st.sidebar:
        st.header("A. Upload files")
        uploaded_docs = st.file_uploader(
            "Bilingual documents",
            type=["docx", "pdf", "txt"],
            accept_multiple_files=True,
        )
        uploaded_refs = st.file_uploader(
            "Optional reference regulation documents",
            type=["docx", "pdf", "txt"],
            accept_multiple_files=True,
        )
        st.toggle(
            "Use API for Part C bilingual pair detection",
            key="use_api_pairing",
        )
        st.toggle(
            "Use API for paragraph translation review",
            key="use_paragraph_api",
        )
        st.toggle(
            "Use API for reference comparison",
            key="use_reference_api",
        )
        st.selectbox(
            "API provider",
            ["DeepSeek", "OpenAI", "OpenAI-compatible", "Anthropic"],
            index=["DeepSeek", "OpenAI", "OpenAI-compatible", "Anthropic"].index(st.session_state["api_provider"]),
            key="api_provider",
        )
        if st.session_state["api_provider"] == "DeepSeek" and st.session_state["model_name"] in {"gpt-4o-mini", ""}:
            st.session_state["model_name"] = "deepseek-v4-flash"
        if st.session_state["api_provider"] == "DeepSeek" and not st.session_state["api_base_url"]:
            st.session_state["api_base_url"] = "https://api.deepseek.com"
        st.text_input(
            provider_key_label(st.session_state["api_provider"]),
            type="password",
            help="Stored only in this Streamlit session. You can also use LLM_API_KEY, DEEPSEEK_API_KEY, OPENAI_API_KEY, ANTHROPIC_API_KEY, or Streamlit secrets.",
            key="api_key",
        )
        if st.session_state["api_provider"] in {"DeepSeek", "OpenAI-compatible"}:
            st.text_input(
                "API base URL",
                placeholder="https://api.example.com/v1",
                key="api_base_url",
            )
        st.text_input("Model", key="model_name")

        if st.button("Extract and review", type="primary"):
            st.session_state["docs"] = load_uploads(uploaded_docs, "bilingual")
            st.session_state["refs"] = load_uploads(uploaded_refs, "reference")

        section_options = build_review_section_options(st.session_state["docs"])
        option_keys = [option["key"] for option in section_options]
        if st.session_state["review_section_key"] not in option_keys:
            st.session_state["review_section_key"] = "__all_from_1__"
        st.selectbox(
            "Review section / chapter",
            option_keys,
            key="review_section_key",
            format_func={option["key"]: option["label"] for option in section_options}.get,
        )


def load_uploads(uploaded_files, label: str) -> list[DocumentResult]:
    results: list[DocumentResult] = []
    for uploaded in uploaded_files or []:
        try:
            results.append(extract_uploaded_file(uploaded.name, uploaded.getvalue()))
        except Exception as exc:
            st.error(f"Could not process {label} file {uploaded.name}: {exc}")
    return results


def build_review_section_options(docs: list[DocumentResult]) -> list[dict[str, object]]:
    options: list[dict[str, object]] = [
        {
            "key": "__all_from_1__",
            "label": "All documents: from point 1 onward",
            "file_name": None,
            "start_order": None,
            "end_order": None,
        }
    ]
    for doc in docs:
        sections = detect_numbered_sections(doc.blocks)
        for idx, section in enumerate(sections):
            end_order = next(
                (
                    later["order"]
                    for later in sections[idx + 1 :]
                    if later["level"] <= section["level"]
                ),
                None,
            )
            options.append(
                {
                    "key": f"{doc.file_name}::{section['number']}::{section['order']}",
                    "label": f"{doc.file_name}: {section['number']} {section['title']}",
                    "file_name": doc.file_name,
                    "start_order": section["order"],
                    "end_order": end_order,
                }
            )
    return options


def detect_numbered_sections(blocks: list[TextBlock]) -> list[dict[str, object]]:
    sections: list[dict[str, object]] = []
    for block in sorted(blocks, key=lambda item: item.order):
        text = block.text.strip()
        match = re.match(r"^(\d+(?:\.\d+)*)(?:\s|[\.、．):：-])\s*(.+)?", text)
        if not match:
            continue
        number = match.group(1)
        title = (match.group(2) or "").strip()
        sections.append(
            {
                "number": number,
                "title": title[:100],
                "order": block.order,
                "level": number.count(".") + 1,
            }
        )
    return sections


def selected_review_section_option(docs: list[DocumentResult]) -> dict[str, object]:
    options = build_review_section_options(docs)
    selected_key = st.session_state.get("review_section_key", "__all_from_1__")
    return next((option for option in options if option["key"] == selected_key), options[0])


def filter_paragraph_review_pairs(pairs: list[BilingualPair], blocks: list[TextBlock], selected: dict[str, object]) -> list[BilingualPair]:
    block_by_id = {block.block_id: block for block in blocks}
    blocks_by_file: dict[str, list[TextBlock]] = {}
    for block in blocks:
        blocks_by_file.setdefault(block.file_name, []).append(block)
    first_point_by_file = {
        file_name: find_first_numbered_point_order(file_blocks)
        for file_name, file_blocks in blocks_by_file.items()
    }
    review_pairs: list[BilingualPair] = []
    for pair in pairs:
        pair_order = infer_pair_order(pair, blocks_by_file.get(pair.file_name, []), block_by_id)
        if selected["key"] == "__all_from_1__":
            first_point_order = first_point_by_file.get(pair.file_name)
            if first_point_order is not None and pair_order is not None and pair_order < first_point_order:
                continue
        else:
            if pair.file_name != selected["file_name"]:
                continue
            start_order = selected["start_order"]
            end_order = selected["end_order"]
            if pair_order is None:
                continue
            if start_order is not None and pair_order < int(start_order):
                continue
            if end_order is not None and pair_order >= int(end_order):
                continue
        review_pairs.append(pair)
    return review_pairs


def infer_pair_order(pair: BilingualPair, file_blocks: list[TextBlock], block_by_id: dict[str, TextBlock]) -> int | None:
    matched_blocks = [
        block
        for block in (
            block_by_id.get(pair.chinese_block_id or ""),
            block_by_id.get(pair.english_block_id or ""),
        )
        if block
    ]
    if not matched_blocks:
        matched_blocks = [
            block
            for block in (
                match_pair_text_to_block(pair.chinese_text, file_blocks),
                match_pair_text_to_block(pair.english_text, file_blocks),
            )
            if block
        ]
    if not matched_blocks and pair.page_number is not None:
        matched_blocks = [block for block in file_blocks if block.page_number == pair.page_number]
    return min((block.order for block in matched_blocks), default=None)


def match_pair_text_to_block(text: str, blocks: list[TextBlock]) -> TextBlock | None:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return None
    for block in blocks:
        block_text = re.sub(r"\s+", " ", block.text or "").strip()
        if clean in block_text or block_text in clean:
            return block
    best_block: TextBlock | None = None
    best_score = 0
    needle = clean[:300]
    for block in blocks:
        score = fuzz.partial_ratio(needle, re.sub(r"\s+", " ", block.text or "").strip()[:500])
        if score > best_score:
            best_block = block
            best_score = score
    return best_block if best_score >= 82 else None


def find_first_numbered_point_order(blocks: list[TextBlock]) -> int | None:
    for block in sorted(blocks, key=lambda item: item.order):
        text = block.text.strip()
        if re.match(r"^(?:1|1\.0|1\.1)(?:\s|[\.、．):：-])", text):
            return block.order
    return None


def render_summary(docs: list[DocumentResult], pairs_by_file: dict[str, list[BilingualPair]]) -> None:
    st.header("B. Document summary")
    summaries = [build_document_summary(doc, pairs_by_file.get(doc.file_name, [])) for doc in docs]
    st.dataframe(pd.DataFrame(summaries), width="stretch", hide_index=True)
    for doc in docs:
        for warning in doc.warnings:
            st.warning(f"{doc.file_name}: {warning}")
        if not pairs_by_file.get(doc.file_name):
            st.warning(f"{doc.file_name}: No likely bilingual Chinese-English pairs were detected.")


def render_pair_review(pairs: list[BilingualPair], warnings: list[str]) -> None:
    st.header("C. Bilingual pair review")
    for warning in warnings:
        st.info(warning)
    if not pairs:
        st.info("No bilingual pairs detected.")
        return
    pair_records = dataclasses_to_records(pairs)
    st.dataframe(pd.DataFrame(pair_records), width="stretch", hide_index=True)
    with st.expander("Highlighted pair preview", expanded=False):
        for pair in pairs[:30]:
            badge = {"High": "green", "Medium": "orange", "Low": "red"}.get(pair.confidence, "gray")
            st.markdown(
                f"""
                <div style="border-left:4px solid {badge}; padding:0.5rem 0.75rem; margin-bottom:0.75rem; background:#fafafa">
                  <strong>{pair.confidence} confidence</strong> · {pair.location}<br>
                  <span style="color:#8a1f11"><strong>中文:</strong> {pair.chinese_text}</span><br>
                  <span style="color:#174a7c"><strong>English:</strong> {pair.english_text}</span>
                </div>
                """,
                unsafe_allow_html=True,
            )


def render_api_paragraph_review(rows: list[dict], warnings: list[str], provider: str, model: str, reviewed_count: int, total_pairs: int, scope_label: str) -> None:
    st.header("D. API paragraph review")
    st.caption(f"Review scope: {scope_label}. Judging {reviewed_count} of {total_pairs} detected pairs.")
    for warning in warnings:
        st.warning(warning)
    if not rows:
        if warnings:
            st.info("No API paragraph review rows were returned because the API review did not complete. Check the warning above, then click Extract and review again.")
        else:
            st.info("No substantive paragraph pairs were available for API paragraph review.")
        return
    df = pd.DataFrame(rows)
    status_filter = st.multiselect("API status", sorted(df["API status"].dropna().unique()), default=sorted(df["API status"].dropna().unique()))
    filtered = df[df["API status"].isin(status_filter)] if status_filter else df
    st.dataframe(filtered, width="stretch", hide_index=True)


def render_translation_report(issues: list[dict], warnings: list[str], provider: str, api_enabled: bool, reviewed_count: int, total_pairs: int, scope_label: str) -> None:
    st.header("E. Translation issue report")
    if api_enabled:
        st.caption(f"Review scope: {scope_label}. This report judges {reviewed_count} of {total_pairs} detected pairs and includes API-generated issue rows from Part D, plus deterministic checks.")
    else:
        st.caption(f"Review scope: {scope_label}. This report judges {reviewed_count} of {total_pairs} detected pairs and is generated from deterministic checks because paragraph API review is disabled.")
    for warning in warnings:
        st.warning(warning)
    if not issues:
        st.success("No translation issues found by the enabled checks.")
        return
    df = pd.DataFrame(issues)
    severity_filter = st.multiselect("Severity", ["Critical", "Major", "Minor"], default=["Critical", "Major", "Minor"])
    filtered = df[df["severity"].isin(severity_filter)] if "severity" in df else df
    st.dataframe(filtered, width="stretch", hide_index=True)


def render_terminology_report(issues: list[dict]) -> None:
    st.header("F. Terminology consistency report")
    if not issues:
        st.success("No terminology consistency issues found.")
        return
    st.dataframe(pd.DataFrame(issues), width="stretch", hide_index=True)


def render_regulatory_report(rows: list[dict]) -> None:
    st.header("G. Regulatory reference report")
    if not rows:
        st.info("No external regulatory references detected.")
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_reference_comparison(rows: list[dict], warnings: list[str]) -> None:
    st.header("H. Reference regulation comparison")
    for warning in warnings:
        st.info(warning)
    if not rows:
        return
    st.dataframe(pd.DataFrame(rows), width="stretch", hide_index=True)


def render_export(
    pairs: list[BilingualPair],
    api_paragraph_rows: list[dict],
    translation_issues: list[dict],
    terminology_issues: list[dict],
    regulatory_refs: list[dict],
    reference_rows: list[dict],
) -> None:
    st.header("I. Export report")
    pair_records = dataclasses_to_records(pairs)
    excel = build_excel_report({
        "Bilingual pairs": pair_records,
        "API paragraph review": api_paragraph_rows,
        "Translation issues": translation_issues,
        "Terminology issues": terminology_issues,
        "Regulatory references": regulatory_refs,
        "Reference comparison": reference_rows,
    })
    st.download_button(
        "Download Excel report",
        excel,
        file_name="bilingual_regulatory_review.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    word = build_word_report(translation_issues, terminology_issues, regulatory_refs, reference_rows)
    st.download_button(
        "Download Word report",
        word,
        file_name="bilingual_regulatory_review.docx",
        mime="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


if __name__ == "__main__":
    main()
