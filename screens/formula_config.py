import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView
)
from PySide6.QtCore import Qt


class FormulaConfigWindow(QWidget):
    """Placeholder popup for the database-driven ExternalImport source.

    Will eventually list each stock alongside the formula used to calculate
    its value from other columns. Formula definitions and calculation logic
    are not implemented yet — this is a stub window.
    """

    _HEADERS = ["Stock", "Formula"]

    def __init__(self, theme=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Stock Formulas")
        self.resize(600, 400)
        self._build()

    def _build(self):
        t = self._theme
        txt = t.get("text_primary") if t else "#e6edf3"
        txt_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider") if t else "#30363d"

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)

        title = QLabel("Stock Formulas")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color: {txt};")
        layout.addWidget(title)

        note = QLabel(
            "Formula configuration is not available yet. This list will show "
            "each stock and the formula used to calculate its value once "
            "that logic is defined."
        )
        note.setFont(font_scale.font(font_scale.SMALL, False))
        note.setStyleSheet(f"color: {txt_s};")
        note.setWordWrap(True)
        layout.addWidget(note)

        self._table = QTableWidget(0, len(self._HEADERS))
        self._table.setFont(font_scale.font(font_scale.SMALL, False))
        self._table.setHorizontalHeaderLabels(self._HEADERS)
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self._table, 1)
