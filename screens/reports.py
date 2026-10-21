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

import threading

import font_scale
from PySide6.QtCore import QDate, Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QComboBox, QCompleter, QDateEdit, QDoubleSpinBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QListWidget, QListWidgetItem, QMessageBox, QPushButton, QScrollArea, QSpinBox, QStackedWidget,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)
from PySide6.QtWebEngineWidgets import QWebEngineView

from screens.report_column_picker import ColumnPickerWidget
from screens.report_indicator_picker import IndicatorPickerWidget
from services import (
    emv_report_data, fuku_live_report_data, lmv_report_data, report_columns,
    report_metrics, report_recipients, report_store, sector_report_data, strategy_store,
)
from services.strategy_alerts import config_store as alerts_config_store
from services import indicator_library
from services import inception_historical_field_series as hfs
from services.report_engine import pdf_export, templates

_REPORT_TYPE_LABELS = {
    report_store.REPORT_TYPE_LMV: "LMV EOD Report",
    report_store.REPORT_TYPE_EMV: "EMV EOD Report",
    report_store.REPORT_TYPE_FUKU_LIVE: "Fuku Live Report",
    report_store.REPORT_TYPE_SECTOR: "Sector Report",
}
_REPORT_TYPE_DESCRIPTIONS = {
    report_store.REPORT_TYPE_LMV: "Strategy performance — directional yield, "
                                   "comparison, ratios, investment simulation.",
    report_store.REPORT_TYPE_EMV: "Historical trend/condition analysis with "
                                   "user-defined categories and Fuku Score.",
    report_store.REPORT_TYPE_FUKU_LIVE: "Per-alert live report — Fuku Score, "
                                         "support/resistance, lifecycle.",
    report_store.REPORT_TYPE_SECTOR: "EOD or Live sector heatmaps, strongest/weakest "
                                      "sectors, sector bars and stock drill-down.",
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
        # Local alert_history is per-machine and capped at ~500 records, so
        # even a recent Daily/Weekly report can be empty on a machine that
        # didn't fire the alerts — always supplement from the backend
        # (best-effort: failures just fall back to local history).
        include_backend=True,
        backtest=subject.get("source") == "backtest",
        compare=subject.get("compare"),
        indicator_ids=subject.get("indicator_ids"), indicator_symbols=subject.get("indicator_symbols"),
        indicator_days=int(subject.get("indicator_days") or 60),
    )
    return lmv_report_data.build_report_html(
        data, doc_title=report.get("name", "LMV EOD Report"), columns=report.get("columns")
    )


