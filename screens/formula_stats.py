"""
Formula Stats screen (Data menu > Formula Stats): pick an existing strategy
and a number of days, and see Min/Max/Average/etc. of each of that
strategy's formula columns, computed per stock over the most recent N
trading days of saved historic data. The day-count/aggregate controls,
results table and right-click day-by-day breakdown all live in
components/formula_stats_panel.py's FormulaStatsPanel — this screen just
adds the "which strategy" picker on top of it. That same panel also backs
Live Master View's per-cell history popup for a strategy column whose
formula uses one of the AVG_DAYS/MIN_DAYS/etc. historic aggregate functions
(services/strategy_engine.py) — see docs/strategy-builder.md's "Historic
(N days) Aggregates" section for how those functions fit into the formula
language itself, which is the primary way to pull a historic aggregate into
a strategy now (a column, a condition, a notification metric — anywhere a
formula runs) rather than through this screen's ad-hoc analysis view.
"""
import font_scale

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QComboBox
from PySide6.QtCore import Qt

from components.formula_stats_panel import FormulaStatsPanel
from services import strategy_store


class FormulaStatsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._strategies: list = []
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

        strat_row = QHBoxLayout()
        strat_row.setSpacing(10)
        strat_lbl = QLabel("Strategy")
        strat_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        strat_row.addWidget(strat_lbl)
        self._strategy_combo = QComboBox()
        self._strategy_combo.setMinimumWidth(220)
        self._strategy_combo.setFont(font_scale.font(font_scale.SMALL, False))
        self._strategy_combo.currentIndexChanged.connect(self._sync_panel_columns)
        strat_row.addWidget(self._strategy_combo)
        strat_row.addStretch()
        layout.addLayout(strat_row)

        self._panel = FormulaStatsPanel(t, columns=[], parent=self)
        # This screen decides *which* strategy's columns Compute should run
        # against (and shows a strategy-named message when it has none), so
        # Compute is driven through _on_compute rather than the panel's
        # default self-contained wiring.
        self._panel._compute_btn.clicked.disconnect()
        self._panel._compute_btn.clicked.connect(self._on_compute)
        layout.addWidget(self._panel, 1)

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

        self._panel._compute_btn.setEnabled(bool(self._strategies))
        self._sync_panel_columns()
        if not self._strategies:
            self._panel._status_lbl.setText("No strategies yet — create one in Strategy Builder first.")

    def showEvent(self, event):
        super().showEvent(event)
        self.reload_strategies()

    def _sync_panel_columns(self, *_args):
        idx = self._strategy_combo.currentIndex()
        if 0 <= idx < len(self._strategies):
            self._panel.set_columns(self._strategies[idx].get("columns", []))
        else:
            self._panel.set_columns([])

    # ── compute ──────────────────────────────────────────────────────────────

    def _on_compute(self):
        idx = self._strategy_combo.currentIndex()
        if idx < 0 or idx >= len(self._strategies):
            return
        strategy = self._strategies[idx]
        if not strategy.get("columns"):
            self._panel._status_lbl.setText(f'"{strategy.get("name")}" has no formula columns to analyze.')
            return
        self._panel.set_columns(strategy["columns"])
        self._panel.compute()

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        self._panel.refresh_theme()
