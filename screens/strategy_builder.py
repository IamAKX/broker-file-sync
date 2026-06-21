import font_scale
"""
Strategy Builder screen.
"""

import copy
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QSizePolicy, QDialog,
    QColorDialog, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

from services import strategy_store as store


# ── theme helpers — always read at call-time so toggling works ─────────────

def _t(theme, key: str) -> str:
    """Read a theme token; return a safe fallback if theme is None."""
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "accent_hover": "#2ea043",
        "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "input_bg": "#0d1117",
        "divider": "#2a2f36", "destructive": "#da3633",
        "status_orange": "#e3b341",
    }
    if theme:
        try:
            return theme.get(key)
        except Exception:
            pass
    return _FALLBACK.get(key, "#888")


def _apply_dialog_bg(dialog: QDialog, theme):
    bg  = _t(theme, "background")
    txt = _t(theme, "text_primary")
    dialog.setStyleSheet(
        f"QDialog{{background:{bg};color:{txt};}}"
        f"QWidget{{background:{bg};color:{txt};}}"
        f"QLabel{{background:transparent;}}"
        f"QFrame{{background:{_t(theme,'card_bg')};border:1px solid {_t(theme,'border')};border-radius:6px;}}"
        f"QLineEdit{{background:{_t(theme,'input_bg')};color:{txt};"
        f"border:1px solid {_t(theme,'border')};border-radius:4px;padding:4px 8px;}}"
        f"QPushButton{{background:{_t(theme,'button_bg')};color:{txt};"
        f"border:1px solid {_t(theme,'border')};border-radius:4px;padding:4px 10px;}}"
        f"QPushButton:hover{{border-color:{_t(theme,'accent')};color:{_t(theme,'accent')};}}"
        f"QScrollArea{{background:transparent;border:none;}}"
        f"QScrollBar:vertical{{background:{_t(theme,'card_bg')};width:6px;}}"
        f"QScrollBar::handle:vertical{{background:{_t(theme,'border')};border-radius:3px;}}"
    )


# ── small widget helpers ───────────────────────────────────────────────────

def _btn(text, accent=False, theme=None, small=False, danger=False, outlined=False):
    b = QPushButton(text)
    b.setFixedHeight(28 if small else 34)
    b.setFont(QFont("", 13 if small else 11))
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    _restyle_btn(b, theme, accent=accent, danger=danger, outlined=outlined)
    return b


def _restyle_btn(b: QPushButton, theme, accent=False, danger=False, outlined=False):
    if danger:
        c = _t(theme, "destructive")
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{c};"
            f"border:1px solid {c};border-radius:5px;padding:0 12px;}}"
            f"QPushButton:hover{{background:{c};color:#fff;}}"
        )
    elif outlined:
        a  = _t(theme, "accent")
        ah = _t(theme, "accent_hover")
        b.setStyleSheet(
            f"QPushButton{{background:transparent;color:{a};"
            f"border:1px solid {a};border-radius:5px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{a};color:{_t(theme,'background')};}}"
        )
    elif accent:
        a  = _t(theme, "accent")
        ah = _t(theme, "accent_hover")
        fg = _t(theme, "background")   # dark mode → dark text on bright green; light → white on dark green
        b.setStyleSheet(
            f"QPushButton{{background:{a};color:{fg};"
            "border:none;border-radius:5px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{ah};color:{fg};}}"
        )
    else:
        bg  = _t(theme, "button_bg")
        bd  = _t(theme, "border")
        txt = _t(theme, "text_primary")
        a   = _t(theme, "accent")
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{txt};"
            f"border:1px solid {bd};border-radius:5px;padding:0 12px;}}"
            f"QPushButton:hover{{border-color:{a};color:{a};}}"
        )


def _sep(theme) -> QFrame:
    f = QFrame()
    f.setFixedHeight(1)
    f.setStyleSheet(f"background:{_t(theme,'divider')};border:none;")
    return f


# ── formula → display string ───────────────────────────────────────────────

def _tokens_to_display(tokens: list) -> str:
    parts = []
    for tok in tokens:
        kind = tok.get("type", "op")
        val  = tok.get("value", "")
        if kind == "col":
            parts.append(f"[{val}]")
        elif kind == "self":
            parts.append("THIS")
        elif kind == "func":
            fname = val.rstrip("(")
            col_arg = tok.get("col_arg", "")
            if fname.endswith("_ALL"):
                parts.append(f"{fname}({col_arg})")
            else:
                parts.append(f"{fname}(")
        elif kind == "num":
            parts.append(val)
        else:
            parts.append(f" {val} ")
    return "".join(parts).strip() or "—"


# ── Token chip widget ──────────────────────────────────────────────────────

