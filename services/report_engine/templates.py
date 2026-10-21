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
from contextlib import contextmanager
from contextvars import ContextVar
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
/* A page can't scroll sideways, so a wide table must shrink to fit instead of
   running off the right edge (#87): the more columns, the smaller the type and
   padding, and headers/cells may wrap. */
table.report-table.dense-1 {{ font-size: 10px; }}
table.report-table.dense-1 th, table.report-table.dense-1 td {{ padding: 5px 5px; }}
table.report-table.dense-2 {{ font-size: 9px; }}
table.report-table.dense-2 th, table.report-table.dense-2 td {{ padding: 4px 3px; }}
table.report-table.dense-3 {{ font-size: 8px; }}
table.report-table.dense-3 th, table.report-table.dense-3 td {{ padding: 3px 2px; }}
table.report-table.dense-1 th, table.report-table.dense-2 th, table.report-table.dense-3 th {{ white-space: normal; vertical-align: bottom; }}
table.report-table.dense-3 td {{ white-space: normal; word-break: break-word; }}
table.report-table.dense-1 .status-pill {{ font-size: 9px; padding: 1px 6px; }}
table.report-table.dense-2 .status-pill, table.report-table.dense-3 .status-pill {{ font-size: 8px; padding: 1px 4px; }}

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


