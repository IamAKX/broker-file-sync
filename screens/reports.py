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

Per-report-type wizard fields and report content live in _populate_*_fields/
_build_*_html below, one pair per report type, dispatched by report["type"].
LMV EOD is wired to real data (services.lmv_report_data); EMV EOD and Fuku
Live still render a clearly-labeled placeholder page until their own data
layers land, so the full pipeline (wizard -> save -> generate -> preview ->
download) stays real and testable for every type today, not a mock.
"""

from datetime import date, datetime, timedelta

import font_scale
from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QComboBox, QDateEdit, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from services import (
    emv_report_data, fuku_live_report_data, lmv_report_data, report_metrics,
    report_recipients, report_store, strategy_store,
)
from services import inception_historical_field_series as hfs
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
_TIMEFRAME_OPTIONS = [
    (report_metrics.TIMEFRAME_DAILY, "Daily"),
    (report_metrics.TIMEFRAME_WEEKLY, "Weekly"),
    (report_metrics.TIMEFRAME_MONTHLY, "Monthly"),
    (report_metrics.TIMEFRAME_QUARTERLY, "Quarterly"),
    (report_metrics.TIMEFRAME_CUSTOM, "Custom Range"),
]


def _parse_float(text: str, default: float) -> float:
    try:
        return float(text.strip())
    except (ValueError, AttributeError):
        return default


def _clear_layout(layout):
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.deleteLater()
        elif item.layout() is not None:
            _clear_layout(item.layout())


def _build_placeholder_html(report: dict) -> str:
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


def _build_lmv_html(report: dict) -> str:
    subject = report.get("subject_config", {})
    tf = report.get("timeframe", {})
    mode = tf.get("mode", report_metrics.TIMEFRAME_DAILY)
    custom_from = date.fromisoformat(tf["from"]) if tf.get("from") else None
    custom_to = date.fromisoformat(tf["to"]) if tf.get("to") else None
    date_from, date_to = report_metrics.resolve_preset_range(mode, custom_from, custom_to)

    data = lmv_report_data.build_report_data(
        subject.get("strategy_a_id"), subject.get("strategy_b_id"),
        # Bucketing granularity is deliberately always daily here — *mode*
        # only sizes the lookback window (resolve_preset_range above); LMV
        # trades are daily-resolution events regardless of how far back the
        # selected horizon looks, and charts.line_chart already thins x-axis
        # labels adaptively for a long daily range.
        report_metrics.TIMEFRAME_DAILY, date_from, date_to,
        subject.get("investment_amount", lmv_report_data.DEFAULT_INVESTMENT_AMOUNT),
        # Only worth the network round trip for a Custom range, which can
        # reach further back than local history's retention — see
        # services.lmv_report_data.build_report_data's own docstring.
        include_backend=(mode == report_metrics.TIMEFRAME_CUSTOM),
    )
    return lmv_report_data.build_report_html(data, doc_title=report.get("name", "LMV EOD Report"))


def _build_emv_html(report: dict) -> str:
    subject = report.get("subject_config", {})
    subtype = subject.get("subtype", "stock")

    if subtype == "strategy":
        as_of = date.fromisoformat(subject["as_of_date"]) if subject.get("as_of_date") else date.today()
        classification = emv_report_data.classify_strategy(subject.get("strategy_id"), as_of)
        return emv_report_data.build_strategy_report_html(
            classification, doc_title=report.get("name", "EMV EOD Report")
        )

    symbol = emv_report_data.resolve_symbol(subject.get("symbol", ""))
    field = subject.get("field", "CLOSE")
    n_periods = int(subject.get("n_periods", 20))
    # Generous calendar-day buffer so N trading days are actually covered
    # even with weekends/holidays in between; historical_field_series only
    # ever returns real trading days regardless, and the extra buffer is
    # trimmed back down to exactly n_periods below.
    date_to = date.today()
    date_from = date_to - timedelta(days=int(n_periods * 1.6) + 10)
    data = emv_report_data.build_stock_report_data(symbol, field, date_from, date_to)
    if len(data["series"]) > n_periods:
        data["series"] = data["series"][-n_periods:]
        data["stats"] = hfs.condition_stats(data["series"])
    return emv_report_data.build_stock_report_html(data, doc_title=report.get("name", "EMV EOD Report"))


def _build_fuku_live_html(report: dict) -> str:
    subject = report.get("subject_config", {})
    data = fuku_live_report_data.build_report_data(
        subject.get("strategy_id"), subject.get("symbol", ""),
        signal=report.get("_signal"),
    )
    return fuku_live_report_data.build_report_html(data, doc_title=report.get("name", "Fuku Live Report"))


def _build_report_html(report: dict) -> str:
    report_type = report.get("type")
    if report_type == report_store.REPORT_TYPE_LMV:
        return _build_lmv_html(report)
    if report_type == report_store.REPORT_TYPE_EMV:
        return _build_emv_html(report)
    if report_type == report_store.REPORT_TYPE_FUKU_LIVE:
        return _build_fuku_live_html(report)
    return _build_placeholder_html(report)


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

        self._type_fields_layout = QVBoxLayout()
        self._type_fields_layout.setSpacing(10)
        card_lay.addLayout(self._type_fields_layout)

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

    def _field_label(self, text: str) -> QLabel:
        t = self._controller.theme
        lbl = QLabel(text)
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        return lbl

    def _populate_lmv_fields(self):
        layout = self._type_fields_layout
        strategies = strategy_store.load_all()

        layout.addWidget(self._field_label("Strategy A"))
        self._strategy_a_combo = QComboBox()
        for s in strategies:
            self._strategy_a_combo.addItem(s.get("name", ""), s.get("id"))
        layout.addWidget(self._strategy_a_combo)

        layout.addWidget(self._field_label("Strategy B (optional — enables comparison)"))
        self._strategy_b_combo = QComboBox()
        self._strategy_b_combo.addItem("None — single strategy", None)
        for s in strategies:
            self._strategy_b_combo.addItem(s.get("name", ""), s.get("id"))
        layout.addWidget(self._strategy_b_combo)

        layout.addWidget(self._field_label("Timeframe"))
        self._timeframe_combo = QComboBox()
        for key, label in _TIMEFRAME_OPTIONS:
            self._timeframe_combo.addItem(label, key)
        layout.addWidget(self._timeframe_combo)

        date_row = QHBoxLayout()
        today = QDate.currentDate()
        date_row.addWidget(QLabel("From:"))
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd-MMM-yyyy")
        self._from_date.setDate(today.addDays(-6))
        date_row.addWidget(self._from_date)
        date_row.addWidget(QLabel("To:"))
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd-MMM-yyyy")
        self._to_date.setDate(today)
        date_row.addWidget(self._to_date)
        date_row.addStretch()
        layout.addLayout(date_row)

        layout.addWidget(self._field_label("Investment Simulation Amount (₹) — used with Strategy A"))
        self._investment_edit = QLineEdit(str(int(lmv_report_data.DEFAULT_INVESTMENT_AMOUNT)))
        layout.addWidget(self._investment_edit)

        if not strategies:
            note = self._field_label("No strategies configured yet — create one in Strategy Builder first.")
            layout.addWidget(note)

    def _on_emv_subtype_changed(self):
        is_strategy = self._emv_subtype_combo.currentData() == "strategy"
        self._emv_stock_frame.setVisible(not is_strategy)
        self._emv_strategy_frame.setVisible(is_strategy)

    def _populate_emv_fields(self):
        from services import inception_strategy_store

        layout = self._type_fields_layout

        layout.addWidget(self._field_label("Report Subject"))
        self._emv_subtype_combo = QComboBox()
        self._emv_subtype_combo.addItem("Stock — historical field trend", "stock")
        self._emv_subtype_combo.addItem("Strategy — qualifying stocks", "strategy")
        self._emv_subtype_combo.currentIndexChanged.connect(self._on_emv_subtype_changed)
        layout.addWidget(self._emv_subtype_combo)

        # Stock subtype fields
        self._emv_stock_frame = QFrame()
        stock_lay = QVBoxLayout(self._emv_stock_frame)
        stock_lay.setContentsMargins(0, 0, 0, 0)
        stock_lay.setSpacing(8)
        stock_lay.addWidget(self._field_label("Stock Symbol"))
        self._emv_symbol_edit = QLineEdit()
        self._emv_symbol_edit.setPlaceholderText("e.g. DIVISLAB")
        stock_lay.addWidget(self._emv_symbol_edit)
        stock_lay.addWidget(self._field_label("Field"))
        self._emv_field_combo = QComboBox()
        for code in hfs.available_fields():
            self._emv_field_combo.addItem(code, code)
        self._emv_field_combo.setEditable(False)
        idx = self._emv_field_combo.findData("DT")
        if idx >= 0:
            self._emv_field_combo.setCurrentIndex(idx)
        stock_lay.addWidget(self._emv_field_combo)
        stock_lay.addWidget(self._field_label("Number of Periods (trading days)"))
        self._emv_periods_spin = QSpinBox()
        self._emv_periods_spin.setRange(2, 500)
        self._emv_periods_spin.setValue(20)
        stock_lay.addWidget(self._emv_periods_spin)
        layout.addWidget(self._emv_stock_frame)

        # Strategy subtype fields
        self._emv_strategy_frame = QFrame()
        strat_lay = QVBoxLayout(self._emv_strategy_frame)
        strat_lay.setContentsMargins(0, 0, 0, 0)
        strat_lay.setSpacing(8)
        strat_lay.addWidget(self._field_label("Strategy"))
        self._emv_strategy_combo = QComboBox()
        strategies = inception_strategy_store.load_all()
        for s in strategies:
            self._emv_strategy_combo.addItem(f'{s.get("name", "")} ({s.get("category", "")})', s.get("id"))
        strat_lay.addWidget(self._emv_strategy_combo)
        strat_lay.addWidget(self._field_label("As Of Date"))
        self._emv_as_of_date = QDateEdit()
        self._emv_as_of_date.setCalendarPopup(True)
        self._emv_as_of_date.setDisplayFormat("dd-MMM-yyyy")
        self._emv_as_of_date.setDate(QDate.currentDate())
        strat_lay.addWidget(self._emv_as_of_date)
        if not strategies:
            strat_lay.addWidget(self._field_label(
                "No Inception strategies configured yet — create one in Inception > Strategy Builder."
            ))
        layout.addWidget(self._emv_strategy_frame)

        self._on_emv_subtype_changed()

    def _populate_fuku_live_fields(self):
        layout = self._type_fields_layout
        layout.addWidget(self._field_label("Alert (Strategy — Symbol)"))
        self._fuku_signal_combo = QComboBox()
        signals = fuku_live_report_data.list_available_signals()
        for s in signals:
            state_label = "OPEN" if s["state"] == "open" else (s["resolution"] or "RESOLVED").replace("_", " ").upper()
            self._fuku_signal_combo.addItem(
                f'{s["strategy_name"]} — {s["symbol"]} ({state_label})',
                (s["strategy_id"], s["symbol"]),
            )
        layout.addWidget(self._fuku_signal_combo)
        if not signals:
            layout.addWidget(self._field_label(
                "No open or recent alerts found — this report needs at least one "
                "Strategy Notifications signal to have fired."
            ))

    def _populate_placeholder_fields(self, type_label: str):
        note = self._field_label(
            f"{type_label}-specific options (subject, fields, sections) will "
            f"appear here as this report type is built out."
        )
        note.setWordWrap(True)
        self._type_fields_layout.addWidget(note)

    def _start_new_report(self, report_type: str):
        self._active_report = report_store.new_report(
            report_type, f"{_REPORT_TYPE_LABELS[report_type]} — {datetime.now().strftime('%d-%b-%Y')}"
        )
        self._wizard_title.setText(f"New {_REPORT_TYPE_LABELS[report_type]}")
        self._name_edit.setText(self._active_report["name"])
        self._recipients_edit.setText("")

        _clear_layout(self._type_fields_layout)
        if report_type == report_store.REPORT_TYPE_LMV:
            self._populate_lmv_fields()
        elif report_type == report_store.REPORT_TYPE_EMV:
            self._populate_emv_fields()
        elif report_type == report_store.REPORT_TYPE_FUKU_LIVE:
            self._populate_fuku_live_fields()
        else:
            self._populate_placeholder_fields(_REPORT_TYPE_LABELS[report_type])

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

        if self._active_report["type"] == report_store.REPORT_TYPE_LMV:
            if self._strategy_a_combo.count() == 0:
                QMessageBox.warning(
                    self, "No Strategies", "Create a strategy in Strategy Builder first."
                )
                return
            strategy_a_id = self._strategy_a_combo.currentData()
            strategy_b_id = self._strategy_b_combo.currentData()
            mode = self._timeframe_combo.currentData()
            investment_amount = _parse_float(
                self._investment_edit.text(), lmv_report_data.DEFAULT_INVESTMENT_AMOUNT
            )
            self._active_report["subject_config"] = {
                "strategy_a_id": strategy_a_id,
                "strategy_b_id": strategy_b_id,
                "investment_amount": investment_amount,
            }
            self._active_report["timeframe"] = {
                "mode": mode,
                "from": self._from_date.date().toPython().isoformat(),
                "to": self._to_date.date().toPython().isoformat(),
            }
        elif self._active_report["type"] == report_store.REPORT_TYPE_EMV:
            subtype = self._emv_subtype_combo.currentData()
            if subtype == "strategy":
                if self._emv_strategy_combo.count() == 0:
                    QMessageBox.warning(
                        self, "No Strategies",
                        "Create an Inception strategy in Strategy Builder first.",
                    )
                    return
                self._active_report["subject_config"] = {
                    "subtype": "strategy",
                    "strategy_id": self._emv_strategy_combo.currentData(),
                    "as_of_date": self._emv_as_of_date.date().toPython().isoformat(),
                }
            else:
                symbol = self._emv_symbol_edit.text().strip()
                if not symbol:
                    QMessageBox.warning(self, "Symbol Required", "Enter a stock symbol.")
                    return
                self._active_report["subject_config"] = {
                    "subtype": "stock",
                    "symbol": symbol,
                    "field": self._emv_field_combo.currentData(),
                    "n_periods": self._emv_periods_spin.value(),
                }
        elif self._active_report["type"] == report_store.REPORT_TYPE_FUKU_LIVE:
            if self._fuku_signal_combo.count() == 0:
                QMessageBox.warning(
                    self, "No Alerts",
                    "No open or recent Strategy Notifications alerts found to report on.",
                )
                return
            strategy_id, symbol = self._fuku_signal_combo.currentData()
            self._active_report["subject_config"] = {"strategy_id": strategy_id, "symbol": symbol}

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
        self._email_btn.clicked.connect(self._email_report)
        header_row.addWidget(self._email_btn)

        layout.addLayout(header_row)

        self._preview_view = QWebEngineView()
        layout.addWidget(self._preview_view, 1)

        return page

    def open_fuku_live_for_signal(self, signal: dict):
        """Entry point from Live Alerts' Quick View: generates the Full Live
        Report straight from *signal* (a backend-sourced alert row, which
        the local state_store lookup wouldn't necessarily find) without the
        wizard. Not saved to the gallery — the "_signal" key is transient
        (stripped by report_store when saving a copy is never done here)."""
        report = report_store.new_report(
            report_store.REPORT_TYPE_FUKU_LIVE,
            f'Fuku Live — {signal.get("symbol", "")} ({datetime.now().strftime("%d-%b-%Y")})',
        )
        report["subject_config"] = {"strategy_id": signal.get("strategy_id"), "symbol": signal.get("symbol", "")}
        report["_signal"] = signal
        self._generate_and_preview(report)

    def _generate_and_preview(self, report: dict):
        self._active_report = report
        try:
            html = _build_report_html(report)
        except Exception as exc:
            QMessageBox.warning(self, "Report Generation Failed", f"Could not generate this report:\n\n{exc}")
            return
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

    def _email_report(self):
        if not self._active_report:
            return
        recipients = report_recipients.load_recipients(self._active_report["id"])
        if not recipients:
            QMessageBox.information(
                self, "No Recipients",
                "This report has no saved email recipients. Add some from the wizard "
                "(edit the report) before emailing it.",
            )
            return

        import os
        import tempfile

        from api.exceptions import ApiError, NetworkError

        self._email_btn.setEnabled(False)
        self._email_btn.setText("Sending…")

        fd, tmp_path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)

        def on_pdf_done(success: bool, error: str | None):
            if not success:
                self._email_btn.setEnabled(True)
                self._email_btn.setText("Email")
                QMessageBox.warning(self, "Email Failed", error or "Could not generate the PDF to send.")
                return
            try:
                from api import reports_api
                reports_api.send_report_email(
                    tmp_path, recipients, subject=self._active_report.get("name", "Report"),
                )
            except (ApiError, NetworkError) as exc:
                QMessageBox.warning(self, "Email Failed", f"Could not send the report:\n\n{exc}")
            except Exception as exc:  # noqa: BLE001
                QMessageBox.warning(self, "Email Failed", f"Could not send the report:\n\n{exc}")
            else:
                QMessageBox.information(
                    self, "Report Emailed", f"Sent to: {', '.join(recipients)}"
                )
            finally:
                self._email_btn.setEnabled(True)
                self._email_btn.setText("Email")
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

        pdf_export.render_to_pdf(self._last_rendered_html, tmp_path, on_pdf_done)

    # ── theme ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        # Gallery/wizard/preview pages use theme colors only at construction
        # time via inline stylesheets (same convention as screens/jobs.py) —
        # rebuild them so a live theme toggle picks up the new palette
        # rather than leaving stale colors on inline-styled widgets.
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
        self._stack.setCurrentWidget(self._gallery_page)