class TokenChip(QFrame):
    remove_requested = Signal(object)

    _DARK_COLORS = {
        "col":   ("#1d6fa455", "#cce5ff"),
        "func":  ("#6f42c155", "#ede0ff"),
        "op":    ("#44444466", "#cccccc"),
        "paren": ("#44444466", "#cccccc"),
        "num":   ("#27674955", "#d1fae5"),
        "self":  ("#9a670055", "#fef3c7"),
    }
    _LIGHT_COLORS = {
        "col":   ("#cce5ff", "#1d4e89"),
        "func":  ("#ede0ff", "#4a1d96"),
        "op":    ("#e5e7eb", "#374151"),
        "paren": ("#e5e7eb", "#374151"),
        "num":   ("#d1fae5", "#065f46"),
        "self":  ("#fef3c7", "#78350f"),
    }

    def __init__(self, token: dict, theme=None, parent=None):
        super().__init__(parent)
        self._token = token
        self._theme = theme
        self._build()

    def token(self):
        return self._token

    def _build(self):
        tok  = self._token
        kind = tok.get("type", "op")
        text = tok.get("value", "SELF") if kind != "self" else "THIS"
        if kind == "func":
            fname = text.rstrip("(")
            col_arg = tok.get("col_arg", "")
            text = f"{fname}({col_arg})" if tok.get("col_arg") else text

        is_dark = (self._theme.current_mode == "dark") if self._theme else True
        palette = self._DARK_COLORS if is_dark else self._LIGHT_COLORS
        bg, fg = palette.get(kind, palette["op"])

        lay = QHBoxLayout(self)
        lay.setContentsMargins(6, 2, 2, 2)
        lay.setSpacing(2)

        lbl = QLabel(text)
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color:{fg};background:transparent;border:none;")

        x = QPushButton("×")
        x.setFixedSize(16, 16)
        x.setFont(font_scale.font(font_scale.SMALL, False))
        x.setCursor(Qt.CursorShape.PointingHandCursor)
        x.setStyleSheet(
            f"QPushButton{{background:transparent;color:{fg};border:none;padding:0;}}"
            "QPushButton:hover{color:red;}"
        )
        x.clicked.connect(lambda: self.remove_requested.emit(self))

        lay.addWidget(lbl)
        lay.addWidget(x)

        self.setStyleSheet(f"QFrame{{background:{bg};border-radius:4px;}}")
        self.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(22)


# ── Formula Builder widget ─────────────────────────────────────────────────

OPERATORS  = ["+", "−", "×", "÷", "(", ")"]
OP_MAP     = {"−": "-", "×": "*", "÷": "/", "+": "+", "(": "(", ")": ")"}
FUNCTIONS  = ["MIN(", "MAX(", "ABS(", "ROUND(", "FLOOR(", "CEIL(", "SUM(", "IF("]
AGG_FUNCS  = ["SUM_ALL(", "MIN_ALL(", "MAX_ALL(", "AVG_ALL(", "COUNT_ALL("]
COND_OPS   = [">", "<", ">=", "<=", "==", "!=", "AND", "OR", "NOT"]


