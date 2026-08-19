"""Inception > Strategy Builder — same click-to-build formula UX as today's
Strategy Builder (screens.strategy_builder.FormulaBuilder, reused as-is: same
operators/functions palette), but scoped to Inception's own field universe
(raw OPEN/HIGH/LOW/CLOSE/VOL/OPENINT + every Group A/B computed column from
the backend's app/services/inception_columns.py + this domain's own saved
formula variables) and its own strategy list — kept fully separate from LMV's
Strategy Builder/Formula Builder (see api/inception_api.py: a distinct
/inception/strategies + /inception/formula-variables backend store).

Deliberately a smaller screen than screens.strategy_builder.StrategyBuilderScreen:
no categories/clone/kebab-menu card UI, no conditional-format (fmt_rules) on
columns, no Notifications section, no cross-row aggregate functions (SUM_ALL/
etc — the server-side evaluator doesn't implement them, see
inception_strategy_engine's docstring in broker-sync-api) — all of LMV's
live-tick-specific machinery (day_history threading, N-day aggregates) simply
doesn't apply here since Inception's own history is already fully precomputed
server-side. Formula compile-testing calls the backend's
POST /inception/compile-check (dummy-float validation) instead of evaluating
locally against a live row, since there's no "currently loaded sheet" here.
"""

import uuid
import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QLineEdit,
    QListWidget, QListWidgetItem, QFrame, QScrollArea, QDialog, QCheckBox,
    QMessageBox,
)
from PySide6.QtCore import Qt, QTimer

from api import inception_api
from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from screens.strategy_builder import FormulaBuilder, _tokens_to_display


def _t(theme, key):
    return theme.get(key) if theme else "#888888"


