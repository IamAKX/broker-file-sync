"""Inception > Formula Stats: pick a strategy and a From/To date range, see
Min/Max/Average/etc. of each of that strategy's formula columns, computed
per instrument from the locally-synced historic bar cache — the Inception
equivalent of screens/formula_stats.py's LMV screen (Data menu).

The one structural difference from the LMV screen (besides the data
source): LMV's version picks a rolling "last N trading days" window (an
int day-count spinbox) since it's always relative to today's live data.
Inception's dataset is a fixed historic series spanning back to 2013, not
"N days ago from today" in the same live sense, so this screen asks for an
explicit From/To range instead (two QDateEdit fields, same widget/style
screens/inception_hmv.py's own From/To pair uses) — no day-count spinbox.

Computing per-day Group A/B values across the full instrument universe for
a wide date range can take a while on a cold cache (see services.
inception_compute_service's module docstring) — _FormulaStatsLoadWorker
runs services.inception_compute_service.range_rows + services.
formula_stats_engine.compute_stats on a background QThread (same pattern
as screens.inception_hmv._HmvLoadWorker) with a QProgressBar driven by
range_rows' progress_cb.

The results table + right-click day-by-day breakdown intentionally
duplicate (rather than embed) components/formula_stats_panel.py's
FormulaStatsPanel table logic — that panel's own fetch path is hardwired
to api/lmv_snapshot_api.get_range's "int days or a fixed read-only range"
model, not a fetch this screen already runs itself on a background thread;
reusing its free functions (build_daily_popup, fmt_value) where they're
already meant to be shared (see that module's own docstring) avoids
duplicating THOSE, while keeping this screen's fetch/threading fully its
own — same "reuse the small reusable pieces, build a smaller purpose-built
whole" choice screens/inception_strategy_builder.py made for reusing
FormulaBuilder without the larger StrategyEditor.
"""

import font_scale
from datetime import date, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QDateEdit, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QProgressBar, QSizePolicy,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal
from PySide6.QtGui import QAction

from components.formula_stats_panel import build_daily_popup, fmt_value
from screens.inception_view_by_date import _display_symbol
from services import inception_bars_store, inception_compute_service, inception_strategy_store
from services.formula_stats_engine import AGGREGATES, DEFAULT_AGGREGATES, compute_stats
from services.strategy_engine import expand_columns_for_stats


class _FormulaStatsLoadWorker(QThread):
    progress = Signal(int, int)     # done, total instruments
    succeeded = Signal(dict, int)   # computed {symbol: {...}}, day count
    failed = Signal(str)

    def __init__(self, columns: list, date_from: date, date_to: date, parent=None):
        super().__init__(parent)
        self._columns = columns
        self._date_from = date_from
        self._date_to = date_to

    def run(self):
        try:
            range_response = inception_compute_service.range_rows(
                self._date_from, self._date_to,
                progress_cb=lambda done, total: self.progress.emit(done, total),
            )
            # range_rows() itself leaves "display_name" == "symbol" (the raw
            # "_I"-suffixed canonical name) — stripping that suffix for
            # display is this screens layer's job, same helper screens.
            # inception_hmv/inception_view_by_date already use for it.
            for day in range_response["days"]:
                for stock in day["stocks"]:
                    stock["display_name"] = _display_symbol(stock["symbol"])
            computed = compute_stats(expand_columns_for_stats(self._columns), range_response)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(computed, len(range_response["days"]))


class InceptionFormulaStatsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._strategies: list = []
        self._computed: dict = {}
        self._table_columns: list = []
        self._table_columns_source: list = []
        self._agg_checks: dict = {}
        self._worker: _FormulaStatsLoadWorker | None = None
        self._build()
        self.reload_strategies()

    # ── build ────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Inception — Formula Stats")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        desc = QLabel(
            "Pick a strategy and a From/To date range to see aggregate "
            "statistics for each of its formula columns, computed per "
            "instrument from the locally-synced historic data. Right-click "
            "a result cell to see the individual day-by-day values."
        )
        desc.setWordWrap(True)
        desc.setFont(font_scale.font(font_scale.SMALL, False))
        desc.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(desc)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(10)

        strat_lbl = QLabel("Strategy")
        strat_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        toolbar.addWidget(strat_lbl)
        self._strategy_combo = QComboBox()
        self._strategy_combo.setMinimumWidth(200)
        self._strategy_combo.setFont(font_scale.font(font_scale.SMALL, False))
        toolbar.addWidget(self._strategy_combo)

        today = date.today()
        default_from = today - timedelta(days=365)

        toolbar.addWidget(QLabel("From:"))
        self._from_date = QDateEdit()
        self._from_date.setCalendarPopup(True)
        self._from_date.setDisplayFormat("dd-MMM-yyyy")
        self._from_date.setDate(QDate(default_from.year, default_from.month, default_from.day))
        self._from_date.setFont(font_scale.font(font_scale.SMALL, False))
        toolbar.addWidget(self._from_date)

        toolbar.addWidget(QLabel("To:"))
        self._to_date = QDateEdit()
        self._to_date.setCalendarPopup(True)
        self._to_date.setDisplayFormat("dd-MMM-yyyy")
        self._to_date.setDate(QDate(today.year, today.month, today.day))
        self._to_date.setFont(font_scale.font(font_scale.SMALL, False))
        toolbar.addWidget(self._to_date)

        self._style_calendar_popups()

        self._compute_btn = QPushButton("Compute")
        self._compute_btn.setFixedHeight(30)
        self._compute_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._compute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_compute_btn()
        self._compute_btn.clicked.connect(self._on_compute)
        toolbar.addWidget(self._compute_btn)
        toolbar.addStretch()
        layout.addLayout(toolbar)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        agg_row = QHBoxLayout()
        agg_row.setSpacing(12)
        agg_lbl = QLabel("Aggregates:")
        agg_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        agg_row.addWidget(agg_lbl)
        for name in AGGREGATES:
            cb = QCheckBox(name)
            cb.setFont(font_scale.font(font_scale.SMALL, False))
            cb.setChecked(name in DEFAULT_AGGREGATES)
            self._agg_checks[name] = cb
            agg_row.addWidget(cb)
        agg_row.addStretch()
        layout.addLayout(agg_row)

        self._status_lbl = QLabel("Choose a strategy and date range, then Compute.")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(self._status_lbl)

        self._table = QTableWidget()
        self._table.setFont(font_scale.font(font_scale.SMALL, False))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        self._table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self._table.customContextMenuRequested.connect(self._show_context_menu)
        self._table.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        layout.addWidget(self._table, 1)

    def _style_compute_btn(self):
        t = self._controller.theme
        self._compute_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 16px; }}"
            f"QPushButton:disabled {{ background: {t.get('button_bg')}; color: {t.get('text_secondary')}; }}"
        )

    def _style_calendar_popups(self):
        from components.availability_calendar import themed_calendar_stylesheet
        t = self._controller.theme
        stylesheet = themed_calendar_stylesheet(t)
        for date_edit in (self._from_date, self._to_date):
            cal = date_edit.calendarWidget()
            if cal is not None:
                cal.setStyleSheet(stylesheet)

    # ── strategy list ────────────────────────────────────────────────────

    def reload_strategies(self):
        """Any strategy is eligible here, active or not — this is an
        analysis tool, not a live filter, same rule screens/formula_stats.py
        (its LMV counterpart) uses. Called on every showEvent so edits made
        in Inception's Strategy Builder are picked up without cross-screen
        signal wiring."""
        previous_id = None
        if self._strategies and 0 <= self._strategy_combo.currentIndex() < len(self._strategies):
            previous_id = self._strategies[self._strategy_combo.currentIndex()].get("id")

        self._strategies = inception_strategy_store.load_all()
        self._strategy_combo.clear()
        for strat in self._strategies:
            self._strategy_combo.addItem(strat.get("name", "Unnamed"))

        if previous_id is not None:
            for i, strat in enumerate(self._strategies):
                if strat.get("id") == previous_id:
                    self._strategy_combo.setCurrentIndex(i)
                    break

        self._compute_btn.setEnabled(bool(self._strategies))
        if not self._strategies:
            self._status_lbl.setText("No strategies yet — create one in Inception > Strategy Builder first.")

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_strategies()

    # ── compute ──────────────────────────────────────────────────────────

    def _current_range(self) -> tuple:
        qf, qt = self._from_date.date(), self._to_date.date()
        return date(qf.year(), qf.month(), qf.day()), date(qt.year(), qt.month(), qt.day())

    def _on_compute(self):
        t = self._controller.theme
        idx = self._strategy_combo.currentIndex()
        if idx < 0 or idx >= len(self._strategies):
            return
        strategy = self._strategies[idx]
        columns = strategy.get("columns", [])
        if not columns:
            self._status_lbl.setText(f'"{strategy.get("name")}" has no formula columns to analyze.')
            return

        date_from, date_to = self._current_range()
        if date_from > date_to:
            self._status_lbl.setText("From date must be on or before To date.")
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        if inception_bars_store.last_synced_date() is None:
            self._status_lbl.setText(
                "No Inception data synced to this device yet — open Inception > "
                "Data & Settings and click Sync Now."
            )
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        if self._worker is not None and self._worker.isRunning():
            return

        self._table_columns_source = columns
        self._compute_btn.setEnabled(False)
        self._compute_btn.setText("Computing…")
        self._status_lbl.setText("Computing…")
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._progress_bar.setRange(0, 0)   # busy/indeterminate until the first progress tick arrives
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._worker = _FormulaStatsLoadWorker(columns, date_from, date_to, parent=self)
        self._worker.progress.connect(self._on_progress)
        self._worker.succeeded.connect(self._on_succeeded)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_progress(self, done: int, total: int):
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(done)
        self._status_lbl.setText(f"Computing… {done}/{total} instruments")

    def _on_succeeded(self, computed: dict, n_days: int):
        t = self._controller.theme
        self._compute_btn.setEnabled(True)
        self._compute_btn.setText("Compute")
        self._progress_bar.setVisible(False)
        self._computed = computed
        self._populate_table()
        self._status_lbl.setText(
            f"{len(computed)} instrument(s) · {len(self._table_columns_source)} formula "
            f"column(s) · {n_days} day(s) of data."
        )
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")

    def _on_failed(self, message: str):
        t = self._controller.theme
        self._compute_btn.setEnabled(True)
        self._compute_btn.setText("Compute")
        self._progress_bar.setVisible(False)
        self._status_lbl.setText(f"Compute failed: {message}")
        self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")

    # ── table ────────────────────────────────────────────────────────────

    def _populate_table(self):
        checked_aggs = [name for name in AGGREGATES if self._agg_checks[name].isChecked()]
        self._table_columns = [
            (col["name"], agg) for col in self._table_columns_source for agg in checked_aggs
        ]

        headers = ["Symbol", "Display Name"] + [
            f"{col_name} ({agg})" for col_name, agg in self._table_columns
        ]
        symbols = sorted(self._computed.keys())

        self._table.clear()
        self._table.setColumnCount(len(headers))
        self._table.setHorizontalHeaderLabels(headers)
        self._table.setRowCount(len(symbols))

        for r, symbol in enumerate(symbols):
            entry = self._computed[symbol]
            self._table.setItem(r, 0, QTableWidgetItem(symbol))
            self._table.setItem(r, 1, QTableWidgetItem(entry.get("display_name") or symbol))
            for c, (col_name, agg) in enumerate(self._table_columns, start=2):
                value = entry["columns"].get(col_name, {}).get(agg)
                self._table.setItem(r, c, QTableWidgetItem(fmt_value(value)))

        self._table.resizeColumnsToContents()

    # ── right-click: day-by-day breakdown ───────────────────────────────

    def _show_context_menu(self, pos):
        index = self._table.indexAt(pos)
        if not index.isValid() or index.column() < 2:
            return
        row, col = index.row(), index.column()
        symbol_item = self._table.item(row, 0)
        if symbol_item is None:
            return
        symbol = symbol_item.text()
        col_name, _agg = self._table_columns[col - 2]

        t = self._controller.theme
        menu = QMenu(self)
        menu.setFont(font_scale.font(font_scale.SMALL, False))
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        menu.setStyleSheet(
            f"QMenu{{background-color:{t.get('card_bg')};color:{t.get('text_primary')};"
            f"border:1px solid {t.get('border')};border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:6px 24px 6px 12px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{t.get('accent')};color:{t.get('background')};}}"
        )
        date_from, date_to = self._current_range()
        action = QAction(f"View {date_from.isoformat()} to {date_to.isoformat()} — {col_name}", menu)
        action.triggered.connect(lambda: self._show_daily_popup(symbol, col_name))
        menu.addAction(action)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _show_daily_popup(self, symbol: str, col_name: str):
        entry = self._computed.get(symbol, {})
        daily = entry.get("columns", {}).get(col_name, {}).get("daily", [])
        dlg = build_daily_popup(self._controller.theme, self, symbol, col_name, daily)
        dlg.exec()

    # ── theme ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        self._style_compute_btn()
        if "Compute failed" not in self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._style_calendar_popups()