class FormulaBuilder(QWidget):
    changed = Signal()

    def __init__(self, tokens: list, lmv_headers: list,
                 theme=None, mode="value", parent=None):
        super().__init__(parent)
        self._tokens      = list(tokens)
        self._lmv_headers = lmv_headers
        self._theme       = theme
        self._mode        = mode
        self._chips: list[TokenChip] = []
        self._build()
        self._refresh_chips()

    def get_tokens(self) -> list:
        return list(self._tokens)

    def _build(self):
        t      = self._theme
        bd     = _t(t, "border")
        inp_bg = _t(t, "input_bg")
        txt    = _t(t, "text_primary")
        txts   = _t(t, "text_secondary")
        accent = _t(t, "accent")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        # ── Token area ────────────────────────────────────────────────────
        token_frame = QFrame()
        token_frame.setMinimumHeight(44)
        token_frame.setStyleSheet(
            f"QFrame{{background:{inp_bg};border:1px solid {bd};border-radius:6px;}}"
        )
        self._token_layout = QHBoxLayout(token_frame)
        self._token_layout.setContentsMargins(8, 4, 8, 4)
        self._token_layout.setSpacing(4)
        self._token_layout.addStretch()
        root.addWidget(token_frame)

        # ── Preview label ─────────────────────────────────────────────────
        self._preview_lbl = QLabel("—")
        self._preview_lbl.setFont(QFont("Menlo,Consolas,monospace", 10))
        self._preview_lbl.setStyleSheet(
            f"color:{accent};background:transparent;border:none;padding:2px 0;"
        )
        self._preview_lbl.setWordWrap(True)
        root.addWidget(self._preview_lbl)

        # ── Number input ──────────────────────────────────────────────────
        num_row = QHBoxLayout()
        self._num_input = QLineEdit()
        self._num_input.setPlaceholderText("Constant…")
        self._num_input.setFixedHeight(30)
        self._num_input.setFont(font_scale.font(font_scale.SMALL, False))
        self._num_input.setFixedWidth(110)

        add_num = QPushButton("Add")
        add_num.setFixedHeight(30)
        add_num.setFont(font_scale.font(font_scale.SMALL, False))
        add_num.setCursor(Qt.CursorShape.PointingHandCursor)
        add_num.setStyleSheet(
            f"QPushButton{{background:{accent};color:{_t(t,'background')};border:none;border-radius:4px;padding:0 10px;}}"
        )
        add_num.clicked.connect(self._add_number)

        clr = QPushButton("Clear")
        clr.setFixedHeight(30)
        clr.setFont(font_scale.font(font_scale.SMALL, False))
        clr.setCursor(Qt.CursorShape.PointingHandCursor)
        clr.setStyleSheet(
            f"QPushButton{{background:transparent;color:{txts};"
            f"border:1px solid {bd};border-radius:4px;padding:0 10px;}}"
        )
        clr.clicked.connect(self._clear)

        num_row.addWidget(QLabel("Number:"))
        num_row.addWidget(self._num_input)
        num_row.addWidget(add_num)
        num_row.addSpacing(8)
        num_row.addWidget(clr)
        num_row.addStretch()
        root.addLayout(num_row)

        # ── Operators ─────────────────────────────────────────────────────
        self._add_button_row(root, "Operators", OPERATORS, "op")

        if self._mode == "condition":
            self._add_button_row(root, "Conditions", COND_OPS, "op")
            this_row = QHBoxLayout()
            lbl = QLabel("Self-ref:")
            lbl.setFont(font_scale.font(font_scale.SMALL, False))
            lbl.setStyleSheet(f"color:{txts};")
            this_btn = QPushButton("THIS (own value)")
            this_btn.setFixedHeight(28)
            this_btn.setFont(font_scale.font(font_scale.SMALL, False))
            this_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            this_btn.setStyleSheet(
                "QPushButton{background:#9a670033;color:#fbbf24;"
                "border:1px solid #9a670066;border-radius:4px;padding:0 10px;}"
                "QPushButton:hover{background:#9a670066;}"
            )
            this_btn.clicked.connect(lambda: self._add_token({"type": "self"}))
            this_row.addWidget(lbl)
            this_row.addWidget(this_btn)
            this_row.addStretch()
            root.addLayout(this_row)

        # ── Per-row functions ─────────────────────────────────────────────
        self._add_button_row(root, "Functions", FUNCTIONS, "func")

        # ── Aggregate functions ───────────────────────────────────────────
        agg_lbl = QLabel("Aggregate (across all rows):")
        agg_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        agg_lbl.setStyleSheet(f"color:{txts};")
        root.addWidget(agg_lbl)

        agg_inner = QWidget()
        agg_row   = QHBoxLayout(agg_inner)
        agg_row.setContentsMargins(0, 0, 0, 0)
        agg_row.setSpacing(6)
        for fname in AGG_FUNCS:
            b = self._chip_button(fname)
            b.clicked.connect(lambda _, fn=fname: self._add_agg_func(fn))
            agg_row.addWidget(b)
        agg_row.addStretch()
        root.addWidget(agg_inner)

        # ── LMV column chips ──────────────────────────────────────────────
        col_lbl = QLabel("LMV Columns (click to insert):")
        col_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        col_lbl.setStyleSheet(f"color:{txts};")
        root.addWidget(col_lbl)

        col_scroll = QScrollArea()
        col_scroll.setFrameShape(QFrame.Shape.NoFrame)
        col_scroll.setFixedHeight(70)
        col_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        col_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        col_inner = QWidget()
        col_row   = QHBoxLayout(col_inner)
        col_row.setContentsMargins(0, 4, 0, 4)
        col_row.setSpacing(6)
        for h in self._lmv_headers:
            b = self._chip_button(h, color="col")
            b.clicked.connect(lambda _, name=h:
                              self._add_token({"type": "col", "value": name}))
            col_row.addWidget(b)
        col_row.addStretch()
        col_scroll.setWidget(col_inner)
        col_scroll.setWidgetResizable(True)
        root.addWidget(col_scroll)

    def _add_button_row(self, layout, label_text: str, items: list, tok_type: str):
        txts = _t(self._theme, "text_secondary")
        lbl = QLabel(f"{label_text}:")
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color:{txts};")
        layout.addWidget(lbl)

        row_w  = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)
        for item in items:
            b = self._chip_button(item, color=tok_type)
            val = OP_MAP.get(item, item)
            b.clicked.connect(lambda _, v=val, tt=tok_type:
                              self._add_token({"type": tt, "value": v}))
            row_lay.addWidget(b)
        row_lay.addStretch()
        layout.addWidget(row_w)

    def _chip_button(self, text: str, color: str = "func") -> QPushButton:
        t      = self._theme
        accent = _t(t, "accent")
        bd     = _t(t, "border")
        txt    = _t(t, "text_primary")
        is_dark = (t.current_mode == "dark") if t else True
        _DARK = {
            "col":  ("#1d6fa433", "#9ecff7"),
            "func": ("#6f42c133", "#d8b4fe"),
            "op":   (bd + "44",   txt),
        }
        _LIGHT = {
            "col":  ("#dbeafe", "#1e40af"),
            "func": ("#f3e8ff", "#6d28d9"),
            "op":   ("#e5e7eb", "#374151"),
        }
        palette = _DARK if is_dark else _LIGHT
        bg, fg = palette.get(color, palette["op"])
        b = QPushButton(text)
        b.setFixedHeight(26)
        b.setFont(font_scale.font(font_scale.SMALL, False))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};"
            f"border:1px solid {bd};border-radius:4px;padding:0 8px;}}"
            f"QPushButton:hover{{border-color:{accent};}}"
        )
        return b

    # ── Token management ──────────────────────────────────────────────────

    def _add_token(self, token: dict):
        self._tokens.append(token)
        self._refresh_chips()
        self.changed.emit()

    def _add_number(self):
        text = self._num_input.text().strip()
        if not text:
            return
        try:
            float(text)
        except ValueError:
            return
        self._add_token({"type": "num", "value": text})
        self._num_input.clear()

    def _add_agg_func(self, fname: str):
        dlg = _AggColDialog(fname, self._lmv_headers, self._theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            col = dlg.selected_col()
            self._add_token({"type": "func", "value": fname, "col_arg": col})

    def _clear(self):
        self._tokens.clear()
        self._refresh_chips()
        self.changed.emit()

    def _remove_chip(self, chip: TokenChip):
        idx = self._chips.index(chip)
        del self._tokens[idx]
        self._refresh_chips()
        self.changed.emit()

    def _refresh_chips(self):
        for chip in self._chips:
            self._token_layout.removeWidget(chip)
            chip.deleteLater()
        self._chips.clear()

        for tok in self._tokens:
            chip = TokenChip(tok, self._theme, self)
            chip.remove_requested.connect(self._remove_chip)
            self._token_layout.insertWidget(self._token_layout.count() - 1, chip)
            self._chips.append(chip)

        # Update preview
        self._preview_lbl.setText(_tokens_to_display(self._tokens))


# ── Aggregate column picker ────────────────────────────────────────────────

class _AggColDialog(QDialog):
    def __init__(self, fname: str, headers: list, theme=None, parent=None):
        super().__init__(parent)
        self._headers = headers
        self._theme   = theme
        self.setWindowTitle(f"{fname} — pick column")
        self.setFixedWidth(300)
        self._sel = headers[0] if headers else ""
        _apply_dialog_bg(self, theme)
        self._build(fname)

    def _build(self, fname):
        accent = _t(self._theme, "accent")
        fg     = _t(self._theme, "background")
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel(f"Column for {fname}:"))

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(220)
        inner = QWidget()
        vlay  = QVBoxLayout(inner)
        vlay.setSpacing(4)
        for h in self._headers:
            b = QPushButton(h)
            b.setFlat(True)
            b.setFont(font_scale.font(font_scale.SMALL, False))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, name=h: self._pick(name))
            vlay.addWidget(b)
        vlay.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll)

        ok = QPushButton("OK")
        ok.setFixedHeight(32)
        ok.setStyleSheet(
            f"QPushButton{{background:{accent};color:{fg};border:none;border-radius:5px;}}"
        )
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)

    def _pick(self, name):
        self._sel = name
        self.accept()

    def selected_col(self):
        return self._sel


