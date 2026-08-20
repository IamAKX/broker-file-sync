"""Inception > Strategy Builder — same visual layout and category/card
sidebar as today's LMV Strategy Builder (screens.strategy_builder), reusing
its generic (non-LMV-specific) building blocks directly: StrategyCard,
_CategorySection, _AddCategoryDialog, _tokens_to_display, _btn/_sep/
_apply_dialog_bg/_svg_icon. Formula editing reuses the actual Expression
Editor (screens.formula_editor.ExpressionEditorDialog/VariablesManagerDialog)
— the same searchable Functions/Operators/Fields/Constants/Variables catalogue
LMV's Strategy Builder uses — via two small, backward-compatible additions to
those classes (`sections`/`variable_store` params, both defaulting to prior
LMV behavior; see that module for the full rationale): `sections` drops
"Historic Value"/"Rows" (day_history point-lookups and cross-instrument
"[Field] of Symbol" references aren't wired up for Inception's field set);
`variable_store` points the Variables tab/"Save as Variable" at
services.inception_formula_variable_store instead of LMV's.

Backed by its own store (services.inception_strategy_store) and its own
category list — kept fully separate from LMV's, per the Inception feature's
design. Deliberately excludes the Notifications section LMV's editor has
(per project decision: Inception has no live price ticking, so there's no
signal source for it yet).

Every strategy here is evaluated entirely on THIS client, exactly like LMV's
own Strategy Builder — the backend (`/inception/strategies`) is
storage/sync only, never computation. See screens.inception_view_by_date/
screens.inception_hmv for where active strategies actually get applied to
displayed rows (services.strategy_engine.apply_strategies, the same local
engine LMV's live/historical views use), and this module's own
"Test Formula" (ExpressionEditorDialog's built-in Compile & Test, via
services.strategy_engine.compile_check — also local) for validating a
formula against a dummy row (every offered field set to 1.0) while editing.
"""

import copy
import font_scale
from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFrame, QScrollArea,
    QDialog, QComboBox, QColorDialog, QMessageBox, QPushButton,
)

from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from services import inception_columns
from services import inception_strategy_store as store
from services import inception_formula_variable_store as var_store
from screens.strategy_builder import (
    StrategyCard, _CategorySection, _AddCategoryDialog,
    _ADD_CATEGORY_SENTINEL, _tokens_to_display, _btn, _sep, _apply_dialog_bg,
    _svg_icon, _t,
)
from screens.formula_editor import ExpressionEditorDialog, VariablesManagerDialog

# Historic Value (day_history point-lookups) and Rows (cross-instrument "of
# Symbol") aren't implemented server-side for Inception yet — see module
# docstring.
INCEPTION_SECTIONS = ["Functions", "Operators", "Fields", "Constants", "Variables"]


def _dummy_row(fields: list) -> dict:
    return {f: 1.0 for f in fields}


