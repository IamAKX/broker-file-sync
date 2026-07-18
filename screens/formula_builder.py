"""Edit menu -> ExternalImport Formula Builder.

List + editor screen (same shape as Strategy Builder) for the 56 built-in
ExternalImport formulas. Each formula's expression is edited with a
click-to-build chip editor (screens.formula_field_editor) over the fixed
domain vocabulary in services.formula_tokens — not a free-text spreadsheet
cell. Users can edit any built-in formula's fields and add their own.
"""
import copy
import os
import re
import uuid

import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QComboBox, QMessageBox
)
from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from services import config_store
from services import formula_tokens as ft
from screens.formula_field_editor import FormulaFieldEditorDialog

_STORE_KEY = "external_import_formulas"
_FREQUENCIES = ["DAILY", "WEEKLY", "MONTHLY"]
_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(_ASSETS_DIR, filename)
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


def _t(theme, key: str) -> str:
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "destructive": "#da3633",
    }
    if theme:
        try:
            return theme.get(key)
        except Exception:
            pass
    return _FALLBACK.get(key, "#888")


def _default_formulas() -> list:
    return [
        {
            "id": code, "code": code,
            "name": defn["name"], "tokens": copy.deepcopy(defn["tokens"]),
            "description": defn["description"], "frequency": defn["frequency"],
        }
        for code, defn in ((c, ft.BUILTIN_FORMULAS[c]) for c in ft.BUILTIN_CODES)
    ]


class FormulaCard(QFrame):
    def __init__(self, formula: dict, theme=None, parent=None):
        super().__init__(parent)
        self._formula = formula
        self._theme = theme
        self._on_edit = None
        self._on_delete = None
        self._build()

    def set_callbacks(self, on_edit, on_delete):
        self._on_edit = on_edit
        self._on_delete = on_delete

    def _build(self):
        t = self._theme
        bg, bd = _t(t, "button_bg"), _t(t, "border")
        txt, txts, accent = _t(t, "text_primary"), _t(t, "text_secondary"), _t(t, "accent")
        self.setStyleSheet(f"QFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 8, 12, 8)
        lay.setSpacing(4)

        top = QHBoxLayout()
        code_lbl = QLabel(self._formula["code"])
        code_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        code_lbl.setStyleSheet(f"color:{txt};background:transparent;")
        freq_lbl = QLabel(self._formula["frequency"])
        freq_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        freq_lbl.setStyleSheet(
            f"color:{txts};background:transparent;border:1px solid {txts}55;"
            "border-radius:3px;padding:0 6px;"
        )
        edit_b = QPushButton("Edit")
        edit_b.setFixedWidth(50)
        edit_b.setFont(font_scale.font(font_scale.SMALL, False))
        edit_b.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_b.clicked.connect(lambda: self._on_edit and self._on_edit(self._formula))
        destructive = _t(t, "destructive")
        del_b = QPushButton()
        del_b.setFixedSize(30, 26)
        del_b.setIconSize(QSize(14, 14))
        del_b.setCursor(Qt.CursorShape.PointingHandCursor)
        del_b.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"border:1px solid {destructive};border-radius:4px;}}"
            f"QPushButton:hover{{background:{destructive};}}"
        )
        del_b.setIcon(_svg_icon("cross.svg", destructive))

        def _on_enter(_, b=del_b, c=destructive):
            b.setIcon(_svg_icon("cross.svg", "#ffffff"))

        def _on_leave(_, b=del_b, c=destructive):
            b.setIcon(_svg_icon("cross.svg", c))

        del_b.enterEvent = _on_enter
        del_b.leaveEvent = _on_leave
        del_b.clicked.connect(lambda: self._on_delete and self._on_delete(self._formula["id"]))

        top.addWidget(code_lbl)
        top.addSpacing(8)
        top.addWidget(freq_lbl)
        top.addStretch()
        top.addWidget(edit_b)
        top.addSpacing(4)
        top.addWidget(del_b)
        lay.addLayout(top)

        name_lbl = QLabel(self._formula["name"])
        name_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        name_lbl.setStyleSheet(f"color:{txts};background:transparent;")
        name_lbl.setWordWrap(True)
        lay.addWidget(name_lbl)

        formula_lbl = QLabel(ft.tokens_to_display(self._formula["tokens"]))
        formula_lbl.setFont(QFont("Menlo,Consolas,monospace", 9))
        formula_lbl.setStyleSheet(f"color:{accent};background:transparent;")
        formula_lbl.setWordWrap(True)
        lay.addWidget(formula_lbl)


