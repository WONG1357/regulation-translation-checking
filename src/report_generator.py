from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

import pandas as pd

from .highlight_renderer import render_highlighted_document


def ensure_output_dir(path: str | Path = "outputs") -> Path:
    output = Path(path)
    output.mkdir(parents=True, exist_ok=True)
    return output


def save_json(name: str, data: Any, output_dir: str | Path = "outputs") -> Path:
    path = ensure_output_dir(output_dir) / name
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def save_csv(name: str, records: Any, output_dir: str | Path = "outputs") -> Path:
    path = ensure_output_dir(output_dir) / name
    frame = records if isinstance(records, pd.DataFrame) else pd.DataFrame(records)
    frame.to_csv(path, index=False, encoding="utf-8-sig")
    return path


def build_final_report(
    document_name: str,
    blocks: list[dict[str, Any]],
    pairs: list[dict[str, Any]],
    block_statuses: list[dict[str, Any]],
    coverage_summary: dict[str, int],
    translation_findings: list[dict[str, Any]],
    terminology_findings: list[dict[str, Any]],
    regulation_references: list[dict[str, Any]],
    regulation_review: list[dict[str, Any]],
) -> str:
    def table(records: list[dict[str, Any]]) -> str:
        if not records:
            return "<p>No findings.</p>"
        return pd.DataFrame(records).to_html(index=False, escape=True, border=0, classes="report-table")

    highlighted = render_highlighted_document(blocks, pairs, block_statuses, show_headers=False)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>Bilingual Review Report</title>
<style>
body{{font-family:Arial,sans-serif;max-width:1200px;margin:32px auto;padding:0 20px;color:#202124}}
h1,h2{{color:#17324d}} .summary{{display:flex;flex-wrap:wrap;gap:10px}}
.metric{{background:#f4f7fa;padding:12px;border-radius:8px;min-width:150px}}
.report-table{{border-collapse:collapse;width:100%;font-size:13px}} .report-table th,.report-table td{{border:1px solid #ddd;padding:7px;vertical-align:top}}
.doc-page{{border-top:3px solid #d9e2ec;margin-top:24px;padding-top:8px}} .pair-label{{font-size:11px;font-weight:bold;float:right}}
</style></head><body>
<h1>Bilingual Chinese-English Document Review</h1>
<h2>1. Document summary</h2><p>{html.escape(document_name)} · {len(blocks)} extracted blocks · {len(pairs)} pairs</p>
<h2>2. Coverage summary</h2><div class="summary">{''.join(f'<div class="metric"><b>{html.escape(k)}</b><br>{v}</div>' for k,v in coverage_summary.items())}</div>
<h2>3. Translation accuracy findings</h2>{table(translation_findings)}
<h2>4. Terminology consistency findings</h2>{table(terminology_findings)}
<h2>5. Regulation references</h2>{table(regulation_references)}
<h2>6. Regulation review findings</h2>{table(regulation_review)}
<h2>7. Highlighted paired document view</h2>{highlighted}
</body></html>"""


def save_final_report(report_html: str, output_dir: str | Path = "outputs") -> Path:
    path = ensure_output_dir(output_dir) / "final_report.html"
    path.write_text(report_html, encoding="utf-8")
    return path