def _build_emv_html(report: dict) -> str:
    subject = report.get("subject_config", {})
    subtype = subject.get("subtype", "stock")

    if subtype == "trend":
        as_of = date.fromisoformat(subject["as_of_date"]) if subject.get("as_of_date") else date.today()
        classification = emv_report_data.classify_trend(
            subject.get("category_id"), subject.get("timeframe", "Daily"), as_of,
            multi_timeframe=bool(subject.get("multi_timeframe")),
            with_days_true=bool(subject.get("days_true", True)),
        )
        return emv_report_data.build_trend_report_html(
            classification, doc_title=report.get("name", "EMV EOD Report"), columns=report.get("columns"),
            show_days_true=bool(subject.get("days_true", True)),
            multi_timeframe=bool(subject.get("multi_timeframe")),
        )

    if subtype == "strategy":
        as_of = date.fromisoformat(subject["as_of_date"]) if subject.get("as_of_date") else date.today()
        classification = emv_report_data.classify_strategy(subject.get("strategy_id"), as_of)
        return emv_report_data.build_strategy_report_html(
            classification, doc_title=report.get("name", "EMV EOD Report"),
            columns=report.get("columns"),
            bubble_x=subject.get("bubble_x"), bubble_y=subject.get("bubble_y"),
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
    indicator_ids = subject.get("indicator_ids") or []
    data = emv_report_data.build_stock_report_data(
        symbol, field, date_from, date_to, indicator_ids,
        extra_fields=subject.get("extra_fields"), field_color=subject.get("field_color"),
    )
    if len(data["series"]) > n_periods:
        data["series"] = data["series"][-n_periods:]
        for extra in data["extras"]:
            extra["series"] = extra["series"][-n_periods:]
        data["stats"] = hfs.condition_stats(data["series"])
        # Re-derive against the trimmed window so plots match the shown periods.
        data["indicator_sections"] = emv_report_data.indicator_sections_for(
            symbol, data["series"], indicator_ids
        )
    return emv_report_data.build_stock_report_html(data, doc_title=report.get("name", "EMV EOD Report"))


def _is_fuku_strategy_scope(report: dict) -> bool:
    return (report.get("type") == report_store.REPORT_TYPE_FUKU_LIVE
            and (report.get("subject_config") or {}).get("scope") == "strategy")


def _is_live_sector(report: dict) -> bool:
    return (report.get("type") == report_store.REPORT_TYPE_SECTOR
            and (report.get("subject_config") or {}).get("mode") == "live")


def _is_auto_refresh_report(report: dict) -> bool:
    """Reports that regenerate on a timer while their preview is open."""
    return _is_fuku_strategy_scope(report) or _is_live_sector(report)


def _build_sector_html(report: dict, lmv_snapshot: tuple | None = None) -> str:
    subject = report.get("subject_config", {})
    metric = subject.get("metric") or None
    mode = subject.get("mode", "eod")
    if mode == "live":
        headers, data = lmv_snapshot if lmv_snapshot else ([], [])
        source = sector_report_data.live_stocks(headers, data, metric)
    else:
        as_of = date.fromisoformat(subject["as_of_date"]) if subject.get("as_of_date") else date.today()
        source = sector_report_data.eod_stocks(as_of, metric)
    sector_data = sector_report_data.build_sector_report_data(
        source, mode, metric, selected_sector=subject.get("sector"),
        primary_timeframe=subject.get("primary_timeframe", "Daily"),
        heat_step=subject.get("heat_step") or None,
        refresh_minutes=int(subject.get("refresh_minutes") or 0) if mode == "live" else 0,
    )
    return sector_report_data.build_sector_report_html(sector_data, doc_title=report.get("name", "Sector Report"))


def _build_fuku_live_html(report: dict, new_since: datetime | None = None) -> str:
    subject = report.get("subject_config", {})
    if subject.get("scope") == "strategy":
        data = fuku_live_report_data.build_strategy_report_data(
            subject.get("strategy_id"),
            include_stopped=bool(subject.get("include_stopped")),
            include_cancelled=bool(subject.get("include_cancelled")),
            include_achieved=bool(subject.get("include_achieved")),
            new_since=new_since, refresh_minutes=int(subject.get("refresh_minutes") or 0),
            indicator_ids=subject.get("indicator_ids"), indicator_days=int(subject.get("indicator_days") or 60),
            show_why=bool(subject.get("show_why", True)),
        )
        return fuku_live_report_data.build_strategy_report_html(
            data, doc_title=report.get("name", "Fuku Live Report"))
    data = fuku_live_report_data.build_report_data(
        subject.get("strategy_id"), subject.get("symbol", ""),
        signal=report.get("_signal"),
        indicator_ids=subject.get("indicator_ids"), indicator_days=int(subject.get("indicator_days") or 60),
        show_why=bool(subject.get("show_why", True)),
    )
    return fuku_live_report_data.build_report_html(data, doc_title=report.get("name", "Fuku Live Report"))


def _build_report_html(report: dict, new_since: datetime | None = None, lmv_snapshot: tuple | None = None) -> str:
    report_type = report.get("type")
    if report_type == report_store.REPORT_TYPE_LMV:
        html = _build_lmv_html(report)
    elif report_type == report_store.REPORT_TYPE_EMV:
        html = _build_emv_html(report)
    elif report_type == report_store.REPORT_TYPE_FUKU_LIVE:
        html = _build_fuku_live_html(report, new_since)
    elif report_type == report_store.REPORT_TYPE_SECTOR:
        html = _build_sector_html(report, lmv_snapshot)
    else:
        html = _build_placeholder_html(report)
    # Light/Dark chosen in the wizard — applied here so every report type
    # (and the live auto-refresh) gets it, both in the preview and the PDF.
    return templates.apply_theme(html, (report.get("visuals") or {}).get("theme"))


def _make_searchable(combo: QComboBox) -> QComboBox:
    """Dropdown with type-ahead filtering (contains, case-insensitive) that
    still only accepts the listed items — for long strategy/alert lists."""
    combo.setEditable(True)
    combo.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
    completer = combo.completer()
    completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
    completer.setFilterMode(Qt.MatchFlag.MatchContains)
    combo.setMaxVisibleItems(20)
    return combo


class _SymbolCombo(QComboBox):
    """Editable stock dropdown with type-ahead. setText/text mirror QLineEdit
    so the wizard code (and tests) written against the old free-text field
    keep working — the user can still type any symbol that isn't listed."""

    def __init__(self, symbols: list):
        super().__init__()
        self.setEditable(True)
        self.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.addItems(symbols)
        self.setCurrentIndex(-1)
        self.lineEdit().setPlaceholderText("Select or type a stock, e.g. DIVISLAB")
        completer = QCompleter(symbols, self)
        completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.setCompleter(completer)

    def setText(self, text: str):
        self.setCurrentText(text)

    def text(self) -> str:
        return self.currentText()


def _color_button_style(color: str) -> str:
    return (f"QPushButton {{ background: {color}; border: 1px solid #64748b; border-radius: 4px; "
            f"min-width: 26px; max-width: 26px; min-height: 22px; max-height: 22px; }}")


class ReportsScreen(QWidget):
    # (generation token, report, html or None, error text or None) — emitted
    # from the report-building thread, delivered on the GUI thread.
    _html_ready = Signal(int, object, object, object)

    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        # Building a report (EMV strategy: a whole-universe snapshot) can take
        # many seconds; it runs on a worker thread so the window stays
        # responsive. Tests that assert on the result straight after a call
        # turn this off to build inline.
        self._async_generation = True
        self._generation_token = 0
        self._html_ready.connect(self._on_html_ready)
        self._active_report: dict | None = None
        self._last_rendered_html: str | None = None
        # Fuku Live strategy reports regenerate on this timer while the
        # preview is showing; _last_generated_at is the "new since" cutoff.
        self._refresh_timer = QTimer(self)
        self._refresh_timer.timeout.connect(self._auto_refresh_tick)
        self._last_generated_at: datetime | None = None
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

            edit_btn = QPushButton("Edit")
            edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            edit_btn.clicked.connect(lambda _, r=report: self._edit_report(r))
            actions_lay.addWidget(edit_btn)

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

        theme_label = QLabel("Report appearance")
        theme_label.setFont(font_scale.font(font_scale.SMALL, False))
        theme_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_lay.addWidget(theme_label)
        self._report_theme_combo = QComboBox()
        self._report_theme_combo.addItem("Light", "light")
        self._report_theme_combo.addItem("Dark", "dark")
        card_lay.addWidget(self._report_theme_combo)

        self._type_fields_layout = QVBoxLayout()
        self._type_fields_layout.setSpacing(10)
        card_lay.addLayout(self._type_fields_layout)

        # Scrollable: with the many per-type fields (indicator picker, column
        # picker, ...) a plain layout squeezed every widget below its usable
        # height on a normal window (#79).
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(card)
        layout.addWidget(scroll, 1)

        btn_row = QHBoxLayout()
        back_btn = QPushButton("Cancel")
        back_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        back_btn.clicked.connect(self._leave_preview)
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
        self._timeframe_combo.currentIndexChanged.connect(self._sync_lmv_date_range)

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
        self._sync_lmv_date_range()

        layout.addWidget(self._field_label("Trades from"))
        self._lmv_source_combo = QComboBox()
        self._lmv_source_combo.addItem("Recorded alerts (what the strategy actually fired)", "recorded")
        self._lmv_source_combo.addItem(
            "Back-test — replay the strategy over stored daily LMV data (works even if it was not active)",
            "backtest")
        layout.addWidget(self._lmv_source_combo)

        layout.addWidget(self._field_label("Investment Simulation Amount (₹) — used with Strategy A"))
        self._investment_edit = QLineEdit(str(int(lmv_report_data.DEFAULT_INVESTMENT_AMOUNT)))
        layout.addWidget(self._investment_edit)

        self._add_indicator_fields(layout, with_symbols=True)

        layout.addWidget(self._field_label("Cross-Compare — compare two assets under Strategy A"))
        self._compare_mode_combo = QComboBox()
        self._compare_mode_combo.addItem("Stock vs Stock", "stock")
        self._compare_mode_combo.addItem("Sector vs Sector", "sector")
        layout.addWidget(self._compare_mode_combo)
        compare_row = QHBoxLayout()
        self._compare_asset_1 = QLineEdit()
        self._compare_asset_2 = QLineEdit()
        self._compare_asset_1.setPlaceholderText("Asset 1 (blank = auto, e.g. ALKEM)")
        self._compare_asset_2.setPlaceholderText("Asset 2 (blank = auto, e.g. TATASTEEL)")
        compare_row.addWidget(self._compare_asset_1)
        compare_row.addWidget(self._compare_asset_2)
        layout.addLayout(compare_row)

        layout.addWidget(self._field_label(
            "Trade table columns (leave Selected empty for the default set)"
        ))
        metric_names = []
        for cfg in alerts_config_store.load_configs().values():
            metric_names += [m.get("name") for m in cfg.get("metrics", [])]
        self._lmv_column_picker = ColumnPickerWidget(report_columns.lmv_catalog(metric_names))
        layout.addWidget(self._lmv_column_picker)

        if not strategies:
            note = self._field_label("No strategies configured yet — create one in Strategy Builder first.")
            layout.addWidget(note)

    def _sync_lmv_date_range(self):
        """From/To only apply to Custom Range — for Daily/Weekly/... they were
        silently ignored while still looking editable (#78: a 06-Oct..15-Oct
        range produced a report of just 'today'). Show the range the preset
        really uses and lock the pickers."""
        custom = self._timeframe_combo.currentData() == report_metrics.TIMEFRAME_CUSTOM
        if not custom:
            lo, hi = report_metrics.resolve_preset_range(self._timeframe_combo.currentData())
            self._from_date.setDate(QDate(lo.year, lo.month, lo.day))
            self._to_date.setDate(QDate(hi.year, hi.month, hi.day))
        self._from_date.setEnabled(custom)
        self._to_date.setEnabled(custom)

    def _refresh_indicator_choices(self):
        checked = {
            self._emv_indicator_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._emv_indicator_list.count())
            if self._emv_indicator_list.item(i).checkState() == Qt.CheckState.Checked
        }
        self._emv_indicator_list.clear()
        for inst in indicator_library.load_instances():
            item = QListWidgetItem(
                f'{indicator_library.instance_label(inst["key"], inst["params"])}'
                f' — {indicator_library.get_definition(inst["key"])["name"]}'
            )
            item.setData(Qt.ItemDataRole.UserRole, inst["id"])
            # Deliberately NOT ItemIsUserCheckable: itemClicked toggles the
            # state itself, and the native toggle would double-flip it.
            item.setCheckState(Qt.CheckState.Checked if inst["id"] in checked else Qt.CheckState.Unchecked)
            self._emv_indicator_list.addItem(item)

    @staticmethod
    def _toggle_indicator_item(item: QListWidgetItem):
        item.setCheckState(
            Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
            else Qt.CheckState.Checked
        )

    def _set_all_indicators(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._emv_indicator_list.count()):
            self._emv_indicator_list.item(i).setCheckState(state)

    def _open_indicator_library(self):
        from screens.indicator_library_dialog import IndicatorLibraryDialog
        IndicatorLibraryDialog(parent=self).exec()
        self._refresh_indicator_choices()

    def _selected_indicator_ids(self) -> list:
        return [
            self._emv_indicator_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._emv_indicator_list.count())
            if self._emv_indicator_list.item(i).checkState() == Qt.CheckState.Checked
        ]

    def _on_emv_subtype_changed(self):
        subtype = self._emv_subtype_combo.currentData()
        self._emv_stock_frame.setVisible(subtype == "stock")
        self._emv_strategy_frame.setVisible(subtype == "strategy")
        self._emv_trend_frame.setVisible(subtype == "trend")

    @staticmethod
    def _emv_symbol_choices() -> list:
        """Display names of every stock with synced bars, sorted — the
        stock dropdown's choices."""
        try:
            from services import inception_bars_store
            names = {emv_report_data._display_symbol(sym) for sym in inception_bars_store.available_symbols()}
        except Exception:
            names = set()
        return sorted(n for n in names if n)

    def _refresh_trend_category_choices(self):
        from services import trend_categories
        current = self._emv_trend_category.currentData()
        self._emv_trend_category.clear()
        self._emv_trend_category.addItem("All categories", None)
        for cat in trend_categories.load_all():
            if cat.get("active"):
                self._emv_trend_category.addItem(cat["name"], cat["id"])
        self._select_data(self._emv_trend_category, current)

    def _open_trend_category_manager(self):
        from screens.trend_category_dialog import TrendCategoryDialog
        TrendCategoryDialog(parent=self).exec()
        self._refresh_trend_category_choices()

    def _pick_primary_field_color(self):
        chosen = QColorDialog.getColor(QColor(self._emv_field_color), self, "Field line colour")
        if chosen.isValid():
            self._set_primary_field_color(chosen.name())

    def _set_primary_field_color(self, color: str):
        self._emv_field_color = color
        self._emv_field_color_btn.setStyleSheet(_color_button_style(color))

    def _add_extra_field(self):
        name = self._emv_extra_combo.currentData()
        primary = self._emv_field_combo.currentData()
        if not name or name == primary or any(e["field"] == name for e in self._emv_extra_fields):
            return
        palette = emv_report_data.EXTRA_FIELD_COLORS
        self._emv_extra_fields.append({"field": name, "color": palette[len(self._emv_extra_fields) % len(palette)]})
        self._refresh_extra_field_list()

    def _selected_extra_row(self) -> int:
        return self._emv_extra_list.currentRow()

    def _recolor_extra_field(self):
        row = self._selected_extra_row()
        if row < 0:
            return
        chosen = QColorDialog.getColor(QColor(self._emv_extra_fields[row]["color"]), self, "Column line colour")
        if chosen.isValid():
            self._emv_extra_fields[row]["color"] = chosen.name()
            self._refresh_extra_field_list(select=row)

    def _remove_extra_field(self):
        row = self._selected_extra_row()
        if row >= 0:
            del self._emv_extra_fields[row]
            self._refresh_extra_field_list()

    def _refresh_extra_field_list(self, select: int = -1):
        self._emv_extra_list.clear()
        for entry in self._emv_extra_fields:
            item = QListWidgetItem(f'■  {entry["field"]}   ({entry["color"]})')
            item.setForeground(QColor(entry["color"]))
            self._emv_extra_list.addItem(item)
        if select >= 0:
            self._emv_extra_list.setCurrentRow(select)

    def _populate_emv_fields(self):
        from services import inception_strategy_store

        layout = self._type_fields_layout

        layout.addWidget(self._field_label("Report Subject"))
        self._emv_subtype_combo = QComboBox()
        self._emv_subtype_combo.addItem("Stock — historical field trend", "stock")
        self._emv_subtype_combo.addItem("Strategy — qualifying stocks", "strategy")
        self._emv_subtype_combo.addItem("Trend category — stocks by classification", "trend")
        self._emv_subtype_combo.currentIndexChanged.connect(self._on_emv_subtype_changed)
        layout.addWidget(self._emv_subtype_combo)

        # Stock subtype fields
        self._emv_stock_frame = QFrame()
        stock_lay = QVBoxLayout(self._emv_stock_frame)
        stock_lay.setContentsMargins(0, 0, 0, 0)
        stock_lay.setSpacing(8)
        stock_lay.addWidget(self._field_label("Stock Symbol"))
        self._emv_symbol_edit = _SymbolCombo(self._emv_symbol_choices())
        stock_lay.addWidget(self._emv_symbol_edit)
        stock_lay.addWidget(self._field_label("Field (compared against Close)"))
        field_row = QHBoxLayout()
        self._emv_field_combo = QComboBox()
        for code in hfs.available_fields(include_gap_dates=False):
            self._emv_field_combo.addItem(code, code)
        self._emv_field_combo.setEditable(False)
        idx = self._emv_field_combo.findData("DT")
        if idx >= 0:
            self._emv_field_combo.setCurrentIndex(idx)
        field_row.addWidget(self._emv_field_combo, 1)
        self._emv_field_color = emv_report_data.DEFAULT_FIELD_COLOR
        self._emv_field_color_btn = QPushButton()
        self._emv_field_color_btn.setToolTip("Line colour for this field")
        self._emv_field_color_btn.setStyleSheet(_color_button_style(self._emv_field_color))
        self._emv_field_color_btn.clicked.connect(self._pick_primary_field_color)
        field_row.addWidget(self._emv_field_color_btn)
        stock_lay.addLayout(field_row)

        stock_lay.addWidget(self._field_label("Compare with more columns (each plotted on the same chart)"))
        self._emv_extra_fields: list = []
        add_row = QHBoxLayout()
        self._emv_extra_combo = QComboBox()
        for code in hfs.available_fields(include_gap_dates=False):
            self._emv_extra_combo.addItem(code, code)
        add_row.addWidget(self._emv_extra_combo, 1)
        add_extra_btn = QPushButton("Add")
        add_extra_btn.clicked.connect(self._add_extra_field)
        add_row.addWidget(add_extra_btn)
        stock_lay.addLayout(add_row)
        self._emv_extra_list = QListWidget()
        self._emv_extra_list.setMaximumHeight(110)
        stock_lay.addWidget(self._emv_extra_list)
        extra_btn_row = QHBoxLayout()
        recolor_btn = QPushButton("Colour…")
        recolor_btn.clicked.connect(self._recolor_extra_field)
        remove_btn = QPushButton("Remove")
        remove_btn.clicked.connect(self._remove_extra_field)
        extra_btn_row.addWidget(recolor_btn)
        extra_btn_row.addWidget(remove_btn)
        extra_btn_row.addStretch()
        stock_lay.addLayout(extra_btn_row)
        stock_lay.addWidget(self._field_label("Number of Periods (trading days)"))
        self._emv_periods_spin = QSpinBox()
        self._emv_periods_spin.setRange(2, 500)
        self._emv_periods_spin.setValue(20)
        stock_lay.addWidget(self._emv_periods_spin)
        stock_lay.addWidget(self._field_label("Indicators to plot (from the Indicator Library)"))
        self._emv_indicator_list = QListWidget()
        self._emv_indicator_list.setMaximumHeight(160)
        # Clicking anywhere on a row toggles its checkbox (the native box is
        # near-invisible on the dark theme, so users clicked the text, which
        # only highlighted the row and left the indicator unselected), and
        # the box gets an explicit border + accent fill when checked.
        t = self._controller.theme
        self._emv_indicator_list.setStyleSheet(
            f"QListWidget::indicator {{ width: 14px; height: 14px; border: 1px solid "
            f"{t.get('text_secondary')}; border-radius: 3px; background: transparent; }}"
            f"QListWidget::indicator:checked {{ background: {t.get('accent')}; "
            f"border-color: {t.get('accent')}; }}"
        )
        self._emv_indicator_list.itemClicked.connect(self._toggle_indicator_item)
        self._refresh_indicator_choices()
        stock_lay.addWidget(self._emv_indicator_list)
        select_row = QHBoxLayout()
        select_all_btn = QPushButton("Select All")
        select_all_btn.clicked.connect(lambda: self._set_all_indicators(True))
        select_row.addWidget(select_all_btn)
        clear_all_btn = QPushButton("Deselect All")
        clear_all_btn.clicked.connect(lambda: self._set_all_indicators(False))
        select_row.addWidget(clear_all_btn)
        select_row.addStretch()
        stock_lay.addLayout(select_row)
        manage_btn = QPushButton("Manage Indicator Library…")
        manage_btn.clicked.connect(self._open_indicator_library)
        stock_lay.addWidget(manage_btn)
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
        strat_lay.addWidget(self._field_label("Stock map (bubble chart) axes"))
        bubble_row = QHBoxLayout()
        self._emv_bubble_x = QComboBox()
        self._emv_bubble_y = QComboBox()
        for combo in (self._emv_bubble_x, self._emv_bubble_y):
            for metric in emv_report_data.BUBBLE_METRICS:
                combo.addItem(metric, metric)
        self._select_data(self._emv_bubble_x, emv_report_data.BUBBLE_DEFAULT_X)
        self._select_data(self._emv_bubble_y, emv_report_data.BUBBLE_DEFAULT_Y)
        bubble_row.addWidget(QLabel("X:"))
        bubble_row.addWidget(self._emv_bubble_x, 1)
        bubble_row.addWidget(QLabel("Y:"))
        bubble_row.addWidget(self._emv_bubble_y, 1)
        strat_lay.addLayout(bubble_row)
        strat_lay.addWidget(self._field_label(
            "Table columns (leave Selected empty for Stock / Sector / Fuku Score)"
        ))
        self._emv_column_picker = ColumnPickerWidget(report_columns.emv_catalog(hfs.available_fields()))
        strat_lay.addWidget(self._emv_column_picker)
        if not strategies:
            strat_lay.addWidget(self._field_label(
                "No Inception strategies configured yet — create one in Inception > Strategy Builder."
            ))
        layout.addWidget(self._emv_strategy_frame)

        # Trend-category subtype fields (issue #64)
        self._emv_trend_frame = QFrame()
        trend_lay = QVBoxLayout(self._emv_trend_frame)
        trend_lay.setContentsMargins(0, 0, 0, 0)
        trend_lay.setSpacing(8)
        trend_lay.addWidget(self._field_label("Trend category"))
        cat_row = QHBoxLayout()
        self._emv_trend_category = QComboBox()
        cat_row.addWidget(self._emv_trend_category, 1)
        manage_cats_btn = QPushButton("Manage categories…")
        manage_cats_btn.clicked.connect(self._open_trend_category_manager)
        cat_row.addWidget(manage_cats_btn)
        trend_lay.addLayout(cat_row)
        trend_lay.addWidget(self._field_label("Timeframe"))
        self._emv_trend_timeframe = QComboBox()
        from services import trend_categories
        for tf in trend_categories.TIMEFRAMES:
            self._emv_trend_timeframe.addItem(tf, tf)
        trend_lay.addWidget(self._emv_trend_timeframe)
        trend_lay.addWidget(self._field_label("As Of Date"))
        self._emv_trend_as_of = QDateEdit()
        self._emv_trend_as_of.setCalendarPopup(True)
        self._emv_trend_as_of.setDisplayFormat("dd-MMM-yyyy")
        self._emv_trend_as_of.setDate(QDate.currentDate())
        trend_lay.addWidget(self._emv_trend_as_of)
        self._emv_trend_days_true = QCheckBox("Show how many days each stock has been true (Days True)")
        self._emv_trend_days_true.setChecked(True)
        trend_lay.addWidget(self._emv_trend_days_true)
        self._emv_trend_multi = QCheckBox("Show each stock's classification across all timeframes (Daily / Weekly / Monthly / Quarterly)")
        trend_lay.addWidget(self._emv_trend_multi)
        trend_lay.addWidget(self._field_label("Extra evidence columns (leave Selected empty for none)"))
        self._emv_trend_columns = ColumnPickerWidget([c for c in hfs.available_fields()])
        trend_lay.addWidget(self._emv_trend_columns)
        layout.addWidget(self._emv_trend_frame)
        self._refresh_trend_category_choices()
        self._on_emv_subtype_changed()

        self._on_emv_subtype_changed()

    def _add_indicator_fields(self, layout, with_symbols: bool):
        """The "plot indicators" controls shared by the LMV and Fuku Live
        wizards (issue #71): which Indicator Library entries, how many trading
        days, and (LMV only) which stocks."""
        layout.addWidget(self._field_label("Plot indicators (from the Indicator Library, optional)"))
        self._report_indicator_picker = IndicatorPickerWidget(self._controller.theme)
        layout.addWidget(self._report_indicator_picker)
        layout.addWidget(self._field_label("Indicator chart period (trading days)"))
        self._report_indicator_days = QSpinBox()
        self._report_indicator_days.setRange(10, 500)
        self._report_indicator_days.setValue(60)
        layout.addWidget(self._report_indicator_days)
        self._report_indicator_symbols = None
        if with_symbols:
            layout.addWidget(self._field_label(
                "Indicator stocks (comma separated; blank = the 5 most-traded stocks of Strategy A)"))
            self._report_indicator_symbols = QLineEdit()
            self._report_indicator_symbols.setPlaceholderText("e.g. HAL, ABB, TCS")
            layout.addWidget(self._report_indicator_symbols)

    def _indicator_settings(self) -> dict:
        symbols = []
        if self._report_indicator_symbols is not None:
            symbols = [x.strip() for x in self._report_indicator_symbols.text().split(",") if x.strip()]
        out = {"indicator_ids": self._report_indicator_picker.selected_ids(),
               "indicator_days": self._report_indicator_days.value()}
        if self._report_indicator_symbols is not None:
            out["indicator_symbols"] = symbols
        return out

    def _prefill_indicator_fields(self, cfg: dict):
        self._report_indicator_picker.set_selected(cfg.get("indicator_ids") or [])
        self._report_indicator_days.setValue(int(cfg.get("indicator_days") or 60))
        if self._report_indicator_symbols is not None:
            self._report_indicator_symbols.setText(", ".join(cfg.get("indicator_symbols") or []))

    def _populate_fuku_live_fields(self):
        layout = self._type_fields_layout
        layout.addWidget(self._field_label("Report scope"))
        self._fuku_scope_combo = QComboBox()
        self._fuku_scope_combo.addItem("Entire strategy — every active stock", "strategy")
        self._fuku_scope_combo.addItem("Single stock alert", "single")
        self._fuku_scope_combo.currentIndexChanged.connect(self._on_fuku_scope_changed)
        layout.addWidget(self._fuku_scope_combo)

        signals = fuku_live_report_data.list_available_signals()

        # Strategy-wide options
        self._fuku_strategy_frame = QFrame()
        strat_lay = QVBoxLayout(self._fuku_strategy_frame)
        strat_lay.setContentsMargins(0, 0, 0, 0)
        strat_lay.addWidget(self._field_label("Strategy"))
        self._fuku_strategy_combo = _make_searchable(QComboBox())
        # Every configured strategy, not only those with an alert on this
        # machine (local alert history is per-machine and capped, so the
        # list was often empty or missing the strategy being asked for).
        seen = set()
        names_by_id = {s_["strategy_id"]: s_["strategy_name"] for s_ in signals}
        for st in strategy_store.load_all():
            if st.get("id") and st["id"] not in seen:
                seen.add(st["id"])
                self._fuku_strategy_combo.addItem(st.get("name") or st["id"], st["id"])
        for sid, sname in names_by_id.items():
            if sid not in seen:
                seen.add(sid)
                self._fuku_strategy_combo.addItem(sname or sid, sid)
        strat_lay.addWidget(self._fuku_strategy_combo)
        strat_lay.addWidget(self._field_label("Also include (besides open trades)"))
        self._fuku_inc_stopped = QCheckBox("Stopped-out trades")
        self._fuku_inc_cancelled = QCheckBox("Cancelled trades (entry already beyond the targets)")
        self._fuku_inc_achieved = QCheckBox("Trades that achieved all targets")
        for cb in (self._fuku_inc_stopped, self._fuku_inc_cancelled, self._fuku_inc_achieved):
            strat_lay.addWidget(cb)
        strat_lay.addWidget(self._field_label(
            "Auto-refresh every N minutes while the preview is open (0 = off) — new matches are added "
            "to the top and highlighted"
        ))
        self._fuku_refresh_spin = QSpinBox()
        self._fuku_refresh_spin.setRange(0, 240)
        self._fuku_refresh_spin.setValue(5)
        strat_lay.addWidget(self._fuku_refresh_spin)
        layout.addWidget(self._fuku_strategy_frame)

        # Single-alert picker (the original behaviour)
        self._fuku_single_frame = QFrame()
        single_lay = QVBoxLayout(self._fuku_single_frame)
        single_lay.setContentsMargins(0, 0, 0, 0)
        single_lay.addWidget(self._field_label("Alert (Strategy — Symbol)"))
        self._fuku_signal_combo = _make_searchable(QComboBox())
        for s_ in signals:
            state_label = "OPEN" if s_["state"] == "open" else (s_["resolution"] or "RESOLVED").replace("_", " ").upper()
            self._fuku_signal_combo.addItem(
                f'{s_["strategy_name"]} — {s_["symbol"]} ({state_label})',
                (s_["strategy_id"], s_["symbol"]),
            )
        single_lay.addWidget(self._fuku_signal_combo)
        layout.addWidget(self._fuku_single_frame)
        self._on_fuku_scope_changed()
        # Both scopes: not every recipient should see the trigger reasoning.
        self._fuku_show_why = QCheckBox('Show the "Why this signal triggered" section')
        self._fuku_show_why.setChecked(True)
        layout.addWidget(self._fuku_show_why)
        self._add_indicator_fields(layout, with_symbols=False)

        if not signals:
            layout.addWidget(self._field_label(
                "No open or recent alerts found — this report needs at least one "
                "Strategy Notifications signal to have fired."
            ))

    def _on_fuku_scope_changed(self):
        is_strategy = self._fuku_scope_combo.currentData() == "strategy"
        self._fuku_strategy_frame.setVisible(is_strategy)
        self._fuku_single_frame.setVisible(not is_strategy)

    def _populate_sector_fields(self):
        """Sector Report wizard (issue #66)."""
        from services import inception_sector, trend_categories  # noqa: F401  (trend import keeps lazy-import style uniform)

        layout = self._type_fields_layout
        layout.addWidget(self._field_label("Report mode"))
        self._sector_mode_combo = QComboBox()
        self._sector_mode_combo.addItem("EOD — end-of-day snapshot of the synced data", "eod")
        self._sector_mode_combo.addItem("Live — latest values from the open Live Master View", "live")
        self._sector_mode_combo.currentIndexChanged.connect(self._on_sector_mode_changed)
        layout.addWidget(self._sector_mode_combo)

        self._sector_eod_frame = QFrame()
        eod_lay = QVBoxLayout(self._sector_eod_frame)
        eod_lay.setContentsMargins(0, 0, 0, 0)
        eod_lay.addWidget(self._field_label("EOD date (the latest synced trading day on or before it is used)"))
        self._sector_as_of = QDateEdit()
        self._sector_as_of.setCalendarPopup(True)
        self._sector_as_of.setDisplayFormat("dd-MMM-yyyy")
        self._sector_as_of.setDate(QDate.currentDate())
        eod_lay.addWidget(self._sector_as_of)
        layout.addWidget(self._sector_eod_frame)

        self._sector_live_frame = QFrame()
        live_lay = QVBoxLayout(self._sector_live_frame)
        live_lay.setContentsMargins(0, 0, 0, 0)
        live_lay.addWidget(self._field_label(
            "Auto-refresh every N minutes while the preview is open (0 = off). Needs the Live Master View "
            "to be running."))
        self._sector_refresh_spin = QSpinBox()
        self._sector_refresh_spin.setRange(0, 240)
        self._sector_refresh_spin.setValue(5)
        live_lay.addWidget(self._sector_refresh_spin)
        layout.addWidget(self._sector_live_frame)

        layout.addWidget(self._field_label("Sector view"))
        self._sector_view_combo = QComboBox()
        self._sector_view_combo.addItem("All sectors", None)
        try:
            inception_sector.refresh()
            for name in inception_sector.all_sectors():
                self._sector_view_combo.addItem(f"Specific sector — {name}", name)
        except Exception:
            pass
        layout.addWidget(self._sector_view_combo)

        layout.addWidget(self._field_label("Default timeframe (shown first)"))
        self._sector_timeframe_combo = QComboBox()
        for tf in sector_report_data.TIMEFRAMES:
            self._sector_timeframe_combo.addItem(tf, tf)
        layout.addWidget(self._sector_timeframe_combo)

        layout.addWidget(self._field_label("Custom % change metric (optional, in addition to Daily / Weekly / Monthly)"))
        self._sector_metric_combo = QComboBox()
        self._sector_metric_combo.addItem("None — default Daily / Weekly / Monthly only", sector_report_data.METRIC_NONE)
        self._sector_metric_combo.addItem("Two fields — % change from field A to field B", sector_report_data.METRIC_PAIR)
        self._sector_metric_combo.addItem("A strategy's column", sector_report_data.METRIC_STRATEGY)
        self._sector_metric_combo.currentIndexChanged.connect(self._on_sector_metric_changed)
        layout.addWidget(self._sector_metric_combo)

        self._sector_pair_frame = QFrame()
        pair_lay = QHBoxLayout(self._sector_pair_frame)
        pair_lay.setContentsMargins(0, 0, 0, 0)
        self._sector_pair_from = QComboBox()
        self._sector_pair_to = QComboBox()
        for combo in (self._sector_pair_from, self._sector_pair_to):
            combo.setEditable(True)
            for code in hfs.available_fields(include_gap_dates=False):
                combo.addItem(code)
        self._sector_pair_from.setCurrentText("MT")
        self._sector_pair_to.setCurrentText("CLOSE")
        pair_lay.addWidget(QLabel("From (A):"))
        pair_lay.addWidget(self._sector_pair_from, 1)
        pair_lay.addWidget(QLabel("To (B):"))
        pair_lay.addWidget(self._sector_pair_to, 1)
        layout.addWidget(self._sector_pair_frame)

        self._sector_strategy_frame = QFrame()
        strat_lay = QHBoxLayout(self._sector_strategy_frame)
        strat_lay.setContentsMargins(0, 0, 0, 0)
        self._sector_strategy_combo = QComboBox()
        self._sector_strategy_combo.currentIndexChanged.connect(self._refresh_sector_strategy_columns)
        self._sector_column_combo = QComboBox()
        strat_lay.addWidget(self._sector_strategy_combo, 1)
        strat_lay.addWidget(self._sector_column_combo, 1)
        layout.addWidget(self._sector_strategy_frame)

        layout.addWidget(self._field_label("Heatmap colour step in % (0 = automatic)"))
        self._sector_step_spin = QDoubleSpinBox()
        self._sector_step_spin.setRange(0, 1000)
        self._sector_step_spin.setDecimals(2)
        self._sector_step_spin.setValue(0)
        layout.addWidget(self._sector_step_spin)

        self._on_sector_mode_changed()
        self._on_sector_metric_changed()

    def _sector_strategies(self) -> list:
        """Strategies whose columns can serve as the custom metric: Inception
        strategies for an EOD report, Live Master View strategies for a Live
        one (each mode evaluates against its own data)."""
        from services import inception_strategy_store
        mode = self._sector_mode_combo.currentData()
        return list(inception_strategy_store.load_all() if mode == "eod" else strategy_store.load_all())

    def _on_sector_mode_changed(self):
        is_eod = self._sector_mode_combo.currentData() == "eod"
        self._sector_eod_frame.setVisible(is_eod)
        self._sector_live_frame.setVisible(not is_eod)
        previous = self._sector_strategy_combo.currentData()
        self._sector_strategy_combo.blockSignals(True)
        self._sector_strategy_combo.clear()
        for strat in self._sector_strategies():
            self._sector_strategy_combo.addItem(strat.get("name", ""), strat.get("id"))
        self._sector_strategy_combo.blockSignals(False)
        self._select_data(self._sector_strategy_combo, previous)
        self._refresh_sector_strategy_columns()

    def _refresh_sector_strategy_columns(self):
        current = self._sector_column_combo.currentText()
        self._sector_column_combo.clear()
        strat = next((s for s in self._sector_strategies() if s.get("id") == self._sector_strategy_combo.currentData()), None)
        for col in (strat or {}).get("columns", []):
            if col.get("name"):
                self._sector_column_combo.addItem(col["name"])
        if current:
            self._sector_column_combo.setCurrentText(current)

    def _on_sector_metric_changed(self):
        kind = self._sector_metric_combo.currentData()
        self._sector_pair_frame.setVisible(kind == sector_report_data.METRIC_PAIR)
        self._sector_strategy_frame.setVisible(kind == sector_report_data.METRIC_STRATEGY)

    def _populate_placeholder_fields(self, type_label: str):
        note = self._field_label(
            f"{type_label}-specific options (subject, fields, sections) will "
            f"appear here as this report type is built out."
        )
        note.setWordWrap(True)
        self._type_fields_layout.addWidget(note)

    def _start_new_report(self, report_type: str):
        report = report_store.new_report(
            report_type, f"{_REPORT_TYPE_LABELS[report_type]} — {datetime.now().strftime('%d-%b-%Y')}"
        )
        self._open_wizard(report, f"New {_REPORT_TYPE_LABELS[report_type]}")

    def _edit_active_report(self):
        if self._active_report is None:
            return
        if "_signal" in self._active_report:
            QMessageBox.information(
                self, "Not Editable",
                "This one-off report was generated from a live alert and has no saved settings.",
            )
            return
        self._edit_report(self._active_report)

    def _edit_report(self, report: dict):
        """Reopen the wizard prefilled with a saved report's settings.
        Saving keeps the report id, so it updates in place."""
        self._open_wizard(
            report, f"Edit {_REPORT_TYPE_LABELS.get(report['type'], 'Report')}", prefill=True
        )

    def _open_wizard(self, report: dict, title: str, prefill: bool = False):
        report_type = report["type"]
        self._active_report = report
        self._wizard_title.setText(title)
        self._name_edit.setText(report.get("name", ""))
        self._recipients_edit.setText(
            "; ".join(report_recipients.load_recipients(report["id"])) if prefill else ""
        )
        self._select_data(self._report_theme_combo, (report.get("visuals") or {}).get("theme", "light"))

        _clear_layout(self._type_fields_layout)
        if report_type == report_store.REPORT_TYPE_LMV:
            self._populate_lmv_fields()
        elif report_type == report_store.REPORT_TYPE_EMV:
            self._populate_emv_fields()
        elif report_type == report_store.REPORT_TYPE_FUKU_LIVE:
            self._populate_fuku_live_fields()
        elif report_type == report_store.REPORT_TYPE_SECTOR:
            self._populate_sector_fields()
        else:
            self._populate_placeholder_fields(_REPORT_TYPE_LABELS[report_type])
        if prefill:
            self._prefill_fields(report)

        self._stack.setCurrentWidget(self._wizard_page)

    @staticmethod
    def _select_data(combo: QComboBox, value):
        idx = combo.findData(value)
        if idx >= 0:
            combo.setCurrentIndex(idx)

    def _prefill_fields(self, report: dict):
        cfg = report.get("subject_config") or {}
        rtype = report["type"]
        if rtype == report_store.REPORT_TYPE_LMV:
            self._select_data(self._strategy_a_combo, cfg.get("strategy_a_id"))
            self._select_data(self._strategy_b_combo, cfg.get("strategy_b_id"))
            tf = report.get("timeframe") or {}
            self._select_data(self._timeframe_combo, tf.get("mode"))
            for edit, key in ((self._from_date, "from"), (self._to_date, "to")):
                d = QDate.fromString(str(tf.get(key) or ""), Qt.DateFormat.ISODate)
                if d.isValid():
                    edit.setDate(d)
            self._sync_lmv_date_range()
            self._select_data(self._lmv_source_combo, cfg.get("source", "recorded"))
            if cfg.get("investment_amount") is not None:
                self._investment_edit.setText(str(int(cfg["investment_amount"])))
            self._prefill_indicator_fields(cfg)
            compare = cfg.get("compare") or {}
            self._select_data(self._compare_mode_combo, compare.get("mode", "stock"))
            self._compare_asset_1.setText(compare.get("asset_1") or "")
            self._compare_asset_2.setText(compare.get("asset_2") or "")
            self._lmv_column_picker.set_columns(report.get("columns") or [])
        elif rtype == report_store.REPORT_TYPE_EMV:
            subtype = cfg.get("subtype", "stock")
            self._select_data(self._emv_subtype_combo, subtype)
            if subtype == "trend":
                self._select_data(self._emv_trend_category, cfg.get("category_id"))
                self._select_data(self._emv_trend_timeframe, cfg.get("timeframe", "Daily"))
                d = QDate.fromString(str(cfg.get("as_of_date") or ""), Qt.DateFormat.ISODate)
                if d.isValid():
                    self._emv_trend_as_of.setDate(d)
                self._emv_trend_days_true.setChecked(bool(cfg.get("days_true", True)))
                self._emv_trend_multi.setChecked(bool(cfg.get("multi_timeframe")))
                self._emv_trend_columns.set_columns(report.get("columns") or [])
            elif subtype == "strategy":
                self._select_data(self._emv_strategy_combo, cfg.get("strategy_id"))
                d = QDate.fromString(str(cfg.get("as_of_date") or ""), Qt.DateFormat.ISODate)
                if d.isValid():
                    self._emv_as_of_date.setDate(d)
                self._select_data(self._emv_bubble_x, cfg.get("bubble_x", emv_report_data.BUBBLE_DEFAULT_X))
                self._select_data(self._emv_bubble_y, cfg.get("bubble_y", emv_report_data.BUBBLE_DEFAULT_Y))
                self._emv_column_picker.set_columns(report.get("columns") or [])
            else:
                self._emv_symbol_edit.setText(cfg.get("symbol", ""))
                self._select_data(self._emv_field_combo, cfg.get("field"))
                self._set_primary_field_color(cfg.get("field_color") or emv_report_data.DEFAULT_FIELD_COLOR)
                self._emv_extra_fields = emv_report_data.normalize_extra_fields(cfg.get("extra_fields"))
                self._refresh_extra_field_list()
                if cfg.get("n_periods"):
                    self._emv_periods_spin.setValue(int(cfg["n_periods"]))
                chosen = set(cfg.get("indicator_ids") or [])
                for i in range(self._emv_indicator_list.count()):
                    item = self._emv_indicator_list.item(i)
                    if item.data(Qt.ItemDataRole.UserRole) in chosen:
                        item.setCheckState(Qt.CheckState.Checked)
        elif rtype == report_store.REPORT_TYPE_SECTOR:
            self._select_data(self._sector_mode_combo, cfg.get("mode", "eod"))
            d = QDate.fromString(str(cfg.get("as_of_date") or ""), Qt.DateFormat.ISODate)
            if d.isValid():
                self._sector_as_of.setDate(d)
            self._sector_refresh_spin.setValue(int(cfg.get("refresh_minutes") or 0))
            self._select_data(self._sector_view_combo, cfg.get("sector"))
            self._select_data(self._sector_timeframe_combo, cfg.get("primary_timeframe", "Daily"))
            self._sector_step_spin.setValue(float(cfg.get("heat_step") or 0))
            metric = cfg.get("metric") or {}
            self._select_data(self._sector_metric_combo, metric.get("kind", sector_report_data.METRIC_NONE))
            if metric.get("kind") == sector_report_data.METRIC_PAIR:
                self._sector_pair_from.setCurrentText(metric.get("from", ""))
                self._sector_pair_to.setCurrentText(metric.get("to", ""))
            elif metric.get("kind") == sector_report_data.METRIC_STRATEGY:
                self._select_data(self._sector_strategy_combo, metric.get("strategy_id"))
                self._refresh_sector_strategy_columns()
                self._sector_column_combo.setCurrentText(metric.get("column", ""))
        elif rtype == report_store.REPORT_TYPE_FUKU_LIVE:
            scope = cfg.get("scope", "single")
            self._prefill_indicator_fields(cfg)
            self._fuku_show_why.setChecked(bool(cfg.get("show_why", True)))
            self._select_data(self._fuku_scope_combo, scope)
            if scope == "strategy":
                self._select_data(self._fuku_strategy_combo, cfg.get("strategy_id"))
                self._fuku_inc_stopped.setChecked(bool(cfg.get("include_stopped")))
                self._fuku_inc_cancelled.setChecked(bool(cfg.get("include_cancelled")))
                self._fuku_inc_achieved.setChecked(bool(cfg.get("include_achieved")))
                self._fuku_refresh_spin.setValue(int(cfg.get("refresh_minutes") or 0))
            else:
                self._select_data(
                    self._fuku_signal_combo, (cfg.get("strategy_id"), cfg.get("symbol"))
                )

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
                "source": self._lmv_source_combo.currentData(),
                "compare": {
                    "mode": self._compare_mode_combo.currentData(),
                    "asset_1": self._compare_asset_1.text().strip(),
                    "asset_2": self._compare_asset_2.text().strip(),
                },
                **self._indicator_settings(),
            }
            self._active_report["timeframe"] = {
                "mode": mode,
                "from": self._from_date.date().toPython().isoformat(),
                "to": self._to_date.date().toPython().isoformat(),
            }
            self._active_report["columns"] = self._lmv_column_picker.columns()
        elif self._active_report["type"] == report_store.REPORT_TYPE_EMV:
            subtype = self._emv_subtype_combo.currentData()
            if subtype == "trend":
                self._active_report["subject_config"] = {
                    "subtype": "trend",
                    "category_id": self._emv_trend_category.currentData(),
                    "timeframe": self._emv_trend_timeframe.currentData(),
                    "as_of_date": self._emv_trend_as_of.date().toPython().isoformat(),
                    "days_true": self._emv_trend_days_true.isChecked(),
                    "multi_timeframe": self._emv_trend_multi.isChecked(),
                }
                self._active_report["columns"] = self._emv_trend_columns.columns()
            elif subtype == "strategy":
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
                    "bubble_x": self._emv_bubble_x.currentData(),
                    "bubble_y": self._emv_bubble_y.currentData(),
                }
                self._active_report["columns"] = self._emv_column_picker.columns()
            else:
                symbol = self._emv_symbol_edit.text().strip()
                if not symbol:
                    QMessageBox.warning(self, "Symbol Required", "Enter a stock symbol.")
                    return
                self._active_report["subject_config"] = {
                    "subtype": "stock",
                    "symbol": symbol,
                    "field": self._emv_field_combo.currentData(),
                    "field_color": self._emv_field_color,
                    "extra_fields": [dict(e) for e in self._emv_extra_fields],
                    "n_periods": self._emv_periods_spin.value(),
                    "indicator_ids": self._selected_indicator_ids(),
                }
        elif self._active_report["type"] == report_store.REPORT_TYPE_SECTOR:
            kind = self._sector_metric_combo.currentData()
            metric = None
            if kind == sector_report_data.METRIC_PAIR:
                a, b = self._sector_pair_from.currentText().strip(), self._sector_pair_to.currentText().strip()
                if not a or not b or a.upper() == b.upper():
                    QMessageBox.warning(self, "Custom Metric", "Pick two different fields for the custom % change.")
                    return
                metric = {"kind": kind, "from": a, "to": b}
            elif kind == sector_report_data.METRIC_STRATEGY:
                column = self._sector_column_combo.currentText().strip()
                if not column or self._sector_strategy_combo.currentData() is None:
                    QMessageBox.warning(self, "Custom Metric", "Pick a strategy that has a column to use as the metric.")
                    return
                metric = {"kind": kind, "strategy_id": self._sector_strategy_combo.currentData(),
                          "strategy_name": self._sector_strategy_combo.currentText(), "column": column}
            self._active_report["subject_config"] = {
                "mode": self._sector_mode_combo.currentData(),
                "as_of_date": self._sector_as_of.date().toPython().isoformat(),
                "refresh_minutes": self._sector_refresh_spin.value(),
                "sector": self._sector_view_combo.currentData(),
                "primary_timeframe": self._sector_timeframe_combo.currentData(),
                "metric": metric,
                "heat_step": self._sector_step_spin.value() or None,
            }
        elif self._active_report["type"] == report_store.REPORT_TYPE_FUKU_LIVE:
            if self._fuku_scope_combo.currentData() == "strategy":
                if self._fuku_strategy_combo.count() == 0:
                    QMessageBox.warning(
                        self, "No Strategies",
                        "No strategy with Strategy Notifications alerts found to report on.",
                    )
                    return
                self._active_report["subject_config"] = {
                    "scope": "strategy",
                    "strategy_id": self._fuku_strategy_combo.currentData(),
                    "include_stopped": self._fuku_inc_stopped.isChecked(),
                    "include_cancelled": self._fuku_inc_cancelled.isChecked(),
                    "include_achieved": self._fuku_inc_achieved.isChecked(),
                    "refresh_minutes": self._fuku_refresh_spin.value(),
                    "show_why": self._fuku_show_why.isChecked(),
                    **self._indicator_settings(),
                }
            else:
                if self._fuku_signal_combo.count() == 0:
                    QMessageBox.warning(
                        self, "No Alerts",
                        "No open or recent Strategy Notifications alerts found to report on.",
                    )
                    return
                strategy_id, symbol = self._fuku_signal_combo.currentData()
                self._active_report["subject_config"] = {"strategy_id": strategy_id, "symbol": symbol,
                                                         "show_why": self._fuku_show_why.isChecked(),
                                                         **self._indicator_settings()}

        self._active_report["name"] = name
        self._active_report.setdefault("visuals", {})["theme"] = self._report_theme_combo.currentData()
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

        self._edit_btn = QPushButton("Edit")
        self._edit_btn.setToolTip("Change this report's settings")
        self._edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._edit_btn.clicked.connect(self._edit_active_report)
        header_row.addWidget(self._edit_btn)

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
        refresh = int((report.get("subject_config") or {}).get("refresh_minutes") or 0)
        started = datetime.now()
        # First run: stocks entered within one refresh interval count as new.
        new_since = started - timedelta(minutes=refresh) if (_is_fuku_strategy_scope(report) and refresh) else None
        snapshot = self._lmv_snapshot_for(report)
        self._refresh_timer.stop()
        self._generation_token += 1
        token = self._generation_token

        if not self._async_generation:
            try:
                html = _build_report_html(report, new_since, snapshot)
            except Exception as exc:
                QMessageBox.warning(self, "Report Generation Failed", f"Could not generate this report:\n\n{exc}")
                return
            self._finish_generation(report, html, started)
            return

        self._set_generating(report)

        def work():
            try:
                html, error = _build_report_html(report, new_since, snapshot), None
            except Exception as exc:  # shown to the user on the GUI thread
                html, error = None, str(exc)
            try:
                self._html_ready.emit(token, report, html, error)
            except RuntimeError:
                pass  # the screen was destroyed while this was building

        threading.Thread(target=work, name="report-generation", daemon=True).start()

    def _set_generating(self, report: dict):
        self._preview_title.setText(f'Generating "{report.get("name", "report")}"…')
        self._preview_view.setHtml(
            '<html><body style="font-family:sans-serif;color:#64748b;display:flex;align-items:center;'
            'justify-content:center;height:90vh;font-size:16px;">Generating report — this can take a '
            "moment for large strategies…</body></html>"
        )
        for btn in (self._download_btn, self._email_btn, self._edit_btn):
            btn.setEnabled(False)
        self._stack.setCurrentWidget(self._preview_page)

    def _on_html_ready(self, token: int, report: dict, html, error):
        if token != self._generation_token:
            return  # a newer generation superseded this one
        for btn in (self._download_btn, self._email_btn, self._edit_btn):
            btn.setEnabled(True)
        if error is not None:
            QMessageBox.warning(self, "Report Generation Failed", f"Could not generate this report:\n\n{error}")
            self._stack.setCurrentWidget(self._gallery_page)
            return
        self._finish_generation(report, html, datetime.now())

    def _finish_generation(self, report: dict, html: str, started: datetime):
        self._last_rendered_html = html
        self._last_generated_at = started
        self._preview_title.setText(report.get("name", "Report Preview"))
        self._preview_view.setHtml(html)
        self._stack.setCurrentWidget(self._preview_page)
        refresh = int((report.get("subject_config") or {}).get("refresh_minutes") or 0)
        if _is_auto_refresh_report(report) and refresh:
            self._refresh_timer.start(refresh * 60_000)

    def _lmv_snapshot_for(self, report: dict):
        """The open Live Master View's (headers, data) for a Live sector
        report — read here on the GUI thread, then handed to the worker, so
        one generation sees one consistent snapshot."""
        if not _is_live_sector(report):
            return None
        getter = getattr(self._controller, "get_lmv_snapshot", None)
        return getter() if callable(getter) else None

    def _leave_preview(self):
        self._refresh_timer.stop()
        self._generation_token += 1   # drop any generation still in flight
        self._stack.setCurrentWidget(self._gallery_page)

    def _auto_refresh_tick(self):
        """Regenerate the active Fuku Live strategy report: existing stocks
        get their latest status, stocks that matched since the previous
        generation are added upfront and highlighted. Keeps the reader's
        scroll position."""
        report = self._active_report
        if (report is None or not _is_auto_refresh_report(report)
                or self._stack.currentWidget() is not self._preview_page):
            self._refresh_timer.stop()
            return
        started = datetime.now()
        try:
            html = _build_report_html(report, self._last_generated_at, self._lmv_snapshot_for(report))
        except Exception:
            return  # keep showing the last good report; try again next tick
        self._last_rendered_html = html
        self._last_generated_at = started

        def restore_scroll(y):
            # runJavaScript answers asynchronously — the screen may have been
            # closed (preview view deleted) by then.
            try:
                def _after(ok):
                    try:
                        self._preview_view.loadFinished.disconnect(_after)
                        self._preview_view.page().runJavaScript(f"window.scrollTo(0, {int(y or 0)});")
                    except (TypeError, RuntimeError):
                        pass
                self._preview_view.loadFinished.connect(_after)
                self._preview_view.setHtml(html)
            except RuntimeError:
                pass

        self._preview_view.page().runJavaScript("window.scrollY", restore_scroll)

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
