"""
Indicator Library dialog — browse the registered indicators by category,
configure their parameters, and save the configured ones ("My Indicators").
Saved indicators surface as fields in strategy conditions and are the
selectable set for report charts (services.indicator_library).
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QHBoxLayout, QLabel,
    QListWidget, QListWidgetItem, QPushButton, QSpinBox, QTreeWidget,
    QTreeWidgetItem, QVBoxLayout, QWidget,
)

from services import indicator_library as il


class IndicatorLibraryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Indicator Library")
        self.setMinimumSize(760, 520)
        self._param_widgets: dict = {}
        self._current_key: str | None = None
        self._build()
        self._refresh_saved()

    def _build(self):
        layout = QVBoxLayout(self)
        body = QHBoxLayout()

        self._tree = QTreeWidget()
        self._tree.setHeaderHidden(True)
        for category in il.CATEGORIES:
            defs = [d for d in il.list_definitions() if d["category"] == category]
            if not defs:
                continue
            top = QTreeWidgetItem([category])
            top.setFlags(top.flags() & ~Qt.ItemFlag.ItemIsSelectable)
            for d in defs:
                child = QTreeWidgetItem([f'{d["key"]} — {d["name"]}'])
                child.setData(0, Qt.ItemDataRole.UserRole, d["key"])
                top.addChild(child)
            self._tree.addTopLevelItem(top)
        self._tree.expandAll()
        self._tree.currentItemChanged.connect(self._on_select)
        body.addWidget(self._tree, 1)

        right = QVBoxLayout()
        self._title = QLabel("Select an indicator")
        right.addWidget(self._title)
        self._form_host = QWidget()
        self._form = QFormLayout(self._form_host)
        right.addWidget(self._form_host)
        self._label_preview = QLabel("")
        right.addWidget(self._label_preview)
        self._panel_note = QLabel("")
        right.addWidget(self._panel_note)
        self._add_btn = QPushButton("Add to My Indicators")
        self._add_btn.setEnabled(False)
        self._add_btn.clicked.connect(self._add)
        right.addWidget(self._add_btn)
        right.addStretch()
        body.addLayout(right, 1)
        layout.addLayout(body, 2)

        layout.addWidget(QLabel("My Indicators (available as strategy fields and report charts)"))
        self._saved = QListWidget()
        layout.addWidget(self._saved, 1)
        row = QHBoxLayout()
        remove = QPushButton("Remove Selected")
        remove.clicked.connect(self._remove)
        close = QPushButton("Close")
        close.clicked.connect(self.accept)
        row.addWidget(remove)
        row.addStretch()
        row.addWidget(close)
        layout.addLayout(row)

    def _on_select(self, item, _prev=None):
        key = item.data(0, Qt.ItemDataRole.UserRole) if item else None
        if not key:
            return
        self._current_key = key
        defn = il.get_definition(key)
        self._title.setText(f'{defn["name"]}  ({defn["category"]})')
        self._panel_note.setText(
            "Plotted on the price chart" if defn["panel"] == "overlay" else "Plotted in its own sub-panel"
        )
        while self._form.rowCount():
            self._form.removeRow(0)
        self._param_widgets = {}
        for spec in defn["params"]:
            if spec["type"] == "int":
                w = QSpinBox()
                w.setRange(spec["min"], spec["max"])
                w.setValue(spec["default"])
                w.valueChanged.connect(self._update_preview)
            elif spec["type"] == "float":
                w = QDoubleSpinBox()
                w.setRange(spec["min"], spec["max"])
                w.setSingleStep(0.1)
                w.setValue(spec["default"])
                w.valueChanged.connect(self._update_preview)
            else:
                w = QComboBox()
                w.addItems(spec["choices"])
                w.setCurrentText(spec["default"])
                w.currentTextChanged.connect(self._update_preview)
            self._param_widgets[spec["name"]] = w
            self._form.addRow(spec["label"], w)
        self._add_btn.setEnabled(True)
        self._update_preview()

    def _params(self) -> dict:
        out = {}
        for name, w in self._param_widgets.items():
            out[name] = w.currentText() if isinstance(w, QComboBox) else w.value()
        return out

    def _update_preview(self, *_):
        if self._current_key:
            self._label_preview.setText(
                "Field name: " + il.instance_label(self._current_key, self._params())
            )

    def _add(self):
        if self._current_key:
            il.save_instance(il.new_instance(self._current_key, self._params()))
            self._refresh_saved()

    def _refresh_saved(self):
        self._saved.clear()
        for inst in il.load_instances():
            item = QListWidgetItem(
                f'{il.instance_label(inst["key"], inst["params"])}  —  {il.get_definition(inst["key"])["name"]}'
            )
            item.setData(Qt.ItemDataRole.UserRole, inst["id"])
            self._saved.addItem(item)

    def _remove(self):
        item = self._saved.currentItem()
        if item:
            il.delete_instance(item.data(Qt.ItemDataRole.UserRole))
            self._refresh_saved()