class InceptionColumnEditorDialog(QDialog):
    """Add/edit one strategy column: a name + a value formula, built with
    the same FormulaBuilder widget the live Strategy Builder uses."""

    def __init__(self, column: dict | None, fields: list, theme=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._column = dict(column) if column else {"name": "", "formula": []}
        self.setWindowTitle("Edit Column" if column else "Add Column")
        self.setMinimumWidth(480)
        bg = _t(theme, "background")
        self.setStyleSheet(f"QDialog{{background:{bg};}}")
        self._build(fields)

    def _build(self, fields: list):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Column Name:"))
        self._name_edit = QLineEdit(self._column.get("name", ""))
        self._name_edit.setFixedHeight(32)
        name_row.addWidget(self._name_edit)
        layout.addLayout(name_row)

        layout.addWidget(QLabel("Formula:"))
        self._formula_builder = FormulaBuilder(
            self._column.get("formula", []), fields, theme=t, mode="value",
            field_label="Inception Fields", show_aggregates=False,
        )
        layout.addWidget(self._formula_builder)

        self._test_lbl = QLabel("")
        self._test_lbl.setWordWrap(True)
        self._test_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        layout.addWidget(self._test_lbl)

        btn_row = QHBoxLayout()
        test_btn = QPushButton("Test Formula")
        test_btn.setFixedHeight(32)
        test_btn.clicked.connect(self._on_test)
        btn_row.addWidget(test_btn)
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(32)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("OK")
        ok_btn.setFixedHeight(32)
        accent = _t(t, "accent")
        ok_btn.setStyleSheet(
            f"QPushButton{{background:{accent};color:{_t(t,'background')};border:none;border-radius:5px;padding:0 16px;}}"
        )
        ok_btn.clicked.connect(self._on_accept)
        btn_row.addWidget(ok_btn)
        layout.addLayout(btn_row)

    def _on_test(self):
        t = self._theme
        formula = self._formula_builder.get_tokens()
        try:
            result = inception_api.compile_check(formula)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        if result.get("ok"):
            self._test_lbl.setText("✓ Formula compiles.")
            self._test_lbl.setStyleSheet(f"color:{_t(t,'accent')};")
        else:
            self._test_lbl.setText(f"✗ {result.get('error') or 'Formula failed to compile.'}")
            self._test_lbl.setStyleSheet(f"color:{_t(t,'status_red')};")

    def _on_accept(self):
        name = self._name_edit.text().strip()
        if not name:
            self._test_lbl.setText("Column name is required.")
            self._test_lbl.setStyleSheet(f"color:{_t(self._theme,'status_red')};")
            return
        self._column["name"] = name
        self._column["formula"] = self._formula_builder.get_tokens()
        self.accept()

    def result_column(self) -> dict:
        return self._column


class InceptionStrategyBuilderScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._strategies: list = []
        self._current: dict | None = None   # the strategy being edited (server shape, or a new draft)
        self._fields: list = []
        self._build()
        QTimer.singleShot(0, self._reload_all)

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 24)
        outer.setSpacing(16)

        # ── left: strategy list ──────────────────────────────────────────────
        left = QVBoxLayout()
        title = QLabel("Inception — Strategy Builder")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        left.addWidget(title)

        new_btn = QPushButton("+ New Strategy")
        new_btn.setFixedHeight(32)
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.clicked.connect(self._on_new)
        left.addWidget(new_btn)

        self._list = QListWidget()
        self._list.setFont(font_scale.font(font_scale.SMALL, False))
        self._list.currentRowChanged.connect(self._on_list_row_changed)
        left.addWidget(self._list, 1)

        left_wrap = QWidget()
        left_wrap.setLayout(left)
        left_wrap.setFixedWidth(280)
        outer.addWidget(left_wrap)

        div = QFrame()
        div.setFrameShape(QFrame.Shape.VLine)
        div.setStyleSheet(f"color:{t.get('divider')};")
        outer.addWidget(div)

        # ── right: editor ─────────────────────────────────────────────────────
        right_scroll = QScrollArea()
        right_scroll.setWidgetResizable(True)
        right_scroll.setFrameShape(QFrame.Shape.NoFrame)
        right_inner = QWidget()
        self._right = QVBoxLayout(right_inner)
        self._right.setSpacing(12)
        right_scroll.setWidget(right_inner)
        outer.addWidget(right_scroll, 1)

        self._build_editor_widgets()
        self._set_editor_visible(False)

    def _build_editor_widgets(self):
        name_row = QHBoxLayout()
        name_row.addWidget(QLabel("Name:"))
        self._name_edit = QLineEdit()
        self._name_edit.setFixedHeight(32)
        name_row.addWidget(self._name_edit)
        self._active_check = QCheckBox("Active")
        name_row.addWidget(self._active_check)
        self._right.addLayout(name_row)

        self._right.addWidget(QLabel("Row Filter (leave empty to include every instrument):"))
        self._row_filter_builder = FormulaBuilder(
            [], [], theme=self._controller.theme, mode="condition",
            field_label="Inception Fields", show_aggregates=False,
        )
        self._right.addWidget(self._row_filter_builder)

        cols_header = QHBoxLayout()
        cols_header.addWidget(QLabel("Columns:"))
        add_col_btn = QPushButton("+ Add Column")
        add_col_btn.setFixedHeight(28)
        add_col_btn.clicked.connect(self._on_add_column)
        cols_header.addWidget(add_col_btn)
        cols_header.addStretch()
        self._right.addLayout(cols_header)

        self._columns_list = QListWidget()
        self._columns_list.setFont(font_scale.font(font_scale.SMALL, False))
        self._columns_list.setFixedHeight(160)
        self._columns_list.itemDoubleClicked.connect(self._on_edit_column)
        self._right.addWidget(self._columns_list)

        col_btn_row = QHBoxLayout()
        edit_col_btn = QPushButton("Edit Selected")
        edit_col_btn.clicked.connect(self._on_edit_column)
        col_btn_row.addWidget(edit_col_btn)
        del_col_btn = QPushButton("Delete Selected")
        del_col_btn.clicked.connect(self._on_delete_column)
        col_btn_row.addWidget(del_col_btn)
        col_btn_row.addStretch()
        self._right.addLayout(col_btn_row)

        self._status_lbl = QLabel("")
        self._status_lbl.setWordWrap(True)
        self._right.addWidget(self._status_lbl)

        bottom_row = QHBoxLayout()
        save_btn = QPushButton("Save")
        save_btn.setFixedHeight(34)
        save_btn.clicked.connect(self._on_save)
        bottom_row.addWidget(save_btn)
        delete_btn = QPushButton("Delete Strategy")
        delete_btn.setFixedHeight(34)
        delete_btn.clicked.connect(self._on_delete_strategy)
        bottom_row.addWidget(delete_btn)
        bottom_row.addStretch()
        self._right.addLayout(bottom_row)
        self._delete_strategy_btn = delete_btn

        self._editor_widgets = [
            self._name_edit, self._active_check, self._row_filter_builder,
            self._columns_list,
        ]

    def _set_editor_visible(self, visible: bool):
        for w in self._editor_widgets:
            w.setEnabled(visible)

    # ── data loading ─────────────────────────────────────────────────────────

    def _reload_all(self):
        t = self._controller.theme
        try:
            columns_result = inception_api.list_columns()
            variables_result = inception_api.list_variables()
            strategies_result = inception_api.list_strategies()
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._fields = [c["code"] for c in columns_result.get("columns", [])]
        self._fields += [v["name"] for v in variables_result.get("variables", [])]
        self._strategies = strategies_result.get("strategies", [])
        self._refresh_list()

    def _refresh_list(self):
        self._list.blockSignals(True)
        self._list.clear()
        for s in self._strategies:
            label = s["name"] + ("" if s.get("active", True) else "  (inactive)")
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, s["id"])
            self._list.addItem(item)
        self._list.blockSignals(False)

    def _on_list_row_changed(self, row: int):
        if row < 0 or row >= len(self._strategies):
            return
        self._load_strategy_into_editor(self._strategies[row])

    def _load_strategy_into_editor(self, strategy: dict):
        self._current = dict(strategy)
        self._name_edit.setText(strategy.get("name", ""))
        self._active_check.setChecked(strategy.get("active", True))
        self._rebuild_row_filter_builder(strategy.get("row_filter", []))
        self._columns_list.clear()
        for col in strategy.get("columns", []):
            self._add_column_list_item(col)
        self._set_editor_visible(True)
        self._delete_strategy_btn.setEnabled(True)
        self._status_lbl.setText("")

    def _rebuild_row_filter_builder(self, tokens: list):
        # FormulaBuilder has no public "reset tokens" — swap the widget instance.
        old = self._row_filter_builder
        idx = self._right.indexOf(old)
        new = FormulaBuilder(
            tokens, self._fields, theme=self._controller.theme, mode="condition",
            field_label="Inception Fields", show_aggregates=False,
        )
        self._right.insertWidget(idx, new)
        self._right.removeWidget(old)
        old.deleteLater()
        self._row_filter_builder = new
        self._editor_widgets = [w if w is not old else new for w in self._editor_widgets]

    def _add_column_list_item(self, col: dict):
        item = QListWidgetItem(f"{col['name']}  =  {_tokens_to_display(col.get('formula', []))}")
        item.setData(Qt.ItemDataRole.UserRole, col)
        self._columns_list.addItem(item)

    # ── strategy actions ─────────────────────────────────────────────────────

    def _on_new(self):
        self._current = {
            "id": str(uuid.uuid4()), "name": "New Strategy", "active": True,
            "category": "Daily", "columns": [], "row_filter": [],
        }
        self._list.clearSelection()
        self._list.setCurrentRow(-1)
        self._name_edit.setText("")
        self._active_check.setChecked(True)
        self._rebuild_row_filter_builder([])
        self._columns_list.clear()
        self._set_editor_visible(True)
        self._delete_strategy_btn.setEnabled(False)  # not saved yet
        self._status_lbl.setText("Unsaved new strategy — fill in and Save.")
        self._status_lbl.setStyleSheet(f"color:{_t(self._controller.theme,'text_secondary')};")

    def _on_save(self):
        if self._current is None:
            return
        t = self._controller.theme
        name = self._name_edit.text().strip()
        if not name:
            self._status_lbl.setText("Name is required.")
            self._status_lbl.setStyleSheet(f"color:{_t(t,'status_red')};")
            return
        columns = [
            self._columns_list.item(i).data(Qt.ItemDataRole.UserRole)
            for i in range(self._columns_list.count())
        ]
        row_filter = self._row_filter_builder.get_tokens()
        active = self._active_check.isChecked()
        category = self._current.get("category", "Daily")
        try:
            result = inception_api.upsert_strategy(
                self._current["id"], name, active, category, columns, row_filter,
            )
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._status_lbl.setText("Saved.")
        self._status_lbl.setStyleSheet(f"color:{_t(t,'accent')};")
        self._delete_strategy_btn.setEnabled(True)
        # Refresh the list from the server response rather than re-fetching
        # everything — same "server response is truth" pattern as the LMV
        # Strategy Builder's save flow.
        existing_idx = next((i for i, s in enumerate(self._strategies) if s["id"] == result["id"]), None)
        if existing_idx is not None:
            self._strategies[existing_idx] = result
        else:
            self._strategies.append(result)
        self._current = dict(result)
        self._refresh_list()

    def _on_delete_strategy(self):
        if self._current is None or "id" not in self._current:
            return
        t = self._controller.theme
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Strategy")
        msg.setText(f"Delete \"{self._current.get('name', '')}\"? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            inception_api.delete_strategy(self._current["id"])
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = [s for s in self._strategies if s["id"] != self._current["id"]]
        self._current = None
        self._refresh_list()
        self._set_editor_visible(False)
        self._status_lbl.setText("Deleted.")
        self._status_lbl.setStyleSheet(f"color:{_t(t,'text_secondary')};")

    # ── column actions ───────────────────────────────────────────────────────

    def _on_add_column(self):
        dlg = InceptionColumnEditorDialog(None, self._current_field_universe(), self._controller.theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._add_column_list_item(dlg.result_column())

    def _on_edit_column(self):
        item = self._columns_list.currentItem()
        if item is None:
            return
        col = item.data(Qt.ItemDataRole.UserRole)
        dlg = InceptionColumnEditorDialog(col, self._current_field_universe(), self._controller.theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            new_col = dlg.result_column()
            item.setText(f"{new_col['name']}  =  {_tokens_to_display(new_col.get('formula', []))}")
            item.setData(Qt.ItemDataRole.UserRole, new_col)

    def _on_delete_column(self):
        row = self._columns_list.currentRow()
        if row >= 0:
            self._columns_list.takeItem(row)

    def _current_field_universe(self) -> list:
        # This strategy's own already-added column names are offered too
        # (a later column can reference an earlier one), same spirit as the
        # live Strategy Builder's _combined_headers_and_values.
        own_cols = [
            self._columns_list.item(i).data(Qt.ItemDataRole.UserRole)["name"]
            for i in range(self._columns_list.count())
        ]
        return self._fields + [c for c in own_cols if c not in self._fields]

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        pass
