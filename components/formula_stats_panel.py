"""
Reusable "day-count + aggregates + results table" panel for testing one or
more formulas over the last N historic trading days. Two callers:

  - screens/formula_stats.py (Data menu: pick a strategy, see every one of
    its columns' stats for every stock — a free-standing analysis tool).
  - screens/live_viewer.py (click a Live Master View cell in a strategy
    column whose formula uses an AVG_DAYS/MIN_DAYS/etc. historic aggregate
    function — services/strategy_engine.py — to see the day-by-day values
    behind that one stock's aggregate, pre-filtered and pre-computed).

For building a historic aggregate INTO a strategy itself (a column, a
condition, a notification metric), the primary mechanism is those _DAYS
formula functions directly — see docs/strategy-builder.md's "Historic
(N days) Aggregates" section — not this panel; this panel is for ad-hoc
after-the-fact inspection.

Fetches via api/lmv_snapshot_api.get_range(); the actual per-day formula
evaluation + aggregation is services/formula_stats_engine.compute_stats —
this module is just the Qt controls/table around it.
"""
import font_scale

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QSpinBox,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QDialog, QFrame, QSizePolicy,
)
from PySide6.QtCore import Qt, QThread, Signal
from PySide6.QtGui import QAction

from api import lmv_snapshot_api
from api.exceptions import ApiError, NetworkError
from services.formula_stats_engine import (
    AGGREGATES, DEFAULT_AGGREGATES, compute_stats, fetch_range_response,
)
from services.strategy_engine import expand_columns_for_stats

MAX_DAYS = 90


# Deliberately not imported from screens.strategy_builder — components/
# shouldn't depend on screens/ (this is a components/ module used by more
# than one screen). Small, self-contained duplicates instead (same pattern
# screens/formula_editor.py already uses for its own _t).

def _t(theme, key: str) -> str:
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "input_bg": "#0d1117", "destructive": "#da3633",
        "divider": "#2a2f36",
    }
    if theme:
        try:
            return theme.get(key)
        except Exception:
            pass
    return _FALLBACK.get(key, "#888")


def apply_dialog_bg(dialog, theme):
    bg = _t(theme, "background")
    txt = _t(theme, "text_primary")
    dialog.setStyleSheet(
        f"QDialog{{background:{bg};color:{txt};}}"
        f"QWidget{{background:{bg};color:{txt};}}"
        f"QLabel{{background:transparent;}}"
    )


def fmt_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


class _ComputeWorker(QThread):
    """Runs the network fetch (api.lmv_snapshot_api.get_range, via
    fetch_range_response) AND the per-day/per-stock formula evaluation
    (compute_stats) off the GUI thread — same shape as every other
    network-backed worker in this app (e.g. screens.inception_admin_sync.
    _AdminSyncWorker). compute() used to run both synchronously: on a slow
    or genuinely-timed-out response, the whole app went "Not Responding"
    for the entire wait, and any error (network or otherwise) left the
    table showing nothing with no way to tell why short of a modal popup
    that made the freeze feel even longer — see issue #22."""
    succeeded = Signal(dict)
    failed = Signal(str)

    def __init__(self, range_fetcher, window, columns: list, parent=None):
        super().__init__(parent)
        self._range_fetcher = range_fetcher
        self._window = window
        self._columns = columns

    def run(self):
        try:
            range_response = fetch_range_response(self._range_fetcher, self._window)
            computed = compute_stats(expand_columns_for_stats(self._columns), range_response)
        except (ApiError, NetworkError) as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # never let an unexpected error kill the worker thread silently
            self.failed.emit(f"Unexpected error: {exc}")
            return
        self.succeeded.emit(computed)


