import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt


class HistoricDataViewer(QWidget):
    """Read-only popup showing the saved historic rows/columns for one date."""

    def __init__(self, headers: list, rows: list, date_str: str, theme=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle(f"Historic Data — {date_str}")
        self.resize(1000, 600)
        self._build(headers, rows)

    def _build(self, headers: list, rows: list):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)

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

        for r, row in enumerate(rows):
            for c in range(len(headers)):
                value = row[c] if c < len(row) else ""
                item = QTableWidgetItem("" if value is None else str(value))
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
                self._table.setItem(r, c, item)

        layout.addWidget(self._table, 1)

    def refresh_theme(self):
        self._table.repaint()