class FormulaEditorPanel(QWidget):
    def __init__(self, formula: dict, theme=None, parent=None):
        super().__init__(parent)
        self._formula = copy.deepcopy(formula)
        self._theme = theme
        self._on_saved = None
        self._build()

    def set_on_saved(self, callback):
        self._on_saved = callback

    def _build(self):
        t = self._theme
        txts = _t(t, "text_secondary")
        accent = _t(t, "accent")

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        code_row = QHBoxLayout()
        code_lbl = QLabel("Code:")
        code_lbl.setFixedWidth(110)
        self._code_edit = QLineEdit(self._formula.get("code", ""))
        self._code_edit.setFixedHeight(34)
        code_row.addWidget(code_lbl)
        code_row.addWidget(self._code_edit)
        root.addLayout(code_row)

        name_row = QHBoxLayout()
        name_lbl = QLabel("Name:")
        name_lbl.setFixedWidth(110)
        self._name_edit = QLineEdit(self._formula.get("name", ""))
        self._name_edit.setFixedHeight(34)
        name_row.addWidget(name_lbl)
        name_row.addWidget(self._name_edit)
        root.addLayout(name_row)

        formula_row = QHBoxLayout()
        formula_lbl = QLabel("Formula:")
        formula_lbl.setFixedWidth(110)
        self._formula_preview = QLabel(ft.tokens_to_display(self._formula.get("tokens", [])))
        self._formula_preview.setFont(QFont("Menlo,Consolas,monospace", 10))
        self._formula_preview.setStyleSheet(f"color:{accent};background:transparent;")
        self._formula_preview.setWordWrap(True)
        edit_formula_btn = QPushButton("Edit Formula…")
        edit_formula_btn.setFixedHeight(30)
        edit_formula_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_formula_btn.clicked.connect(self._open_formula_editor)
        formula_row.addWidget(formula_lbl)
        formula_row.addWidget(self._formula_preview, 1)
        formula_row.addWidget(edit_formula_btn)
        root.addLayout(formula_row)

        desc_row = QHBoxLayout()
        desc_lbl = QLabel("Description:")
        desc_lbl.setFixedWidth(110)
        self._desc_edit = QLineEdit(self._formula.get("description", ""))
        self._desc_edit.setFixedHeight(34)
        desc_row.addWidget(desc_lbl)
        desc_row.addWidget(self._desc_edit)
        root.addLayout(desc_row)

        freq_row = QHBoxLayout()
        freq_lbl = QLabel("Frequency:")
        freq_lbl.setFixedWidth(110)
        self._freq_combo = QComboBox()
        self._freq_combo.addItems(_FREQUENCIES)
        self._freq_combo.setCurrentText(self._formula.get("frequency", "DAILY"))
        self._freq_combo.setFixedHeight(34)
        freq_row.addWidget(freq_lbl)
        freq_row.addWidget(self._freq_combo)
        root.addLayout(freq_row)

        root.addStretch()

        hint = QLabel(
            "Formula edits here describe the calculation for reference — the "
            "actual ExternalImport calculation engine is fixed and tested "
            "separately."
        )
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color:{txts};")
        hint.setWordWrap(True)
        root.addWidget(hint)

        btn_row = QHBoxLayout()
        save_btn = QPushButton("Save Formula")
        save_btn.setFixedHeight(34)
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"QPushButton{{background:{accent};color:{_t(t,'background')};"
            "border:none;border-radius:5px;padding:0 20px;}"
        )
        save_btn.clicked.connect(self._save)
        btn_row.addStretch()
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def _open_formula_editor(self):
        dlg = FormulaFieldEditorDialog(
            self._formula.get("tokens", []), self._theme,
            exclude_code=self._formula.get("code"), parent=self,
        )
        if dlg.exec():
            self._formula["tokens"] = dlg.get_tokens()
            self._formula_preview.setText(ft.tokens_to_display(self._formula["tokens"]))

    def _save(self):
        self._formula["code"] = self._code_edit.text().strip() or self._formula.get("code", "")
        self._formula["name"] = self._name_edit.text().strip()
        self._formula["description"] = self._desc_edit.text().strip()
        self._formula["frequency"] = self._freq_combo.currentText()
        if self._on_saved:
            self._on_saved(copy.deepcopy(self._formula))


class FormulaBuilderScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._theme = controller.theme
        self._formulas: list = config_store.load_json(_STORE_KEY, _default_formulas())
        self._active_editor = None
        self._build()

    def _build(self):
        t = self._theme
        bd, card, bg = _t(t, "border"), _t(t, "card_bg"), _t(t, "background")
        txts = _t(t, "text_secondary")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        topbar = QFrame()
        topbar.setFixedHeight(56)
        topbar.setStyleSheet(f"QFrame{{background:{card};border-bottom:1px solid {bd};}}")
        self._topbar = topbar
        top_lay = QHBoxLayout(topbar)
        top_lay.setContentsMargins(20, 0, 20, 0)
        title = QLabel("ExternalImport Formula Builder")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        top_lay.addWidget(title)
        top_lay.addStretch()
        reset_btn = QPushButton("Reset to Defaults")
        reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        reset_btn.clicked.connect(self._reset_to_defaults)
        add_btn = QPushButton("+ Add Formula")
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(
            f"QPushButton{{background:{_t(t,'accent')};color:{_t(t,'background')};"
            "border:none;border-radius:5px;padding:6px 16px;}"
        )
        add_btn.clicked.connect(self._add_formula)
        self._add_btn = add_btn
        top_lay.addWidget(reset_btn)
        top_lay.addSpacing(8)
        top_lay.addWidget(add_btn)
        root.addWidget(topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._left_frame = QFrame()
        self._left_frame.setFixedWidth(360)
        self._left_frame.setStyleSheet(f"QFrame{{background:{card};border-right:1px solid {bd};}}")
        left_root = QVBoxLayout(self._left_frame)
        left_root.setContentsMargins(12, 12, 12, 12)
        left_root.setSpacing(8)
        list_title = QLabel(f"Formulas ({len(self._formulas)})")
        list_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        self._list_title = list_title
        left_root.addWidget(list_title)

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
        body.addWidget(self._left_frame)

        self._right_frame = QFrame()
        self._right_frame.setStyleSheet(f"QFrame{{background:{bg};}}")
        right_root = QVBoxLayout(self._right_frame)
        right_root.setContentsMargins(0, 0, 0, 0)
        self._placeholder = QLabel("← Select a formula to edit, or add a new one")
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
        body.addWidget(self._right_frame, 1)

        root.addLayout(body, 1)

        self._refresh_list()

    def _refresh_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._list_title.setText(f"Formulas ({len(self._formulas)})")
        for formula in self._formulas:
            card = FormulaCard(formula, self._theme, parent=self)
            card.set_callbacks(self._open_editor, self._delete_formula)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    def _open_editor(self, formula: dict):
        while self._editor_slot.count():
            item = self._editor_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        editor = FormulaEditorPanel(formula, self._theme, self)
        editor.set_on_saved(lambda updated, fid=formula["id"]: self._on_formula_saved(fid, updated))
        self._editor_slot.addWidget(editor)
        self._active_editor = editor
        self._placeholder.hide()
        self._editor_container.show()

    def _add_formula(self):
        formula = {
            "id": str(uuid.uuid4()), "code": "NEW", "name": "New Formula",
            "tokens": [], "description": "", "frequency": "DAILY",
        }
        self._formulas.append(formula)
        self._persist()
        self._refresh_list()
        self._open_editor(formula)

    def _delete_formula(self, formula_id: str):
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Formula")
        msg.setText("Delete this formula? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        self._formulas = [f for f in self._formulas if f["id"] != formula_id]
        self._persist()
        self._refresh_list()
        self._placeholder.show()
        self._editor_container.hide()
        self._active_editor = None

    def _on_formula_saved(self, formula_id: str, updated: dict):
        for i, f in enumerate(self._formulas):
            if f["id"] == formula_id:
                updated["id"] = formula_id
                self._formulas[i] = updated
                break
        self._persist()
        self._refresh_list()

    def _reset_to_defaults(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Reset to Defaults")
        msg.setText("Reset all formulas to the 56 built-in defaults? Custom formulas and edits will be lost.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        self._formulas = _default_formulas()
        self._persist()
        self._refresh_list()
        self._placeholder.show()
        self._editor_container.hide()
        self._active_editor = None

    def _persist(self):
        config_store.save_json(_STORE_KEY, self._formulas)

    def refresh_theme(self):
        t = self._theme
        bd, card, bg = _t(t, "border"), _t(t, "card_bg"), _t(t, "background")
        txts = _t(t, "text_secondary")
        self._topbar.setStyleSheet(f"QFrame{{background:{card};border-bottom:1px solid {bd};}}")
        self._left_frame.setStyleSheet(f"QFrame{{background:{card};border-right:1px solid {bd};}}")
        self._right_frame.setStyleSheet(f"QFrame{{background:{bg};}}")
        self._placeholder.setStyleSheet(f"color:{txts};")
        self._add_btn.setStyleSheet(
            f"QPushButton{{background:{_t(t,'accent')};color:{_t(t,'background')};"
            "border:none;border-radius:5px;padding:6px 16px;}"
        )
        self._refresh_list()
        # Re-open editor with fresh theme if visible (mirrors Strategy Builder)
        if self._editor_container.isVisible():
            self._editor_container.hide()
            self._placeholder.show()
            self._active_editor = None
