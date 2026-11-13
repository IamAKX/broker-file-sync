"""Builds the "Save chat as PDF" document for Ask Fuku (screens/chat.py).

The transcript is turned into one self-contained HTML page - questions,
answers as they are shown (so an answer switched to Tamil is saved in Tamil)
and the data rows behind any answer that has a "Show data" table - and printed
through the same Chromium path as the Reports feature
(services.report_engine.pdf_export), which shapes Tamil text correctly.
"""

import html
import re
from datetime import datetime

# (left, top, right, bottom) for pdf_export.render_to_pdf: this page reserves no
# padding of its own, unlike the report templates.
PAGE_MARGINS_MM = (14, 14, 14, 14)

_CSS = """
body { font-family: -apple-system, "Segoe UI", "Helvetica Neue", Arial, "Nirmala UI", "Tamil Sangam MN",
       "Noto Sans Tamil", sans-serif; font-size: 10.5pt; line-height: 1.45; color: #1c2430; margin: 0; }
h1.doc-title { font-size: 17pt; margin: 0 0 2px 0; }
.meta { color: #667085; font-size: 9pt; margin-bottom: 16px; border-bottom: 1px solid #d9dee7; padding-bottom: 10px; }
.turn { margin: 0 0 12px 0; padding: 9px 12px; border-radius: 8px; border: 1px solid #d9dee7; }
.turn.user { background: #eef4ff; border-color: #c9dafc; }
.turn.error { color: #b42318; }
.who { font-size: 8.5pt; font-weight: 700; letter-spacing: .04em; text-transform: uppercase; color: #667085;
       margin-bottom: 3px; }
.text p { margin: 0 0 6px 0 !important; }
.text h1, .text h2, .text h3, .text h4 { margin: 8px 0 4px 0 !important; font-size: 11.5pt; }
.text h1 span, .text h2 span, .text h3 span, .text h4 span { font-size: 11.5pt !important; }
.text ul, .text ol { margin: 0 0 6px 0 !important; padding-left: 20px; }
table { border-collapse: collapse; margin: 6px 0 !important; font-size: 9pt; }
th, td { border: 1px solid #c8ced9; padding: 3px 7px !important; text-align: left; vertical-align: top; }
th { background: #f1f3f7; font-weight: 700; }
td.num { text-align: right; white-space: nowrap; }
tr { page-break-inside: avoid; }
.data-title { font-size: 8.5pt; font-weight: 700; color: #667085; margin: 8px 0 0 0; text-transform: uppercase;
              letter-spacing: .04em; }
.caption { color: #667085; font-size: 8.5pt; }
.footer { color: #667085; font-size: 8.5pt; margin-top: 16px; border-top: 1px solid #d9dee7; padding-top: 8px; }
"""

DISCLAIMER = "Answers are generated from Fuku Lens data and may contain mistakes. Not investment advice."


def markdown_to_html(text: str) -> str:
    """Answer Markdown -> an HTML fragment, via Qt's own Markdown reader (the one
    the chat bubble renders with), so the PDF shows what the screen shows."""
    from PySide6.QtGui import QTextDocument

    doc = QTextDocument()
    doc.setMarkdown(text)
    full = doc.toHtml()
    match = re.search(r"<body[^>]*>(.*)</body>", full, re.DOTALL)
    fragment = match.group(1) if match else html.escape(text).replace("\n", "<br>")
    # Qt writes the app's font and its own table chrome inline; the page CSS decides those.
    fragment = re.sub(r"font-family:[^;\"]*;?", "", fragment)
    fragment = re.sub(r"<table[^>]*>", "<table>", fragment)
    return fragment


def _data_table(details: dict) -> str:
    columns, rows = details.get("columns") or [], details.get("rows") or []
    if not columns:
        return ""
    head = "".join(f"<th>{html.escape(str(c))}</th>" for c in columns)
    body = []
    for row in rows:
        cells = []
        for val in row:
            cls = ' class="num"' if isinstance(val, (int, float)) and not isinstance(val, bool) else ""
            cells.append(f"<td{cls}>{html.escape('' if val is None else str(val))}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    note = f"{details.get('row_count', len(rows))} row(s)"
    if details.get("truncated"):
        note += f" - first {len(rows)} shown"
    return (
        '<div class="data-title">Data</div>'
        f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"
        f'<div class="caption">{html.escape(note)}</div>'
    )


def build_html(turns: list[dict], saved_at: datetime | None = None, user_name: str = "") -> str:
    """*turns*: [{"role": "user"|"assistant", "text": str, "details": dict|None,
    "error": bool}] oldest first; "details" is the rows event behind an answer
    ({"columns", "rows", "row_count", "truncated"})."""
    saved_at = saved_at or datetime.now()
    meta = "Saved " + saved_at.strftime("%d %b %Y, %H:%M")
    if user_name:
        meta += f" · {html.escape(user_name)}"
    parts = []
    for turn in turns:
        is_user = turn.get("role") == "user"
        text = turn.get("text") or ""
        if is_user or turn.get("error"):
            body = html.escape(text).replace("\n", "<br>")
        else:
            body = markdown_to_html(text)
        cls = "user" if is_user else ("assistant error" if turn.get("error") else "assistant")
        table = "" if is_user or not turn.get("details") else _data_table(turn["details"])
        parts.append(
            f'<div class="turn {cls}"><div class="who">{"You" if is_user else "Fuku"}</div>'
            f'<div class="text">{body}</div>{table}</div>'
        )
    return (
        '<!DOCTYPE html><html><head><meta charset="utf-8"><title>Ask Fuku chat</title>'
        f"<style>{_CSS}</style></head><body>"
        f'<h1 class="doc-title">Ask Fuku chat</h1><div class="meta">{meta}</div>'
        f"{''.join(parts)}"
        f'<div class="footer">{DISCLAIMER}</div></body></html>'
    )


def default_filename(saved_at: datetime | None = None) -> str:
    return "Ask_Fuku_chat_" + (saved_at or datetime.now()).strftime("%Y-%m-%d_%H%M") + ".pdf"
