"""Inception > HMV (Historic Master View) — the computed metric/column grid,
shown year-wise or period-wise: pick a period type (Calendar Year / Quarter /
Half-Year / Financial Year) and a specific period, see one row per instrument
with that period's raw + Group A/B computed columns (see backend
app/services/inception_columns.py) as columns — same idea as the live LMV
grid, but built from the historical dataset's last trading day of the chosen
period instead of a live tick.
"""

import font_scale
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt

from api import inception_api
from api.exceptions import ApiError, NetworkError
from components.column_filter_popup import ColumnFilterPopup
from components.error_popup import show_api_error

_PERIOD_TYPES = [
    ("Calendar Year", "year"),
    ("Quarter", "quarter"),
    ("Half Year", "half_year"),
    ("Financial Year", "financial_year"),
]


class InceptionHmvScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._headers: list = []
        self._data: list = []
        self._visible_cols: set = set()
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

        self._period_type_combo = QComboBox()
        self._period_type_combo.setFont(font_scale.font(font_scale.SMALL, False))
        for label, _ in _PERIOD_TYPES:
            self._period_type_combo.addItem(label)
        self._period_type_combo.currentIndexChanged.connect(self._on_period_type_changed)
        toolbar.addWidget(self._period_type_combo)

        this_year = date.today().year
        self._year_spin = QSpinBox()
        self._year_spin.setRange(2000, this_year + 1)
        self._year_spin.setValue(this_year)
        self._year_spin.setFont(font_scale.font(font_scale.SMALL, False))
        toolbar.addWidget(self._year_spin)

        self._sub_period_combo = QComboBox()
        self._sub_period_combo.setFont(font_scale.font(font_scale.SMALL, False))
        toolbar.addWidget(self._sub_period_combo)

        self._load_btn = QPushButton("Load")
        self._load_btn.setFixedHeight(30)
        self._load_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._load_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._load_btn.clicked.connect(self._on_load)
        toolbar.addWidget(self._load_btn)

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

        bottom = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        bottom.addWidget(self._status_lbl)
        bottom.addStretch()
        layout.addLayout(bottom)

        self._on_period_type_changed(0)

    # ── period selector ──────────────────────────────────────────────────────

    def _on_period_type_changed(self, index: int):
        _, kind = _PERIOD_TYPES[index]
        self._sub_period_combo.clear()
        if kind == "quarter":
            self._sub_period_combo.addItems(["Q1", "Q2", "Q3", "Q4"])
            self._sub_period_combo.setVisible(True)
        elif kind == "half_year":
            self._sub_period_combo.addItems(["H1", "H2"])
            self._sub_period_combo.setVisible(True)
        else:
            self._sub_period_combo.setVisible(False)

    def _current_period(self) -> tuple[str, str]:
        _, kind = _PERIOD_TYPES[self._period_type_combo.currentIndex()]
        year = self._year_spin.value()
        if kind == "quarter":
            return kind, f"{year}-{self._sub_period_combo.currentText()}"
        if kind == "half_year":
            return kind, f"{year}-{self._sub_period_combo.currentText()}"
        return kind, str(year)

    # ── load ─────────────────────────────────────────────────────────────────

    def _on_load(self):
        t = self._controller.theme
        period_type, period = self._current_period()
        self._load_btn.setEnabled(False)
        self._load_btn.setText("Loading...")
        try:
            result = inception_api.get_hmv(period_type, period)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        finally:
            self._load_btn.setEnabled(True)
            self._load_btn.setText("Load")

        rows = result.get("rows", [])
        as_of = result.get("as_of_date")
        self._as_of_lbl.setText(f"As of {as_of}" if as_of else "No trading day in this period")

        if not rows:
            self._headers, self._data = [], []
            self._table.setRowCount(0)
            self._table.setColumnCount(0)
            self._status_lbl.setText(f"No data for {period_type} {period}.")
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        metric_keys = sorted({k for r in rows for k in r.get("values", {})})
        self._headers = ["Symbol"] + metric_keys
        self._data = [
            [r["symbol"]] + [r.get("values", {}).get(k) for k in metric_keys]
            for r in rows
        ]
        self._visible_cols = set(range(len(self._headers)))
        self._populate_table()
        self._status_lbl.setText(f"{len(rows)} instruments.")
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")

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
        if "Symbol" in self._headers:
            visible.add(self._headers.index("Symbol"))
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        self._as_of_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        if not self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._table.repaint()
