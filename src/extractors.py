from __future__ import annotations

import io
import re
from pathlib import Path

import fitz
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph

from .utils import (
    MAX_FILE_SIZE_MB,
    SUPPORTED_EXTENSIONS,
    DocumentResult,
    TextBlock,
    contains_english,
    contains_chinese,
    normalize_text,
)


HEADING_STYLE_RE = re.compile(r"heading|标题", re.I)
DOC_NUMBER_RE = re.compile(r"\b(?:doc(?:ument)?\.?\s*(?:no|number)|文件编号)[:：\s]*([A-Z0-9_\-/\.]+)", re.I)
REVISION_RE = re.compile(r"\b(?:rev(?:ision)?\.?|版本|修订)[:：\s]*([A-Z0-9_\-/\.]+)", re.I)


def validate_upload(file_name: str, file_size: int | None = None) -> str:
    suffix = Path(file_name).suffix.lower().lstrip(".")
    if suffix not in SUPPORTED_EXTENSIONS:
        raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")
    if file_size and file_size > MAX_FILE_SIZE_MB * 1024 * 1024:
        raise ValueError(f"File is larger than {MAX_FILE_SIZE_MB} MB")
    return suffix


def extract_uploaded_file(file_name: str, data: bytes) -> DocumentResult:
    file_type = validate_upload(file_name, len(data))
    if not data:
        raise ValueError("Uploaded file is empty")
    if file_type == "docx":
        return extract_docx(file_name, data)
    if file_type == "pdf":
        return extract_pdf(file_name, data)
    if file_type == "txt":
        return extract_txt(file_name, data)
    raise ValueError(f"Unsupported file type: {file_type}")


def extract_docx(file_name: str, data: bytes) -> DocumentResult:
    doc = Document(io.BytesIO(data))
    blocks: list[TextBlock] = []
    warnings: list[str] = []
    order = 0
    paragraph_number = 0
    current_heading: str | None = None

    table_index = 0
    for item in _iter_docx_body(doc):
        if isinstance(item, Paragraph):
            text = normalize_text(item.text)
            if not text:
                continue
            style_name = item.style.name if item.style else ""
            is_heading = bool(HEADING_STYLE_RE.search(style_name)) or _looks_like_heading(text)
            if is_heading:
                current_heading = text
            paragraph_number += 1
            blocks.append(
                TextBlock(
                    block_id=f"{file_name}:p:{paragraph_number}",
                    file_name=file_name,
                    file_type="docx",
                    text=text,
                    block_type="heading" if is_heading else "paragraph",
                    order=order,
                    section_heading=current_heading,
                    paragraph_number=paragraph_number,
                )
            )
            order += 1
        elif isinstance(item, Table):
            for row_index, row in enumerate(item.rows):
                row_texts = [normalize_text(cell.text) for cell in row.cells]
                row_text = " | ".join(t for t in row_texts if t)
                if not row_text:
                    continue
                blocks.append(
                    TextBlock(
                        block_id=f"{file_name}:t:{table_index}:r:{row_index}",
                        file_name=file_name,
                        file_type="docx",
                        text=row_text,
                        block_type="table_row",
                        order=order,
                        section_heading=current_heading,
                        table_index=table_index,
                        row_index=row_index,
                    )
                )
                order += 1
            table_index += 1

    if not blocks:
        warnings.append("No readable text found in DOCX.")

    all_text = "\n".join(block.text for block in blocks)
    metadata = extract_key_metadata(all_text)
    metadata["page_count"] = None
    return DocumentResult(file_name, "docx", blocks, warnings, metadata)


def _iter_docx_body(document: Document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def extract_pdf(file_name: str, data: bytes) -> DocumentResult:
    blocks: list[TextBlock] = []
    warnings: list[str] = []
    pdf = fitz.open(stream=data, filetype="pdf")
    order = 0
    current_heading: str | None = None

    for page_idx in range(pdf.page_count):
        page = pdf.load_page(page_idx)
        text = normalize_text(page.get_text("text"))
        if not text:
            warnings.append(f"Page {page_idx + 1}: no extractable text found; scanned/image-based content may require OCR.")
            continue
        page_lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
        if not page_lines:
            continue
        for line_idx, line in enumerate(_merge_pdf_lines(page_lines)):
            if _looks_like_heading(line):
                current_heading = line
            blocks.append(
                TextBlock(
                    block_id=f"{file_name}:pg:{page_idx + 1}:b:{line_idx}",
                    file_name=file_name,
                    file_type="pdf",
                    text=line,
                    block_type="heading" if _looks_like_heading(line) else "paragraph",
                    order=order,
                    page_number=page_idx + 1,
                    section_heading=current_heading,
                    paragraph_number=line_idx + 1,
                )
            )
            order += 1

    if not blocks:
        warnings.append("No readable text found in PDF. The file may be scanned or image-based and require OCR.")

    all_text = "\n".join(block.text for block in blocks)
    metadata = extract_key_metadata(all_text)
    metadata["page_count"] = pdf.page_count
    return DocumentResult(file_name, "pdf", blocks, warnings, metadata)


def extract_txt(file_name: str, data: bytes) -> DocumentResult:
    warnings: list[str] = []
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        text = data.decode("utf-16", errors="ignore")
        warnings.append("Text file was not UTF-8; decoded with fallback encoding.")

    blocks: list[TextBlock] = []
    current_heading: str | None = None
    for idx, para in enumerate(re.split(r"\n\s*\n|\r\n\s*\r\n", text)):
        clean = normalize_text(para)
        if not clean:
            continue
        if _looks_like_heading(clean):
            current_heading = clean
        blocks.append(
            TextBlock(
                block_id=f"{file_name}:txt:{idx}",
                file_name=file_name,
                file_type="txt",
                text=clean,
                block_type="heading" if _looks_like_heading(clean) else "paragraph",
                order=len(blocks),
                section_heading=current_heading,
                paragraph_number=idx + 1,
            )
        )

    if not blocks:
        warnings.append("No readable text found in TXT file.")
    metadata = extract_key_metadata(text)
    metadata["page_count"] = None
    return DocumentResult(file_name, "txt", blocks, warnings, metadata)


def extract_key_metadata(text: str) -> dict[str, str | None]:
    lines = [normalize_text(line) for line in text.splitlines() if normalize_text(line)]
    title = next((line for line in lines[:20] if contains_chinese(line) or contains_english(line)), None)
    doc_no_match = DOC_NUMBER_RE.search(text)
    rev_match = REVISION_RE.search(text)
    return {
        "title": title,
        "document_number": doc_no_match.group(1) if doc_no_match else None,
        "revision": rev_match.group(1) if rev_match else None,
    }


def _looks_like_heading(text: str) -> bool:
    if len(text) > 120:
        return False
    if re.match(r"^\s*(\d+(\.\d+){0,4}|[A-Z]\.?)\s+.+", text):
        return True
    if "/" in text and contains_chinese(text) and contains_english(text) and len(text) < 80:
        return True
    return False


def _merge_pdf_lines(lines: list[str]) -> list[str]:
    merged: list[str] = []
    buffer = ""
    for line in lines:
        if not buffer:
            buffer = line
            continue
        if len(buffer) < 80 and not re.search(r"[。.;；:]$", buffer):
            buffer = f"{buffer} {line}"
        else:
            merged.append(buffer)
            buffer = line
    if buffer:
        merged.append(buffer)
    return merged
