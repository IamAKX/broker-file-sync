"""
Formula Stats screen (Data menu > Formula Stats): pick an existing strategy
and a number of days, and see Min/Max/Average/etc. of each of that
strategy's formula columns, computed per stock over the most recent N
trading days of saved historic data (services/formula_stats_engine.py does
the actual recompute, reusing services/strategy_engine.evaluate — the same
evaluator used for live LMV data). Right-click any result cell to see the
individual day-by-day values behind it.
"""
import font_scale

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox,
    QSpinBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QAbstractItemView, QMenu, QDialog, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QAction

from api import lmv_snapshot_api
from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from screens.strategy_builder import _apply_dialog_bg, _t
from services import strategy_store
from services.formula_stats_engine import AGGREGATES, DEFAULT_AGGREGATES, compute_stats

_MAX_DAYS = 90


class FormulaStatsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._strategies: list = []
        self._computed: dict = {}
        self._table_columns: list = []   # [(formula_column_name, aggregate_name), ...]
        self._agg_checks: dict = {}      # aggregate name -> QCheckBox
        self._build()
        self.reload_strategies()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Formula Stats")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        desc = QLabel(
            "Pick a strategy and a number of days to see aggregate statistics "
            "for each of its formula columns, computed per stock from saved "
            "historic data. Right-click a result cell to see the individual "
            "day-by-day values."
        )
        desc.setWordWrap(True)
        desc.setFont(font_scale.font(font_scale.SMALL, False))
        desc.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(desc)

        controls = QHBoxLayout()
        controls.setSpacing(10)

        strat_lbl = QLabel("Strategy")
        strat_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        controls.addWidget(strat_lbl)
        self._strategy_combo = QComboBox()
        self._strategy_combo.setMinimumWidth(220)
        self._strategy_combo.setFont(font_scale.font(font_scale.SMALL, False))
        controls.addWidget(self._strategy_combo)

        days_lbl = QLabel("Days")
        days_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        controls.addWidget(days_lbl)
        self._days_spin = QSpinBox()
        self._days_spin.setRange(1, _MAX_DAYS)
        self._days_spin.setValue(20)
        self._days_spin.setFont(font_scale.font(font_scale.SMALL, False))
        controls.addWidget(self._days_spin)

        self._compute_btn = QPushButton("Compute")
        self._compute_btn.setFixedHeight(32)
        self._compute_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._compute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_compute_btn()
        self._compute_btn.clicked.connect(self._on_compute)
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

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {t.get('divider')};")
        layout.addWidget(div)

        self._status_lbl = QLabel("Pick a strategy, choose a day count, then Compute.")
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
        layout.addWidget(self._table, 1)

    def _style_compute_btn(self):
        t = self._controller.theme
        self._compute_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 16px; }}"
            f"QPushButton:disabled {{ background: {t.get('button_bg')}; color: {t.get('text_secondary')}; }}"
        )

    # ── strategy list ────────────────────────────────────────────────────────

    def reload_strategies(self):
        """Re-pull the strategy list (any strategy is eligible here, active
        or not — this is an analysis tool, not a live filter). Called on
        every showEvent so edits made in Strategy Builder are picked up
        without any cross-screen signal wiring, and from
        app_window.py::reload_per_user_data on a second user's login within
        the same process."""
        previous_id = None
        if self._strategies and 0 <= self._strategy_combo.currentIndex() < len(self._strategies):
            previous_id = self._strategies[self._strategy_combo.currentIndex()].get("id")

        self._strategies = strategy_store.load_all()
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
            self._status_lbl.setText("No strategies yet — create one in Strategy Builder first.")

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_strategies()

    # ── compute ──────────────────────────────────────────────────────────────

    def _on_compute(self):
        idx = self._strategy_combo.currentIndex()
        if idx < 0 or idx >= len(self._strategies):
            return
        strategy = self._strategies[idx]
        if not strategy.get("columns"):
            self._status_lbl.setText(f'"{strategy.get("name")}" has no formula columns to analyze.')
            return

        days = self._days_spin.value()
        self._compute_btn.setEnabled(False)
        self._compute_btn.setText("Computing…")
        try:
            range_response = lmv_snapshot_api.get_range(days)
        except (ApiError, NetworkError) as exc:
            self._compute_btn.setEnabled(True)
            self._compute_btn.setText("Compute")
            show_api_error(self._controller.theme, self, exc)
            return
        self._compute_btn.setEnabled(True)
        self._compute_btn.setText("Compute")

        self._computed = compute_stats(strategy, range_response)
        self._populate_table(strategy)

    def _populate_table(self, strategy: dict):
        checked_aggs = [name for name in AGGREGATES if self._agg_checks[name].isChecked()]
        columns = strategy.get("columns", [])
        self._table_columns = [(col["name"], agg) for col in columns for agg in checked_aggs]

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
                self._table.setItem(r, c, QTableWidgetItem(_fmt_value(value)))

        self._table.resizeColumnsToContents()
        if self._computed and columns:
            any_entry = next(iter(self._computed.values()))
            n_days = len(any_entry["columns"].get(columns[0]["name"], {}).get("daily", []))
        else:
            n_days = 0
        self._status_lbl.setText(
            f"{len(symbols)} stock(s) · {len(columns)} formula column(s) · {n_days} day(s) of data."
        )

    # ── right-click: day-by-day breakdown ───────────────────────────────────

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
        # Same native-NSMenu translucency fix used elsewhere (e.g.
        # screens/strategy_builder.py's card overflow menu) — without this,
        # macOS renders it washed-out/illegible regardless of the app's theme.
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        menu.setStyleSheet(
            f"QMenu{{background-color:{_t(t,'card_bg')};color:{_t(t,'text_primary')};"
            f"border:1px solid {_t(t,'border')};border-radius:6px;padding:4px;}}"
            f"QMenu::item{{padding:6px 24px 6px 12px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{_t(t,'accent')};color:{_t(t,'background')};}}"
        )
        action = QAction(f"View last {self._days_spin.value()} days — {col_name}", menu)
        action.triggered.connect(lambda: self._show_daily_popup(symbol, col_name))
        menu.addAction(action)
        menu.exec(self._table.viewport().mapToGlobal(pos))

    def _show_daily_popup(self, symbol: str, col_name: str):
        entry = self._computed.get(symbol, {})
        daily = entry.get("columns", {}).get(col_name, {}).get("daily", [])

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{symbol} — {col_name}")
        _apply_dialog_bg(dlg, self._controller.theme)
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
            table.setItem(r, 1, QTableWidgetItem(_fmt_value(value)))
        table.resizeColumnsToContents()
        layout.addWidget(table)

        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dlg.accept)
        layout.addWidget(close_btn)

        dlg.resize(340, 420)
        dlg.exec()

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        self._style_compute_btn()


def _fmt_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)
