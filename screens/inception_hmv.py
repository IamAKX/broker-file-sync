"""Inception > HMV (Historic Master View) — the computed metric/column grid:
pick a From/To date range, see one row per locally-synced instrument with
raw + Group A/B + Formula Builder computed columns (see services.
inception_columns, services.inception_formula_builder_columns) as of the
last synced trading day on or before To — same idea as the live LMV grid,
but built from the locally-synced historical dataset instead of a live tick.

The date range isn't just a display window — a column whose formula needs
more history than [from, to] actually contains comes back blank (e.g. 52WH
needs ~52 weeks of data; a 6-month range leaves it blank) rather than
silently reaching outside the range or always showing a value regardless of
what the user selected. See services.inception_formula_engine.
required_lookback_start and services.inception_compute_service.
_apply_range_gate for where that's enforced — this screen just surfaces
whatever comes back (a blank cell for a gated column, no separate
"insufficient range" indicator needed since the row itself explains it —
see the status label after Load).

All of this runs locally now (services.inception_compute_service, backed by
services.inception_bars_store) — see screens.inception_settings for the
sync status / Sync Now action this screen depends on having been run at
least once.

Computing Group A/B across the full ~213-instrument universe can take
anywhere from a couple seconds to (on a cold cache, long history) upwards
of a minute — see inception_compute_service's module docstring on why, and
what it caches to make repeat loads fast. _HmvLoadWorker runs it on a
background QThread (same pattern as screens.inception_settings._SyncWorker)
so the UI never freezes, with a QProgressBar driven by inception_compute_
service.hmv's progress_cb (one tick per instrument) standing in for "is
this actually still working" during a slow cold load.

── Strategies ────────────────────────────────────────────────────────────────
Unlike View by Date/the rest, this screen keeps a live, in-memory strategy
list (self._strategies) and a "⚡ Strategies" picker (screens.live_viewer.
StrategyPickerPopup, reused as-is — it's already generic) so more than one
strategy can be selected and applied at once, exactly like LMV's own picker.
Before this existed, HMV silently applied EVERY strategy marked "active" in
Strategy Builder, all unioned together (services.strategy_engine.
apply_strategies: a row survives if it passes ANY active strategy's row
filter) — with several strategies active by default and most having no
filter at all, a filter on any ONE of them looked like it "did nothing" or
behaved inconsistently, because the others (unfiltered) kept every row in
regardless. The picker lets the user isolate exactly which strategies count
for a given look, the same fix LMV already had.

Sector + Symbol are frozen at the left edge via components.
frozen_table_columns (see that module — generalizes screens.live_viewer's
single-column Scrip Name freeze to two columns) and always stay visible
regardless of the Columns filter, same convention LMV uses for Scrip Name.

Column order can also be set from Config Editor's "Inception HMV Column
Order" tab (screens.config_editor, services.config_store.
INCEPTION_HMV_COLUMN_ORDER) instead of dragging — see
_restore_saved_column_order, same idea as LMV's own "Main Column Order" tab
+ screens.live_viewer._restore_column_order, under a separate key since
Inception's column universe is entirely different from LMV's. Unlike LMV,
a drag here isn't auto-persisted back to that list (LMV's live-drag-persist
interacts with its own frozen-column pinning in a way that isn't worth
replicating here too) — the Config Editor tab is the one way to save an
order, and it's re-applied on every render.
"""

import font_scale
from datetime import date, timedelta

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QProgressBar,
)
from PySide6.QtCore import Qt, QDate, QThread, Signal

from api.exceptions import ApiError, NetworkError
from components.column_filter_popup import ColumnFilterPopup
from components.error_popup import show_api_error
from components.frozen_table_columns import FrozenColumns
from screens.inception_view_by_date import _display_symbol
from services import (
    inception_bars_store, inception_compute_service, inception_formula_builder_columns,
    inception_sector, inception_strategy_store,
)
from services.strategy_engine import apply_strategies

_FROZEN_HEADERS = ["Sector", "Symbol"]