class FormulaStatsPanel(QWidget):
    """*columns* is a list of {"name": str, "formula": tokens} dicts —
    either a strategy's saved columns, or ad-hoc ones built just for this
    test. When *symbol_filter* is set, the results table (and day count) are
    still fully general, but only that one stock's row is ever shown —
    used for Live Master View's per-cell history popup, where the stock is
    already known from the click.

    *initial_date_range* (a (date_from, date_to) tuple), when given instead
    of *initial_days*, fixes the window to that exact range — read-only, no
    day-count spinbox — used for a VALUE_ON_DATE column's click-through
    popup (screens.live_viewer._open_formula_history), where the "range" is
    a single fixed date (date_from == date_to), not something to explore
    interactively. At most one of the two should be passed;
    *initial_date_range* wins if both are.
    """

    def __init__(self, theme, columns: list, symbol_filter: str = None,
                 initial_days: int = 20, initial_date_range: tuple = None,
                 parent=None):
        super().__init__(parent)
        self._theme = theme
        self._columns = list(columns)
        self._symbol_filter = symbol_filter
        self._fixed_window = initial_date_range
        self._computed: dict = {}
        self._table_columns: list = []
        self._agg_checks: dict = {}
        self._worker: _ComputeWorker | None = None
        self._build(initial_days)

    def set_columns(self, columns: list):
        self._columns = list(columns)

    # ── build ────────────────────────────────────────────────────────────

    def _build(self, initial_days: int):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        if self._fixed_window is not None:
            date_from, date_to = self._fixed_window
            range_lbl = QLabel(
                f"Date: {date_from}" if date_from == date_to
                else f"Date range: {date_from} → {date_to}")
            range_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            controls.addWidget(range_lbl)
        else:
            days_lbl = QLabel("Days")
            days_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            controls.addWidget(days_lbl)
            self._days_spin = QSpinBox()
            self._days_spin.setRange(1, MAX_DAYS)
            self._days_spin.setValue(initial_days)
            self._days_spin.setFont(font_scale.font(font_scale.SMALL, False))
            controls.addWidget(self._days_spin)

        self._compute_btn = QPushButton("Compute")
        self._compute_btn.setFixedHeight(32)
        self._compute_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._compute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_compute_btn()
        self._compute_btn.clicked.connect(self.compute)
        controls.addWidget(self._compute_btn)
        controls.addStretch()
        layout.addLayout(controls)

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

        initial_status = "Click Compute." if self._fixed_window is not None else "Choose a day count, then Compute."
        self._status_lbl = QLabel(initial_status)
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {_t(t,'text_secondary')};")
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
        t = self._theme
        self._compute_btn.setStyleSheet(
            f"QPushButton {{ background: {_t(t,'accent')}; color: {_t(t,'background')};"
            f"border: none; border-radius: 4px; padding: 0 16px; }}"
            f"QPushButton:disabled {{ background: {_t(t,'button_bg')}; color: {_t(t,'text_secondary')}; }}"
        )

    # ── compute ──────────────────────────────────────────────────────────

    def compute(self):
        if not self._columns:
            self._status_lbl.setText("No formula columns to analyze.")
            return
        if self._worker is not None and self._worker.isRunning():
            return
        # An int (days spinbox) or the fixed (date_from, date_to) tuple —
        # fetch_range_response resolves either into the same {"days": [...]}
        # shape via lmv_snapshot_api.get_range, filtering client-side for
        # the fixed-range case (see services.formula_stats_engine).
        window = self._fixed_window if self._fixed_window is not None else self._days_spin.value()
        self._compute_btn.setEnabled(False)
        self._compute_btn.setText("Computing…")
        self._status_lbl.setText("Fetching and computing…")

        # Both the network fetch AND the per-day/per-stock formula
        # evaluation (compute_stats) run on a background thread — this
        # used to be a synchronous GUI-thread call, so a slow response (a
        # range request scales with the full stock universe times the day
        # count) or a genuine timeout froze the whole app ("Not
        # Responding") for the entire wait, on top of a modal popup on
        # failure that made the freeze feel even longer. See issue #22 and
        # api.lmv_snapshot_api.get_range's own docstring (also given a
        # longer timeout, since the generic 15s default was itself a
        # frequent, spurious failure on this specific heavy endpoint).
        #
        # A column's formula can reference another of THIS SAME strategy's
        # own columns by name (e.g. "Trigger Price" = [Floor_10D] * 1.01) —
        # an already-supported pattern for live Live Master View rendering
        # (services.strategy_engine.apply_strategies enriches each row with
        # every earlier column's value as it goes). compute_stats has no
        # such enrichment — its per-day row_dict is raw historic-snapshot
        # metrics only — so an unexpanded sibling reference would silently
        # evaluate to None on every day. expand_columns_for_stats resolves
        # those references first (scoped to self._columns only — the
        # live_viewer.py caller passes just the one clicked column, where
        # this is a no-op) — see services.strategy_engine._expand_col_refs
        # for the full "why", including why it must be paren-wrapped. Done
        # inside the worker (not here) since expand_columns_for_stats/
        # compute_stats are themselves part of the potentially-slow work.
        self._worker = _ComputeWorker(lmv_snapshot_api.get_range, window, self._columns, parent=self)
        self._worker.succeeded.connect(self._on_compute_succeeded)
        self._worker.failed.connect(self._on_compute_failed)
        self._worker.start()

    def _on_compute_succeeded(self, computed: dict):
        self._compute_btn.setEnabled(True)
        self._compute_btn.setText("Compute")
        self._computed = computed
        self._populate_table()

    def _on_compute_failed(self, msg: str):
        # Status text, not a blocking modal (show_api_error) — a transient
        # network hiccup on this specific heavy endpoint was common enough
        # ("Been happening a lot") that a modal every time was itself part
        # of the reported problem; the button re-enabling means Compute can
        # just be clicked again. Same non-blocking convention screens.
        # live_viewer.py's own "N-Day Data" refresh already uses for the
        # identical underlying call.
        self._compute_btn.setEnabled(True)
        self._compute_btn.setText("Compute")
        self._status_lbl.setText(f"Compute failed: {msg}"[:200])

    def _populate_table(self):
        checked_aggs = [name for name in AGGREGATES if self._agg_checks[name].isChecked()]
        self._table_columns = [(col["name"], agg) for col in self._columns for agg in checked_aggs]

        headers = ["Symbol", "Display Name"] + [
            f"{col_name} ({agg})" for col_name, agg in self._table_columns
        ]
        symbols = sorted(self._computed.keys())
        if self._symbol_filter is not None:
            symbols = [s for s in symbols if s == self._symbol_filter]

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
        if self._computed and self._columns:
            any_entry = next(iter(self._computed.values()))
            n_days = len(any_entry["columns"].get(self._columns[0]["name"], {}).get("daily", []))
        else:
            n_days = 0
        self._status_lbl.setText(
            f"{len(symbols)} stock(s) · {len(self._columns)} formula column(s) · {n_days} day(s) of data."
        )

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

        t = self._theme
        menu = QMenu(self)
        menu.setFont(font_scale.font(font_scale.SMALL, False))
        # Native-NSMenu translucency fix (see screens/strategy_builder.py's
        # card overflow menu) — without this, macOS renders it washed-out/
        # illegible regardless of the app's theme.
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        menu.setStyleSheet(
            f"QMenu{{background-color:{_t(t,'card_bg')};color:{_t(t,'text_primary')};"
            f"border:1px solid {_t(t,'border')};border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:6px 24px 6px 12px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{_t(t,'accent')};color:{_t(t,'background')};}}"
        )
        if self._fixed_window is not None:
            window_desc = f"{self._fixed_window[0]} to {self._fixed_window[1]}"
        else:
            window_desc = f"last {self._days_spin.value()} days"
        action = QAction(f"View {window_desc} — {col_name}", menu)
        action.triggered.connect(lambda: self.show_daily_popup(symbol, col_name))
        menu.addAction(action)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def show_daily_popup(self, symbol: str, col_name: str):
        entry = self._computed.get(symbol, {})
        daily = entry.get("columns", {}).get(col_name, {}).get("daily", [])
        dlg = build_daily_popup(self._theme, self, symbol, col_name, daily)
        dlg.exec()

    # ── theme ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        self._style_compute_btn()
        self._status_lbl.setStyleSheet(f"color: {_t(self._theme,'text_secondary')};")