# ── Column editor dialog ───────────────────────────────────────────────────

class ColumnEditorDialog(QDialog):
    def __init__(self, col_def: dict, lmv_headers: list, theme=None, parent=None):
        super().__init__(parent)
        self._col   = copy.deepcopy(col_def)
        self._lmv   = lmv_headers
        self._theme = theme
        self.setWindowTitle("Edit Column")
        self.resize(720, 640)
        _apply_dialog_bg(self, theme)
        self._build()

    def _build(self):
        t    = self._theme
        txts = _t(t, "text_secondary")
        bd   = _t(t, "border")

        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 20)

        # Name
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

        # Formula
        flbl = QLabel("Formula (value):")
        flbl.setFont(font_scale.font(font_scale.SMALL, True))
        root.addWidget(flbl)

        self._formula_builder = FormulaBuilder(
            self._col.get("formula", []), self._lmv, t, mode="value", parent=self
        )
        self._formula_builder.changed.connect(
            lambda: self._col.update({"formula": self._formula_builder.get_tokens()})
        )
        root.addWidget(self._formula_builder)

        root.addWidget(_sep(t))

        # Conditional formatting
        fmt_hdr = QHBoxLayout()
        fmt_lbl = QLabel("Conditional Formatting:")
        fmt_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        add_rule = _btn("+ Add Rule", theme=t, small=True)
        add_rule.clicked.connect(self._add_fmt_rule)
        fmt_hdr.addWidget(fmt_lbl)
        fmt_hdr.addStretch()
        fmt_hdr.addWidget(add_rule)
        root.addLayout(fmt_hdr)

        hint = QLabel("First matching rule wins. Use THIS to reference this column's own value.")
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color:{txts};background:transparent;")
        root.addWidget(hint)

        self._fmt_scroll = QScrollArea()
        self._fmt_scroll.setWidgetResizable(True)
        self._fmt_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fmt_scroll.setMinimumHeight(100)
        self._fmt_inner  = QWidget()
        self._fmt_inner.setStyleSheet("background:transparent;")
        self._fmt_layout = QVBoxLayout(self._fmt_inner)
        self._fmt_layout.setSpacing(8)
        self._fmt_layout.setContentsMargins(0, 0, 0, 0)
        self._fmt_layout.addStretch()
        self._fmt_scroll.setWidget(self._fmt_inner)
        root.addWidget(self._fmt_scroll, 1)

        self._refresh_fmt_rules()

        # Buttons
        btn_row = QHBoxLayout()
        ok  = _btn("Save Column", accent=True, theme=t)
        can = _btn("Cancel", theme=t)
        ok.clicked.connect(self.accept)
        can.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(can)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

    def _add_fmt_rule(self):
        self._col["fmt_rules"].append(store.new_fmt_rule())
        self._refresh_fmt_rules()

    def _remove_fmt_rule(self, idx: int):
        del self._col["fmt_rules"][idx]
        self._refresh_fmt_rules()

    def _refresh_fmt_rules(self):
        t  = self._theme
        bg = _t(t, "button_bg")
        bd = _t(t, "border")

        while self._fmt_layout.count() > 1:
            item = self._fmt_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, rule in enumerate(self._col.get("fmt_rules", [])):
            rule_frame = QFrame()
            rule_frame.setStyleSheet(
                f"QFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"
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

            color_btn = QPushButton()
            color_btn.setFixedSize(28, 22)
            color_btn.setStyleSheet(
                f"background:{rule['color']};border:1px solid #555;border-radius:4px;"
            )
            color_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            color_btn.setToolTip("Pick color")
            color_btn.clicked.connect(lambda _, i=idx, cb=color_btn: self._pick_color(i, cb))

            del_btn = _btn("✕", theme=t, small=True, danger=True)
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, i=idx: self._remove_fmt_rule(i))

            color_lbl = QLabel("Color:")
            color_lbl.setStyleSheet("background:transparent;")
            hdr.addWidget(color_lbl)
            hdr.addWidget(color_btn)
            hdr.addSpacing(8)
            hdr.addWidget(del_btn)
            rlay.addLayout(hdr)

            cond_lbl = QLabel("Condition (evaluates to true/false):")
            cond_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            cond_lbl.setStyleSheet("background:transparent;")
            rlay.addWidget(cond_lbl)

            cond_builder = FormulaBuilder(
                rule.get("condition", []), self._lmv, t,
                mode="condition", parent=self
            )
            cond_builder.changed.connect(
                lambda _, i=idx, cb=cond_builder:
                self._update_condition(i, cb.get_tokens())
            )
            rlay.addWidget(cond_builder)
            self._fmt_layout.insertWidget(self._fmt_layout.count() - 1, rule_frame)

    def _update_condition(self, idx: int, tokens: list):
        if idx < len(self._col["fmt_rules"]):
            self._col["fmt_rules"][idx]["condition"] = tokens

    def _pick_color(self, idx: int, btn: QPushButton):
        current = QColor(self._col["fmt_rules"][idx]["color"])
        color   = QColorDialog.getColor(current, self, "Pick Rule Color")
        if color.isValid():
            hex_color = color.name()
            self._col["fmt_rules"][idx]["color"] = hex_color
            btn.setStyleSheet(
                f"background:{hex_color};border:1px solid #555;border-radius:4px;"
            )

    def result_col(self) -> dict:
        self._col["name"]    = self._name_edit.text().strip()
        self._col["formula"] = self._formula_builder.get_tokens()
        return self._col


