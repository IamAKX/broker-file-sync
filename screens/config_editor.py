import font_scale
import re
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QMessageBox,
    QHeaderView, QAbstractItemView, QSizePolicy, QLineEdit
)
from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from config_defaults import (
    SECTOR_STOCK_DATA,
    SCRIPT_NAME_DATA,
    MAIN_COLUMN_NAME_DATA,
    MAIN_COLUMN_ORDER_DATA,
)


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^>]*></rect>', '', svg)
    svg = re.sub(r'(<svg\b[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect|g)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)



class ConfigTabWidget(QWidget):
    def __init__(self, col_headers: list, default_data: list, theme,
                 reorderable: bool = False, store_key: str = None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._col_headers = col_headers
        self._default_data = [tuple(r) for r in default_data]
        self._reorderable = reorderable
        self._store_key = store_key
        # Load persisted rows for this tab, falling back to defaults.
        if store_key:
            from services import config_store
            self._initial_data = [tuple(r) for r in
                                  config_store.load_tab(store_key, default_data)]
        else:
            self._initial_data = self._default_data
        # column indices
        self._order_col = 0 if reorderable else None
        self._data_start = 1 if reorderable else 0
        self._del_col = self._data_start + len(col_headers)
        self._total_cols = self._del_col + 1
        self._build()

    def _build(self):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        # Toolbar
        toolbar = QHBoxLayout()
        add_btn = QPushButton("+ Add Row")
        add_btn.setFixedHeight(32)
        add_btn.setFont(font_scale.font(font_scale.SMALL, False))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(
            f"background: transparent; color: {t.get('accent')};"
            f"border: 1px solid {t.get('accent')}; border-radius: 4px; padding: 0 14px;"
        )
        add_btn.clicked.connect(self._add_row)
        toolbar.addWidget(add_btn)

        self._count_lbl = QLabel()
        self._count_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._count_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        toolbar.addWidget(self._count_lbl)
        toolbar.addStretch()

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search…")
        self._search_box.setFixedHeight(32)
        self._search_box.setFixedWidth(220)
        self._search_box.setFont(font_scale.font(font_scale.SMALL, False))
        self._search_box.textChanged.connect(self._on_search)
        toolbar.addWidget(self._search_box)
        layout.addLayout(toolbar)

        # Table
        self._table = QTableWidget(0, self._total_cols)
        self._table.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        self._table.setShowGrid(True)

        # Header labels
        headers = []
        if self._reorderable:
            headers.append("ORDER")
        headers.extend(self._col_headers)
        headers.append("")
        self._table.setHorizontalHeaderLabels(headers)

        self._sort_col = None
        self._sort_asc = True

        hh = self._table.horizontalHeader()
        if self._reorderable:
            hh.setSectionResizeMode(self._order_col, QHeaderView.ResizeMode.Fixed)
            hh.resizeSection(self._order_col, 72)
        for i in range(self._data_start, self._del_col):
            hh.setSectionResizeMode(i, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(self._del_col, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(self._del_col, 44)
        hh.setSectionsClickable(True)
        hh.sectionClicked.connect(self._on_header_clicked)

        for row_data in self._initial_data:
            self._insert_row(row_data)

        self._update_count()
        layout.addWidget(self._table, 1)

        # Bottom buttons
        divider = QWidget()
        divider.setFixedHeight(1)
        divider.setStyleSheet(f"background-color: {t.get('divider')};")
        layout.addWidget(divider)

        btn_row = QHBoxLayout()
        btn_row.addStretch()

        reset_btn = QPushButton("Reset")
        reset_btn.setFixedHeight(36)
        reset_btn.setFont(font_scale.font(font_scale.MEDIUM, False))
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset)

        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(36)
        save_btn.setFont(font_scale.font(font_scale.MEDIUM, True))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; padding: 0 28px;"
        )
        save_btn.clicked.connect(self._save)

        btn_row.addWidget(reset_btn)
        btn_row.addSpacing(8)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    @staticmethod
    def _outlined_style(color: str) -> str:
        return (
            f"QPushButton {{ background: transparent; color: {color};"
            f"border: 1px solid {color}; border-radius: 4px; font-size: {font_scale.SMALL}pt; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {color}; color: #ffffff; }}"
        )

    @staticmethod
    def _wire_hover_icon(btn: QPushButton, svg_file: str, normal_color: str):
        """Swap icon color on hover so it stays visible against filled background."""
        btn.setIcon(_svg_icon(svg_file, normal_color))
        def on_enter(_):
            btn.setIcon(_svg_icon(svg_file, "#ffffff"))
        def on_leave(_):
            btn.setIcon(_svg_icon(svg_file, normal_color))
        btn.enterEvent = on_enter
        btn.leaveEvent = on_leave

    def _make_order_widget(self):
        cyan = "#06b6d4"
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 4, 6, 4)
        h.setSpacing(4)

        up_btn = QPushButton()
        up_btn.setFixedSize(26, 26)
        up_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        up_btn.setIconSize(QSize(14, 14))
        up_btn.setStyleSheet(self._outlined_style(cyan))
        self._wire_hover_icon(up_btn, "up.svg", cyan)

        dn_btn = QPushButton()
        dn_btn.setFixedSize(26, 26)
        dn_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dn_btn.setIconSize(QSize(14, 14))
        dn_btn.setStyleSheet(self._outlined_style(cyan))
        self._wire_hover_icon(dn_btn, "down.svg", cyan)

        up_btn.clicked.connect(lambda _, b=up_btn: self._move_row(b, -1))
        dn_btn.clicked.connect(lambda _, b=dn_btn: self._move_row(b, +1))
        h.addWidget(up_btn)
        h.addWidget(dn_btn)
        return w

    def _make_delete_widget(self):
        red = self._theme.get("status_red")
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 0, 6, 0)
        btn = QPushButton()
        btn.setFixedSize(28, 28)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setIconSize(QSize(14, 14))
        btn.setStyleSheet(self._outlined_style(red))
        self._wire_hover_icon(btn, "cross.svg", red)
        btn.clicked.connect(lambda _, b=btn: self._delete_row(b))
        h.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    def _insert_row(self, data=None):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setRowHeight(row, 40)

        if self._reorderable:
            self._table.setCellWidget(row, self._order_col, self._make_order_widget())

        for i in range(len(self._col_headers)):
            val = data[i] if data and i < len(data) else ""
            self._table.setItem(row, self._data_start + i, QTableWidgetItem(str(val)))

        self._table.setCellWidget(row, self._del_col, self._make_delete_widget())

    def _row_of_button(self, btn, col):
        for row in range(self._table.rowCount()):
            cw = self._table.cellWidget(row, col)
            if cw and btn in cw.findChildren(QPushButton):
                return row
        return -1

    def _delete_row(self, btn):
        row = self._row_of_button(btn, self._del_col)
        if row >= 0:
            self._table.removeRow(row)
            self._update_count()

    def _move_row(self, btn, direction: int):
        if self._order_col is None:
            return
        row = self._row_of_button(btn, self._order_col)
        if row < 0:
            return
        target = row + direction
        if 0 <= target < self._table.rowCount():
            self._swap_rows(row, target)

    def _swap_rows(self, r1: int, r2: int):
        for col in range(self._data_start, self._del_col):
            item1 = self._table.takeItem(r1, col)
            item2 = self._table.takeItem(r2, col)
            if item1:
                self._table.setItem(r2, col, item1)
            if item2:
                self._table.setItem(r1, col, item2)

    def _on_header_clicked(self, logical_col: int):
        # Only sort data columns, not ORDER or delete columns
        if logical_col < self._data_start or logical_col >= self._del_col:
            return
        if self._sort_col == logical_col:
            self._sort_asc = not self._sort_asc
        else:
            self._sort_col = logical_col
            self._sort_asc = True
        self._sort_by_col(logical_col, self._sort_asc)
        self._update_header_indicators()

    def _sort_by_col(self, col: int, ascending: bool):
        data = self.get_data()
        key_idx = col - self._data_start
        data.sort(key=lambda r: r[key_idx].lower() if key_idx < len(r) else "", reverse=not ascending)
        self._table.setRowCount(0)
        for row_data in data:
            self._insert_row(row_data)
        self._update_count()

    def _update_header_indicators(self):
        hh = self._table.horizontalHeader()
        for col in range(self._data_start, self._del_col):
            label = self._col_headers[col - self._data_start]
            if col == self._sort_col:
                arrow = " ▲" if self._sort_asc else " ▼"
                self._table.horizontalHeaderItem(col).setText(label + arrow)
            else:
                self._table.horizontalHeaderItem(col).setText(label)
        hh.viewport().update()

    def _update_count(self):
        self._count_lbl.setText(f"{self._table.rowCount()} rows")

    def _add_row(self):
        self._insert_row()
        self._update_count()
        self._table.scrollToBottom()

    def _on_search(self, text: str):
        query = text.strip().lower()
        for row in range(self._table.rowCount()):
            match = False
            if not query:
                match = True
            else:
                for col in range(self._data_start, self._del_col):
                    item = self._table.item(row, col)
                    if item and query in item.text().lower():
                        match = True
                        break
            self._table.setRowHidden(row, not match)

    def _reset(self):
        reply = QMessageBox.question(
            self, "Reset", "Reset to default data? Unsaved changes will be lost.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply == QMessageBox.StandardButton.Yes:
            self._search_box.blockSignals(True)
            self._search_box.clear()
            self._search_box.blockSignals(False)
            self._table.setRowCount(0)
            for row_data in self._default_data:
                self._insert_row(row_data)
            self._update_count()

    def _save(self):
        if self._store_key:
            from services import config_store
            config_store.save_tab(self._store_key, self.get_data())
        QMessageBox.information(self, "Saved", "Configuration saved successfully.")

    def get_data(self) -> list:
        result = []
        for row in range(self._table.rowCount()):
            row_data = []
            for col in range(self._data_start, self._del_col):
                item = self._table.item(row, col)
                row_data.append(item.text() if item else "")
            result.append(tuple(row_data))
        return result


class ConfigEditorScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Config Editor")
        title.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        layout.addWidget(title)

        subtitle = QLabel("Manage sector, script, column name, and column order mappings")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.setFont(font_scale.font(font_scale.MEDIUM, False))

        tabs.addTab(
            ConfigTabWidget(["Sector", "Stock"], SECTOR_STOCK_DATA, t,
                            store_key="sector_stock"),
            "Sector Stock"
        )
        tabs.addTab(
            ConfigTabWidget(["Stock", "Initial"], SCRIPT_NAME_DATA, t,
                            store_key="script_name"),
            "Script Name"
        )
        tabs.addTab(
            ConfigTabWidget(["Actual", "Renamed"], MAIN_COLUMN_NAME_DATA, t,
                            store_key="main_column_name"),
            "Main Column Name"
        )
        tabs.addTab(
            ConfigTabWidget(["Column Name"], MAIN_COLUMN_ORDER_DATA, t,
                            reorderable=True, store_key="main_column_order"),
            "Main Column Order"
        )

        layout.addWidget(tabs, 1)
