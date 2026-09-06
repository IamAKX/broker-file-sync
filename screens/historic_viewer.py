import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton, QLineEdit, QComboBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor

from components.column_filter_popup import ColumnFilterPopup
from components.frozen_table_columns import FrozenColumns

_CATEGORIES = ["All", "Daily", "Weekly", "Monthly", "Common"]


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
    (column filtering hides columns rather than removing them, and search/
    sector filtering hide rows the same way), so this is applied once here
    rather than needing to be re-applied on every filter/search change.

    *column_categories* (backward-compatible, defaults to None — no Category
    combo shown, exactly today's behavior for every existing caller): a
    {column_name: "Daily"|"Weekly"|"Monthly"|"Common"} map — screens.
    inception_view_by_date builds this from each active strategy's own
    category, one entry per strategy-added column. A column not in this map
    (every raw/base column, plus any strategy column when this is omitted
    entirely) is never affected by the Category filter — same convention as
    screens.live_viewer's category combo only ever gating STRATEGY columns.
    Unlike LMV's live grid, this popup's columns are fixed at construction
    (the strategies that produced them were already chosen and applied
    before View was clicked) — so this only ever shows/hides already-built
    columns, it never re-evaluates strategies.

    A Sector filter combo appears automatically whenever *headers* contains
    a "Sector" column (same "All" + every distinct value in *rows*
    convention as screens.lmv_snapshot_viewer's own sector combo) — no
    extra param needed, backward-compatible for a caller with no Sector
    column at all (e.g. Historic Upload's Browse by Date).

    The "↺ Reset" button clears everything this widget itself owns: column
    visibility (the Columns popup's selection) and any drag-reordering back
    to how *headers* was originally ordered, plus the Sector/Category
    filters and the Symbol search box — a "back to how this popup looked
    when it first opened" action. It deliberately does NOT touch the
    persisted Config Editor "Inception Column Order" setting (or anything
    about which strategies are applied) — those are a different screen's/
    button's job, same reasoning screens.live_viewer's own column-order
    reset draws between "this popup's on-screen state" and "a saved
    cross-session preference".
    """

    def __init__(self, headers: list, rows: list, date_str: str, theme=None,
                 parent=None, title: str = None, frozen_headers: list = None,
                 cell_highlights: dict = None, column_categories: dict = None):
        super().__init__(parent)
        self._theme = theme
        self._headers = headers
        self._date_str = date_str
        self._symbol_col = headers.index("Symbol") if "Symbol" in headers else -1
        self._sector_col = headers.index("Sector") if "Sector" in headers else -1
        self._visible_cols = set(range(len(headers)))
        self._selected_category = "All"
        self._column_categories = dict(column_categories) if column_categories else {}
        self._frozen_headers = list(frozen_headers) if frozen_headers else []
        self._sector_combo = None
        self._category_combo = None
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

        combo_style = (
            f"QComboBox {{ background: {inp_bg}; color: {txt};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 8px; }}"
        )

        if self._sector_col >= 0:
            sectors = sorted({
                str(row[self._sector_col]) for row in rows
                if self._sector_col < len(row) and row[self._sector_col] not in (None, "")
            })
            self._sector_combo = QComboBox()
            self._sector_combo.addItems(["All"] + sectors)
            self._sector_combo.setFixedHeight(30)
            self._sector_combo.setFont(font_scale.font(font_scale.SMALL, False))
            self._sector_combo.setStyleSheet(combo_style)
            self._sector_combo.currentTextChanged.connect(self._on_sector_changed)
            toolbar.addWidget(self._sector_combo)
            toolbar.addSpacing(8)

        if self._column_categories:
            self._category_combo = QComboBox()
            self._category_combo.addItems(_CATEGORIES)
            self._category_combo.setFixedHeight(30)
            self._category_combo.setFont(font_scale.font(font_scale.SMALL, False))
            self._category_combo.setStyleSheet(combo_style)
            self._category_combo.currentTextChanged.connect(self._on_category_changed)
            toolbar.addWidget(self._category_combo)
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

        self._reset_btn = QPushButton("↺  Reset")
        self._reset_btn.setFixedHeight(30)
        self._reset_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setToolTip(
            "Reset columns — restores column visibility and order, and "
            "clears the Sector/Category filters and Symbol search."
        )
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._reset_btn.clicked.connect(self._reset_columns)
        toolbar.addWidget(self._reset_btn)

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

    # ── Columns (visibility + category) ──────────────────────────────────────

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
        self._apply_column_visibility()

    def _on_category_changed(self, text: str):
        self._selected_category = text
        self._apply_column_visibility()

    def _category_hides(self, col: int) -> bool:
        if self._selected_category == "All" or not self._column_categories:
            return False
        cat = self._column_categories.get(self._headers[col])
        return cat is not None and cat != self._selected_category

    def _apply_column_visibility(self):
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols or self._category_hides(c))
        if self._frozen_headers:
            self._freeze.configure(self._headers, self._frozen_headers, self._freeze_style())

    # ── Rows (Symbol search + Sector filter) ─────────────────────────────────

    def _on_search(self, text: str):
        self._apply_row_filters()

    def _on_sector_changed(self, text: str):
        self._apply_row_filters()

    def _apply_row_filters(self):
        query = self._search_box.text().strip().lower()
        sector_sel = self._sector_combo.currentText() if self._sector_combo is not None else "All"
        for row in range(self._table.rowCount()):
            symbol_ok = True
            if self._symbol_col >= 0:
                item = self._table.item(row, self._symbol_col)
                symbol_ok = not query or (item is not None and query in item.text().lower())
            sector_ok = True
            if self._sector_col >= 0 and sector_sel != "All":
                item = self._table.item(row, self._sector_col)
                sector_ok = item is not None and item.text() == sector_sel
            self._table.setRowHidden(row, not (symbol_ok and sector_ok))
        # The frozen Sector/Symbol overlay (self._freeze) shares the table's
        # model but not its row-hidden view state — without this, filtering
        # out non-matching rows leaves the overlay showing its own
        # unfiltered rows, so a remaining match's data (compacted to the
        # top of the now-filtered real table) visually lines up with
        # whatever symbol the STILL-unfiltered overlay happens to show at
        # that same position instead of its own — e.g. searching
        # "bajfinance" showing that row's data next to "360ONE" (simply the
        # first row alphabetically, never hidden on the overlay side).
        self._freeze.sync_row_hidden()
        self._update_stock_count_label()

    def _update_stock_count_label(self):
        visible = sum(
            1 for r in range(self._table.rowCount())
            if not self._table.isRowHidden(r)
        )
        self._stock_count_lbl.setText(f"Stocks : {visible}")

    # ── Reset ─────────────────────────────────────────────────────────────────

    def _reset_columns(self):
        self._visible_cols = set(range(len(self._headers)))
        self._selected_category = "All"
        if self._category_combo is not None:
            self._category_combo.blockSignals(True)
            self._category_combo.setCurrentText("All")
            self._category_combo.blockSignals(False)
        if self._sector_combo is not None:
            self._sector_combo.blockSignals(True)
            self._sector_combo.setCurrentText("All")
            self._sector_combo.blockSignals(False)
        self._search_box.blockSignals(True)
        self._search_box.clear()
        self._search_box.blockSignals(False)

        # Column order back to *headers*' own original (logical) order —
        # undoes any drag-reordering done in this popup, same convention
        # screens.live_viewer's own reset uses for its column order.
        hdr = self._table.horizontalHeader()
        for target_visual in range(hdr.count()):
            current_visual = hdr.visualIndex(target_visual)
            if current_visual != target_visual:
                hdr.moveSection(current_visual, target_visual)

        self._apply_column_visibility()
        self._apply_row_filters()

    def refresh_theme(self):
        self._table.repaint()
        if self._frozen_headers:
            self._freeze.configure(self._headers, self._frozen_headers, self._freeze_style())