# ── Strategy card ──────────────────────────────────────────────────────────

class StrategyCard(QFrame):
    edit_requested   = Signal(dict)
    delete_requested = Signal(str)
    toggled          = Signal(str, bool)

    def __init__(self, strategy: dict, theme=None, parent=None):
        super().__init__(parent)
        self._strategy = strategy
        self._theme    = theme
        self.setObjectName("stratCard")
        self._build()

    def _build(self):
        t    = self._theme
        txt  = _t(t, "text_primary")
        txts = _t(t, "text_secondary")
        a    = _t(t, "accent")

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 12, 10)
        lay.setSpacing(4)

        top = QHBoxLayout()
        name_lbl = QLabel(self._strategy.get("name", "Unnamed"))
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        name_lbl.setStyleSheet(f"color:{txt};background:transparent;")

        active = self._strategy.get("active", True)
        _color = a if active else txts
        toggle = QPushButton("● Active" if active else "○ Inactive")
        toggle.setFixedHeight(24)
        toggle.setFont(font_scale.font(font_scale.SMALL, False))
        toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        toggle.setCheckable(True)
        toggle.setChecked(active)
        toggle.setStyleSheet(
            f"QPushButton{{background:transparent;color:{_color};"
            f"border:1px solid {_color}44;border-radius:4px;padding:0 8px;}}"
        )
        toggle.clicked.connect(self._on_toggle)
        self._toggle_btn = toggle

        top.addWidget(name_lbl)
        top.addStretch()
        top.addWidget(toggle)
        lay.addLayout(top)

        ncols  = len(self._strategy.get("columns", []))
        info   = QLabel(f"{ncols} column{'s' if ncols != 1 else ''}")
        info.setFont(font_scale.font(font_scale.SMALL, False))
        info.setStyleSheet(f"color:{txts};background:transparent;")
        lay.addWidget(info)

        act_row = QHBoxLayout()
        edit_btn = _btn("Edit", theme=t, small=True)
        del_btn  = _btn("Delete", theme=t, small=True, danger=True)
        edit_btn.clicked.connect(lambda: self.edit_requested.emit(self._strategy))
        del_btn.clicked.connect(lambda: self.delete_requested.emit(self._strategy["id"]))
        act_row.addWidget(edit_btn)
        act_row.addWidget(del_btn)
        act_row.addStretch()
        lay.addLayout(act_row)

    def _on_toggle(self, checked: bool):
        self._strategy["active"] = checked
        a    = _t(self._theme, "accent")
        txts = _t(self._theme, "text_secondary")
        c    = a if checked else txts
        self._toggle_btn.setText("● Active" if checked else "○ Inactive")
        self._toggle_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{c};"
            f"border:1px solid {c}44;border-radius:4px;padding:0 8px;}}"
        )
        self.toggled.emit(self._strategy["id"], checked)


