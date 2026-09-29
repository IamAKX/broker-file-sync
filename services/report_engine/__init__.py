"""
Shared rendering/export plumbing for the Reports feature (LMV EOD, EMV EOD,
Fuku Live) — the one place report HTML gets built and turned into a PDF, so
every report type (services.lmv_report_data, services.emv_report_data, ...)
shares the same visual language and export path instead of each hand-rolling
its own.

  templates.py   — the base report HTML layout (header/KPI row/chart-and-
                    table slots/footer with "Page X of Y") and small
                    composable section builders, in plain Python string
                    building — no templating-language dependency (Jinja2
                    etc.) added just for this; report content is closer to
                    "build a tree of HTML snippets from Python data" than
                    to designer-edited template files, so f-strings/html.
                    escape() are enough and keep the dependency footprint
                    (and PyInstaller build surface) unchanged.
  charts.py       — pure-Python inline-SVG chart generators (line/donut/bar/
                    progress) consumed by templates.py's render context.
  pdf_export.py   — renders the built HTML to a PDF file via a hidden
                    QWebEngineView, so the in-app preview and the exported
                    PDF are pixel-identical (one render path, not two).

Deliberately NOT built on a vendored JS charting library (e.g. Chart.js):
charts are rendered server-side (Python) as plain inline SVG embedded
directly in the HTML. This keeps PDF export fully synchronous/deterministic
(no waiting on client-side JS to finish drawing before printToPdf fires, no
JS bundle to vendor/version for offline use in a PyInstaller build) while
still giving CSS-quality visual polish — gradients, rounded donut arcs,
hover titles via SVG <title> — that QPainter/reportlab-style manual layout
can't match as cheaply.
"""
