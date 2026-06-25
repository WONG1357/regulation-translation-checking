from __future__ import annotations

from typing import Any

from src.schemas import BlockType, ExtractedBlock, SourceType
from src.utils import language_of, normalize_text, stable_id


class OCRUnavailableError(RuntimeError):
    pass


def ocr_page(
    image: Any,
    page_number: int,
    *,
    languages: str = "chi_sim+chi_tra+eng",
    confidence_floor: float = 0.25,
) -> list[ExtractedBlock]:
    """OCR a page image and group nearby words into line-level blocks."""
    try:
        import pytesseract
        from pytesseract import Output
    except ImportError as exc:
        raise OCRUnavailableError(
            "pytesseract is not installed. Install the OCR extra and Tesseract language packs."
        ) from exc

    try:
        data = pytesseract.image_to_data(
            image, lang=languages, output_type=Output.DICT, config="--psm 6"
        )
    except Exception as exc:
        raise OCRUnavailableError(f"OCR execution failed: {exc}") from exc

    lines: dict[tuple[int, int, int], list[int]] = {}
    for index, raw_text in enumerate(data.get("text", [])):
        text = normalize_text(raw_text)
        try:
            confidence = max(float(data["conf"][index]), 0.0) / 100.0
        except (ValueError, TypeError):
            confidence = 0.0
        if not text or confidence < confidence_floor:
            continue
        key = (
            int(data["block_num"][index]),
            int(data["par_num"][index]),
            int(data["line_num"][index]),
        )
        lines.setdefault(key, []).append(index)

    blocks: list[ExtractedBlock] = []
    for order, indexes in enumerate(lines.values()):
        text = normalize_text(" ".join(data["text"][i] for i in indexes))
        left = min(int(data["left"][i]) for i in indexes)
        top = min(int(data["top"][i]) for i in indexes)
        right = max(int(data["left"][i]) + int(data["width"][i]) for i in indexes)
        bottom = max(int(data["top"][i]) + int(data["height"][i]) for i in indexes)
        confidence = sum(max(float(data["conf"][i]), 0.0) for i in indexes) / (
            len(indexes) * 100.0
        )
        blocks.append(
            ExtractedBlock(
                block_id=stable_id("ocr", page_number, order, text),
                page=page_number,
                block_type=BlockType.paragraph,
                language=language_of(text),
                text=text,
                bbox=(left, top, right, bottom),
                source=SourceType.ocr,
                confidence=min(confidence, 0.92),
                reading_order=order,
                warnings=["OCR-derived text; verify against the source image."],
            )
        )
    return blocks

