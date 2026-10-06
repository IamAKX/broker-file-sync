"""
Base report HTML layout + small composable section builders, shared by
every report type (LMV EOD, EMV EOD, Fuku Live). See the package docstring
for why this is plain Python string building rather than a templating
language.

Pagination: printToPdf's underlying engine (Chromium via QtWebEngine) does
NOT support CSS Paged Media's `@page` margin-box page-number counters
(`counter(page)`/`counter(pages)` in `@bottom-center` etc. are unimplemented
in Blink) — so "Page X of Y" cannot be a browser-generated running counter
here. Instead, report content is pre-paginated in Python: each report type's
data layer decides what belongs on which physical page (matching every
spec's own "never split a table row/KPI card/chart awkwardly across pages"
rule, which a browser's own reflow-based pagination can't guarantee anyway)
and passes ``render_report()`` one HTML string per page; this module wraps
each in a fixed-size `.report-page` block with `break-after: page` and its
own literal "Page X of Y" footer text — a real value, not a live counter,
which is exactly right since the page count is already known once the
caller has decided how content is split.
"""

import html
from datetime import datetime

# A4 in mm — matches pdf_export.py's default QPageSize.A4. Content is laid
# out at this exact physical size so the on-screen preview (QWebEngineView
# showing this same HTML) and the printed PDF are pixel-identical; margins
# live here (CSS padding) rather than in pdf_export.py's QPageLayout, so
# there aren't two independent margin settings to keep in sync.
PAGE_WIDTH_MM = 210
PAGE_HEIGHT_MM = 297
PAGE_PADDING_MM = 12

_BASE_CSS = f"""
:root {{
  --text-primary: #0F172A;
  --text-secondary: #64748b;
  --header-blue: #1E3A8A;
  --border: #CBD5E1;
  --positive-text: #15803D;
  --positive-bg: #DCFCE7;
  --negative-text: #B91C1C;
  --negative-bg: #FEE2E2;
  --neutral-bg: #F1F5F9;
  --accent: #2979FF;
  --accent-amber: #D97706;
}}
* {{ box-sizing: border-box; }}
svg {{ max-width: 100%; height: auto; }}
html, body {{ margin: 0; padding: 0; background: #ffffff; }}
body {{
  font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  color: var(--text-primary);
}}
.report-page {{
  width: {PAGE_WIDTH_MM}mm;
  min-height: {PAGE_HEIGHT_MM}mm;
  padding: {PAGE_PADDING_MM}mm;
  margin: 0 auto 6mm auto;
  background: #ffffff;
  position: relative;
  break-after: page;
  page-break-after: always;
}}
.report-page:last-child {{ break-after: auto; page-break-after: auto; }}
/* A page block exactly as tall as the sheet plus its preview-only bottom margin
   spills a blank sliver page after every page when printed. */
@media print {{
  .report-page {{ margin: 0; min-height: 0; height: {PAGE_HEIGHT_MM - 0.5}mm; overflow: hidden; }}
}}

.report-header {{
  display: flex; justify-content: space-between; align-items: flex-start;
  border-bottom: 2px solid var(--header-blue); padding-bottom: 8px; margin-bottom: 14px;
}}
.report-header h1 {{
  font-size: 18px; color: var(--header-blue); margin: 0 0 2px 0; font-weight: 700;
}}
.report-header .subtitle {{ font-size: 12px; color: var(--text-secondary); margin: 0; }}
.report-header .meta {{ text-align: right; font-size: 11px; color: var(--text-secondary); }}

.kpi-row {{ display: flex; gap: 10px; flex-wrap: wrap; margin-bottom: 16px; }}
.kpi-card {{
  flex: 1 1 120px; border: 1px solid var(--border); border-radius: 8px;
  padding: 10px 12px; background: var(--neutral-bg);
}}
.kpi-card .kpi-label {{ font-size: 10px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .04em; }}
.kpi-card .kpi-value {{ font-size: 18px; font-weight: 700; margin-top: 2px; }}
.kpi-card .kpi-sublabel {{ font-size: 10px; color: var(--text-secondary); margin-top: 2px; }}
.kpi-card.positive .kpi-value {{ color: var(--positive-text); }}
.kpi-card.negative .kpi-value {{ color: var(--negative-text); }}

.section {{ margin-bottom: 16px; }}
.section h2 {{ font-size: 13px; color: var(--header-blue); margin: 0 0 6px 0; font-weight: 700; }}
.section .section-subtitle {{ font-size: 10px; color: var(--text-secondary); margin: -4px 0 8px 0; }}

table.report-table {{ width: 100%; border-collapse: collapse; font-size: 11px; }}
table.report-table th {{
  text-align: left; padding: 6px 8px; border-bottom: 1px solid var(--header-blue);
  color: var(--header-blue); font-weight: 700; white-space: nowrap;
}}
table.report-table td {{
  padding: 5px 8px; border-bottom: 1px solid var(--border); white-space: nowrap;
}}
table.report-table tr:last-child td {{ border-bottom: none; }}

.status-pill {{
  display: inline-block; padding: 1px 8px; border-radius: 999px; font-size: 10px; font-weight: 700;
}}
.status-pill.positive {{ color: var(--positive-text); background: var(--positive-bg); }}
.status-pill.negative {{ color: var(--negative-text); background: var(--negative-bg); }}
.status-pill.neutral {{ color: var(--text-secondary); background: var(--neutral-bg); }}
.status-pill.warning {{ color: var(--accent-amber); background: #FEF3C7; }}

.legend {{ display: flex; flex-direction: column; gap: 4px; font-size: 11px; }}
.legend-row {{ display: flex; align-items: center; gap: 6px; }}
.legend-swatch {{ width: 10px; height: 10px; border-radius: 2px; display: inline-block; }}
.legend-label {{ flex: 1; color: var(--text-secondary); }}
.legend-value {{ font-weight: 700; }}

.progress-track {{
  width: 100%; height: 8px; border-radius: 4px; background: var(--neutral-bg); overflow: hidden;
}}
.progress-fill {{ height: 100%; border-radius: 4px; }}
.progress-label {{ font-size: 10px; color: var(--text-secondary); }}

.chart-row {{ display: flex; gap: 16px; align-items: flex-start; flex-wrap: wrap; }}

.report-footer {{
  position: absolute; bottom: {PAGE_PADDING_MM / 2}mm; left: {PAGE_PADDING_MM}mm;
  right: {PAGE_PADDING_MM}mm; display: flex; justify-content: space-between;
  font-size: 9px; color: var(--text-secondary); border-top: 1px solid var(--border); padding-top: 4px;
}}
"""


