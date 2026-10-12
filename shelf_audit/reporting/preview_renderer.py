"""Escaped HTML preview of the report model, independent of Streamlit."""

from base64 import b64encode
from html import escape
from pathlib import Path

from .formatting import BLUE, NAVY, DEFAULT_LOGO_PATH, load_logo, metadata_rows
from .models import ShelfOpportunityReport
from .templates import NO_OPPORTUNITIES_TEXT, WHY_LABEL, RECOMMENDATION_LABEL


def render_preview(report: ShelfOpportunityReport, *, logo_path: Path | None = DEFAULT_LOGO_PATH) -> str:
    logo = load_logo(logo_path)
    parts = [f'''<style>
    .kk-shelf-report {{background:white;color:{NAVY};padding:32px;max-width:850px;
      margin:auto;font-family:Arial,sans-serif;line-height:1.55;border:1px solid #e1e4eb;}}
    .kk-shelf-report h1 {{font-size:28px;color:{NAVY};margin:20px 0 4px;}}
    .kk-shelf-report h2 {{font-size:21px;color:{NAVY};margin:6px 0 18px;}}
    .kk-shelf-report .kk-label {{font-size:11px;letter-spacing:1px;font-weight:bold;color:{BLUE};}}
    .kk-shelf-report .kk-copy {{white-space:pre-wrap;overflow-wrap:anywhere;margin:6px 0 18px;}}
    .kk-shelf-report section {{border-top:1px solid #dce1ea;padding:24px 0 4px;}}
    .kk-shelf-report footer {{border-top:1px solid #dce1ea;margin-top:24px;padding-top:14px;font-size:11px;}}
    </style><article class="kk-shelf-report">''']
    if logo:
        parts.append(f'<img alt="Kendal King" src="data:image/png;base64,{b64encode(logo).decode()}" style="width:90px;height:auto">')
    parts.append(f'<h1>{escape(report.title)}</h1>')
    if report.subtitle:
        parts.append(f'<p>{escape(report.subtitle)}</p>')
    for label, value in metadata_rows(report.metadata):
        parts.append(f'<p class="kk-copy"><strong>{escape(label)}:</strong> {escape(value)}</p>')
    for item in report.opportunities:
        parts.append(
            f'<section><div class="kk-label">{item.number:02d}</div>'
            f'<h2 class="kk-copy">{escape(item.title)}</h2>'
            f'<div class="kk-label">{WHY_LABEL.upper()}</div>'
            f'<p class="kk-copy">{escape(item.evidence)}</p>'
            f'<div class="kk-label">{RECOMMENDATION_LABEL.upper()}</div>'
            f'<p class="kk-copy">{escape(item.recommendation)}</p></section>'
        )
    if not report.opportunities:
        parts.append(f'<section><p>{NO_OPPORTUNITIES_TEXT}</p></section>')
    parts.append(f'<footer>{escape(report.footer_text)}</footer></article>')
    return "".join(parts)
