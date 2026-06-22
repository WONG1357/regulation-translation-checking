from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import fitz
from docx import Document
from docx.oxml.table import CT_Tbl
from docx.oxml.text.paragraph import CT_P
from docx.table import Table
from docx.text.paragraph import Paragraph


SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)+(?:\.[A-Za-z])?[.)]?)\s*(.*)")
HEADING_RE = re.compile(r"^(heading|title|标题)", re.I)


def detect_language(text: str) -> str:
    zh = len(re.findall(r"[\u3400-\u9fff]", text))
    en = len(re.findall(r"[A-Za-z]", text))
    numbers = len(re.findall(r"\d", text))
    meaningful = zh + en
    if zh and en:
        return "mixed"
    if zh and (zh >= en or zh >= 2):
        return "zh"
    if en:
        return "en"
    if numbers or re.fullmatch(r"[\W\d_]+", text or ""):
        return "number"
    return "unknown"


def extract_document(file_name: str, data: bytes) -> list[dict[str, Any]]:
    suffix = Path(file_name).suffix.lower()
    if suffix == ".pdf":
        blocks = _extract_pdf(data)
    elif suffix == ".docx":
        blocks = _extract_docx(data)
    elif suffix == ".txt":
        blocks = _extract_txt(data)
    else:
        raise ValueError(f"Unsupported file type: {suffix}")
    if not blocks:
        raise ValueError("No readable text was extracted. Scanned PDFs may require OCR.")
    return blocks


def _base_block(
    block_id: str,
    page: int,
    order: int,
    text: str,
    block_type: str,
    bbox: list[float] | None = None,
    heading_hint: bool = False,
) -> dict[str, Any]:
    text = re.sub(r"[ \t]+", " ", text.replace("\u3000", " ")).strip()
    match = SECTION_RE.match(text)
    is_heading = heading_hint or bool(match and len(text) <= 220)
    return {
        "block_id": block_id,
        "page": page,
        "order": order,
        "text": text,
        "language": detect_language(text),
        "block_type": "heading" if is_heading and block_type == "paragraph" else block_type,
        "section": match.group(1).rstrip(".)") if match else None,
        "heading": text if is_heading else None,
        "bbox": bbox,
    }


def _extract_pdf(data: bytes) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    with fitz.open(stream=data, filetype="pdf") as pdf:
        order = 1
        for page_index, page in enumerate(pdf, start=1):
            raw = page.get_text("blocks", sort=True)
            for block_index, item in enumerate(raw, start=1):
                text = re.sub(r"\s*\n\s*", " ", str(item[4])).strip()
                if not text:
                    continue
                bbox = [round(float(v), 2) for v in item[:4]]
                blocks.append(
                    _base_block(
                        f"p{page_index:03d}_b{block_index:04d}",
                        page_index,
                        order,
                        text,
                        "paragraph",
                        bbox,
                    )
                )
                order += 1
    return blocks


def _iter_docx(document: Document):
    for child in document.element.body.iterchildren():
        if isinstance(child, CT_P):
            yield Paragraph(child, document)
        elif isinstance(child, CT_Tbl):
            yield Table(child, document)


def _extract_docx(data: bytes) -> list[dict[str, Any]]:
    document = Document(io.BytesIO(data))
    blocks: list[dict[str, Any]] = []
    order = 1
    table_number = 0
    for item in _iter_docx(document):
        if isinstance(item, Paragraph):
            text = item.text.strip()
            if not text:
                continue
            style = item.style.name if item.style else ""
            blocks.append(
                _base_block(
                    f"p001_b{order:04d}",
                    1,
                    order,
                    text,
                    "paragraph",
                    None,
                    bool(HEADING_RE.search(style)),
                )
            )
            order += 1
        else:
            table_number += 1
            for row_number, row in enumerate(item.rows, start=1):
                cells = [re.sub(r"\s+", " ", cell.text).strip() for cell in row.cells]
                text = " | ".join(value for value in cells if value)
                if not text:
                    continue
                block = _base_block(
                    f"p001_t{table_number:03d}_r{row_number:04d}",
                    1,
                    order,
                    text,
                    "table_row",
                )
                block["table_id"] = f"table_{table_number:03d}"
                block["row"] = row_number
                blocks.append(block)
                order += 1
    return blocks


def _extract_txt(data: bytes) -> list[dict[str, Any]]:
    try:
        text = data.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = data.decode("utf-16", errors="replace")
    blocks: list[dict[str, Any]] = []
    for line in re.split(r"\r?\n", text):
        clean = line.strip()
        if not clean:
            continue
        order = len(blocks) + 1
        blocks.append(_base_block(f"p001_b{order:04d}", 1, order, clean, "paragraph"))
    return blocks
