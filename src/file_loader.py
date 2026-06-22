from __future__ import annotations

from pathlib import Path
from typing import Any


SUPPORTED_TYPES = {".pdf", ".docx", ".txt"}
MAX_FILE_SIZE = 50 * 1024 * 1024


def load_uploaded_file(uploaded_file: Any) -> tuple[str, bytes]:
    """Validate a Streamlit UploadedFile and return its name and bytes."""
    if uploaded_file is None:
        raise ValueError("Please upload a PDF, DOCX, or TXT document.")
    name = Path(uploaded_file.name).name
    if Path(name).suffix.lower() not in SUPPORTED_TYPES:
        raise ValueError("Unsupported file type. Please upload PDF, DOCX, or TXT.")
    data = uploaded_file.getvalue()
    if not data:
        raise ValueError("The uploaded file is empty.")
    if len(data) > MAX_FILE_SIZE:
        raise ValueError("The uploaded file is larger than 50 MB.")
    return name, data