def esc(value) -> str:
    return html.escape(str(value)) if value is not None else ""


def kpi_card(label: str, value: str, sublabel: str = "", kind: str = "neutral") -> str:
    """*kind*: "neutral" | "positive" | "negative" — colors the value text
    (per every spec's "directional yield displayed consistently" rule)."""
    css_class = "kpi-card" if kind == "neutral" else f"kpi-card {kind}"
    sub = f'<div class="kpi-sublabel">{esc(sublabel)}</div>' if sublabel else ""
    return (
        f'<div class="{css_class}"><div class="kpi-label">{esc(label)}</div>'
        f'<div class="kpi-value">{esc(value)}</div>{sub}</div>'
    )


def status_pill(text: str, kind: str = "neutral") -> str:
    return f'<span class="status-pill {esc(kind)}">{esc(text)}</span>'


def data_table(headers: list, rows: list, column_html: set | None = None) -> str:
    """*rows*: list of row-sequences aligned to *headers*. Each cell is
    escaped by default; a header name listed in *column_html* is inserted
    RAW instead (for a status-pill/progress-bar cell already built by
    another helper in this module) — callers must escape any user data
    themselves before passing it through that column."""
    column_html = column_html or set()
    head = "".join(f"<th>{esc(h)}</th>" for h in headers)
    body_rows = []
    for row in rows:
        cells = []
        for header, value in zip(headers, row):
            cells.append(f"<td>{value if header in column_html else esc(value)}</td>")
        body_rows.append(f"<tr>{''.join(cells)}</tr>")
    return (
        f'<table class="report-table"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table>'
    )


def section(title: str, body_html: str, subtitle: str = "") -> str:
    sub = f'<p class="section-subtitle">{esc(subtitle)}</p>' if subtitle else ""
    return f'<div class="section"><h2>{esc(title)}</h2>{sub}{body_html}</div>'


def report_header(title: str, subtitle: str, generated_at: datetime, extra_meta: str = "") -> str:
    when = generated_at.strftime("%d-%m-%Y %H:%M")
    meta = f'Generated: {esc(when)}'
    if extra_meta:
        meta += f'<br/>{esc(extra_meta)}'
    return (
        f'<div class="report-header"><div><h1>{esc(title)}</h1>'
        f'<p class="subtitle">{esc(subtitle)}</p></div>'
        f'<div class="meta">{meta}</div></div>'
    )


def render_report(pages: list, doc_title: str = "Report") -> str:
    """*pages*: list of already-built inner HTML strings, one per physical
    page (see this module's own docstring for why pagination is decided by
    the caller, not this function). Returns one standalone, self-contained
    HTML document (CSS inlined, no external asset references) ready for
    pdf_export.render_to_pdf() or a QWebEngineView preview.
    """
    total = len(pages)
    page_blocks = []
    for i, inner in enumerate(pages, start=1):
        page_blocks.append(
            f'<div class="report-page">{inner}'
            f'<div class="report-footer"><span>{esc(doc_title)}</span>'
            f'<span>Page {i} of {total}</span></div></div>'
        )
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8">'
        f'<title>{esc(doc_title)}</title><style>{_BASE_CSS}</style></head>'
        f'<body>{"".join(page_blocks)}</body></html>'
    )