/* ── Fuku Live report cards ── */
.fk-card {{ border: 1px solid var(--border); border-radius: 10px; padding: 12px 14px; margin-bottom: 14px; background: #fff; break-inside: avoid; }}
.fk-card.fk-new {{ border-color: #F59E0B; box-shadow: 0 0 0 2px #FEF3C7; }}
.fk-card.fk-buy {{ border-left: 5px solid #16a34a; }}
.fk-card.fk-sell {{ border-left: 5px solid #dc2626; }}
.fk-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 10px; margin-bottom: 8px; }}
.fk-sym {{ font-size: 17px; font-weight: 800; letter-spacing: .01em; }}
.fk-sub {{ font-size: 10px; color: var(--text-secondary); margin-top: 2px; }}
.fk-badges {{ display: flex; gap: 6px; flex-wrap: wrap; align-items: center; justify-content: flex-end; }}
.fk-badge {{ display: inline-block; padding: 2px 9px; border-radius: 999px; font-size: 10px; font-weight: 800; letter-spacing: .03em; }}
.fk-badge.buy {{ color: #fff; background: #16a34a; }}
.fk-badge.sell {{ color: #fff; background: #dc2626; }}
.fk-badge.open {{ color: #1d4ed8; background: #DBEAFE; border: 1px solid #93C5FD; }}
.fk-badge.win {{ color: #15803D; background: #DCFCE7; border: 1px solid #86EFAC; }}
.fk-badge.loss {{ color: #B91C1C; background: #FEE2E2; border: 1px solid #FCA5A5; }}
.fk-badge.cancel {{ color: #92400E; background: #FEF3C7; border: 1px solid #FCD34D; }}
.fk-badge.partial {{ color: #0F766E; background: #CCFBF1; border: 1px solid #5EEAD4; }}
.fk-badge.new {{ color: #fff; background: #F59E0B; }}
.fk-kpis {{ display: flex; gap: 6px; margin-bottom: 10px; }}
.fk-kpi {{ flex: 1; border: 1px solid var(--border); border-radius: 7px; padding: 5px 8px; background: var(--neutral-bg); min-width: 0; }}
.fk-kpi .l {{ font-size: 8px; color: var(--text-secondary); text-transform: uppercase; letter-spacing: .05em; }}
.fk-kpi .v {{ font-size: 13px; font-weight: 800; margin-top: 1px; white-space: nowrap; }}
.fk-kpi.pos .v {{ color: var(--positive-text); }}
.fk-kpi.neg .v {{ color: var(--negative-text); }}
.fk-kpi.score .v {{ color: #B45309; }}
.fk-cols {{ display: flex; gap: 14px; align-items: flex-start; }}
.fk-col-main {{ flex: 1.5; min-width: 0; }}
.fk-col-side {{ flex: 1; min-width: 0; }}
.fk-h {{ font-size: 10px; font-weight: 800; color: var(--header-blue); text-transform: uppercase; letter-spacing: .06em; margin: 0 0 5px 0; }}
.fk-chips {{ display: flex; flex-direction: column; gap: 3px; margin-bottom: 10px; }}
.fk-chip {{ font-size: 10px; padding: 2px 8px; border-radius: 6px; font-weight: 600; }}
.fk-chip.ok {{ color: #166534; background: #DCFCE7; }}
.fk-chip.no {{ color: #991B1B; background: #FEE2E2; }}
.fk-tl {{ position: relative; margin-left: 5px; padding-left: 14px; border-left: 2px solid #CBD5E1; }}
.fk-tl-item {{ position: relative; margin-bottom: 6px; font-size: 10px; }}
.fk-tl-item::before {{ content: ""; position: absolute; left: -20px; top: 2px; width: 10px; height: 10px; border-radius: 50%; background: #3B82F6; border: 2px solid #fff; box-shadow: 0 0 0 1px #CBD5E1; }}
.fk-tl-item.good::before {{ background: #16a34a; }}
.fk-tl-item.bad::before {{ background: #dc2626; }}
.fk-tl-item.pending::before {{ background: #F59E0B; }}
.fk-tl-item .t {{ font-weight: 800; }}
.fk-tl-item .d {{ color: var(--text-secondary); }}
.fk-prog {{ display: flex; align-items: center; gap: 8px; margin-top: 4px; font-size: 10px; }}
.fk-prog .n {{ width: 112px; font-weight: 700; white-space: nowrap; }}
.fk-prog .bar {{ flex: 1; }}
.fk-prog .p {{ width: 64px; text-align: right; color: var(--text-secondary); white-space: nowrap; }}
.fk-sector-head {{ display: flex; align-items: center; gap: 8px; margin: 4px 0 8px 0; }}
.fk-sector-head .name {{ font-size: 14px; font-weight: 800; color: var(--header-blue); }}
.fk-sector-head .cnt {{ font-size: 10px; font-weight: 700; padding: 1px 8px; border-radius: 999px; background: var(--neutral-bg); color: var(--text-secondary); }}
.fk-note {{ font-size: 9px; color: var(--text-secondary); margin-top: 4px; }}

.report-footer {{
  position: absolute; bottom: {PAGE_PADDING_MM / 2}mm; left: {PAGE_PADDING_MM}mm;
  right: {PAGE_PADDING_MM}mm; display: flex; justify-content: space-between;
  font-size: 9px; color: var(--text-secondary); border-top: 1px solid var(--border); padding-top: 4px;
}}
"""


# Dark-mode overrides appended after _BASE_CSS (see apply_theme). The charts
# are inline SVG with fixed light-theme colours, so they're remapped here by
# attribute selector rather than threading a theme through every chart call.
_DARK_CSS = """
:root {
  --text-primary: #E2E8F0; --text-secondary: #94A3B8; --header-blue: #93C5FD; --border: #334155;
  --positive-text: #86EFAC; --positive-bg: #14532D; --negative-text: #FCA5A5; --negative-bg: #7F1D1D;
  --neutral-bg: #1E293B; --accent-amber: #FBBF24;
}
html, body { background: #0B1220; }
.report-page { background: #0F172A; }
.status-pill.warning { background: #78350F; color: #FCD34D; }
.fk-card { background: #111C33; }
.fk-card.fk-new { box-shadow: 0 0 0 2px #78350F; }
.fk-kpi.score .v { color: #FBBF24; }
.fk-badge.open { color: #93C5FD; background: #1E3A8A; border-color: #2563EB; }
.fk-badge.win { color: #86EFAC; background: #14532D; border-color: #16A34A; }
.fk-badge.loss { color: #FCA5A5; background: #7F1D1D; border-color: #DC2626; }
.fk-badge.cancel { color: #FCD34D; background: #78350F; border-color: #D97706; }
.fk-badge.partial { color: #5EEAD4; background: #134E4A; border-color: #0D9488; }
.fk-chip.ok { color: #86EFAC; background: #14532D; }
.fk-chip.no { color: #FCA5A5; background: #7F1D1D; }
.fk-tl-item::before { border-color: #0F172A; box-shadow: 0 0 0 1px #475569; }
.fk-tl { border-left-color: #475569; }
svg text[fill="#334155"], svg text[fill="#0f172a"], svg text[fill="#0F172A"] { fill: #E2E8F0; }
svg text[fill="#64748b"], svg text[fill="#94a3b8"] { fill: #94A3B8; }
svg line[stroke="#E2E8F0"] { stroke: #334155; }
svg line[stroke="#CBD5E1"] { stroke: #475569; }
svg line[stroke="#0F172A"] { stroke: #E2E8F0; }
svg circle[fill="#fff"], svg circle[fill="#ffffff"] { fill: #0F172A; }
"""

THEMES = ("light", "dark")


def apply_theme(html_doc: str, theme: str | None) -> str:
    """Re-skin a finished report document for *theme* ("light" is a no-op).
    Dark appends _DARK_CSS after the base stylesheet, so every report type
    gets it without its own builder knowing about themes."""
    if theme != "dark":
        return html_doc
    return html_doc.replace("</style>", _DARK_CSS + "</style>", 1)


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
    n = len(headers)
    density = "" if n <= 8 else (" dense-1" if n <= 11 else (" dense-2" if n <= 14 else " dense-3"))
    return (
        f'<table class="report-table{density}"><thead><tr>{head}</tr></thead>'
        f'<tbody>{"".join(body_rows)}</tbody></table>'
    )


def section(title: str, body_html: str, subtitle: str = "") -> str:
    sub = f'<p class="section-subtitle">{esc(subtitle)}</p>' if subtitle else ""
    return f'<div class="section"><h2>{esc(title)}</h2>{sub}{body_html}</div>'


# When a saved report is regenerated, it must read as the report that was
# originally generated (#100): the builder wraps its work in generated_as_of(),
# and every header then shows that original timestamp instead of "now".
_GENERATED_AT: ContextVar = ContextVar("report_generated_at", default=None)


@contextmanager
def generated_as_of(original: datetime | None):
    token = _GENERATED_AT.set(original)
    try:
        yield
    finally:
        _GENERATED_AT.reset(token)


def report_header(title: str, subtitle: str, generated_at: datetime, extra_meta: str = "") -> str:
    original = _GENERATED_AT.get()
    if original is not None:
        if abs((generated_at - original).total_seconds()) > 120:
            regenerated = f'Regenerated: {generated_at.strftime("%d-%m-%Y %H:%M")}'
            extra_meta = f"{extra_meta} · {regenerated}" if extra_meta else regenerated
        generated_at = original
    when = generated_at.strftime("%d-%m-%Y %H:%M")
    meta = f'Generated: {esc(when)}'
    if extra_meta:
        meta += f'<br/>{esc(extra_meta)}'
    import branding
    logo = branding.report_logo_html()
    text = (f'<div><h1>{esc(branding.prefixed_report_title(title))}</h1>'
            f'<p class="subtitle">{esc(subtitle)}</p></div>')
    left = f'<div style="display:flex;align-items:center;gap:12px;">{logo}{text}</div>' if logo else text
    return (
        f'<div class="report-header">{left}'
        f'<div class="meta">{meta}</div></div>'
    )


def render_report(pages: list, doc_title: str = "Report") -> str:
    """*pages*: list of already-built inner HTML strings, one per physical
    page (see this module's own docstring for why pagination is decided by
    the caller, not this function). Returns one standalone, self-contained
    HTML document (CSS inlined, no external asset references) ready for
    pdf_export.render_to_pdf() or a QWebEngineView preview.
    """
    import branding
    doc_title = branding.prefixed_report_title(doc_title)
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
