from __future__ import annotations

from pathlib import Path

from src.ocr_extractor import OCRUnavailableError, ocr_page
from src.schemas import BlockType, ExtractedBlock, SourceType
from src.utils import language_of, normalize_text, stable_id


def _classify_visual_block(text: str, font_size: float, page_height: float, bbox) -> BlockType:
    y0 = bbox[1] if bbox else 0
    y1 = bbox[3] if bbox else page_height
    if y1 <= page_height * 0.16:
        return BlockType.header
    if y0 >= page_height * 0.93:
        return BlockType.footer
    stripped = text.strip()
    if stripped.startswith(("-", "•", "·")) or (
        len(stripped) > 2 and stripped[:2].lower() in {f"{c})" for c in "abcdefgh"}
    ):
        return BlockType.bullet
    if font_size >= 12.0 or (len(stripped) < 90 and any(ch.isdigit() for ch in stripped[:8])):
        return BlockType.heading
    return BlockType.paragraph


def _extract_text_blocks(page, page_number: int) -> list[ExtractedBlock]:
    data = page.get_text("dict", sort=True)
    result: list[ExtractedBlock] = []
    order = 0
    for raw in data.get("blocks", []):
        if raw.get("type") != 0:
            continue
        lines: list[str] = []
        font_sizes: list[float] = []
        for line in raw.get("lines", []):
            spans = line.get("spans", [])
            line_text = "".join(span.get("text", "") for span in spans)
            if normalize_text(line_text):
                lines.append(line_text)
            font_sizes.extend(float(span.get("size", 0.0)) for span in spans)
        text = "\n".join(normalize_text(line) for line in lines if normalize_text(line))
        if not text:
            continue
        bbox = tuple(float(value) for value in raw.get("bbox", (0, 0, 0, 0)))
        font_size = max(font_sizes) if font_sizes else 0.0
        result.append(
            ExtractedBlock(
                block_id=stable_id("pdf", page_number, order, bbox, text),
                page=page_number,
                block_type=_classify_visual_block(
                    text, font_size, float(page.rect.height), bbox
                ),
                language=language_of(text),
                text=text,
                bbox=bbox,
                source=SourceType.text_extraction,
                confidence=1.0,
                font_size=font_size or None,
                reading_order=order,
            )
        )
        order += 1
    return result


def _extract_tables(pdf_path: Path, page_number: int) -> list[ExtractedBlock]:
    try:
        import pdfplumber
    except ImportError:
        return []

    result: list[ExtractedBlock] = []
    with pdfplumber.open(str(pdf_path), pages=[page_number]) as pdf:
        page = pdf.pages[0]
        for table_index, table in enumerate(page.find_tables() or []):
            extracted = table.extract() or []
            table_id = stable_id("table", page_number, table_index, table.bbox)
            row_height = (table.bbox[3] - table.bbox[1]) / max(len(extracted), 1)
            for row_index, row in enumerate(extracted):
                cells = [normalize_text(cell or "") for cell in row]
                text = " | ".join(cell for cell in cells if cell)
                if not text:
                    continue
                bbox = (
                    float(table.bbox[0]),
                    float(table.bbox[1] + row_index * row_height),
                    float(table.bbox[2]),
                    float(table.bbox[1] + (row_index + 1) * row_height),
                )
                result.append(
                    ExtractedBlock(
                        block_id=stable_id("row", page_number, table_index, row_index, text),
                        page=page_number,
                        block_type=BlockType.table_row,
                        language=language_of(text),
                        text=text,
                        bbox=bbox,
                        source=SourceType.text_extraction,
                        confidence=0.98,
                        reading_order=10000 + table_index * 100 + row_index,
                        table_id=table_id,
                        row_index=row_index,
                    )
                )
    return result


def extract_pdf(
    pdf_path: str | Path,
    *,
    ocr_fallback: bool = True,
    max_pages: int | None = None,
    text_character_threshold: int = 40,
) -> tuple[list[ExtractedBlock], int, list[str]]:
    """Extract positioned blocks and table rows from a PDF."""
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF extraction.") from exc

    path = Path(pdf_path)
    doc = fitz.open(path)
    page_count = len(doc)
    limit = min(page_count, max_pages) if max_pages else page_count
    blocks: list[ExtractedBlock] = []
    warnings: list[str] = []

    for index in range(limit):
        page_number = index + 1
        page = doc[index]
        page_blocks = _extract_text_blocks(page, page_number)
        extracted_chars = sum(len(block.text) for block in page_blocks)
        if extracted_chars < text_character_threshold and ocr_fallback:
            try:
                matrix = fitz.Matrix(2.0, 2.0)
                pixmap = page.get_pixmap(matrix=matrix, alpha=False)
                from PIL import Image

                image = Image.frombytes("RGB", [pixmap.width, pixmap.height], pixmap.samples)
                page_blocks = ocr_page(image, page_number)
                warnings.append(f"Page {page_number}: OCR fallback used.")
            except (OCRUnavailableError, ImportError) as exc:
                warnings.append(f"Page {page_number}: OCR unavailable ({exc}).")
        elif extracted_chars < text_character_threshold:
            warnings.append(
                f"Page {page_number}: little embedded text found and OCR fallback is disabled."
            )

        try:
            table_blocks = _extract_tables(path, page_number)
            for text_block in page_blocks:
                if not text_block.bbox:
                    continue
                center_x = (text_block.bbox[0] + text_block.bbox[2]) / 2
                center_y = (text_block.bbox[1] + text_block.bbox[3]) / 2
                if any(
                    row.bbox
                    and row.bbox[0] <= center_x <= row.bbox[2]
                    and row.bbox[1] <= center_y <= row.bbox[3]
                    for row in table_blocks
                ):
                    text_block.ignored = True
                    text_block.warnings.append(
                        "Superseded by layout-aware table-row extraction."
                    )
            blocks.extend(page_blocks)
            blocks.extend(table_blocks)
        except Exception as exc:
            blocks.extend(page_blocks)
            warnings.append(f"Page {page_number}: table extraction warning ({exc}).")

    doc.close()
    return blocks, page_count, warnings
