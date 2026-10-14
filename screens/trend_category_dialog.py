"""Manage the EMV Trend report's categories (issue #64): which Inception
strategies put a stock in Bullish / Bottom Up / ... for each timeframe, plus
each category's name, description, colour and active flag. The conditions
themselves are the strategies' (built in Inception > Strategy Builder) — this
dialog only maps categories to them, per spec §5.2 ("every category must be
editable", "create additional categories")."""

import copy

import font_scale
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QCheckBox, QColorDialog, QDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QVBoxLayout,
)

from services import inception_strategy_store, trend_categories


def _swatch_style(color: str) -> str:
    return (f"QPushButton {{ background: {color}; border: 1px solid #64748b; border-radius: 4px; "
            f"min-width: 30px; max-width: 30px; min-height: 22px; max-height: 22px; }}")


class TrendCategoryDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Trend Categories")
        self.resize(900, 560)
        self._cats: list = copy.deepcopy(trend_categories.load_all())
        self._strategies: list = list(inception_strategy_store.load_all())
        self._row = -1
        self._build()
        if self._cats:
            self._category_list.setCurrentRow(0)

    # ── build ────────────────────────────────────────────────────────────

    def _build(self):
        root = QVBoxLayout(self)
        intro = QLabel(
            "A category lists, for each timeframe, the Inception strategies that put a stock in it "
            "(a stock qualifies if it passes ANY of them). Build the conditions in Inception > Strategy Builder."
        )
        intro.setWordWrap(True)
        intro.setFont(font_scale.font(font_scale.SMALL, False))
        root.addWidget(intro)

        body = QHBoxLayout()
        root.addLayout(body, 1)

        left = QVBoxLayout()
        self._category_list = QListWidget()
        self._category_list.setFixedWidth(230)
        self._category_list.currentRowChanged.connect(self._on_row_changed)
        left.addWidget(self._category_list, 1)
        row1 = QHBoxLayout()
        for label, slot in (("Add", self._add_category), ("Delete", self._delete_category)):
            b = QPushButton(label)
            b.clicked.connect(slot)
            row1.addWidget(b)
        left.addLayout(row1)
        row2 = QHBoxLayout()
        for label, delta in (("Up", -1), ("Down", 1)):
            b = QPushButton(label)
            b.clicked.connect(lambda _, d=delta: self._move_category(d))
            row2.addWidget(b)
        left.addLayout(row2)
        body.addLayout(left)

        right = QVBoxLayout()
        head = QHBoxLayout()
        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Category name")
        head.addWidget(self._name_edit, 1)
        self._color = "#2979FF"
        self._color_btn = QPushButton()
        self._color_btn.setToolTip("Category colour (used in the report's distribution chart)")
        self._color_btn.setStyleSheet(_swatch_style(self._color))
        self._color_btn.clicked.connect(self._pick_color)
        head.addWidget(self._color_btn)
        self._active_check = QCheckBox("Active")
        head.addWidget(self._active_check)
        right.addLayout(head)
        self._desc_edit = QLineEdit()
        self._desc_edit.setPlaceholderText("Description")
        right.addWidget(self._desc_edit)

        grid = QHBoxLayout()
        self._tf_lists: dict = {}
        for tf in trend_categories.TIMEFRAMES:
            box = QGroupBox(tf)
            lay = QVBoxLayout(box)
            lst = QListWidget()
            for s in self._strategies:
                item = QListWidgetItem(f'{s.get("name", "")}  ({s.get("category", "")})')
                item.setData(Qt.ItemDataRole.UserRole, s.get("id"))
                item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                item.setCheckState(Qt.CheckState.Unchecked)
                lst.addItem(item)
            lay.addWidget(lst)
            self._tf_lists[tf] = lst
            grid.addWidget(box)
        right.addLayout(grid, 1)
        if not self._strategies:
            right.addWidget(QLabel("No Inception strategies yet — create some in Inception > Strategy Builder."))
        body.addLayout(right, 1)

        buttons = QHBoxLayout()
        buttons.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        buttons.addWidget(cancel)
        buttons.addWidget(save)
        root.addLayout(buttons)
        self._refresh_category_list()

    # ── sync widgets <-> working copy ────────────────────────────────────

    def _refresh_category_list(self, select: int | None = None):
        self._category_list.blockSignals(True)
        self._category_list.clear()
        for cat in self._cats:
            item = QListWidgetItem(f'■  {cat["name"]}' + ("" if cat.get("active", True) else "  (inactive)"))
            item.setForeground(QColor(cat.get("color", "#2979FF")))
            self._category_list.addItem(item)
        if select is not None and 0 <= select < len(self._cats):
            # Reselect WITHOUT the row-changed handler: it would store the
            # editor's (stale) widget values into whichever category now sits
            # at the old row — e.g. after a move/delete — duplicating names.
            self._category_list.setCurrentRow(select)
            self._row = select
            self._load_current()
        self._category_list.blockSignals(False)

    def _store_current(self):
        """Widgets -> the category being edited (before switching/saving)."""
        if not (0 <= self._row < len(self._cats)):
            return
        cat = self._cats[self._row]
        cat["name"] = self._name_edit.text().strip() or cat["name"]
        cat["description"] = self._desc_edit.text().strip()
        cat["active"] = self._active_check.isChecked()
        cat["color"] = self._color
        for tf, lst in self._tf_lists.items():
            cat["rules"][tf] = [
                lst.item(i).data(Qt.ItemDataRole.UserRole)
                for i in range(lst.count()) if lst.item(i).checkState() == Qt.CheckState.Checked
            ]

    def _load_current(self):
        if not (0 <= self._row < len(self._cats)):
            return
        cat = self._cats[self._row]
        self._name_edit.setText(cat["name"])
        self._desc_edit.setText(cat.get("description", ""))
        self._active_check.setChecked(bool(cat.get("active", True)))
        self._color = cat.get("color", "#2979FF")
        self._color_btn.setStyleSheet(_swatch_style(self._color))
        for tf, lst in self._tf_lists.items():
            chosen = set(trend_categories.strategies_for(cat, tf))
            for i in range(lst.count()):
                lst.item(i).setCheckState(
                    Qt.CheckState.Checked if lst.item(i).data(Qt.ItemDataRole.UserRole) in chosen
                    else Qt.CheckState.Unchecked)

    def _on_row_changed(self, row: int):
        self._store_current()
        self._row = row
        self._refresh_category_list_labels()
        self._load_current()

    def _refresh_category_list_labels(self):
        """Keep list labels/colours in step with edits without rebuilding the list."""
        for i, cat in enumerate(self._cats):
            item = self._category_list.item(i)
            if item is not None:
                item.setText(f'■  {cat["name"]}' + ("" if cat.get("active", True) else "  (inactive)"))
                item.setForeground(QColor(cat.get("color", "#2979FF")))

    # ── actions ──────────────────────────────────────────────────────────

    def _pick_color(self):
        chosen = QColorDialog.getColor(QColor(self._color), self, "Category colour")
        if chosen.isValid():
            self._color = chosen.name()
            self._color_btn.setStyleSheet(_swatch_style(self._color))

    def _add_category(self):
        self._store_current()
        name, n = "New category", 1
        existing = {c["name"].lower() for c in self._cats}
        while name.lower() in existing:
            n += 1
            name = f"New category {n}"
        cat = trend_categories.new_category(name)
        # ids must stay unique even when two names slug alike
        used = {c["id"] for c in self._cats}
        while cat["id"] in used:
            cat["id"] += "-2"
        self._cats.append(cat)
        self._refresh_category_list(select=len(self._cats) - 1)

    def _delete_category(self):
        if not (0 <= self._row < len(self._cats)):
            return
        del self._cats[self._row]
        self._row = -1
        self._refresh_category_list(select=min(len(self._cats) - 1, max(0, self._category_list.currentRow())))

    def _move_category(self, delta: int):
        self._store_current()
        row, new = self._row, self._row + delta
        if not (0 <= row < len(self._cats) and 0 <= new < len(self._cats)):
            return
        self._cats[row], self._cats[new] = self._cats[new], self._cats[row]
        self._refresh_category_list(select=new)

    def _save(self):
        self._store_current()
        names = [c["name"].strip().lower() for c in self._cats]
        if len(set(names)) != len(names):
            QMessageBox.warning(self, "Duplicate Names", "Every category needs a different name.")
            return
        trend_categories.save_all(self._cats)
        self.accept()
