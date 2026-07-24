"""
Static (non-live) popup showing a constructed or previously-saved historical
Live Master View. Same Strategies/Filters/Export toolbar as the live LMV
(screens.live_viewer.LiveViewerWindow) — reuses its standalone popup classes
(StrategyPickerPopup, FilterPanelPopup) and services.strategy_engine/
services.lmv_export directly — but the table is built once from the
(headers, data) it's given and never polls/refreshes itself.
"""

import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFrame,
    QComboBox,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QBrush

from components.column_filter_popup import ColumnFilterPopup
from screens.live_viewer import FilterPanelPopup, StrategyPickerPopup
from services import strategy_store
from services.strategy_engine import apply_strategies, get_cell_color


class LmvSnapshotViewer(QWidget):
    """headers/data: the base LMV grid (Sector-first, like the live LMV).
    on_save: callable() -> None, invoked by the Save button; omit (None) to
    hide Save entirely — used for read-only views of already-saved days.
    """

    def __init__(self, headers: list, data: list, trade_date, theme=None,
                 on_save=None, title: str = None, parent=None,
                 show_strategies: bool = True):
        super().__init__(parent)
        self._headers = list(headers)
        self._data = [list(r) for r in data]
        self._trade_date = trade_date
        self._theme = theme
        self._on_save = on_save
        self._show_strategies = show_strategies

        self._visible_cols = set(range(len(self._headers)))
        self._selected_category = "All"
        # Loading/applying strategies here is pure overhead when this viewer
        # is only being used to review the merged columns that will be
        # saved/browsed (e.g. LMV Upload) — those columns never include
        # strategy output, so skip the load entirely in that case.
        self._strategies = (
            [s for s in strategy_store.load_all() if s.get("active")]
            if show_strategies else []
        )

        from config_defaults import SECTOR_STOCK_DATA
        self._sector_map = {stock: sector for sector, stock in SECTOR_STOCK_DATA}

        self._title_text = title or f"Historical LMV — {trade_date.strftime('%d-%b-%Y')}"
        self.setWindowTitle(self._title_text)
        self.resize(1300, 700)
        self._build()
        self._populate_table()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider")        if t else "#30363d"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        top = QHBoxLayout()
        title = QLabel(self._title_text)
        title.setFont(font_scale.font(font_scale.LARGE, True))
        top.addWidget(title)
        top.addStretch()

        # Hidden combos — mirror live_viewer.py's pattern so existing filter
        # logic (category/sector) can read current selection without its own
        # visible widgets cluttering this toolbar.
        self._cat_combo = QComboBox(self)
        self._cat_combo.addItems(["All", "Daily", "Weekly", "Monthly"])
        self._cat_combo.setCurrentText("All")
        self._cat_combo.hide()
        self._cat_combo.currentTextChanged.connect(self._on_category_changed)

        self._sector_combo = QComboBox(self)
        self._sector_combo.addItem("All")
        for s in sorted(set(self._sector_map.values())):
            self._sector_combo.addItem(s)
        self._sector_combo.setCurrentText("All")
        self._sector_combo.hide()
        self._sector_combo.currentTextChanged.connect(self._apply_sector_filter)

        def _toolbar_btn(label):
            btn = QPushButton(label)
            btn.setFixedHeight(30)
            btn.setFont(font_scale.font(font_scale.SMALL, False))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {text_s};"
                f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
                f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
            )
            return btn

        self._filter_btn = _toolbar_btn("⊞  Filters")
        self._filter_btn.clicked.connect(self._show_filter_panel)
        self._export_btn = _toolbar_btn("⭳  Export")
        self._export_btn.clicked.connect(self._export)

        top.addWidget(self._filter_btn)
        top.addSpacing(8)
        if self._show_strategies:
            self._strat_btn = _toolbar_btn("⚡  Strategies")
            self._strat_btn.clicked.connect(self._show_strategy_picker)
            top.addWidget(self._strat_btn)
            top.addSpacing(8)
        top.addWidget(self._export_btn)

        if self._on_save is not None:
            save_btn = QPushButton("Save")
            save_btn.setFixedHeight(30)
            save_btn.setFont(font_scale.font(font_scale.SMALL, True))
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.setStyleSheet(
                f"QPushButton {{ background: {accent}; color: {t.get('background') if t else '#0d1117'};"
                "border: none; border-radius: 4px; padding: 0 16px; }"
                f"QPushButton:hover {{ background: {accent}dd; }}"
            )
            save_btn.clicked.connect(self._on_save)
            top.addSpacing(8)
            top.addWidget(save_btn)

        close_btn = QPushButton("Close")
        close_btn.setFixedHeight(30)
        close_btn.setFont(font_scale.font(font_scale.SMALL, False))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
        )
        close_btn.clicked.connect(self.close)
        top.addSpacing(8)
        top.addWidget(close_btn)
        root.addLayout(top)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {divclr};")
        root.addWidget(div)

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
        root.addWidget(self._table, 1)

        bottom = QHBoxLayout()
        self._stock_count_lbl = QLabel("Stocks : 0")
        self._stock_count_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._stock_count_lbl.setStyleSheet(f"color: {text_s};")
        bottom.addWidget(self._stock_count_lbl)
        bottom.addStretch()
        root.addLayout(bottom)

    @staticmethod
    def _fmt_cell(val) -> str:
        if isinstance(val, float):
            return f"{val:.4f}"
        if val is None:
            return ""
        return str(val)

    # ── Table population (static — no diffing/highlighting) ────────────────────

    def _populate_table(self):
        t = self._theme
        norm_bg  = QColor(t.get("card_bg")      if t else "#1c2128")
        norm_txt = QColor(t.get("text_primary") if t else "#e6edf3")
        win_bg   = t.get("background")          if t else "#0d1117"
        hdr_bg   = t.get("button_bg")           if t else "#21262d"
        strat_hdr = t.get("accent") + "22"      if t else "#39d35322"

        active_strategies = [s for s in self._filtered_strategies() if s.get("active")]
        if active_strategies:
            disp_headers, disp_data = apply_strategies(active_strategies, self._headers, self._data)
        else:
            disp_headers, disp_data = self._headers, self._data
        base_col_count = len(self._headers)

        strat_col_defs = []
        for s in active_strategies:
            for col in s.get("columns", []):
                strat_col_defs.append(col)

        all_dicts = [dict(zip(disp_headers, row)) for row in disp_data]

        self.setStyleSheet(f"background: {win_bg};")
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {norm_bg.name()}; color: {norm_txt.name()}; }}"
            f"QTableWidget QHeaderView::section {{ background: {hdr_bg}; color: {norm_txt.name()}; }}"
        )

        self._table.setColumnCount(len(disp_headers))
        self._table.setHorizontalHeaderLabels(disp_headers)
        self._table.setRowCount(len(disp_data))

        bold_font = font_scale.font(font_scale.SMALL, True)
        scrip_col = disp_headers.index("Scrip Name") if "Scrip Name" in disp_headers else -1
        for r, row in enumerate(disp_data):
            row_dict = all_dicts[r]
            for c, val in enumerate(row):
                item = QTableWidgetItem(self._fmt_cell(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                if c == scrip_col:
                    item.setFont(bold_font)
                item.setForeground(QBrush(norm_txt))
                item.setBackground(QBrush(norm_bg))
                strat_idx = c - base_col_count
                if 0 <= strat_idx < len(strat_col_defs):
                    col_def = strat_col_defs[strat_idx]
                    cell_color = get_cell_color(col_def, val, row_dict, all_dicts)
                    if cell_color:
                        item.setBackground(QBrush(QColor(cell_color)))
                        qc = QColor(cell_color)
                        lum = 0.299 * qc.red() + 0.587 * qc.green() + 0.114 * qc.blue()
                        item.setForeground(QBrush(QColor("#000000" if lum > 128 else "#ffffff")))
                    else:
                        item.setBackground(QBrush(QColor(strat_hdr)))
                self._table.setItem(r, c, item)

        if len(disp_headers) > len(self._headers):
            for c in range(len(self._headers), len(disp_headers)):
                self._visible_cols.add(c)
        for c in range(len(disp_headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)

        self._table.resizeColumnsToContents()
        self._update_strat_btn_label()
        self._apply_sector_filter()

    # ── Strategy picker ──────────────────────────────────────────────────────

    def _filtered_strategies(self) -> list:
        if self._selected_category == "All":
            return self._strategies
        return [s for s in self._strategies if s.get("category", "Daily") == self._selected_category]

    def _on_category_changed(self, text: str):
        self._selected_category = text
        self._visible_cols = set(range(len(self._headers)))
        self._populate_table()
        self._update_filter_btn_label()

    def _show_strategy_picker(self):
        popup = StrategyPickerPopup(self._filtered_strategies(), self._theme, self)
        popup.applied.connect(self._on_strategies_applied)
        btn_pos = self._strat_btn.mapToGlobal(self._strat_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _on_strategies_applied(self, updated: list):
        updated_by_id = {s["id"]: s for s in updated}
        self._strategies = [updated_by_id.get(s["id"], s) for s in self._strategies]
        for s in updated:
            strategy_store.save_strategy(s)
        self._visible_cols = set(range(len(self._headers)))
        self._populate_table()

    def _update_strat_btn_label(self):
        if not self._show_strategies:
            return
        filtered = self._filtered_strategies()
        active = sum(1 for s in filtered if s.get("active"))
        total = len(filtered)
        if total == 0:
            self._strat_btn.setText("⚡  Strategies")
        elif active == 0:
            self._strat_btn.setText("⚡  Strategies  off")
        else:
            self._strat_btn.setText(f"⚡  Strategies  {active}/{total}")

    # ── Filter panel ─────────────────────────────────────────────────────────

    def _show_filter_panel(self):
        sectors = sorted(set(self._sector_map.values()))
        popup = FilterPanelPopup(
            current_category=self._cat_combo.currentText(),
            current_sector=self._sector_combo.currentText(),
            sectors=sectors,
            col_visible=len(self._visible_cols),
            col_total=len(self._headers),
            theme=self._theme,
            parent=self,
        )
        popup.columns_requested.connect(self._show_col_filter)
        popup.category_changed.connect(self._cat_combo.setCurrentText)
        popup.sector_changed.connect(self._sector_combo.setCurrentText)
        popup.cleared.connect(self._clear_all_filters)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _clear_all_filters(self):
        self._cat_combo.setCurrentText("All")
        self._sector_combo.setCurrentText("All")
        if self._headers:
            self._visible_cols = set(range(len(self._headers)))
            for c in range(len(self._headers)):
                self._table.setColumnHidden(c, False)
        self._update_filter_btn_label()

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
        if "Scrip Name" in self._headers:
            visible.add(self._headers.index("Scrip Name"))
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        self._update_filter_btn_label()

    def _update_filter_btn_label(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider")        if t else "#30363d"

        active = 0
        if self._cat_combo.currentText() != "All":
            active += 1
        if self._sector_combo.currentText() != "All":
            active += 1
        total   = len(self._headers)
        visible = len(self._visible_cols)
        if total > 0 and visible < total:
            active += 1

        if active:
            label, color, border = f"⊞  Filters · {active}", accent, accent
        else:
            label, color, border = "⊞  Filters", text_s, divclr

        self._filter_btn.setText(label)
        self._filter_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color};"
            f"border: 1px solid {border}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )

    def _apply_sector_filter(self):
        selected = self._sector_combo.currentText()
        for r in range(self._table.rowCount()):
            if selected == "All":
                self._table.setRowHidden(r, False)
            else:
                item = self._table.item(r, 0)   # Sector is always col 0
                self._table.setRowHidden(r, item is None or item.text() != selected)
        self._update_filter_btn_label()
        self._update_stock_count_label()

    def _update_stock_count_label(self):
        """Count of currently visible (non-filtered-out) rows — kept in sync
        wherever row visibility can change (sector filter, strategy apply,
        category change all end in _apply_sector_filter, called from
        _populate_table)."""
        visible = sum(
            1 for r in range(self._table.rowCount())
            if not self._table.isRowHidden(r)
        )
        self._stock_count_lbl.setText(f"Stocks : {visible}")

    # ── Export ───────────────────────────────────────────────────────────────

    def _visible_table_data(self) -> tuple:
        hdr = self._table.horizontalHeader()
        n = self._table.columnCount()
        cols = [
            hdr.logicalIndex(v) for v in range(n)
            if not self._table.isColumnHidden(hdr.logicalIndex(v))
        ]
        headers = []
        for logical in cols:
            item = self._table.horizontalHeaderItem(logical)
            headers.append(item.text() if item else "")
        rows = []
        for r in range(self._table.rowCount()):
            if self._table.isRowHidden(r):
                continue
            rows.append([
                (self._table.item(r, logical).text() if self._table.item(r, logical) else "")
                for logical in cols
            ])
        return headers, rows

    def _export(self):
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services.lmv_export import export_xlsx

        headers, rows = self._visible_table_data()
        if not headers:
            QMessageBox.information(self, "Export", "Nothing to export yet.")
            return

        default_name = f"lmv_{self._trade_date.isoformat()}.xlsx"
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Historical LMV", default_name, "Excel Workbook (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_xlsx(path, headers, rows)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not export:\n\n{exc}")
            return
        QMessageBox.information(self, "Export", f"Exported {len(rows)} rows to:\n{path}")
