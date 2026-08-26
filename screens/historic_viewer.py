import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton, QLineEdit
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from components.column_filter_popup import ColumnFilterPopup
from components.frozen_table_columns import FrozenColumns


class HistoricDataViewer(QWidget):
    """Read-only popup showing the saved historic rows/columns for one date.

    *frozen_headers*, backward-compatible (defaults to None — no freeze,
    exactly today's behavior for the existing Data > Historic Upload > Browse
    by Date caller), pins the named columns at the left edge via
    components.frozen_table_columns — used by screens.inception_view_by_date
    to keep Sector + Symbol in view while scrolling through Inception's wider
    computed-column set, same idea as screens.live_viewer's Scrip Name
    freeze on the live grid.

    *cell_highlights*, also backward-compatible (defaults to None — no
    coloring, exactly today's behavior for every existing caller), is
    {(row_idx, col_idx): "#rrggbb"} applied as that cell's background (with
    an auto-contrasted text color) at build time. Fully resolved by the
    caller — this widget doesn't know or care WHY a cell is colored (screens.
    inception_view_by_date uses it for "changed since the last View", see
    services.inception_change_highlight, but nothing here is specific to
    that). Row/column indices stay stable for this widget's whole lifetime
    (column filtering hides columns rather than removing them, and search
    hides rows the same way — see _apply_col_filter/_on_search), so this is
    applied once here rather than needing to be re-applied on every filter/
    search change.
    """

    def __init__(self, headers: list, rows: list, date_str: str, theme=None,
                 parent=None, title: str = None, frozen_headers: list = None,
                 cell_highlights: dict = None):
        super().__init__(parent)
        self._theme = theme
        self._headers = headers
        self._date_str = date_str
        self._symbol_col = headers.index("Symbol") if "Symbol" in headers else -1
        self._visible_cols = set(range(len(headers)))
        self._frozen_headers = list(frozen_headers) if frozen_headers else []
        self.setWindowTitle(title if title is not None else f"Historic Data — {date_str}")
        self.resize(1000, 600)
        self._build(headers, rows, cell_highlights or {})

    def _build(self, headers: list, rows: list, cell_highlights: dict):
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
                fill = cell_highlights.get((r, c))
                if fill:
                    from screens.live_viewer import _contrasting_text
                    item.setBackground(QBrush(QColor(fill)))
                    item.setForeground(QBrush(QColor(_contrasting_text(fill))))
                self._table.setItem(r, c, item)

        layout.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._stock_count_lbl = QLabel(f"Stocks : {len(rows)}")
        self._stock_count_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._stock_count_lbl.setStyleSheet(f"color: {text_s};")
        bottom.addWidget(self._stock_count_lbl)
        bottom.addStretch()
        layout.addLayout(bottom)

        self._freeze = FrozenColumns(self._table)
        if self._frozen_headers:
            self._freeze.configure(headers, self._frozen_headers, self._freeze_style())

    def _freeze_style(self) -> str:
        t = self._theme
        bg = t.get("card_bg") if t else "#1c2128"
        txt = t.get("text_primary") if t else "#e6edf3"
        border = t.get("border") if t else "#30363d"
        return (
            f"QTableView {{ background: {bg}; color: {txt}; border-right: 2px solid {border}; }}"
            f"QTableView QHeaderView::section {{ background: {bg}; color: {txt}; }}"
        )

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
        for name in self._frozen_headers:
            if name in self._headers:
                visible.add(self._headers.index(name))
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        if self._frozen_headers:
            self._freeze.configure(self._headers, self._frozen_headers, self._freeze_style())

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
        if self._frozen_headers:
            self._freeze.configure(self._headers, self._frozen_headers, self._freeze_style())
