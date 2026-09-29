"""
Renders report HTML to a PDF file via a hidden QWebEngineView — the same
rendering engine (Chromium, via QtWebEngine) as the in-app report preview
(screens.reports's Preview/Export page will show this exact HTML in a
QWebEngineView too), so "what you see in the preview" and "what prints" are
pixel-identical: one render path, not two. Verified viable under
`QT_QPA_PLATFORM=offscreen` (CI's headless mode, see .github/workflows/
ci.yml) — QWebEngineView.page().printToPdf() renders and prints entirely
off-screen, no real display needed.

Margins default to zero: templates.render_report()'s `.report-page` CSS
already owns physical page padding (PAGE_PADDING_MM), so there's exactly
one source of truth for spacing instead of this module's QPageLayout
margins and that CSS padding both applying and stacking.

Async by nature (loadFinished, then printToPdf's own pdfPrintingFinished
signal) — the first background-style export in this codebase (see the
package docstring). Callers get a result via *on_done*, never a return
value.
"""

from collections.abc import Callable

from PySide6.QtCore import QMarginsF, QUrl
from PySide6.QtGui import QPageLayout, QPageSize
from PySide6.QtWebEngineWidgets import QWebEngineView

# A view mid-render must be kept alive (nothing else holds a reference,
# and callers of render_to_pdf aren't expected to) or Qt garbage-collects
# it out from under the in-flight async load/print — keyed by id(view) so
# completion pops exactly its own entry, not some other concurrent export's.
_PENDING: dict[int, QWebEngineView] = {}


def render_to_pdf(html: str, output_path: str,
                   on_done: Callable[[bool, str | None], None],
                   page_size_id=QPageSize.PageSizeId.A4,
                   margins_mm: tuple = (0, 0, 0, 0)) -> None:
    """Render *html* to *output_path* as a PDF. *on_done(success, error)* is
    called exactly once, from the Qt event loop, once the PDF has been
    written (or failed) — *success* is printToPdf's own boolean; *error* is
    a short message on failure, else None.

    *margins_mm* is (left, top, right, bottom); the default (0,0,0,0)
    assumes the HTML's own CSS already reserves page margin as padding
    (see templates.render_report) — pass non-zero margins only for HTML
    that does NOT already do that.
    """
    view = QWebEngineView()
    _PENDING[id(view)] = view

    layout = QPageLayout(
        QPageSize(page_size_id), QPageLayout.Orientation.Portrait,
        QMarginsF(*margins_mm), QPageLayout.Unit.Millimeter,
    )

    def _cleanup():
        _PENDING.pop(id(view), None)

    def _on_pdf_finished(path: str, success: bool):
        _cleanup()
        on_done(success, None if success else f"PDF export failed writing {path}")

    def _on_load_finished(ok: bool):
        if not ok:
            _cleanup()
            on_done(False, "Report HTML failed to load")
            return
        view.page().printToPdf(output_path, layout)

    view.page().pdfPrintingFinished.connect(_on_pdf_finished)
    view.loadFinished.connect(_on_load_finished)
    # A base QUrl of "file:///" (not a real path) — report HTML has no
    # external asset references to resolve (see the package docstring: no
    # vendored JS, charts are inline SVG), this just satisfies
    # QWebEngineView.setHtml()'s requirement for *some* base URL.
    view.setHtml(html, QUrl("file:///"))