# ── Strategy editor (right panel) ─────────────────────────────────────────

class StrategyEditor(QWidget):
    saved = Signal(dict)

    def __init__(self, strategy: dict, lmv_headers: list, theme=None, parent=None):
        super().__init__(parent)
        self._strategy    = copy.deepcopy(strategy)
        self._lmv_headers = lmv_headers
        self._theme       = theme
        self._build()

    def _build(self):
        t    = self._theme
        txts = _t(t, "text_secondary")

        root = QVBoxLayout(self)
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

        root.addWidget(_sep(t))

        col_hdr = QHBoxLayout()
        col_title = QLabel("Columns")
        col_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        add_col  = _btn("+ Add Column",  outlined=True, theme=t, small=True)
        save_btn = _btn("Save Strategy", accent=True,   theme=t, small=True)
        add_col.clicked.connect(self._add_column)
        save_btn.clicked.connect(self._save)
        col_hdr.addWidget(col_title)
        col_hdr.addStretch()
        col_hdr.addWidget(add_col)
        col_hdr.addSpacing(8)
        col_hdr.addWidget(save_btn)
        root.addLayout(col_hdr)

        is_dark = (t.current_mode == "dark") if t else True
        warn_bg  = "#9a670033" if is_dark else "#fef3c7"
        warn_txt = _t(t, "status_orange")
        warn_bdr = "#9a670066" if is_dark else "#d97706"
        self._warn_lbl = QLabel("⚠  Load Live Master View first — column names are needed to build formulas.")
        self._warn_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._warn_lbl.setStyleSheet(
            f"color:{warn_txt};background:{warn_bg};"
            f"border:1px solid {warn_bdr};border-radius:4px;padding:6px 10px;"
        )
        self._warn_lbl.setWordWrap(True)
        self._warn_lbl.setVisible(not self._lmv_headers)
        root.addWidget(self._warn_lbl)

        self._col_scroll  = QScrollArea()
        self._col_scroll.setWidgetResizable(True)
        self._col_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._col_inner   = QWidget()
        self._col_inner.setStyleSheet("background:transparent;")
        self._col_layout  = QVBoxLayout(self._col_inner)
        self._col_layout.setSpacing(8)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.addStretch()
        self._col_scroll.setWidget(self._col_inner)
        root.addWidget(self._col_scroll, 1)

        self._refresh_columns()

    def _add_column(self):
        col = store.new_column(f"Col{len(self._strategy['columns']) + 1}")
        dlg = ColumnEditorDialog(col, self._lmv_headers, self._theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["columns"].append(dlg.result_col())
            self._refresh_columns()

    def update_lmv_headers(self, headers: list):
        self._lmv_headers = list(headers)
        t = self._theme
        is_dark = (t.current_mode == "dark") if t else True
        warn_bg  = "#9a670033" if is_dark else "#fef3c7"
        warn_txt = _t(t, "status_orange")
        warn_bdr = "#9a670066" if is_dark else "#d97706"
        self._warn_lbl.setStyleSheet(
            f"color:{warn_txt};background:{warn_bg};"
            f"border:1px solid {warn_bdr};border-radius:4px;padding:6px 10px;"
        )
        self._warn_lbl.setVisible(not self._lmv_headers)

    def _edit_column(self, idx: int):
        col = self._strategy["columns"][idx]
        dlg = ColumnEditorDialog(col, self._lmv_headers, self._theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["columns"][idx] = dlg.result_col()
            self._refresh_columns()

    def _delete_column(self, idx: int):
        del self._strategy["columns"][idx]
        self._refresh_columns()

    def _refresh_columns(self):
        t    = self._theme
        bd   = _t(t, "border")
        bg   = _t(t, "button_bg")
        txt  = _t(t, "text_primary")
        txts = _t(t, "text_secondary")
        a    = _t(t, "accent")

        while self._col_layout.count() > 1:
            item = self._col_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, col in enumerate(self._strategy.get("columns", [])):
            row_frame = QFrame()
            row_frame.setStyleSheet(
                f"QFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"
            )
            row_lay = QVBoxLayout(row_frame)
            row_lay.setContentsMargins(12, 8, 12, 8)
            row_lay.setSpacing(4)

            # Top: name + actions
            top_row = QHBoxLayout()
            name_lbl = QLabel(col.get("name", f"Col{idx+1}"))
            name_lbl.setFont(font_scale.font(font_scale.SMALL, True))
            name_lbl.setStyleSheet(f"color:{txt};background:transparent;")

            nrules   = len(col.get("fmt_rules", []))
            rule_lbl = QLabel(f"{nrules} format rule{'s' if nrules != 1 else ''}")
            rule_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            rule_lbl.setStyleSheet(f"color:{txts};background:transparent;")

            edit_b = _btn("Edit", theme=t, small=True)
            del_b  = _btn("✕",   theme=t, small=True, danger=True)
            edit_b.setFixedWidth(50)
            del_b.setFixedWidth(30)
            edit_b.clicked.connect(lambda _, i=idx: self._edit_column(i))
            del_b.clicked.connect(lambda _, i=idx:  self._delete_column(i))

            top_row.addWidget(name_lbl)
            top_row.addSpacing(10)
            top_row.addWidget(rule_lbl)
            top_row.addStretch()
            top_row.addWidget(edit_b)
            top_row.addSpacing(4)
            top_row.addWidget(del_b)
            row_lay.addLayout(top_row)

            # Formula preview line
            formula_preview = QLabel(_tokens_to_display(col.get("formula", [])))
            formula_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            formula_preview.setStyleSheet(
                f"color:{a};background:transparent;border:none;"
                "padding:2px 4px;border-radius:3px;"
            )
            formula_preview.setWordWrap(True)
            row_lay.addWidget(formula_preview)

            self._col_layout.insertWidget(self._col_layout.count() - 1, row_frame)

    def _save(self):
        self._strategy["name"] = self._name_edit.text().strip() or "Untitled"
        self.saved.emit(copy.deepcopy(self._strategy))


# ── Main Strategy Builder screen ───────────────────────────────────────────

class StrategyBuilderScreen(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller          = controller
        self._theme               = controller.theme
        self._strategies: list    = store.load_all()
        self._lmv_headers: list   = []
        self._active_editor       = None
        self._build()

    def _build(self):
        t    = self._theme
        bd   = _t(t, "border")
        bg   = _t(t, "background")
        card = _t(t, "card_bg")
        txts = _t(t, "text_secondary")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Top bar ───────────────────────────────────────────────────────
        self._topbar = QFrame()
        self._topbar.setFixedHeight(56)
        self._topbar.setStyleSheet(
            f"QFrame{{background:{card};border-bottom:1px solid {bd};}}"
        )
        top_lay = QHBoxLayout(self._topbar)
        top_lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel("Strategy Builder")
        title.setFont(font_scale.font(font_scale.LARGE, True))

        self._lmv_warn = QLabel()
        self._lmv_warn.setFont(font_scale.font(font_scale.SMALL, False))
        self._update_lmv_warn()

        new_btn = _btn("+ New Strategy", accent=True, theme=t)
        new_btn.clicked.connect(self._new_strategy)
        self._new_btn = new_btn

        top_lay.addWidget(title)
        top_lay.addSpacing(16)
        top_lay.addWidget(self._lmv_warn)
        top_lay.addStretch()
        top_lay.addWidget(new_btn)
        root.addWidget(self._topbar)

        # ── Body ──────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left panel
        self._left_frame = QFrame()
        self._left_frame.setFixedWidth(260)
        self._left_frame.setStyleSheet(
            f"QFrame{{background:{card};border-right:1px solid {bd};}}"
        )
        left_root = QVBoxLayout(self._left_frame)
        left_root.setContentsMargins(12, 12, 12, 12)
        left_root.setSpacing(8)

        list_title = QLabel("Strategies")
        list_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        left_root.addWidget(list_title)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_inner  = QWidget()
        self._list_inner.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._list_inner)
        self._list_layout.setSpacing(8)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_inner)
        left_root.addWidget(self._list_scroll, 1)
        body.addWidget(self._left_frame)

        # Right panel
        self._right_frame = QFrame()
        self._right_frame.setStyleSheet(f"QFrame{{background:{bg};}}")
        right_root = QVBoxLayout(self._right_frame)
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

        body.addWidget(self._right_frame, 1)
        root.addLayout(body, 1)

        self._refresh_list()

    # ── Strategy list ─────────────────────────────────────────────────────

    def _refresh_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        if not self._strategies:
            empty = QLabel("No strategies yet.\nClick '+ New Strategy'.")
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._list_layout.insertWidget(0, empty)
            return

        for strat in self._strategies:
            card = StrategyCard(strat, self._theme, parent=self)
            card.edit_requested.connect(self._open_editor)
            card.delete_requested.connect(self._delete_strategy)
            card.toggled.connect(self._on_toggled)
            self._list_layout.insertWidget(self._list_layout.count() - 1, card)

    # ── Editor ────────────────────────────────────────────────────────────

    def _open_editor(self, strategy: dict):
        while self._editor_slot.count():
            item = self._editor_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        editor = StrategyEditor(strategy, self._lmv_headers, self._theme, self)
        editor.saved.connect(self._on_strategy_saved)
        self._editor_slot.addWidget(editor)
        self._active_editor = editor

        self._placeholder.hide()
        self._editor_container.show()

    def _new_strategy(self):
        strat = store.new_strategy("New Strategy")
        self._strategies.append(strat)
        self._refresh_list()
        self._open_editor(strat)

    def _delete_strategy(self, strategy_id: str):
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Strategy")
        msg.setText("Delete this strategy? This cannot be undone.")
        msg.setStandardButtons(
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        self._strategies = [s for s in self._strategies if s["id"] != strategy_id]
        store.delete_strategy(strategy_id)
        self._refresh_list()
        self._placeholder.show()
        self._editor_container.hide()
        self._active_editor = None

    def _on_strategy_saved(self, updated: dict):
        for i, s in enumerate(self._strategies):
            if s["id"] == updated["id"]:
                self._strategies[i] = updated
                break
        store.save_strategy(updated)
        self._refresh_list()

    def _on_toggled(self, strategy_id: str, active: bool):
        for s in self._strategies:
            if s["id"] == strategy_id:
                s["active"] = active
                store.save_strategy(s)
                break

    # ── LMV header injection ──────────────────────────────────────────────

    def set_lmv_headers(self, headers: list):
        self._lmv_headers = list(headers)
        self._update_lmv_warn()
        if self._active_editor is not None:
            self._active_editor.update_lmv_headers(self._lmv_headers)

    def _update_lmv_warn(self):
        t = self._theme
        if self._lmv_headers:
            self._lmv_warn.setText(f"✓ {len(self._lmv_headers)} LMV columns loaded")
            self._lmv_warn.setStyleSheet(f"color:{_t(t,'accent')};")
        else:
            self._lmv_warn.setText("LMV not loaded — open Live Master View first")
            self._lmv_warn.setStyleSheet(f"color:{_t(t,'status_orange')};")

    def get_active_strategies(self) -> list:
        return [s for s in self._strategies if s.get("active")]

    # ── Theme propagation ─────────────────────────────────────────────────

    def refresh_theme(self):
        t    = self._theme
        bd   = _t(t, "border")
        bg   = _t(t, "background")
        card = _t(t, "card_bg")
        txts = _t(t, "text_secondary")

        self._topbar.setStyleSheet(
            f"QFrame{{background:{card};border-bottom:1px solid {bd};}}"
        )
        self._left_frame.setStyleSheet(
            f"QFrame{{background:{card};border-right:1px solid {bd};}}"
        )
        self._right_frame.setStyleSheet(f"QFrame{{background:{bg};}}")
        self._placeholder.setStyleSheet(f"color:{txts};")
        _restyle_btn(self._new_btn, t, accent=True)
        self._update_lmv_warn()
        self._refresh_list()
        # Re-open editor with fresh theme if visible
        if self._editor_container.isVisible():
            self._editor_container.hide()
            self._placeholder.show()
            self._active_editor = None
