"""
Dynamic column picker for report wizards (LMV/EMV specs: select, deselect
and reorder any available column, with search). Two lists — available
(searchable) and selected (drag-to-reorder, or Up/Down) — plus Add/Remove.
columns() returns the selected names in order; an empty selection means
"use the report type's default columns" (services.report_columns).
"""

from PySide6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QPushButton, QVBoxLayout, QWidget,
)


class ColumnPickerWidget(QWidget):
    def __init__(self, available: list, selected: list | None = None, parent=None):
        super().__init__(parent)
        self._available = list(available)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        left = QVBoxLayout()
        left.addWidget(QLabel("Available columns"))
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search…")
        self._search.textChanged.connect(self._refresh_available)
        left.addWidget(self._search)
        self._avail_list = QListWidget()
        self._avail_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._avail_list.itemDoubleClicked.connect(lambda _i: self._add())
        left.addWidget(self._avail_list)
        layout.addLayout(left, 1)

        mid = QVBoxLayout()
        mid.addStretch()
        for text, slot in (("Add ▶", self._add), ("◀ Remove", self._remove),
                           ("▲ Up", lambda: self._move(-1)), ("▼ Down", lambda: self._move(1))):
            btn = QPushButton(text)
            btn.clicked.connect(slot)
            mid.addWidget(btn)
        mid.addStretch()
        layout.addLayout(mid)

        right = QVBoxLayout()
        right.addWidget(QLabel("Selected (drag to reorder)"))
        self._sel_list = QListWidget()
        self._sel_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self._sel_list.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self._sel_list.itemDoubleClicked.connect(lambda _i: self._remove())
        right.addWidget(self._sel_list)
        layout.addLayout(right, 1)

        for name in (selected or []):
            if name in self._available:
                self._sel_list.addItem(name)
        self._refresh_available()

    def columns(self) -> list:
        return [self._sel_list.item(i).text() for i in range(self._sel_list.count())]

    def _refresh_available(self):
        needle = self._search.text().strip().lower()
        chosen = set(self.columns())
        self._avail_list.clear()
        for name in self._available:
            if name not in chosen and needle in name.lower():
                self._avail_list.addItem(name)

    def _add(self):
        for item in self._avail_list.selectedItems():
            self._sel_list.addItem(item.text())
        self._refresh_available()

    def _remove(self):
        for item in self._sel_list.selectedItems():
            self._sel_list.takeItem(self._sel_list.row(item))
        self._refresh_available()

    def _move(self, delta: int):
        rows = sorted(self._sel_list.row(i) for i in self._sel_list.selectedItems())
        if not rows:
            return
        if delta < 0 and rows[0] == 0 or delta > 0 and rows[-1] == self._sel_list.count() - 1:
            return
        for r in (rows if delta < 0 else reversed(rows)):
            item = self._sel_list.takeItem(r)
            self._sel_list.insertItem(r + delta, item)
            item.setSelected(True)
