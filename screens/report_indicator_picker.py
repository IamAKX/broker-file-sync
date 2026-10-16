"""Checkable list of Indicator Library entries for a report wizard (issue
#71): pick the indicators to plot, with Select/Deselect All and a shortcut to
the library. Same click-anywhere-toggles behaviour as the EMV stock report's
list (the native checkbox is near-invisible on the dark theme)."""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QHBoxLayout, QListWidget, QListWidgetItem, QPushButton, QVBoxLayout, QWidget,
)

from services import indicator_library


class IndicatorPickerWidget(QWidget):
    def __init__(self, theme=None, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self._list = QListWidget()
        self._list.setMinimumHeight(150)
        self._list.setMaximumHeight(140)
        if theme is not None:
            self._list.setStyleSheet(
                f"QListWidget::indicator {{ width: 14px; height: 14px; border: 1px solid "
                f"{theme.get('text_secondary')}; border-radius: 3px; background: transparent; }}"
                f"QListWidget::indicator:checked {{ background: {theme.get('accent')}; "
                f"border-color: {theme.get('accent')}; }}"
            )
        self._list.itemClicked.connect(self._toggle)
        lay.addWidget(self._list)
        row = QHBoxLayout()
        for label, slot in (("Select All", lambda: self._set_all(True)),
                            ("Deselect All", lambda: self._set_all(False)),
                            ("Manage Indicator Library…", self._open_library)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row.addWidget(b)
        row.addStretch()
        lay.addLayout(row)
        self.refresh()

    # ── public API ───────────────────────────────────────────────────────

    def refresh(self, keep: set | None = None):
        """Reload the library's entries, keeping the current (or given) ticks."""
        keep = self.selected_ids() if keep is None else set(keep)
        self._list.clear()
        for inst in indicator_library.load_instances():
            item = QListWidgetItem(
                f'{indicator_library.instance_label(inst["key"], inst["params"])}'
                f' — {indicator_library.get_definition(inst["key"])["name"]}')
            item.setData(Qt.ItemDataRole.UserRole, inst["id"])
            item.setCheckState(Qt.CheckState.Checked if inst["id"] in keep else Qt.CheckState.Unchecked)
            self._list.addItem(item)

    def selected_ids(self) -> list:
        return [self._list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self._list.count())
                if self._list.item(i).checkState() == Qt.CheckState.Checked]

    def set_selected(self, ids) -> None:
        self.refresh(keep=set(ids or []))

    def count(self) -> int:
        return self._list.count()

    # ── internals ────────────────────────────────────────────────────────

    @staticmethod
    def _toggle(item: QListWidgetItem):
        item.setCheckState(Qt.CheckState.Unchecked if item.checkState() == Qt.CheckState.Checked
                           else Qt.CheckState.Checked)

    def _set_all(self, checked: bool):
        state = Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked
        for i in range(self._list.count()):
            self._list.item(i).setCheckState(state)

    def _open_library(self):
        from screens.indicator_library_dialog import IndicatorLibraryDialog
        IndicatorLibraryDialog(parent=self).exec()
        self.refresh()