def build_daily_popup(theme, parent, symbol: str, col_name: str, daily: list) -> QDialog:
    """The Date/Value table dialog shown for one symbol+column's day-by-day
    values — factored out so screens/live_viewer.py can jump straight to it
    from a cell click without going through FormulaStatsPanel's results
    table first (the stock is already known from which cell was clicked)."""
    dlg = QDialog(parent)
    dlg.setWindowTitle(f"{symbol} — {col_name}")
    apply_dialog_bg(dlg, theme)
    layout = QVBoxLayout(dlg)
    layout.setContentsMargins(16, 16, 16, 16)
    layout.setSpacing(10)

    table = QTableWidget(len(daily), 2)
    table.setFont(font_scale.font(font_scale.SMALL, False))
    table.verticalHeader().setVisible(False)
    table.setHorizontalHeaderLabels(["Date", "Value"])
    table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    for r, (trade_date, value) in enumerate(sorted(daily, key=lambda p: p[0], reverse=True)):
        table.setItem(r, 0, QTableWidgetItem(str(trade_date)))
        table.setItem(r, 1, QTableWidgetItem(fmt_value(value)))
    table.resizeColumnsToContents()
    layout.addWidget(table)

    close_btn = QPushButton("Close")
    close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
    close_btn.clicked.connect(dlg.accept)
    layout.addWidget(close_btn)

    dlg.resize(340, 420)
    return dlg