def _open_expression_editor(tokens: list, fields: list, theme, mode: str,
                             self_value=None, parent=None) -> list | None:
    """Opens the real Expression Editor scoped to Inception's fields/store —
    returns the resulting token list, or None if the user cancelled."""
    row = _dummy_row(fields)
    dlg = ExpressionEditorDialog(
        tokens, fields, [], row, all_lmv_data=[row], theme=theme, mode=mode,
        self_value=self_value, real_lmv_headers=fields,
        sections=INCEPTION_SECTIONS, variable_store=var_store, parent=parent,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.get_tokens()
    return None


# ── column editor dialog (name + formula + conditional formatting) ──────────

class _InceptionColumnEditorDialog(QDialog):
    def __init__(self, col_def: dict, fields: list, theme=None, parent=None):
        super().__init__(parent)
        self._col = copy.deepcopy(col_def)
        self._col.setdefault("fmt_rules", [])
        self._fields = fields
        self._theme = theme
        self.setWindowTitle("Edit Column")
        self.resize(680, 600)
        _apply_dialog_bg(self, theme)
        self._build()

    def _build(self):
        t = self._theme
        txts = _t(t, "text_secondary")
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 20)

        name_row = QHBoxLayout()
        lbl = QLabel("Column name:")
        lbl.setFixedWidth(120)
        self._name_edit = QLineEdit(self._col.get("name", ""))
        self._name_edit.setFixedHeight(34)
        self._name_edit.textChanged.connect(lambda v: self._col.update({"name": v}))
        name_row.addWidget(lbl)
        name_row.addWidget(self._name_edit)
        root.addLayout(name_row)

        root.addWidget(_sep(t))

        formula_row = QHBoxLayout()
        flbl = QLabel("Formula (value):")
        flbl.setFont(font_scale.font(font_scale.SMALL, True))
        flbl.setFixedWidth(130)
        self._formula_preview = QLabel(_tokens_to_display(self._col.get("formula", [])) or "—")
        self._formula_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._formula_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;border:none;")
        self._formula_preview.setWordWrap(True)
        edit_formula_btn = _btn("Edit Formula…", outlined=True, theme=t, small=True)
        edit_formula_btn.clicked.connect(self._open_formula_editor)
        formula_row.addWidget(flbl)
        formula_row.addWidget(self._formula_preview, 1)
        formula_row.addWidget(edit_formula_btn)
        root.addLayout(formula_row)

        root.addWidget(_sep(t))

        fmt_hdr = QHBoxLayout()
        fmt_lbl = QLabel("Conditional Formatting:")
        fmt_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        add_rule = _btn("+ Add Rule", theme=t, small=True)
        add_rule.clicked.connect(self._add_fmt_rule)
        fmt_hdr.addWidget(fmt_lbl)
        fmt_hdr.addStretch()
        fmt_hdr.addWidget(add_rule)
        root.addLayout(fmt_hdr)

        hint = QLabel(
            "Rules are checked top to bottom — the first one whose condition is "
            "true wins. Not applied anywhere yet (HMV coloring lands separately) — "
            "stored here so they're ready when it does."
        )
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color:{txts};background:transparent;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._fmt_scroll = QScrollArea()
        self._fmt_scroll.setWidgetResizable(True)
        self._fmt_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fmt_scroll.setMinimumHeight(100)
        self._fmt_inner = QWidget()
        self._fmt_inner.setStyleSheet("background:transparent;")
        self._fmt_layout = QVBoxLayout(self._fmt_inner)
        self._fmt_layout.setSpacing(8)
        self._fmt_layout.setContentsMargins(0, 0, 0, 0)
        self._fmt_layout.addStretch()
        self._fmt_scroll.setWidget(self._fmt_inner)
        root.addWidget(self._fmt_scroll, 1)
        self._refresh_fmt_rules()

        btn_row = QHBoxLayout()
        ok = _btn("Save Column", accent=True, theme=t)
        can = _btn("Cancel", theme=t)
        ok.clicked.connect(self.accept)
        can.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(can)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

    def _open_formula_editor(self):
        tokens = _open_expression_editor(
            list(self._col.get("formula", [])), self._fields, self._theme, "value", parent=self,
        )
        if tokens is not None:
            self._col["formula"] = tokens
            self._formula_preview.setText(_tokens_to_display(self._col["formula"]) or "—")

    def _add_fmt_rule(self):
        self._col["fmt_rules"].append(store.new_fmt_rule())
        self._refresh_fmt_rules()

    def _remove_fmt_rule(self, idx: int):
        del self._col["fmt_rules"][idx]
        self._refresh_fmt_rules()

    def _move_fmt_rule(self, idx: int, delta: int):
        rules = self._col["fmt_rules"]
        new_idx = idx + delta
        if not (0 <= new_idx < len(rules)):
            return
        rules[idx], rules[new_idx] = rules[new_idx], rules[idx]
        self._refresh_fmt_rules()

    def _refresh_fmt_rules(self):
        t = self._theme
        bg = _t(t, "button_bg")
        bd = _t(t, "border")

        while self._fmt_layout.count() > 1:
            item = self._fmt_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = self._col.get("fmt_rules", [])
        for idx, rule in enumerate(rules):
            rule_frame = QFrame()
            # objectName-scoped (not a bare "QFrame{...}" type selector) —
            # QLabel IS a QFrame subclass, so a bare-type selector here would
            # leak this border onto every label nested inside the frame.
            rule_frame.setObjectName("inceptionFmtRuleFrame")
            rule_frame.setStyleSheet(
                f"QFrame#inceptionFmtRuleFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"
            )
            rlay = QVBoxLayout(rule_frame)
            rlay.setSpacing(6)
            rlay.setContentsMargins(10, 8, 10, 8)

            hdr = QHBoxLayout()
            lbl = QLabel(f"Rule {idx + 1}")
            lbl.setFont(font_scale.font(font_scale.SMALL, True))
            lbl.setStyleSheet("background:transparent;")
            hdr.addWidget(lbl)
            hdr.addStretch()

            color_btn = _colorbutton(rule["color"])
            color_btn.clicked.connect(lambda _, i=idx, cb=color_btn: self._pick_color(i, cb))

            up_btn = _btn("", theme=t, small=True)
            up_btn.setIcon(_svg_icon("up.svg", _t(t, "text_primary")))
            up_btn.setIconSize(QSize(12, 12))
            up_btn.setFixedWidth(28)
            up_btn.setEnabled(idx > 0)
            up_btn.clicked.connect(lambda _, i=idx: self._move_fmt_rule(i, -1))

            down_btn = _btn("", theme=t, small=True)
            down_btn.setIcon(_svg_icon("down.svg", _t(t, "text_primary")))
            down_btn.setIconSize(QSize(12, 12))
            down_btn.setFixedWidth(28)
            down_btn.setEnabled(idx < len(rules) - 1)
            down_btn.clicked.connect(lambda _, i=idx: self._move_fmt_rule(i, 1))

            del_btn = _btn("✕", theme=t, small=True, danger=True)
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, i=idx: self._remove_fmt_rule(i))

            hdr.addWidget(QLabel("Color:"))
            hdr.addWidget(color_btn)
            hdr.addSpacing(8)
            hdr.addWidget(up_btn)
            hdr.addWidget(down_btn)
            hdr.addSpacing(8)
            hdr.addWidget(del_btn)
            rlay.addLayout(hdr)

            target_row = QHBoxLayout()
            target_lbl = QLabel("Apply color to:")
            target_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            target_lbl.setStyleSheet("background:transparent;")
            target_lbl.setMinimumWidth(110)
            target_combo = QComboBox()
            current_target = rule.get("target_column")
            target_options = ["(This column)"] + list(self._fields)
            if current_target and current_target not in target_options:
                target_options.append(current_target)
            target_combo.addItems(target_options)
            target_combo.setCurrentText(current_target or "(This column)")
            target_combo.currentTextChanged.connect(lambda text, i=idx: self._set_fmt_target(i, text))
            target_row.addWidget(target_lbl)
            target_row.addWidget(target_combo, 1)
            rlay.addLayout(target_row)

            cond_row = QHBoxLayout()
            cond_lbl = QLabel("Condition:")
            cond_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            cond_lbl.setStyleSheet("background:transparent;")
            cond_lbl.setMinimumWidth(110)
            cond_preview = QLabel(_tokens_to_display(rule.get("condition", [])) or "—")
            cond_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            cond_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;border:none;")
            cond_preview.setWordWrap(True)
            edit_cond_btn = _btn("Edit Condition…", outlined=True, theme=t, small=True)
            edit_cond_btn.clicked.connect(lambda _, i=idx, lbl=cond_preview: self._open_condition_editor(i, lbl))
            cond_row.addWidget(cond_lbl)
            cond_row.addWidget(cond_preview, 1)
            cond_row.addWidget(edit_cond_btn)
            rlay.addLayout(cond_row)

            self._fmt_layout.insertWidget(self._fmt_layout.count() - 1, rule_frame)

    def _open_condition_editor(self, idx: int, preview_label: QLabel):
        rule = self._col["fmt_rules"][idx]
        # THIS (own value) refers to this column's own computed value — 1.0,
        # same dummy-float convention as every other field in local
        # compile-testing here (see module docstring).
        tokens = _open_expression_editor(
            list(rule.get("condition", [])), self._fields, self._theme, "condition",
            self_value=1.0, parent=self,
        )
        if tokens is not None:
            rule["condition"] = tokens
            preview_label.setText(_tokens_to_display(rule["condition"]) or "—")

    def _set_fmt_target(self, idx: int, text: str):
        self._col["fmt_rules"][idx]["target_column"] = None if text == "(This column)" else text

    def _pick_color(self, idx: int, btn):
        current = QColor(self._col["fmt_rules"][idx]["color"])
        color = QColorDialog.getColor(current, self, "Pick Rule Color")
        if color.isValid():
            hex_color = color.name()
            self._col["fmt_rules"][idx]["color"] = hex_color
            btn.setStyleSheet(f"background:{hex_color};border:1px solid #555;border-radius:4px;")

    def result_col(self) -> dict:
        return self._col


