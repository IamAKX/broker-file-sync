"""
Reports screen (sidebar > Reports) — the shared shell for LMV EOD, EMV EOD
and Fuku Live reports: a Gallery of report types + saved reports, a Wizard
to configure and save a new one, and a Preview/Export page that renders and
lets the user download (or, once the backend attachment endpoint exists,
email) the generated PDF.

This is the FIRST screen in the app that sub-navigates internally (its own
QStackedWidget) rather than living flat in MainWindow's own stack — see
app_window.py's _register_screens, which still only knows this screen by
one top-level "reports" key.

Per-report-type content is intentionally NOT here yet: services.
lmv_report_data / services.emv_report_data / (Fuku Live's own data layer)
each own their report's real KPI/chart/table content and plug into
_build_report_html below as they land — until then, a saved report renders
a clearly-labeled placeholder page so the full pipeline (wizard -> save ->
generate -> preview -> download) is real and testable today, not a mock.
"""

from datetime import datetime

import font_scale
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QMessageBox,
    QPushButton, QStackedWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from services import report_recipients, report_store
from services.report_engine import pdf_export, templates

_REPORT_TYPE_LABELS = {
    report_store.REPORT_TYPE_LMV: "LMV EOD Report",
    report_store.REPORT_TYPE_EMV: "EMV EOD Report",
    report_store.REPORT_TYPE_FUKU_LIVE: "Fuku Live Report",
}
_REPORT_TYPE_DESCRIPTIONS = {
    report_store.REPORT_TYPE_LMV: "Strategy performance — directional yield, "
                                   "comparison, ratios, investment simulation.",
    report_store.REPORT_TYPE_EMV: "Historical trend/condition analysis with "
                                   "user-defined categories and Fuku Score.",
    report_store.REPORT_TYPE_FUKU_LIVE: "Per-alert live report — Fuku Score, "
                                         "support/resistance, lifecycle.",
}


def _build_report_html(report: dict) -> str:
    """Renders *report* to a full HTML document via the shared template
    pipeline. Placeholder content for now — each report type's own data
    layer (services.lmv_report_data etc., landing in later phases) replaces
    this function's body with real KPI cards/charts/tables for its type,
    without changing anything else in this screen.
    """
    type_label = _REPORT_TYPE_LABELS.get(report.get("type"), "Report")
    page = (
        templates.report_header(type_label, report.get("name", ""), datetime.now())
        + templates.section(
            "Report content coming soon",
            '<p style="color:#64748b;font-size:12px;">This report type\'s '
            "real content (KPI cards, charts, tables) isn't wired up yet — "
            "you're looking at the shared report pipeline (layout, PDF "
            "export, pagination) working end-to-end ahead of that.</p>",
        )
    )
    return templates.render_report([page], doc_title=type_label)


class ReportsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._active_report: dict | None = None
        self._last_rendered_html: str | None = None
        self._build()
        self.refresh_gallery()

    # ── build ────────────────────────────────────────────────────────────

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        self._stack = QStackedWidget()
        outer.addWidget(self._stack)

        self._gallery_page = self._build_gallery_page()
        self._wizard_page = self._build_wizard_page()
        self._preview_page = self._build_preview_page()

        self._stack.addWidget(self._gallery_page)
        self._stack.addWidget(self._wizard_page)
        self._stack.addWidget(self._preview_page)
        self._stack.setCurrentWidget(self._gallery_page)

    # ── Gallery ──────────────────────────────────────────────────────────

    def _build_gallery_page(self) -> QWidget:
        t = self._controller.theme
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Reports")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        subtitle = QLabel("Generate, download and email LMV, EMV and Fuku Live reports.")
        subtitle.setFont(font_scale.font(font_scale.SMALL, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        types_row = QHBoxLayout()
        types_row.setSpacing(12)
        for report_type in report_store.REPORT_TYPES:
            types_row.addWidget(self._build_type_card(report_type))
        layout.addLayout(types_row)

        saved_title = QLabel("Saved Reports")
        saved_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        layout.addWidget(saved_title)

        self._saved_table = QTableWidget(0, 4)
        self._saved_table.setHorizontalHeaderLabels(["Name", "Type", "Last Updated", ""])
        self._saved_table.horizontalHeader().setStretchLastSection(False)
        self._saved_table.verticalHeader().setVisible(False)
        self._saved_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._saved_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        layout.addWidget(self._saved_table, 1)

        return page

    def _build_type_card(self, report_type: str) -> QFrame:
        t = self._controller.theme
        card = QFrame()
        card.setObjectName("brokerPanel")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 14, 16, 14)
        card_lay.setSpacing(8)

        name = QLabel(_REPORT_TYPE_LABELS[report_type])
        name.setFont(font_scale.font(font_scale.MEDIUM, True))
        card_lay.addWidget(name)

        desc = QLabel(_REPORT_TYPE_DESCRIPTIONS[report_type])
        desc.setWordWrap(True)
        desc.setFont(font_scale.font(font_scale.SMALL, False))
        desc.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_lay.addWidget(desc)

        new_btn = QPushButton("New Report")
        new_btn.setFixedHeight(30)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 14px; }}"
        )
        new_btn.clicked.connect(lambda: self._start_new_report(report_type))
        card_lay.addWidget(new_btn)
        card_lay.addStretch()
        return card

    def refresh_gallery(self):
        reports = report_store.load_all()
        self._saved_table.setRowCount(len(reports))
        for row, report in enumerate(reports):
            self._saved_table.setItem(row, 0, QTableWidgetItem(report.get("name", "")))
            self._saved_table.setItem(
                row, 1, QTableWidgetItem(_REPORT_TYPE_LABELS.get(report.get("type"), report.get("type", "")))
            )
            self._saved_table.setItem(row, 2, QTableWidgetItem(report.get("updated_at", "")[:19]))

            actions = QWidget()
            actions_lay = QHBoxLayout(actions)
            actions_lay.setContentsMargins(0, 0, 0, 0)
            actions_lay.setSpacing(6)

            gen_btn = QPushButton("Generate")
            gen_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            gen_btn.clicked.connect(lambda _, r=report: self._generate_and_preview(r))
            actions_lay.addWidget(gen_btn)

            del_btn = QPushButton("Delete")
            del_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            del_btn.clicked.connect(lambda _, r=report: self._delete_report(r))
            actions_lay.addWidget(del_btn)

            self._saved_table.setCellWidget(row, 3, actions)

        self._saved_table.resizeColumnsToContents()

    def _delete_report(self, report: dict):
        confirm = QMessageBox.question(
            self, "Delete Report", f'Delete "{report.get("name", "")}"?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if confirm != QMessageBox.StandardButton.Yes:
            return
        report_store.delete_report(report["id"])
        self.refresh_gallery()

    # ── Wizard ───────────────────────────────────────────────────────────

    def _build_wizard_page(self) -> QWidget:
        t = self._controller.theme
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        self._wizard_title = QLabel("New Report")
        self._wizard_title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(self._wizard_title)

        card = QFrame()
        card.setObjectName("brokerPanel")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 16, 20, 16)
        card_lay.setSpacing(10)

        name_label = QLabel("Report Name")
        name_label.setFont(font_scale.font(font_scale.SMALL, False))
        name_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_lay.addWidget(name_label)
        self._name_edit = QLineEdit()
        card_lay.addWidget(self._name_edit)

        recipients_label = QLabel("Email Recipients (separate with ;)")
        recipients_label.setFont(font_scale.font(font_scale.SMALL, False))
        recipients_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_lay.addWidget(recipients_label)
        self._recipients_edit = QLineEdit()
        self._recipients_edit.setPlaceholderText("name@example.com; name2@example.com")
        card_lay.addWidget(self._recipients_edit)

        note = QLabel(
            "Report-type-specific options (columns, timeframe, sections) "
            "will appear here as each report type is built out."
        )
        note.setWordWrap(True)
        note.setFont(font_scale.font(font_scale.SMALL, False))
        note.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_lay.addWidget(note)

        layout.addWidget(card)
        layout.addStretch()

        btn_row = QHBoxLayout()
        back_btn = QPushButton("Cancel")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self._stack.setCurrentWidget(self._gallery_page))
        btn_row.addWidget(back_btn)
        btn_row.addStretch()

        save_btn = QPushButton("Save && Generate")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 16px; height: 32px; }}"
        )
        save_btn.clicked.connect(self._save_and_generate)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

        return page

    def _start_new_report(self, report_type: str):
        self._active_report = report_store.new_report(
            report_type, f"{_REPORT_TYPE_LABELS[report_type]} — {datetime.now().strftime('%d-%b-%Y')}"
        )
        self._wizard_title.setText(f"New {_REPORT_TYPE_LABELS[report_type]}")
        self._name_edit.setText(self._active_report["name"])
        self._recipients_edit.setText("")
        self._stack.setCurrentWidget(self._wizard_page)

    def _save_and_generate(self):
        if self._active_report is None:
            return
        name = self._name_edit.text().strip()
        if not name:
            QMessageBox.warning(self, "Report Name Required", "Enter a name for this report.")
            return

        recipients_text = self._recipients_edit.text().strip()
        if recipients_text:
            parsed, error = report_recipients.parse_recipients(recipients_text)
            if error:
                QMessageBox.warning(self, "Invalid Recipients", error)
                return
        else:
            parsed = []

        self._active_report["name"] = name
        report_store.save_report(self._active_report)
        report_recipients.save_recipients(self._active_report["id"], parsed)

        self.refresh_gallery()
        self._generate_and_preview(self._active_report)

    # ── Preview / Export ─────────────────────────────────────────────────

    def _build_preview_page(self) -> QWidget:
        t = self._controller.theme
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(10)

        header_row = QHBoxLayout()
        self._preview_title = QLabel("Report Preview")
        self._preview_title.setFont(font_scale.font(font_scale.LARGE, True))
        header_row.addWidget(self._preview_title)
        header_row.addStretch()

        back_btn = QPushButton("Back to Reports")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(lambda: self._stack.setCurrentWidget(self._gallery_page))
        header_row.addWidget(back_btn)

        self._download_btn = QPushButton("Download PDF")
        self._download_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._download_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 14px; height: 30px; }}"
        )
        self._download_btn.clicked.connect(self._download_pdf)
        header_row.addWidget(self._download_btn)

        self._email_btn = QPushButton("Email")
        self._email_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._email_btn.setEnabled(False)
        self._email_btn.setToolTip(
            "Email delivery needs the backend's attachment-capable send "
            "endpoint — not deployed yet. Use Download PDF for now."
        )
        header_row.addWidget(self._email_btn)

        layout.addLayout(header_row)

        self._preview_view = QWebEngineView()
        layout.addWidget(self._preview_view, 1)

        return page

    def _generate_and_preview(self, report: dict):
        self._active_report = report
        html = _build_report_html(report)
        self._last_rendered_html = html
        self._preview_title.setText(report.get("name", "Report Preview"))
        self._preview_view.setHtml(html)
        self._stack.setCurrentWidget(self._preview_page)

    def _download_pdf(self):
        if not self._last_rendered_html or not self._active_report:
            return
        default_name = (self._active_report.get("name") or "report").replace(" ", "_") + ".pdf"
        path, _unused = QFileDialog.getSaveFileName(self, "Download Report PDF", default_name, "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"

        self._download_btn.setEnabled(False)
        self._download_btn.setText("Generating…")

        def on_done(success: bool, error: str | None):
            self._download_btn.setEnabled(True)
            self._download_btn.setText("Download PDF")
            if success:
                QMessageBox.information(self, "Report Downloaded", f"Saved to:\n{path}")
            else:
                QMessageBox.warning(self, "Export Failed", error or "Unknown error generating the PDF.")

        pdf_export.render_to_pdf(self._last_rendered_html, path, on_done)

    # ── theme ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        # Gallery/wizard/preview pages use theme colors only at construction
        # time via inline stylesheets (same convention as screens/jobs.py) —
        # rebuild them so a live theme toggle picks up the new palette
        # rather than leaving stale colors on inline-styled widgets.
        current = self._stack.currentWidget()
        self._stack.removeWidget(self._gallery_page)
        self._stack.removeWidget(self._wizard_page)
        self._stack.removeWidget(self._preview_page)
        self._gallery_page = self._build_gallery_page()
        self._wizard_page = self._build_wizard_page()
        self._preview_page = self._build_preview_page()
        self._stack.addWidget(self._gallery_page)
        self._stack.addWidget(self._wizard_page)
        self._stack.addWidget(self._preview_page)
        self.refresh_gallery()
        self._stack.setCurrentWidget(
            self._gallery_page if current not in (self._wizard_page, self._preview_page) else self._gallery_page
        )
