import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton, QLineEdit
)
from PySide6.QtCore import Qt

from components.column_filter_popup import ColumnFilterPopup


class HistoricDataViewer(QWidget):
    """Read-only popup showing the saved historic rows/columns for one date."""

    def __init__(self, headers: list, rows: list, date_str: str, theme=None,
                 parent=None, title: str = None):
        super().__init__(parent)
        self._theme = theme
        self._headers = headers
        self._date_str = date_str
        self._symbol_col = headers.index("Symbol") if "Symbol" in headers else -1
        self._visible_cols = set(range(len(headers)))
        self.setWindowTitle(title if title is not None else f"Historic Data — {date_str}")
        self.resize(1000, 600)
        self._build(headers, rows)

    def _build(self, headers: list, rows: list):
        t = self._theme
        accent = t.get("accent") if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider") if t else "#30363d"
        inp_bg = t.get("input_bg") if t else "#0d1117"
        txt = t.get("text_primary") if t else "#e6edf3"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

        # ── Toolbar ──────────────────────────────────────────────────────────
        toolbar = QHBoxLayout()

        self._filter_btn = QPushButton("⊞  Columns")
        self._filter_btn.setFixedHeight(30)
        self._filter_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._filter_btn.clicked.connect(self._show_col_filter)
        toolbar.addWidget(self._filter_btn)

        toolbar.addSpacing(8)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search Symbol…")
        self._search_box.setFixedHeight(30)
        self._search_box.setFixedWidth(220)
        self._search_box.setFont(font_scale.font(font_scale.SMALL, False))
        self._search_box.setStyleSheet(
            f"QLineEdit {{ background: {inp_bg}; color: {txt};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 10px; }}"
        )
        self._search_box.textChanged.connect(self._on_search)
        toolbar.addWidget(self._search_box)

        toolbar.addStretch()
        layout.addLayout(toolbar)

        # ── Table ────────────────────────────────────────────────────────────
        self._table = QTableWidget(len(rows), len(headers))
        self._table.setFont(font_scale.font(font_scale.SMALL, False))
        self._table.setHorizontalHeaderLabels([str(h) for h in headers])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setShowGrid(True)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setSectionsMovable(True)

        for r, row in enumerate(rows):
            for c in range(len(headers)):
                value = row[c] if c < len(row) else ""
                if value is None:
                    cell_text = ""
                elif isinstance(value, float):
                    cell_text = f"{value:.4f}"
                else:
                    cell_text = str(value)
                item = QTableWidgetItem(cell_text)
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(r, c, item)

        layout.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._stock_count_lbl = QLabel(f"Stocks : {len(rows)}")
        self._stock_count_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._stock_count_lbl.setStyleSheet(f"color: {text_s};")
        bottom.addWidget(self._stock_count_lbl)
        bottom.addStretch()
        layout.addLayout(bottom)

    def _show_col_filter(self):
        if not self._headers:
            return
        popup = ColumnFilterPopup(self._headers, self._visible_cols, self._theme, self)
        popup.columns_changed.connect(self._apply_col_filter)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _apply_col_filter(self, visible: set):
        if self._symbol_col >= 0:
            visible.add(self._symbol_col)
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)

    def _on_search(self, text: str):
        query = text.strip().lower()
        if self._symbol_col < 0:
            return
        for row in range(self._table.rowCount()):
            item = self._table.item(row, self._symbol_col)
            match = not query or (item is not None and query in item.text().lower())
            self._table.setRowHidden(row, not match)
        self._update_stock_count_label()

    def _update_stock_count_label(self):
        visible = sum(
            1 for r in range(self._table.rowCount())
            if not self._table.isRowHidden(r)
        )
        self._stock_count_lbl.setText(f"Stocks : {visible}")

    def refresh_theme(self):
        self._table.repaint()
