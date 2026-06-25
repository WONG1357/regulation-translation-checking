from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any, Iterable, TypeVar

from pydantic import BaseModel

from src.schemas import Language

LOGGER = logging.getLogger("bilingual_regulatory_checker")

SECTION_RE = re.compile(
    r"^\s*(?:section\s*)?(\d+(?:\.\d+)*(?:\.[a-zA-Z]\)?)?|"
    r"附录\s*[IVX一二三四五六七八九十]+)(?=$|[\s:：、,，;\-]|[\u3400-\u9fff])",
    re.IGNORECASE,
)
CHINESE_RE = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff\uf900-\ufaff]")
LATIN_RE = re.compile(r"[A-Za-z]")
REFERENCE_RE = re.compile(
    r"\b(?:ISO[-\s]?\d{4,5}(?::\d{4})?|BS\s+EN\s+ISO\s+\d{4,5}(?::\d{4})?|"
    r"QSP\d{4}|WI\d{3,5}|21\s+CFR(?:\s+Part)?\s*\d+|"
    r"(?:EU\s+)?(?:MDR|MDD)|YY/?T?\s*\d{4}|(?:\d{2}/\d{2}/EEC)|"
    r"Regulation\s*\(EU\)\s*\d{4}/\d+|Directive\s*\d{2}/\d{2}/EEC)\b",
    re.IGNORECASE,
)

T = TypeVar("T", bound=BaseModel)


def configure_logging(level: int = logging.INFO) -> None:
    if not LOGGER.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
        )
        LOGGER.addHandler(handler)
    LOGGER.setLevel(level)


def normalize_text(text: str) -> str:
    text = text.replace("\u00a0", " ").replace("\x00", " ")
    text = re.sub(r"(?<=[A-Za-z])\s+(?=[A-Za-z])", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def language_of(text: str) -> Language:
    chinese = len(CHINESE_RE.findall(text))
    latin = len(LATIN_RE.findall(text))
    total = chinese + latin
    if total == 0:
        return Language.unknown
    if chinese and latin:
        # Compact bilingual labels in quality manuals are often written without a
        # delimiter, e.g. "策划Planning" or "目录Table of Contents". Treat these as
        # mixed even when the Latin character count dominates, otherwise they become
        # bogus English-only blocks. Do not apply this to longer Chinese paragraphs
        # that merely contain Roman/regulatory tokens such as "II a", "MC", or "ISO".
        compact_label = (
            len(text) <= 140
            and chinese <= 24
            and not re.search(r"[。；;!?！？]", text)
        )
        if compact_label:
            return Language.mixed
    zh_ratio = chinese / total
    en_ratio = latin / total
    if zh_ratio >= 0.45 and en_ratio >= 0.30:
        return Language.mixed
    if zh_ratio >= 0.35:
        return Language.zh
    if en_ratio >= 0.55:
        return Language.en
    return Language.mixed


def extract_section(text: str) -> str | None:
    match = SECTION_RE.match(text[:120])
    if not match:
        return None
    section = match.group(1).strip()
    remainder = text[match.end() : 120].strip()
    # A bare "8.2" or "51" on a TOC/table page is a locator, not a section heading.
    # Require some actual heading/prose text after numeric sections before promoting
    # the value into document section state.
    if re.fullmatch(r"\d+(?:\.\d+)+(?:\.[a-zA-Z]\)?)?", section) and not re.search(
        r"[A-Za-z\u3400-\u9fff]", remainder
    ):
        return None
    if re.fullmatch(r"\d+", section):
        if text[match.end() : match.end() + 1] in {"-", "/", "."}:
            return None
        if not re.search(r"[A-Za-z\u3400-\u9fff]", remainder):
            return None
        if int(section) > 15:
            return None
    return section


def extract_references(text: str) -> set[str]:
    return {normalize_text(m.group(0)).upper() for m in REFERENCE_RE.finditer(text)}


def stable_id(prefix: str, *parts: Any, length: int = 12) -> str:
    material = "\x1f".join(str(part) for part in parts)
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:length]
    return f"{prefix}_{digest}"


def chunks(items: list[T], size: int) -> Iterable[list[T]]:
    for start in range(0, len(items), size):
        yield items[start : start + size]


def read_prompt(path: str | Path) -> str:
    return Path(path).read_text(encoding="utf-8")


def json_hash(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, default=str)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def validate_json_response(text: str, schema: type[T]) -> T:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    return schema.model_validate_json(cleaned)


def severity_rank(value: str) -> int:
    return {"Observation": 0, "Minor": 1, "Major": 2, "Critical": 3}.get(value, 0)


def compact_context(text: str, limit: int = 260) -> str:
    text = normalize_text(text)
    return text if len(text) <= limit else f"{text[: limit - 1]}…"