def _colorbutton(color: str):
    b = QPushButton()
    b.setFixedSize(28, 22)
    b.setStyleSheet(f"background:{color};border:1px solid #555;border-radius:4px;")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b

# ── strategy editor (right panel) ────────────────────────────────────────────

class _InceptionStrategyEditor(QWidget):
    saved = Signal(dict)

    def __init__(self, strategy: dict, fields: list, theme=None, parent=None):
        super().__init__(parent)
        self._strategy = copy.deepcopy(strategy)
        self._fields = fields
        self._theme = theme
        self._last_valid_category = self._strategy.get("category", "Daily")
        self._build()

    def _field_names(self) -> list:
        # This strategy's own columns are offered too, same as LMV's
        # _combined_headers_and_values — a later column can reference an
        # earlier one.
        own_cols = [c["name"] for c in self._strategy.get("columns", [])]
        return self._fields + [c for c in own_cols if c not in self._fields]

    def _build(self):
        t = self._theme
        txts = _t(t, "text_secondary")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_inner = QWidget()
        editor_inner.setStyleSheet("background:transparent;")
        root = QVBoxLayout(editor_inner)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        name_row = QHBoxLayout()
        lbl = QLabel("Strategy Name:")
        lbl.setFixedWidth(130)
        self._name_edit = QLineEdit(self._strategy.get("name", ""))
        self._name_edit.setFixedHeight(36)
        self._name_edit.setFont(font_scale.font(font_scale.MEDIUM, False))
        name_row.addWidget(lbl)
        name_row.addWidget(self._name_edit)
        root.addLayout(name_row)

        cat_row = QHBoxLayout()
        cat_lbl = QLabel("Category:")
        cat_lbl.setFixedWidth(130)
        self._category_combo = QComboBox()
        self._category_combo.setFixedHeight(36)
        self._refresh_category_items()
        self._category_combo.activated.connect(self._on_category_activated)
        cat_row.addWidget(cat_lbl)
        cat_row.addWidget(self._category_combo)
        root.addLayout(cat_row)

        root.addWidget(_sep(t))

        filter_hdr = QHBoxLayout()
        filter_title = QLabel("Row Filter")
        filter_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        filter_info = QLabel("(leave blank to include all rows)")
        filter_info.setFont(font_scale.font(font_scale.SMALL, False))
        filter_info.setStyleSheet(f"color:{txts};")
        filter_edit_btn = _btn("Edit Filter…", outlined=True, theme=t, small=True)
        filter_edit_btn.clicked.connect(self._open_filter_editor)
        filter_hdr.addWidget(filter_title)
        filter_hdr.addSpacing(8)
        filter_hdr.addWidget(filter_info)
        filter_hdr.addStretch()
        filter_hdr.addWidget(filter_edit_btn)
        root.addLayout(filter_hdr)

        self._filter_preview = QLabel(_tokens_to_display(self._strategy.get("row_filter", [])))
        self._filter_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._filter_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;border:none;padding:2px 4px;")
        self._filter_preview.setWordWrap(True)
        root.addWidget(self._filter_preview)

        root.addWidget(_sep(t))

        col_hdr = QHBoxLayout()
        col_title = QLabel("Columns")
        col_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        add_col = _btn("+ Add Column", outlined=True, theme=t, small=True)
        add_col.clicked.connect(self._add_column)
        col_hdr.addWidget(col_title)
        col_hdr.addStretch()
        col_hdr.addWidget(add_col)
        root.addLayout(col_hdr)

        self._col_inner = QWidget()
        self._col_inner.setStyleSheet("background:transparent;")
        self._col_layout = QVBoxLayout(self._col_inner)
        self._col_layout.setSpacing(8)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.addStretch()
        root.addWidget(self._col_inner)
        root.addStretch()

        editor_scroll.setWidget(editor_inner)
        outer.addWidget(editor_scroll, 1)

        footer = QFrame()
        footer.setStyleSheet(f"QFrame {{ background: {_t(t, 'card_bg')}; border-top: 1px solid {_t(t, 'border')}; }}")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(20, 10, 20, 10)
        footer_lay.addStretch()
        save_btn = _btn("Save Strategy", accent=True, theme=t)
        save_btn.clicked.connect(self._save)
        footer_lay.addWidget(save_btn)
        outer.addWidget(footer)

        self._refresh_columns()

    def _add_column(self):
        col = store.new_column(f"Col{len(self._strategy['columns']) + 1}")
        dlg = _InceptionColumnEditorDialog(col, self._field_names(), self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["columns"].append(dlg.result_col())
            self._refresh_columns()

    def _edit_column(self, idx: int):
        col = self._strategy["columns"][idx]
        # This column can't reference its own formula.
        fields = [f for f in self._field_names() if f != col.get("name")]
        dlg = _InceptionColumnEditorDialog(col, fields, self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["columns"][idx] = dlg.result_col()
            self._refresh_columns()

    def _clone_column(self, idx: int):
        original = self._strategy["columns"][idx]
        cloned = copy.deepcopy(original)
        cloned["name"] = original["name"] + " (Copy)"
        self._strategy["columns"].insert(idx + 1, cloned)
        self._refresh_columns()

    def _delete_column(self, idx: int):
        del self._strategy["columns"][idx]
        self._refresh_columns()

    def _refresh_columns(self):
        t = self._theme
        bd = _t(t, "border")
        bg = _t(t, "button_bg")
        txt = _t(t, "text_primary")
        txts = _t(t, "text_secondary")
        a = _t(t, "accent")

        while self._col_layout.count() > 1:
            item = self._col_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, col in enumerate(self._strategy.get("columns", [])):
            row_frame = QFrame()
            row_frame.setObjectName("inceptionColumnRowFrame")
            row_frame.setStyleSheet(
                f"QFrame#inceptionColumnRowFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"
            )
            row_lay = QVBoxLayout(row_frame)
            row_lay.setContentsMargins(12, 8, 12, 8)
            row_lay.setSpacing(4)

            top_row = QHBoxLayout()
            name_lbl = QLabel(col.get("name", f"Col{idx+1}"))
            name_lbl.setFont(font_scale.font(font_scale.SMALL, True))
            name_lbl.setStyleSheet(f"color:{txt};background:transparent;")

            nrules = len(col.get("fmt_rules", []))
            rule_lbl = QLabel(f"{nrules} format rule{'s' if nrules != 1 else ''}")
            rule_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            rule_lbl.setStyleSheet(f"color:{txts};background:transparent;")

            edit_b = _btn("Edit", theme=t, small=True)
            clone_b = _btn("Clone", theme=t, small=True, outlined=True)
            del_b = _btn("✕", theme=t, small=True, danger=True)
            edit_b.setFixedWidth(50)
            clone_b.setFixedWidth(64)
            del_b.setFixedWidth(30)
            edit_b.clicked.connect(lambda _, i=idx: self._edit_column(i))
            clone_b.clicked.connect(lambda _, i=idx: self._clone_column(i))
            del_b.clicked.connect(lambda _, i=idx: self._delete_column(i))

            top_row.addWidget(name_lbl)
            top_row.addSpacing(10)
            top_row.addWidget(rule_lbl)
            top_row.addStretch()
            top_row.addWidget(edit_b)
            top_row.addSpacing(4)
            top_row.addWidget(clone_b)
            top_row.addSpacing(4)
            top_row.addWidget(del_b)
            row_lay.addLayout(top_row)

            formula_preview = QLabel(_tokens_to_display(col.get("formula", [])))
            formula_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            formula_preview.setStyleSheet(f"color:{a};background:transparent;border:none;padding:2px 4px;")
            formula_preview.setWordWrap(True)
            row_lay.addWidget(formula_preview)

            self._col_layout.insertWidget(self._col_layout.count() - 1, row_frame)

    def _open_filter_editor(self):
        tokens = _open_expression_editor(
            list(self._strategy.get("row_filter", [])), self._field_names(), self._theme,
            "condition", parent=self,
        )
        if tokens is not None:
            self._strategy["row_filter"] = tokens
            self._filter_preview.setText(_tokens_to_display(self._strategy["row_filter"]))

    def _refresh_category_items(self, select: str | None = None):
        target = select if select is not None else self._last_valid_category
        self._category_combo.blockSignals(True)
        self._category_combo.clear()
        categories = store.all_categories()
        self._category_combo.addItems(categories)
        self._category_combo.addItem(_ADD_CATEGORY_SENTINEL)
        if target in categories:
            self._category_combo.setCurrentText(target)
            self._last_valid_category = target
        self._category_combo.blockSignals(False)

    def _on_category_activated(self, index: int):
        if self._category_combo.itemText(index) != _ADD_CATEGORY_SENTINEL:
            self._last_valid_category = self._category_combo.itemText(index)
            return
        self._prompt_add_category()

    def _prompt_add_category(self):
        dlg = _AddCategoryDialog(self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.category_name()
            if name:
                canonical = store.add_custom_category(name)
                self._refresh_category_items(select=canonical)
                return
        self._refresh_category_items()

    def _save(self):
        self._strategy["name"] = self._name_edit.text().strip() or "Untitled"
        self._strategy["category"] = self._category_combo.currentText()
        self.saved.emit(copy.deepcopy(self._strategy))


# ── main screen ───────────────────────────────────────────────────────────────

class InceptionStrategyBuilderScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._theme = controller.theme
        self._strategies: list = []
        self._fields: list = []
        self._active_editor = None
        self._search_query = ""
        self._expanded_categories: set = set()
        self._build()
        QTimer.singleShot(0, self._reload_all)

    def _build(self):
        t = self._theme
        bd = _t(t, "border")
        bg = _t(t, "background")
        card = _t(t, "card_bg")
        txts = _t(t, "text_secondary")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        topbar = QFrame()
        topbar.setFixedHeight(56)
        topbar.setObjectName("inceptionTopbar")
        topbar.setStyleSheet(f"QFrame#inceptionTopbar{{background:{card};border-bottom:1px solid {bd};}}")
        top_lay = QHBoxLayout(topbar)
        top_lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel("Inception — Strategy Builder")
        title.setFont(font_scale.font(font_scale.LARGE, True))

        vars_btn = _btn("Variables", theme=t)
        vars_btn.clicked.connect(self._open_variables_manager)

        new_btn = _btn("+ New Strategy", accent=True, theme=t)
        new_btn.clicked.connect(self._new_strategy)

        top_lay.addWidget(title)
        top_lay.addStretch()
        top_lay.addWidget(vars_btn)
        top_lay.addSpacing(8)
        top_lay.addWidget(new_btn)
        root.addWidget(topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left_frame = QFrame()
        left_frame.setFixedWidth(300)
        left_frame.setObjectName("inceptionLeftFrame")
        left_frame.setStyleSheet(f"QFrame#inceptionLeftFrame{{background:{card};border-right:1px solid {bd};}}")
        left_root = QVBoxLayout(left_frame)
        left_root.setContentsMargins(12, 12, 12, 12)
        left_root.setSpacing(8)

        list_title = QLabel("Strategies")
        list_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        left_root.addWidget(list_title)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search strategies…")
        self._search_box.setFixedHeight(30)
        self._search_box.setFont(font_scale.font(font_scale.SMALL, False))
        self._search_box.setStyleSheet(
            f"QLineEdit{{background:{_t(t,'input_bg')};color:{_t(t,'text_primary')};"
            f"border:1px solid {_t(t,'border')};border-radius:6px;padding:0 8px;}}"
            f"QLineEdit:focus{{border-color:{_t(t,'accent')};}}"
        )
        self._search_box.textChanged.connect(self._on_search_changed)
        left_root.addWidget(self._search_box)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_inner = QWidget()
        self._list_inner.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._list_inner)
        self._list_layout.setSpacing(8)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_inner)
        left_root.addWidget(self._list_scroll, 1)
        body.addWidget(left_frame)

        right_frame = QFrame()
        right_frame.setObjectName("inceptionRightFrame")
        right_frame.setStyleSheet(f"QFrame#inceptionRightFrame{{background:{bg};}}")
        right_root = QVBoxLayout(right_frame)
        right_root.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("← Select a strategy to edit, or create a new one")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._placeholder.setStyleSheet(f"color:{txts};")
        right_root.addWidget(self._placeholder)

        self._editor_container = QWidget()
        self._editor_container.hide()
        editor_lay = QVBoxLayout(self._editor_container)
        editor_lay.setContentsMargins(0, 0, 0, 0)
        self._editor_slot = editor_lay
        right_root.addWidget(self._editor_container, 1)

        body.addWidget(right_frame, 1)
        root.addLayout(body, 1)

    # ── data loading ─────────────────────────────────────────────────────────

    def _reload_all(self):
        # Local now — Group A/B computation (and the field catalogue that
        # describes it) moved entirely to this client, see
        # services.inception_columns/inception_formula_engine. No network
        # call needed here any more.
        self._fields = [c.code for c in inception_columns.column_catalogue()]
        self._fields += [v["name"] for v in var_store.load_all()]
        self._strategies = store.load_all()
        self._refresh_list()

    # ── strategy list ────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._search_query = text
        self._refresh_list()

    def _on_section_toggled(self, category: str, expanded: bool):
        if expanded:
            self._expanded_categories.add(category)
        else:
            self._expanded_categories.discard(category)

    def _refresh_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

        query = self._search_query.strip().lower()
        filtered = (
            [s for s in self._strategies if query in s.get("name", "").lower()]
            if query else list(self._strategies)
        )

        by_category: dict = {}
        for strat in filtered:
            by_category.setdefault(strat.get("category", "Daily"), []).append(strat)

        ordered_categories = [c for c in store.all_categories() if c in by_category]
        ordered_categories += [c for c in by_category if c not in ordered_categories]

        if not filtered:
            msg = "No strategies yet.\nClick '+ New Strategy'." if not self._strategies else \
                  f"No strategies match “{self._search_query.strip()}”."
            empty = QLabel(msg)
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setStyleSheet(f"color:{_t(self._theme,'text_secondary')};")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._list_layout.insertWidget(0, empty)
            # Still show every category (all empty) so the taxonomy is visible
            # even with zero strategies — matches "categories can be empty now".
            for cat in store.all_categories():
                self._insert_category_section(cat, [])
            return

        for cat in ordered_categories:
            self._insert_category_section(cat, by_category[cat])
        for cat in store.all_categories():
            if cat not in by_category:
                self._insert_category_section(cat, [])

    def _insert_category_section(self, category: str, strategies: list):
        expanded = category in self._expanded_categories
        section = _CategorySection(category, len(strategies), self._theme, expanded, parent=self)
        section.toggled.connect(self._on_section_toggled)
        for strat in strategies:
            card = StrategyCard(strat, self._theme, parent=section)
            card.edit_requested.connect(self._open_editor)
            card.clone_requested.connect(self._on_clone)
            card.delete_requested.connect(self._on_delete)
            card.toggled.connect(self._on_toggle)
            section.add_card(card)
        self._list_layout.insertWidget(self._list_layout.count() - 1, section)

    def _new_strategy(self):
        new = store.new_strategy("New Strategy")
        self._open_editor(new)

    def _open_editor(self, strategy: dict):
        if self._active_editor is not None:
            self._editor_slot.removeWidget(self._active_editor)
            self._active_editor.deleteLater()
        editor = _InceptionStrategyEditor(strategy, self._fields, self._theme, parent=self._editor_container)
        editor.saved.connect(self._on_strategy_saved)
        self._editor_slot.addWidget(editor)
        self._active_editor = editor
        self._placeholder.hide()
        self._editor_container.show()

    def _on_strategy_saved(self, strategy: dict):
        t = self._theme
        try:
            store.save_strategy(strategy)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = store.load_all()
        self._refresh_list()

    def _on_clone(self, strategy: dict):
        cloned = copy.deepcopy(strategy)
        cloned["id"] = store.new_strategy("")["id"]
        cloned["name"] = strategy.get("name", "Strategy") + " (Copy)"
        t = self._theme
        try:
            store.save_strategy(cloned)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = store.load_all()
        self._refresh_list()

    def _on_delete(self, strategy_id: str):
        t = self._theme
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Strategy")
        msg.setText("Delete this strategy? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            store.delete_strategy(strategy_id)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = store.load_all()
        self._refresh_list()
        if self._active_editor is not None and self._active_editor._strategy.get("id") == strategy_id:
            self._editor_slot.removeWidget(self._active_editor)
            self._active_editor.deleteLater()
            self._active_editor = None
            self._editor_container.hide()
            self._placeholder.show()

    def _on_toggle(self, strategy_id: str, active: bool):
        t = self._theme
        strategy = next((s for s in self._strategies if s["id"] == strategy_id), None)
        if strategy is None:
            return
        strategy["active"] = active
        try:
            store.save_strategy(strategy)
        except (ApiError, NetworkError) as exc:
            strategy["active"] = not active   # revert on failure
            show_api_error(t, self, exc)
            self._refresh_list()

    def _open_variables_manager(self):
        row = _dummy_row(self._fields)
        dlg = VariablesManagerDialog(
            self._fields, row, all_lmv_data=[row], theme=self._theme,
            sections=INCEPTION_SECTIONS, variable_store=var_store, parent=self,
        )
        dlg.exec()
        # A variable may have been renamed/added/deleted — refresh the field
        # universe every editor sees on its next open.
        self._fields = [f for f in self._fields if f not in [v["name"] for v in var_store.load_all()]]
        self._fields += [v["name"] for v in var_store.load_all()]

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        pass