class _HmvLoadWorker(QThread):
    progress = Signal(int, int)          # done, total instruments
    succeeded = Signal(object, list)     # as_of_date (date | None), rows
    failed = Signal(str)

    def __init__(self, date_from: date, date_to: date, parent=None):
        super().__init__(parent)
        self._date_from = date_from
        self._date_to = date_to

    def run(self):
        try:
            as_of_date, rows = inception_compute_service.hmv(
                self._date_from, self._date_to,
                progress_cb=lambda done, total: self.progress.emit(done, total),
            )
            if as_of_date is not None:
                self._merge_formula_builder_columns(rows, as_of_date)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(as_of_date, rows)

    @staticmethod
    def _merge_formula_builder_columns(rows: list, as_of_date: date):
        """Adds LMV's ~56 Formula Builder columns (MT, MB, DT, DB, PMH, the
        camarilla pivot ladders, ...) to every row's values dict, computed
        from that same instrument's local bar history — see services.
        inception_formula_builder_columns. Runs on this background thread
        (bars_for_symbol is a cheap indexed query; the calendar-bucket
        arithmetic itself is pure Python but still adds up across ~213
        instruments) so it never blocks the GUI thread. HMV-only for now
        (View by Date / Strategy Builder don't offer these columns yet) —
        scoped here rather than in services.inception_compute_service so it
        doesn't leak into those other call sites.
        """
        for row in rows:
            bars = inception_bars_store.bars_for_symbol(row["symbol"], date_to=as_of_date)
            row["values"].update(inception_formula_builder_columns.compute_for_bars(row["symbol"], bars))


class InceptionHmvScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._headers: list = []       # display headers (raw + sector + strategy columns)
        self._data: list = []          # display rows
        self._raw_headers: list = []   # headers before strategy columns were appended
        self._raw_data: list = []      # rows before strategy columns were appended
        self._strategies: list = []
        self._visible_cols: set = set()
        self._worker: _HmvLoadWorker | None = None
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Inception — HMV")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        toolbar = QHBoxLayout()

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

        # QDateEdit's own popup calendar isn't covered by the app-wide
        # stylesheet's QCalendarWidget rules (theme.py) — those are missing
        # QLabel/header text colors, so day-of-week headers and nav-bar text
        # render in Qt's default (black) on a dark background and are
        # effectively invisible. Reuse the same proven stylesheet the
        # View by Date calendar and formula_editor's date picker already
        # use instead of patching theme.py's incomplete rules.
        self._style_calendar_popups()

        self._load_btn = QPushButton("Load")
        self._load_btn.setFixedHeight(30)
        self._load_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.clicked.connect(self._on_load)
        toolbar.addWidget(self._load_btn)

        toolbar.addSpacing(8)
        self._strat_btn = QPushButton("⚡  Strategies")
        self._strat_btn.setFixedHeight(30)
        self._strat_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._strat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._strat_btn.clicked.connect(self._show_strategy_picker)
        toolbar.addWidget(self._strat_btn)

        toolbar.addSpacing(8)
        self._filter_btn = QPushButton("⊞  Columns")
        self._filter_btn.setFixedHeight(30)
        self._filter_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.clicked.connect(self._show_col_filter)
        toolbar.addWidget(self._filter_btn)

        toolbar.addStretch()
        self._as_of_lbl = QLabel("")
        self._as_of_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._as_of_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        toolbar.addWidget(self._as_of_lbl)
        layout.addLayout(toolbar)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        self._table = QTableWidget()
        self._table.setFont(font_scale.font(font_scale.SMALL, False))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setSectionsMovable(True)
        self._table.setShowGrid(True)
        layout.addWidget(self._table, 1)
        self._freeze = FrozenColumns(self._table)

        bottom = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        bottom.addWidget(self._status_lbl)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _style_calendar_popups(self):
        from components.availability_calendar import themed_calendar_stylesheet
        t = self._controller.theme
        stylesheet = themed_calendar_stylesheet(t)
        for date_edit in (self._from_date, self._to_date):
            cal = date_edit.calendarWidget()
            if cal is not None:
                cal.setStyleSheet(stylesheet)

    def _freeze_style(self) -> str:
        t = self._controller.theme
        bg = t.get("card_bg")
        txt = t.get("text_primary")
        border = t.get("border")
        return (
            f"QTableView {{ background: {bg}; color: {txt}; border-right: 2px solid {border}; }}"
            f"QTableView QHeaderView::section {{ background: {bg}; color: {txt}; }}"
        )

    # ── date range ───────────────────────────────────────────────────────────

    def _current_range(self) -> tuple[date, date]:
        qf, qt = self._from_date.date(), self._to_date.date()
        return date(qf.year(), qf.month(), qf.day()), date(qt.year(), qt.month(), qt.day())

    # ── load ─────────────────────────────────────────────────────────────────

    def _on_load(self):
        t = self._controller.theme
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

        self._load_btn.setEnabled(False)
        self._load_btn.setText("Loading...")
        self._status_lbl.setText("Computing…")
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._progress_bar.setRange(0, 0)   # busy/indeterminate until the first progress tick arrives
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._worker = _HmvLoadWorker(date_from, date_to, parent=self)
        self._worker.progress.connect(self._on_load_progress)
        self._worker.succeeded.connect(lambda as_of_date, rows: self._on_load_succeeded(date_from, date_to, as_of_date, rows))
        self._worker.failed.connect(self._on_load_failed)
        self._worker.start()

    def _on_load_progress(self, done: int, total: int):
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(done)
        self._status_lbl.setText(f"Computing… {done}/{total} instruments")

    def _on_load_succeeded(self, date_from: date, date_to: date, as_of_date, rows: list):
        t = self._controller.theme
        self._load_btn.setEnabled(True)
        self._load_btn.setText("Load")
        self._progress_bar.setVisible(False)

        self._as_of_lbl.setText(f"As of {as_of_date.isoformat()}" if as_of_date else "No synced trading day in this range")

        if not rows:
            self._headers, self._data = [], []
            self._raw_headers, self._raw_data = [], []
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._status_lbl.setText(f"No synced data for {date_from.isoformat()} to {date_to.isoformat()}.")
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        metric_keys = sorted({k for r in rows for k in r.get("values", {})})
        headers = ["Symbol"] + metric_keys
        data = [
            [_display_symbol(r["symbol"])] + [r.get("values", {}).get(k) for k in metric_keys]
            for r in rows
        ]
        headers, data = inception_sector.inject_sector_rows(headers, data)

        self._raw_headers, self._raw_data = headers, data
        # A fresh Load is a wholly new dataset — reset column visibility to
        # "everything shown" rather than trying to carry over indices from
        # whatever the previous load's column layout happened to be.
        self._visible_cols = set(range(len(self._raw_headers)))

        # Reloaded fresh on every Load, same as before — the "⚡ Strategies"
        # picker (see _show_strategy_picker) can further narrow this down to
        # a specific subset for the current session without needing another
        # Load; that picker also re-syncs from the store on open, so a
        # strategy just edited in Strategy Builder always shows up promptly.
        self._strategies = inception_strategy_store.load_all()
        self._recompute_display()
        self._status_lbl.setText(
            f"{len(rows)} instruments. Blank cells mean this range doesn't cover enough "
            f"history for that column (e.g. 52WH needs ~52 weeks)."
        )
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")

    def _on_load_failed(self, message: str):
        t = self._controller.theme
        self._load_btn.setEnabled(True)
        self._load_btn.setText("Load")
        self._progress_bar.setVisible(False)
        self._status_lbl.setText(f"Load failed: {message}")
        self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")

    # ── strategies ───────────────────────────────────────────────────────────

    def _show_strategy_picker(self):
        from screens.live_viewer import StrategyPickerPopup
        t = self._controller.theme
        try:
            self._strategies = inception_strategy_store.load_all()
        except (ApiError, NetworkError):
            pass   # best-effort refresh — picker still opens with whatever it already had
        popup = StrategyPickerPopup(self._strategies, t, self)
        popup.applied.connect(self._on_strategies_applied)
        btn_pos = self._strat_btn.mapToGlobal(self._strat_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _on_strategies_applied(self, updated: list):
        t = self._controller.theme
        updated_by_id = {s["id"]: s for s in updated}
        self._strategies = [updated_by_id.get(s["id"], s) for s in self._strategies]
        for s in updated:
            try:
                inception_strategy_store.save_strategy(s)
            except (ApiError, NetworkError) as exc:
                show_api_error(t, self, exc)
        self._recompute_display()

    def _update_strat_btn_label(self):
        active = sum(1 for s in self._strategies if s.get("active"))
        total = len(self._strategies)
        self._strat_btn.setText("⚡  Strategies" if total == 0 else f"⚡  Strategies  {active}/{total}")

    def _recompute_display(self):
        """Re-derives the displayed headers/data from the cached raw (no
        strategy columns) rows + self._strategies — cheap, client-side, no
        recompute of Group A/B/Formula Builder needed. Used both right after
        a Load and whenever the Strategies picker applies a new selection."""
        if not self._raw_headers:
            self._update_strat_btn_label()
            return
        headers, data = apply_strategies(self._strategies, self._raw_headers, self._raw_data)
        # Keep any strategy-appended column (beyond the raw/base set)
        # visible by default, without undoing a column-visibility choice the
        # user already made for existing columns (same top-up-not-reset rule
        # screens.live_viewer's _populate_table uses). Compared against
        # len(self._raw_headers) — the authoritative "how many base columns
        # exist right now" — rather than the previous self._headers, which
        # could be stale from a completely different prior render.
        if len(headers) > len(self._raw_headers):
            self._visible_cols |= set(range(len(self._raw_headers), len(headers)))
        self._headers, self._data = headers, data
        self._populate_table()
        self._update_strat_btn_label()

    # ── table ────────────────────────────────────────────────────────────────

    @staticmethod
    def _fmt_cell(val) -> str:
        if isinstance(val, float):
            return f"{val:.4f}"
        if val is None:
            return ""
        return str(val)

    def _populate_table(self):
        self._table.setColumnCount(len(self._headers))
        self._table.setHorizontalHeaderLabels(self._headers)
        self._table.setRowCount(len(self._data))
        for r, row in enumerate(self._data):
            for c, val in enumerate(row):
                item = QTableWidgetItem(self._fmt_cell(val))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(r, c, item)
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        self._table.resizeColumnsToContents()
        # Order restored BEFORE the freeze re-pin below, same sequence
        # screens.live_viewer uses for its own saved column order + Scrip
        # Name freeze — so Sector/Symbol always win the leftmost spot
        # regardless of what the saved order says about them.
        self._restore_saved_column_order()
        self._freeze.configure(self._headers, _FROZEN_HEADERS, self._freeze_style())

    def _restore_saved_column_order(self):
        """Reorders columns to match the Config Editor > "Inception HMV
        Column Order" tab's saved list (services.config_store.
        INCEPTION_HMV_COLUMN_ORDER) — same mechanism/shape as screens.
        live_viewer._restore_column_order for LMV's own "Main Column Order"
        tab, under a separate key since Inception's ~150-column universe is
        entirely different from LMV's. That tab exists specifically because
        dragging one column at a time across a table this wide is tedious —
        it lets you list (search + up/down-reorder, no dragging) just the
        columns you want pulled to specific positions; anything not listed
        keeps its current relative position, same partial-list convention
        LMV's own tab already uses (its default only names ~20 of LMV's ~82
        columns, not all of them)."""
        from services import config_store
        saved = config_store.load_column_order(key=config_store.INCEPTION_HMV_COLUMN_ORDER)
        if not saved:
            return
        hdr = self._table.horizontalHeader()
        name_to_logical = {name: i for i, name in enumerate(self._headers)}
        target_visual = 0
        for name in saved:
            logical = name_to_logical.get(name)
            if logical is None:
                continue
            current_visual = hdr.visualIndex(logical)
            if current_visual != target_visual:
                hdr.moveSection(current_visual, target_visual)
            target_visual += 1

    def _show_col_filter(self):
        if not self._headers:
            return
        t = self._controller.theme
        popup = ColumnFilterPopup(self._headers, self._visible_cols, t, self)
        popup.columns_changed.connect(self._apply_col_filter)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _apply_col_filter(self, visible: set):
        for must in _FROZEN_HEADERS:
            if must in self._headers:
                visible.add(self._headers.index(must))
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        self._freeze.configure(self._headers, _FROZEN_HEADERS, self._freeze_style())

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        self._as_of_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        if not self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._style_calendar_popups()
        self._table.repaint()
        if self._headers:
            self._freeze.configure(self._headers, _FROZEN_HEADERS, self._freeze_style())
