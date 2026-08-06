import font_scale
"""
Strategy Builder screen.
"""

import copy
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QLineEdit, QSizePolicy, QDialog,
    QColorDialog, QMessageBox, QApplication, QComboBox,
    QToolButton, QMenu, QSpinBox, QCheckBox
)
from PySide6.QtCore import Qt, Signal, QByteArray, QSize, QPointF
from PySide6.QtGui import QFont, QColor, QIcon, QPixmap, QPainter, QFontMetrics, QAction
from PySide6.QtSvg import QSvgRenderer

from services import strategy_store as store
from services.strategy_alerts import config_store as alerts_config_store
from services.strategy_alerts import models as alerts_models
from services.strategy_alerts import state_store as alerts_state_store
from screens.notifications import ToggleSwitch

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")


def _svg_icon(filename: str, color: str) -> QIcon:
    """Load an assets/icons/*.svg file, recolored to match the current theme
    (the on-disk files are all fill="#000000" placeholders — see the same
    pattern in components/sidebar.py and components/topbar.py). Text glyphs
    like "▲"/"▼"/"ⓘ" render as missing-glyph boxes on some platforms/fonts,
    so buttons that need an icon use this instead of a Unicode character."""
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


# ── theme helpers — always read at call-time so toggling works ─────────────

def _t(theme, key: str) -> str:
    """Read a theme token; return a safe fallback if theme is None."""
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "accent_hover": "#2ea043",
        "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "input_bg": "#0d1117",
        "divider": "#2a2f36", "destructive": "#da3633",
        "status_orange": "#e3b341", "status_blue": "#58a6ff",
        "status_purple": "#a371f7", "status_pink": "#f778ba",
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


# A distinct accent per built-in category so the sidebar reads as organized
# at a glance rather than a flat list — reuses the theme's existing
# qualitative status colors instead of inventing new ones. Custom
# user-added categories (services.strategy_store.add_custom_category) fall
# back to a neutral color via _category_color's .get() default below.
_CATEGORY_COLOR_TOKENS = {
    "Daily": "status_blue", "Weekly": "status_purple",
    "Monthly": "status_orange", "Common": "status_pink",
}


def _category_color(theme, category: str) -> str:
    return _t(theme, _CATEGORY_COLOR_TOKENS.get(category, "text_secondary"))


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
            days_arg = tok.get("days_arg")
            if days_arg is not None:
                parts.append(f"{fname}({col_arg}, {days_arg})")
            elif fname.endswith("_ALL"):
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
    def __init__(self, col_def: dict, lmv_headers: list, theme=None,
                 lmv_first_row: dict = None, all_lmv_data: list = None, parent=None):
        super().__init__(parent)
        self._col           = copy.deepcopy(col_def)
        self._lmv           = lmv_headers
        self._theme         = theme
        self._lmv_first_row = lmv_first_row or {}
        self._all_lmv_data  = all_lmv_data or []
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
        formula_row = QHBoxLayout()
        flbl = QLabel("Formula (value):")
        flbl.setFont(font_scale.font(font_scale.SMALL, True))
        flbl.setFixedWidth(130)

        self._formula_preview = QLabel(_tokens_to_display(self._col.get("formula", [])) or "—")
        self._formula_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._formula_preview.setStyleSheet(
            f"color:{_t(t,'accent')};background:transparent;border:none;"
        )
        self._formula_preview.setWordWrap(True)

        edit_formula_btn = _btn("Edit Formula…", outlined=True, theme=t, small=True)
        edit_formula_btn.clicked.connect(self._open_formula_editor)
        formula_row.addWidget(flbl)
        formula_row.addWidget(self._formula_preview, 1)
        formula_row.addWidget(edit_formula_btn)
        root.addLayout(formula_row)

        root.addWidget(_sep(t))

        # Conditional formatting
        fmt_hdr = QHBoxLayout()
        fmt_lbl = QLabel("Conditional Formatting:")
        fmt_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        help_btn = QPushButton()
        help_btn.setIcon(_svg_icon("info.svg", _t(t, "accent")))
        help_btn.setIconSize(QSize(14, 14))
        help_btn.setFixedSize(22, 22)
        help_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        help_btn.setToolTip("How rule priority works")
        help_btn.setStyleSheet(
            f"QPushButton{{background:transparent;"
            f"border:1px solid {_t(t,'accent')};border-radius:11px;}}"
            f"QPushButton:hover{{background:{_t(t,'accent')}22;}}"
        )
        help_btn.clicked.connect(self._show_fmt_rules_help)
        add_rule = _btn("+ Add Rule", theme=t, small=True)
        add_rule.clicked.connect(self._add_fmt_rule)
        fmt_hdr.addWidget(fmt_lbl)
        fmt_hdr.addWidget(help_btn)
        fmt_hdr.addStretch()
        fmt_hdr.addWidget(add_rule)
        root.addLayout(fmt_hdr)

        hint = QLabel(
            "Rules are checked top to bottom — the first one whose condition is true "
            "wins, and the rest are skipped for that row. Use the ▲ / ▼ buttons to "
            "reorder them (click ⓘ above for an example). Use THIS to reference this "
            "column's own value. \"Apply color to\" picks which LMV column gets "
            "painted — defaults to this column."
        )
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color:{txts};background:transparent;")
        hint.setWordWrap(True)
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

    def _open_formula_editor(self):
        from screens.formula_editor import ExpressionEditorDialog
        dlg = ExpressionEditorDialog(
            tokens=list(self._col.get("formula", [])),
            lmv_headers=self._lmv,
            strategy_col_headers=[],
            lmv_first_row=self._lmv_first_row,
            all_lmv_data=self._all_lmv_data,
            theme=self._theme,
            mode="value",
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._col["formula"] = dlg.get_tokens()
            self._formula_preview.setText(
                _tokens_to_display(self._col["formula"]) or "—"
            )

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

    def _show_fmt_rules_help(self):
        QMessageBox.information(
            self, "How rule priority works",
            "<p>Rules are checked <b>top to bottom</b>. The first rule whose "
            "condition is true is the one that colors the cell — every rule "
            "below it is skipped for that row, even if their conditions are "
            "also true.</p>"
            "<p><b>Example:</b><br>"
            "Rule 1: THIS &gt; 100 &rarr; Green<br>"
            "Rule 2: THIS &gt; 50 &rarr; Red</p>"
            "<p>For a value of 150, both conditions are true — but the cell "
            "turns <b>Green</b>, because Rule 1 is checked first and Red is "
            "never reached.</p>"
            "<p>Use the <b>▲ / ▼</b> buttons on each rule to reorder them — "
            "move a rule up to give it higher priority.</p>",
        )

    def _refresh_fmt_rules(self):
        t  = self._theme
        bg = _t(t, "button_bg")
        bd = _t(t, "border")

        while self._fmt_layout.count() > 1:
            item = self._fmt_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = self._col.get("fmt_rules", [])
        for idx, rule in enumerate(rules):
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

            up_btn = _btn("", theme=t, small=True)
            up_btn.setIcon(_svg_icon("up.svg", _t(t, "text_primary")))
            up_btn.setIconSize(QSize(12, 12))
            up_btn.setFixedWidth(28)
            up_btn.setToolTip("Move up (higher priority)")
            up_btn.setEnabled(idx > 0)
            up_btn.clicked.connect(lambda _, i=idx: self._move_fmt_rule(i, -1))

            down_btn = _btn("", theme=t, small=True)
            down_btn.setIcon(_svg_icon("down.svg", _t(t, "text_primary")))
            down_btn.setIconSize(QSize(12, 12))
            down_btn.setFixedWidth(28)
            down_btn.setToolTip("Move down (lower priority)")
            down_btn.setEnabled(idx < len(rules) - 1)
            down_btn.clicked.connect(lambda _, i=idx: self._move_fmt_rule(i, 1))

            del_btn = _btn("✕", theme=t, small=True, danger=True)
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, i=idx: self._remove_fmt_rule(i))

            color_lbl = QLabel("Color:")
            color_lbl.setStyleSheet("background:transparent;")
            hdr.addWidget(color_lbl)
            hdr.addWidget(color_btn)
            hdr.addSpacing(8)
            hdr.addWidget(up_btn)
            hdr.addWidget(down_btn)
            hdr.addSpacing(8)
            hdr.addWidget(del_btn)
            rlay.addLayout(hdr)

            # Which column this rule's color paints onto when it matches —
            # defaults to this strategy column's own cell (None), but any
            # LMV column can be picked instead (see services.strategy_store's
            # fmt_rule "target_column"). The condition itself is unaffected —
            # THIS in "Edit Condition…" still means this column's own value.
            target_row = QHBoxLayout()
            target_lbl = QLabel("Apply color to:")
            target_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            target_lbl.setStyleSheet("background:transparent;")
            target_lbl.setMinimumWidth(110)

            target_combo = QComboBox()
            current_target = rule.get("target_column")
            target_options = ["(This column)"] + list(self._lmv)
            if current_target and current_target not in target_options:
                target_options.append(current_target)
            target_combo.addItems(target_options)
            target_combo.setCurrentText(current_target or "(This column)")
            target_combo.currentTextChanged.connect(
                lambda text, i=idx: self._set_fmt_target(i, text)
            )
            target_row.addWidget(target_lbl)
            target_row.addWidget(target_combo, 1)
            rlay.addLayout(target_row)

            cond_row = QHBoxLayout()
            cond_lbl = QLabel("Condition:")
            cond_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            cond_lbl.setStyleSheet("background:transparent;")
            cond_lbl.setMinimumWidth(110)

            cond_preview = QLabel(
                _tokens_to_display(rule.get("condition", [])) or "—"
            )
            cond_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            cond_preview.setStyleSheet(
                f"color:{_t(t,'accent')};background:transparent;border:none;"
            )
            cond_preview.setWordWrap(True)

            edit_cond_btn = _btn("Edit Condition…", outlined=True, theme=t, small=True)
            edit_cond_btn.clicked.connect(
                lambda _, i=idx, lbl=cond_preview: self._open_condition_editor(i, lbl)
            )
            cond_row.addWidget(cond_lbl)
            cond_row.addWidget(cond_preview, 1)
            cond_row.addWidget(edit_cond_btn)
            rlay.addLayout(cond_row)
            self._fmt_layout.insertWidget(self._fmt_layout.count() - 1, rule_frame)

    def _open_condition_editor(self, idx: int, preview_label: QLabel):
        from screens.formula_editor import ExpressionEditorDialog
        from services.strategy_engine import evaluate
        from PySide6.QtWidgets import QDialog as _QD
        rule = self._col["fmt_rules"][idx]
        # THIS in a condition refers to this column's own computed value.
        # Evaluate the column's value formula on the first row so the compile
        # test can resolve THIS.
        self_value = evaluate(self._col.get("formula", []),
                              self._lmv_first_row, self._all_lmv_data)
        dlg = ExpressionEditorDialog(
            tokens=list(rule.get("condition", [])),
            lmv_headers=self._lmv,
            strategy_col_headers=[],
            lmv_first_row=self._lmv_first_row,
            all_lmv_data=self._all_lmv_data,
            theme=self._theme,
            mode="condition",
            self_value=self_value,
            parent=self,
        )
        if dlg.exec() == _QD.DialogCode.Accepted:
            self._col["fmt_rules"][idx]["condition"] = dlg.get_tokens()
            preview_label.setText(
                _tokens_to_display(self._col["fmt_rules"][idx]["condition"]) or "—"
            )

    def _set_fmt_target(self, idx: int, text: str):
        self._col["fmt_rules"][idx]["target_column"] = None if text == "(This column)" else text

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
        self._col["name"] = self._name_edit.text().strip()
        # formula is already updated in-place by _open_formula_editor
        return self._col


# ── Strategy card ──────────────────────────────────────────────────────────

class _KebabButton(QToolButton):
    """A "⋯" overflow-menu trigger, painted as three dots rather than set as
    button text — a Unicode ellipsis/dot glyph is exactly the kind of thing
    that renders at a different width (or as a missing-glyph box) depending
    on the platform's default font, which is what made the old text-based
    Active/Inactive toggle button silently push itself off the edge of the
    fixed-width sidebar on Windows while still fitting on macOS. A
    fixed-size, self-painted control sidesteps that whole class of bug."""

    def __init__(self, color: str, parent=None):
        super().__init__(parent)
        self._dot_color = color
        self._menu = None
        self.setFixedSize(26, 26)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setToolTip("More actions")
        # Without this, native styles (e.g. macOS) still paint a raised-button
        # bevel/frame around a QToolButton regardless of a border:none QSS
        # rule — autoRaise is what actually makes it a flat icon button.
        self.setAutoRaise(True)
        self._apply_style(hovered=False)
        self.setAttribute(Qt.WidgetAttribute.WA_Hover, True)
        # setMenu()+ToolButtonPopupMode renders as a native split/dropdown
        # button on some platforms (macOS draws a divider next to the arrow
        # area that QSS can't fully suppress) — showing the menu manually on
        # click keeps this a plain icon button everywhere instead.
        self.clicked.connect(self._show_menu)

    def set_menu(self, menu: QMenu):
        self._menu = menu

    def _show_menu(self):
        if self._menu is not None:
            self._menu.exec(self.mapToGlobal(self.rect().bottomRight()))

    def _apply_style(self, hovered: bool):
        bg = "rgba(128,128,128,0.18)" if hovered else "transparent"
        self.setStyleSheet(
            f"QToolButton{{background:{bg};border:none;border-radius:5px;}}"
            "QToolButton::menu-indicator{width:0px;image:none;}"
        )

    def enterEvent(self, event):
        self._apply_style(hovered=True)
        super().enterEvent(event)

    def leaveEvent(self, event):
        self._apply_style(hovered=False)
        super().leaveEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self._dot_color))
        cx, cy = self.width() / 2, self.height() / 2
        for dy in (-5.5, 0, 5.5):
            p.drawEllipse(QPointF(cx, cy + dy), 1.6, 1.6)
        p.end()


class _CardText(QWidget):
    """Draws single-line, left-aligned, vertically-centered text directly via
    QPainter instead of using a QLabel.

    QLabel — even with an explicit opaque background, zero frame width, and
    with border-radius and native (non-Fusion) styling both ruled out —
    consistently left a stray 1px vertical line at its right edge, but only
    in this exact context (a fixed-width sidebar next to a stretching
    sibling, inside a real top-level window). Every custom-painted widget
    already in this file (ToggleSwitch, _KebabButton) is unaffected, so text
    is drawn directly here rather than chasing the underlying Qt/macOS
    rendering quirk further."""

    def __init__(self, text: str, font: QFont, color: str, parent=None):
        super().__init__(parent)
        self._text = text
        self._color = QColor(color)
        self.setFont(font)
        fm = QFontMetrics(font)
        self.setFixedHeight(fm.height() + 2)

    def sizeHint(self) -> QSize:
        fm = QFontMetrics(self.font())
        return QSize(fm.horizontalAdvance(self._text), fm.height() + 2)

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        p.setPen(self._color)
        p.drawText(self.rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, self._text)
        p.end()


class StrategyCard(QFrame):
    edit_requested   = Signal(dict)
    clone_requested  = Signal(dict)
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
        bd   = _t(t, "border")
        bg   = _t(t, "card_bg")
        accent = _t(t, "accent")

        self.setStyleSheet(
            f"QFrame#stratCard{{background:{bg};border:1px solid {bd};border-radius:8px;}}"
            f"QFrame#stratCard:hover{{border-color:{accent};}}"
        )

        lay = QVBoxLayout(self)
        lay.setContentsMargins(12, 10, 8, 10)
        lay.setSpacing(6)

        # Row 1: name (elided so it can never force the row wider than the
        # sidebar) + an overflow menu for Edit/Clone/Delete — a single
        # fixed-size icon button instead of three text buttons means this
        # row's width no longer depends on how wide "Edit"/"Clone"/"Delete"
        # happen to render on a given platform's font.
        top = QHBoxLayout()
        top.setSpacing(4)

        name = self._strategy.get("name", "Unnamed")
        name_font = font_scale.font(font_scale.MEDIUM, True)
        elided = QFontMetrics(name_font).elidedText(name, Qt.TextElideMode.ElideRight, 175)
        name_lbl = _CardText(elided, name_font, txt, parent=self)
        if elided != name:
            name_lbl.setToolTip(name)
        top.addWidget(name_lbl, 1)

        kebab = _KebabButton(txts, parent=self)
        menu = QMenu(self)
        menu.setFont(font_scale.font(font_scale.SMALL, False))
        # On macOS, QMenu renders via a native, vibrancy-blurred NSMenu that
        # ignores the app's global QSS unless it's given its own stylesheet
        # (that's what pushes Qt to draw the menu itself instead) — without
        # this it showed up washed-out/translucent with barely-legible text.
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        menu.setStyleSheet(
            f"QMenu{{background-color:{bg};color:{txt};border:1px solid {bd};"
            "border-radius:6px;padding:4px;}"
            f"QMenu::item{{padding:6px 24px 6px 12px;border-radius:4px;}}"
            f"QMenu::item:selected{{background:{accent};color:{_t(t,'background')};}}"
            f"QMenu::separator{{height:1px;background:{bd};margin:4px 6px;}}"
        )
        edit_action = QAction("Edit", menu)
        edit_action.triggered.connect(lambda: self.edit_requested.emit(self._strategy))
        clone_action = QAction("Clone", menu)
        clone_action.triggered.connect(lambda: self.clone_requested.emit(self._strategy))
        del_action = QAction("Delete", menu)
        del_action.triggered.connect(lambda: self.delete_requested.emit(self._strategy["id"]))
        menu.addAction(edit_action)
        menu.addAction(clone_action)
        menu.addSeparator()
        menu.addAction(del_action)
        kebab.set_menu(menu)
        top.addWidget(kebab)
        lay.addLayout(top)

        # Row 2: column count on the left, the Active/Inactive toggle on the
        # right. No category badge here — the card already lives inside that
        # category's own collapsible section (see _CategorySection), so
        # repeating "Daily"/"Weekly"/etc. on every single card was redundant.
        meta = QHBoxLayout()
        meta.setSpacing(8)

        ncols = len(self._strategy.get("columns", []))
        info_font = font_scale.font(font_scale.SMALL, False)
        info = _CardText(f"{ncols} column{'s' if ncols != 1 else ''}", info_font, txts, parent=self)
        meta.addWidget(info)

        meta.addStretch()

        active = self._strategy.get("active", True)
        self._toggle = ToggleSwitch(active, parent=self)
        self._toggle.toggled.connect(self._on_toggle)
        meta.addWidget(self._toggle)
        lay.addLayout(meta)

    def _on_toggle(self, checked: bool):
        self._strategy["active"] = checked
        self.toggled.emit(self._strategy["id"], checked)


# ── Category section (collapsible group in the sidebar list) ───────────────

class _CategorySection(QWidget):
    """One collapsible category group in the Strategies sidebar — a header
    ("DAILY (6)") the user can click to collapse/expand, plus the cards
    underneath it. Grouping by category (instead of one flat list) is what
    keeps a sidebar with dozens of strategies scannable."""

    toggled = Signal(str, bool)   # category, expanded

    def __init__(self, category: str, count: int, theme, expanded: bool, parent=None):
        super().__init__(parent)
        self._category = category
        self._theme = theme
        self._expanded = expanded

        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(6)

        self._color = _category_color(theme, category)
        header = QToolButton()
        header.setAutoRaise(True)
        header.setCursor(Qt.CursorShape.PointingHandCursor)
        header.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        header.setFont(font_scale.font(font_scale.SMALL, True))
        header.setStyleSheet(
            f"QToolButton{{background:transparent;border:none;color:{self._color};padding:2px 0;}}"
        )
        header.setIconSize(QSize(10, 10))
        header.clicked.connect(self._on_header_clicked)
        self._header = header
        self._set_header_text(count)
        lay.addWidget(header)

        self._body = QWidget()
        self._body_layout = QVBoxLayout(self._body)
        self._body_layout.setContentsMargins(0, 0, 0, 0)
        self._body_layout.setSpacing(8)
        self._body.setVisible(expanded)
        lay.addWidget(self._body)

    def _set_header_text(self, count: int):
        self._header.setIcon(_svg_icon("down.svg" if self._expanded else "up.svg", self._color))
        self._header.setText(f" {self._category.upper()}  ({count})")

    def _on_header_clicked(self):
        self._expanded = not self._expanded
        self._body.setVisible(self._expanded)
        self._set_header_text(self._body_layout.count())
        self.toggled.emit(self._category, self._expanded)

    def add_card(self, card: QWidget):
        self._body_layout.addWidget(card)


# ── Add-category dialog ─────────────────────────────────────────────────────

_ADD_CATEGORY_SENTINEL = "+ Add New Category…"


class _AddCategoryDialog(QDialog):
    """Also reused for renaming a category (ManageCategoriesDialog passes
    a different title/initial_text/action_label) rather than duplicating
    this same name-prompt layout a second time."""

    def __init__(self, theme, parent=None, title="Add Category",
                 initial_text="", action_label="Add"):
        super().__init__(parent)
        self.setWindowTitle(title)
        _apply_dialog_bg(self, theme)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl = QLabel("CATEGORY NAME")
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color:{_t(theme, 'text_secondary')};")
        layout.addWidget(lbl)

        self._name_edit = QLineEdit(initial_text)
        self._name_edit.setPlaceholderText("e.g. Intraday")
        self._name_edit.setFixedHeight(38)
        self._name_edit.setFont(font_scale.font(font_scale.MEDIUM, False))
        layout.addWidget(self._name_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        add_btn = QPushButton(action_label)
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        add_btn.setStyleSheet(
            f"background:{_t(theme,'accent')};color:{_t(theme,'background')};border:none;"
        )
        add_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(add_btn)
        layout.addLayout(btn_row)

    def category_name(self) -> str:
        return self._name_edit.text().strip()


class ManageCategoriesDialog(QDialog):
    """Rename/delete user-added categories — opened from the app's Edit menu
    (see components/topbar.py, app_window.py). Built-in categories
    (Daily/Weekly/Monthly/Common) aren't listed here at all: they're
    structural (e.g. every new strategy defaults to Daily), so renaming or
    deleting them isn't offered rather than needing extra guardrails for it.
    Deleting a category never deletes its strategies — they're reassigned to
    services.strategy_store.UNDEFINED_CATEGORY (see strategy_store.
    delete_custom_category) so nothing silently disappears."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Manage Categories")
        self.resize(420, 360)
        _apply_dialog_bg(self, theme)
        self._theme = theme
        self._build()

    def _build(self):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        info = QLabel(
            "Built-in categories (Daily/Weekly/Monthly/Common) can't be "
            "renamed or deleted. Deleting a category moves its strategies "
            "to “Undefined” instead of deleting them."
        )
        info.setWordWrap(True)
        info.setFont(font_scale.font(font_scale.SMALL, False))
        info.setStyleSheet(f"color:{_t(t, 'text_secondary')};")
        layout.addWidget(info)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_inner = QWidget()
        self._list_layout = QVBoxLayout(self._list_inner)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.setSpacing(8)
        self._list_layout.addStretch()
        self._scroll.setWidget(self._list_inner)
        layout.addWidget(self._scroll, 1)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.accept)
        btn_row.addWidget(close_btn)
        layout.addLayout(btn_row)

        self._refresh_rows()

    def _refresh_rows(self):
        from services import strategy_store as store

        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

        categories = store.load_custom_categories()
        if not categories:
            empty = QLabel("No custom categories yet.")
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setStyleSheet(f"color:{_t(self._theme, 'text_secondary')};")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            self._list_layout.insertWidget(0, empty)
            return

        for cat in categories:
            self._list_layout.insertWidget(self._list_layout.count() - 1, self._make_row(cat))

    def _make_row(self, category: str) -> QFrame:
        t = self._theme
        row = QFrame()
        row.setObjectName("stratCard")
        row.setStyleSheet(
            f"QFrame#stratCard{{background:{_t(t,'card_bg')};"
            f"border:1px solid {_t(t,'border')};border-radius:6px;}}"
        )
        lay = QHBoxLayout(row)
        lay.setContentsMargins(12, 8, 8, 8)

        name_lbl = QLabel(category)
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        lay.addWidget(name_lbl, 1)

        rename_btn = _btn("Rename", theme=t, small=True)
        rename_btn.clicked.connect(lambda: self._rename(category))
        lay.addWidget(rename_btn)

        del_btn = _btn("Delete", theme=t, small=True, danger=True)
        del_btn.clicked.connect(lambda: self._delete(category))
        lay.addWidget(del_btn)

        return row

    def _rename(self, category: str):
        from services import strategy_store as store

        dlg = _AddCategoryDialog(
            self._theme, parent=self, title="Rename Category",
            initial_text=category, action_label="Rename",
        )
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_name = dlg.category_name()
        if new_name:
            store.rename_custom_category(category, new_name)
            self._refresh_rows()

    def _delete(self, category: str):
        from services import strategy_store as store

        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Category")
        msg.setText(
            f"Delete “{category}”? Any strategies filed under it will "
            f"move to “{store.UNDEFINED_CATEGORY}”, not be deleted."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        store.delete_custom_category(category)
        self._refresh_rows()


# ── Strategy editor (right panel) ─────────────────────────────────────────

# ── Notification section ────────────────────────────────────────────────────

class NotificationSection(QWidget):
    """Inline (non-modal) block inside StrategyEditor: configures when this
    strategy should fire a trade-signal notification (entry alert, then
    Target/Stop Loss/Trailing Exit lifecycle tracking — see
    services/strategy_alerts). Mutates *config* in place; StrategyEditor
    persists it via services.strategy_alerts.config_store on Save, separately
    from services.strategy_store.save_strategy — a notification config never
    touches strategies.json or the strategies backend sync.
    """

    def __init__(self, config: dict, strategy: dict, theme, combined_headers_fn,
                 lmv_first_row: dict, all_lmv_data: list, parent=None):
        super().__init__(parent)
        self._config = config
        self._strategy = strategy
        self._theme = theme
        self._combined_headers_fn = combined_headers_fn
        self._lmv_first_row = lmv_first_row
        self._all_lmv_data = all_lmv_data
        self._build()

    def result_config(self) -> dict:
        return self._config

    def update_lmv_data(self, first_row: dict, all_data: list):
        self._lmv_first_row = first_row
        self._all_lmv_data = all_data

    def _build(self):
        t = self._theme
        txts = _t(t, "text_secondary")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(10)

        hdr = QHBoxLayout()
        title = QLabel("Notifications")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        enabled_lbl = QLabel("Enabled")
        enabled_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._enabled_toggle = ToggleSwitch(bool(self._config.get("enabled")))
        self._enabled_toggle.toggled.connect(lambda v: self._config.update({"enabled": v}))
        hdr.addWidget(title)
        hdr.addStretch()
        hdr.addWidget(enabled_lbl)
        hdr.addWidget(self._enabled_toggle)
        root.addLayout(hdr)

        info = QLabel(
            "Fires an entry alert when the trigger condition holds continuously "
            "for the debounce window (to avoid false breakouts), then tracks "
            "Target / Stop Loss / Trailing Exit crossings until the signal "
            "resolves. Delivered via whichever channels are enabled on the "
            "Notifications screen."
        )
        info.setFont(font_scale.font(font_scale.SMALL, False))
        info.setStyleSheet(f"color:{txts};")
        info.setWordWrap(True)
        root.addWidget(info)

        # ── Direction ────────────────────────────────────────────────────
        dir_row = QHBoxLayout()
        dir_lbl = QLabel("Direction:")
        dir_lbl.setFixedWidth(140)
        self._direction_combo = QComboBox()
        self._direction_combo.addItems([alerts_models.DIRECTION_BUY, alerts_models.DIRECTION_SELL])
        self._direction_combo.setCurrentText(
            self._config.get("direction", alerts_models.DIRECTION_BUY)
        )
        self._direction_combo.currentTextChanged.connect(
            lambda v: self._config.update({"direction": v})
        )
        dir_row.addWidget(dir_lbl)
        dir_row.addWidget(self._direction_combo)
        dir_row.addStretch()
        root.addLayout(dir_row)

        # ── Trigger condition ────────────────────────────────────────────
        # Deliberately a single standalone condition, not "pick one column's
        # existing conditional-formatting rule": a strategy can have several
        # columns, and conditional formatting is inherently per-column, so
        # there's no one well-defined "the strategy's rule" to point at. This
        # condition can reference any/all of the strategy's columns via the
        # same combined-headers picker the row filter and metrics use.
        root.addWidget(_sep(t))
        trig_title = QLabel("Trigger Condition")
        trig_title.setFont(font_scale.font(font_scale.SMALL, True))
        root.addWidget(trig_title)

        self._config.setdefault("trigger_condition", [])

        cond_row = QHBoxLayout()
        cond_lbl = QLabel("Condition:")
        cond_lbl.setFixedWidth(140)
        self._trigger_preview = QLabel(
            _tokens_to_display(self._config.get("trigger_condition", []))
        )
        self._trigger_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._trigger_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;")
        self._trigger_preview.setWordWrap(True)
        edit_trigger_btn = _btn("Edit Condition…", outlined=True, theme=t, small=True)
        edit_trigger_btn.clicked.connect(self._open_trigger_condition_editor)
        cond_row.addWidget(cond_lbl)
        cond_row.addWidget(self._trigger_preview, 1)
        cond_row.addWidget(edit_trigger_btn)
        root.addLayout(cond_row)

        # ── Debounce ─────────────────────────────────────────────────────
        root.addWidget(_sep(t))
        deb_row = QHBoxLayout()
        deb_lbl = QLabel("Debounce (minutes):")
        deb_lbl.setFixedWidth(140)
        self._debounce_spin = QSpinBox()
        self._debounce_spin.setRange(0, 60)
        self._debounce_spin.setValue(int(self._config.get("debounce_minutes", 2)))
        self._debounce_spin.valueChanged.connect(
            lambda v: self._config.update({"debounce_minutes": v})
        )
        deb_row.addWidget(deb_lbl)
        deb_row.addWidget(self._debounce_spin)
        deb_row.addStretch()
        root.addLayout(deb_row)

        # ── Score ────────────────────────────────────────────────────────
        score_row = QHBoxLayout()
        score_lbl = QLabel("Strength/Weakness Score:")
        score_lbl.setFixedWidth(140)
        self._score_edit = QLineEdit(
            "" if self._config.get("score") is None else str(self._config["score"])
        )
        self._score_edit.setPlaceholderText("optional constant")
        self._score_edit.setFixedHeight(30)
        self._score_edit.textChanged.connect(self._on_score_changed)
        score_row.addWidget(score_lbl)
        score_row.addWidget(self._score_edit)
        root.addLayout(score_row)

        # ── Risk:Reward ──────────────────────────────────────────────────
        root.addWidget(_sep(t))
        rr_hdr = QHBoxLayout()
        rr_title = QLabel("Risk : Reward")
        rr_title.setFont(font_scale.font(font_scale.SMALL, True))
        self._rr_enabled_check = QCheckBox("Enabled")
        self._rr_enabled_check.setChecked(self._config.get("risk_reward") is not None)
        self._rr_enabled_check.toggled.connect(self._on_rr_enabled_toggled)
        rr_hdr.addWidget(rr_title)
        rr_hdr.addStretch()
        rr_hdr.addWidget(self._rr_enabled_check)
        root.addLayout(rr_hdr)

        self._rr_widget = QWidget()
        rr_lay = QVBoxLayout(self._rr_widget)
        rr_lay.setContentsMargins(0, 0, 0, 0)
        rr_lay.setSpacing(6)

        num_row = QHBoxLayout()
        num_lbl = QLabel("Numerator:")
        num_lbl.setFixedWidth(140)
        self._rr_num_preview = QLabel()
        self._rr_num_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._rr_num_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;")
        self._rr_num_preview.setWordWrap(True)
        num_btn = _btn("Edit Formula…", outlined=True, theme=t, small=True)
        num_btn.clicked.connect(lambda: self._open_rr_formula_editor("numerator", self._rr_num_preview))
        num_row.addWidget(num_lbl)
        num_row.addWidget(self._rr_num_preview, 1)
        num_row.addWidget(num_btn)
        rr_lay.addLayout(num_row)

        den_row = QHBoxLayout()
        den_lbl = QLabel("Denominator:")
        den_lbl.setFixedWidth(140)
        self._rr_den_preview = QLabel()
        self._rr_den_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._rr_den_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;")
        self._rr_den_preview.setWordWrap(True)
        den_btn = _btn("Edit Formula…", outlined=True, theme=t, small=True)
        den_btn.clicked.connect(lambda: self._open_rr_formula_editor("denominator", self._rr_den_preview))
        den_row.addWidget(den_lbl)
        den_row.addWidget(self._rr_den_preview, 1)
        den_row.addWidget(den_btn)
        rr_lay.addLayout(den_row)

        root.addWidget(self._rr_widget)
        self._refresh_rr_previews()
        self._rr_widget.setVisible(self._config.get("risk_reward") is not None)

        # ── Metrics ──────────────────────────────────────────────────────
        root.addWidget(_sep(t))
        metrics_hdr = QHBoxLayout()
        metrics_title = QLabel("Metrics  (Stop Loss / Target / Trailing Exit / Informational)")
        metrics_title.setFont(font_scale.font(font_scale.SMALL, True))
        add_metric_btn = _btn("+ Add Metric", outlined=True, theme=t, small=True)
        add_metric_btn.clicked.connect(self._add_metric)
        metrics_hdr.addWidget(metrics_title)
        metrics_hdr.addStretch()
        metrics_hdr.addWidget(add_metric_btn)
        root.addLayout(metrics_hdr)

        # No nested QScrollArea here — this list lives inside StrategyEditor's
        # single page-level scroll area (see StrategyEditor._build), so it
        # just flows as normal content instead of getting its own cramped,
        # fixed-height inner scrollbar on top of the outer one.
        self._metrics_inner = QWidget()
        self._metrics_inner.setStyleSheet("background:transparent;")
        self._metrics_layout = QVBoxLayout(self._metrics_inner)
        self._metrics_layout.setSpacing(8)
        self._metrics_layout.setContentsMargins(0, 0, 0, 0)
        self._metrics_layout.addStretch()
        root.addWidget(self._metrics_inner)

        self._refresh_metrics()

    # ── Trigger ──────────────────────────────────────────────────────────

    def _open_trigger_condition_editor(self):
        from screens.formula_editor import ExpressionEditorDialog
        headers, extra_values = self._combined_headers_fn()
        dlg = ExpressionEditorDialog(
            tokens=list(self._config.get("trigger_condition", [])),
            lmv_headers=headers, strategy_col_headers=[],
            lmv_first_row=self._lmv_first_row, all_lmv_data=self._all_lmv_data,
            theme=self._theme, mode="condition", allow_self=False,
            extra_row_values=extra_values, parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._config["trigger_condition"] = dlg.get_tokens()
            self._trigger_preview.setText(
                _tokens_to_display(self._config["trigger_condition"]) or "—"
            )

    # ── Score ────────────────────────────────────────────────────────────

    def _on_score_changed(self, text: str):
        text = text.strip()
        if not text:
            self._config["score"] = None
            return
        try:
            self._config["score"] = float(text)
        except ValueError:
            pass  # leave the last valid value until the text parses again

    # ── Risk:Reward ──────────────────────────────────────────────────────

    def _on_rr_enabled_toggled(self, checked: bool):
        if checked:
            self._config["risk_reward"] = self._config.get("risk_reward") or {
                "numerator": [], "denominator": [],
            }
        else:
            self._config["risk_reward"] = None
        self._rr_widget.setVisible(checked)
        self._refresh_rr_previews()

    def _refresh_rr_previews(self):
        rr = self._config.get("risk_reward") or {"numerator": [], "denominator": []}
        self._rr_num_preview.setText(_tokens_to_display(rr.get("numerator", [])) or "—")
        self._rr_den_preview.setText(_tokens_to_display(rr.get("denominator", [])) or "—")

    def _open_rr_formula_editor(self, key: str, preview_label: QLabel):
        from screens.formula_editor import ExpressionEditorDialog
        headers, extra_values = self._combined_headers_fn()
        rr = self._config.setdefault("risk_reward", {"numerator": [], "denominator": []})
        dlg = ExpressionEditorDialog(
            tokens=list(rr.get(key, [])),
            lmv_headers=headers, strategy_col_headers=[],
            lmv_first_row=self._lmv_first_row, all_lmv_data=self._all_lmv_data,
            theme=self._theme, mode="value", extra_row_values=extra_values, parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            rr[key] = dlg.get_tokens()
            preview_label.setText(_tokens_to_display(rr[key]) or "—")

    # ── Metrics ──────────────────────────────────────────────────────────

    def _add_metric(self):
        self._config["metrics"].append(
            alerts_models.new_metric(f"Metric {len(self._config['metrics']) + 1}")
        )
        self._refresh_metrics()

    def _delete_metric(self, idx: int):
        del self._config["metrics"][idx]
        self._refresh_metrics()

    def _refresh_metrics(self):
        t = self._theme
        bd = _t(t, "border")
        bg = _t(t, "button_bg")

        while self._metrics_layout.count() > 1:
            item = self._metrics_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, m in enumerate(self._config.get("metrics", [])):
            frame = QFrame()
            frame.setStyleSheet(f"QFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}")
            lay = QVBoxLayout(frame)
            lay.setContentsMargins(10, 8, 10, 8)
            lay.setSpacing(6)

            top = QHBoxLayout()
            name_edit = QLineEdit(m.get("name", ""))
            name_edit.setFixedHeight(28)
            name_edit.textChanged.connect(
                lambda v, i=idx: self._config["metrics"][i].update({"name": v})
            )
            role_combo = QComboBox()
            role_combo.addItems(list(alerts_models.ROLES))
            role_combo.setCurrentText(m.get("role", alerts_models.ROLE_INFORMATIONAL))
            role_combo.currentTextChanged.connect(
                lambda v, i=idx: self._config["metrics"][i].update({"role": v})
            )
            del_btn = _btn("✕", theme=t, small=True, danger=True)
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, i=idx: self._delete_metric(i))
            top.addWidget(name_edit, 1)
            top.addWidget(role_combo)
            top.addWidget(del_btn)
            lay.addLayout(top)

            formula_row = QHBoxLayout()
            preview = QLabel(_tokens_to_display(m.get("formula", [])))
            preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;")
            preview.setWordWrap(True)
            edit_btn = _btn("Edit Formula…", outlined=True, theme=t, small=True)
            edit_btn.clicked.connect(lambda _, i=idx, p=preview: self._open_metric_formula_editor(i, p))
            formula_row.addWidget(preview, 1)
            formula_row.addWidget(edit_btn)
            lay.addLayout(formula_row)

            self._metrics_layout.insertWidget(self._metrics_layout.count() - 1, frame)

    def _open_metric_formula_editor(self, idx: int, preview_label: QLabel):
        from screens.formula_editor import ExpressionEditorDialog
        headers, extra_values = self._combined_headers_fn()
        metric = self._config["metrics"][idx]
        dlg = ExpressionEditorDialog(
            tokens=list(metric.get("formula", [])),
            lmv_headers=headers, strategy_col_headers=[],
            lmv_first_row=self._lmv_first_row, all_lmv_data=self._all_lmv_data,
            theme=self._theme, mode="value", extra_row_values=extra_values, parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            metric["formula"] = dlg.get_tokens()
            preview_label.setText(_tokens_to_display(metric["formula"]) or "—")


class StrategyEditor(QWidget):
    saved = Signal(dict)

    def __init__(self, strategy: dict, lmv_headers: list, theme=None, parent=None):
        super().__init__(parent)
        self._strategy      = copy.deepcopy(strategy)
        self._lmv_headers   = lmv_headers
        self._theme         = theme
        self._lmv_first_row: dict = {}
        self._all_lmv_data: list  = []
        self._notif_config = (
            alerts_config_store.load_config(self._strategy["id"])
            or alerts_models.new_notification_config()
        )
        self._build()

    def _field_names(self) -> list:
        """The loaded LMV's real columns plus every Formula Builder (Data
        menu) field — see services.formula_tokens.all_field_codes — that
        isn't already one of them, for any formula/condition editor's Fields
        list. Formula Builder fields only become real LMV columns once
        External Import is configured and computing them, but are offered
        here regardless so a strategy can reference one (e.g. a code just
        added there) right away — unresolved, it evaluates to nothing, same
        as any other momentarily-missing column, rather than being
        unselectable. Re-reads the store fresh on every call (not cached at
        construction) so a field added after this editor opened isn't
        invisible to it.
        """
        from services.formula_tokens import all_field_codes
        extra = [c for c in all_field_codes() if c not in self._lmv_headers]
        return self._lmv_headers + extra

    def _combined_headers_and_values(self) -> tuple:
        """This strategy's own column names + the loaded LMV's columns +
        every Formula Builder field (see _field_names), plus each own-
        column's computed value on the first row — for any formula/
        condition editor that should be able to reference any of these (the
        row filter editor, and every Notifications-section formula/condition
        editor)."""
        from services.strategy_engine import evaluate
        strat_cols = self._strategy.get("columns", [])
        all_headers = self._field_names() + [c["name"] for c in strat_cols]
        extra_values = {}
        for col in strat_cols:
            extra_values[col["name"]] = evaluate(
                col.get("formula", []), self._lmv_first_row, self._all_lmv_data
            )
        return all_headers, extra_values

    def _build(self):
        t    = self._theme
        txts = _t(t, "text_secondary")

        # The whole editor scrolls as one page — Row Filter + Columns +
        # Notifications together can easily exceed the right panel's height
        # (which, unlike this widget, is never itself wrapped in a scroll
        # area — see StrategyBuilderScreen._build's _editor_container), and
        # without an outer scroll here every section was forced to fight for
        # a share of whatever height happened to be available, collapsing
        # below its minimum size and overlapping once two sections
        # (Columns, Notifications) both wanted "the rest of the space".
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
        self._last_valid_category = self._strategy.get("category", "Daily")
        self._refresh_category_items()
        self._category_combo.activated.connect(self._on_category_activated)
        cat_row.addWidget(cat_lbl)
        cat_row.addWidget(self._category_combo)
        root.addLayout(cat_row)

        root.addWidget(_sep(t))

        # ── Row Filter ────────────────────────────────────────────────────────
        filter_hdr = QHBoxLayout()
        filter_title = QLabel("Row Filter")
        filter_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        filter_info = QLabel("(leave blank to include all rows)")
        filter_info.setFont(font_scale.font(font_scale.SMALL, False))
        filter_info.setStyleSheet(f"color:{txts};")
        self._filter_edit_btn = _btn("Edit Filter…", outlined=True, theme=t, small=True)
        self._filter_edit_btn.clicked.connect(self._open_filter_editor)
        filter_hdr.addWidget(filter_title)
        filter_hdr.addSpacing(8)
        filter_hdr.addWidget(filter_info)
        filter_hdr.addStretch()
        filter_hdr.addWidget(self._filter_edit_btn)
        root.addLayout(filter_hdr)

        self._filter_preview = QLabel(
            _tokens_to_display(self._strategy.get("row_filter", []))
        )
        self._filter_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._filter_preview.setStyleSheet(
            f"color:{_t(t,'accent')};background:transparent;border:none;padding:2px 4px;"
        )
        self._filter_preview.setWordWrap(True)
        root.addWidget(self._filter_preview)

        root.addWidget(_sep(t))

        col_hdr = QHBoxLayout()
        col_title = QLabel("Columns")
        col_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        add_col  = _btn("+ Add Column",  outlined=True, theme=t, small=True)
        add_col.clicked.connect(self._add_column)
        col_hdr.addWidget(col_title)
        col_hdr.addStretch()
        col_hdr.addWidget(add_col)
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

        # No nested QScrollArea here — this list lives inside the single
        # page-level scroll area set up below, so it just flows as normal
        # content instead of getting its own cramped, fixed-height inner
        # scrollbar stacked on top of the outer one.
        self._col_inner   = QWidget()
        self._col_inner.setStyleSheet("background:transparent;")
        self._col_layout  = QVBoxLayout(self._col_inner)
        self._col_layout.setSpacing(8)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.addStretch()
        root.addWidget(self._col_inner)

        root.addWidget(_sep(t))
        self._notif_section = NotificationSection(
            self._notif_config, self._strategy, t, self._combined_headers_and_values,
            self._lmv_first_row, self._all_lmv_data, parent=self,
        )
        root.addWidget(self._notif_section)
        root.addStretch()

        editor_scroll.setWidget(editor_inner)
        outer.addWidget(editor_scroll, 1)

        # A persistent footer bar, outside the scroll area, so Save Strategy
        # stays reachable regardless of scroll position — it used to live
        # inline in the Columns header, which scrolled out of view once the
        # Notifications section (below Columns) made the page long.
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
        dlg = ColumnEditorDialog(col, self._field_names(), self._theme,
                                 lmv_first_row=self._lmv_first_row,
                                 all_lmv_data=self._all_lmv_data, parent=self)
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

    def update_lmv_data(self, first_row: dict, all_data: list):
        self._lmv_first_row = first_row
        self._all_lmv_data  = all_data
        self._notif_section.update_lmv_data(first_row, all_data)

    def _edit_column(self, idx: int):
        col = self._strategy["columns"][idx]
        dlg = ColumnEditorDialog(col, self._field_names(), self._theme,
                                 lmv_first_row=self._lmv_first_row,
                                 all_lmv_data=self._all_lmv_data, parent=self)
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

            edit_b  = _btn("Edit",  theme=t, small=True)
            clone_b = _btn("Clone", theme=t, small=True, outlined=True)
            del_b   = _btn("✕",    theme=t, small=True, danger=True)
            edit_b.setFixedWidth(50)
            clone_b.setFixedWidth(64)
            del_b.setFixedWidth(30)
            edit_b.clicked.connect(lambda _, i=idx: self._edit_column(i))
            clone_b.clicked.connect(lambda _, i=idx: self._clone_column(i))
            del_b.clicked.connect(lambda _, i=idx:  self._delete_column(i))

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

    def _open_filter_editor(self):
        from screens.formula_editor import ExpressionEditorDialog
        # A row filter can reference this strategy's own columns by name, so the
        # column names appear in the Fields list (THIS is disabled — ambiguous
        # when a strategy has multiple columns).
        all_headers, extra_values = self._combined_headers_and_values()
        dlg = ExpressionEditorDialog(
            tokens=list(self._strategy.get("row_filter", [])),
            lmv_headers=all_headers,
            strategy_col_headers=[],
            lmv_first_row=self._lmv_first_row,
            all_lmv_data=self._all_lmv_data,
            theme=self._theme,
            mode="condition",
            allow_self=False,
            extra_row_values=extra_values,
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["row_filter"] = dlg.get_tokens()
            self._filter_preview.setText(
                _tokens_to_display(self._strategy["row_filter"])
            )

    def _refresh_category_items(self, select: str | None = None):
        """(Re)populates the combo from services.strategy_store.all_categories(),
        appending the "+ Add New Category…" sentinel last. *select* wins over
        the box's current text (which, when this runs right after the user
        just picked the sentinel, would just be the sentinel itself)."""
        from services import strategy_store as store

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
        from services import strategy_store as store

        dlg = _AddCategoryDialog(self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.category_name()
            if name:
                canonical = store.add_custom_category(name)
                self._refresh_category_items(select=canonical)
                return
        # Cancelled, or blank input — revert off the sentinel back to
        # whatever was actually selected before.
        self._refresh_category_items()

    def _save(self):
        self._strategy["name"]     = self._name_edit.text().strip() or "Untitled"
        self._strategy["category"] = self._category_combo.currentText()
        alerts_config_store.save_config(self._strategy["id"], self._notif_section.result_config())
        self.saved.emit(copy.deepcopy(self._strategy))


# ── Main Strategy Builder screen ───────────────────────────────────────────

class StrategyBuilderScreen(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self._controller          = controller
        self._theme               = controller.theme
        self._strategies: list    = store.load_all()
        self._lmv_headers: list   = []
        self._lmv_first_row: dict = {}
        self._all_lmv_data: list  = []
        self._active_editor       = None
        self._search_query        = ""
        # Empty == every category collapsed — the sidebar starts fully
        # collapsed and a category only stays expanded once the user
        # actually opens it (see _on_section_toggled/_refresh_list below).
        self._expanded_categories: set = set()
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

        vars_btn = _btn("Variables", theme=t)
        vars_btn.clicked.connect(self._open_variables_manager)
        self._vars_btn = vars_btn

        new_btn = _btn("+ New Strategy", accent=True, theme=t)
        new_btn.clicked.connect(self._new_strategy)
        self._new_btn = new_btn

        top_lay.addWidget(title)
        top_lay.addSpacing(16)
        top_lay.addWidget(self._lmv_warn)
        top_lay.addStretch()
        top_lay.addWidget(vars_btn)
        top_lay.addSpacing(8)
        top_lay.addWidget(new_btn)
        root.addWidget(self._topbar)

        # ── Body ──────────────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        # Left panel
        self._left_frame = QFrame()
        self._left_frame.setFixedWidth(300)
        self._left_frame.setStyleSheet(
            f"QFrame{{background:{card};border-right:1px solid {bd};}}"
        )
        left_root = QVBoxLayout(self._left_frame)
        left_root.setContentsMargins(12, 12, 12, 12)
        left_root.setSpacing(8)

        list_title = QLabel("Strategies")
        list_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        left_root.addWidget(list_title)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search strategies…")
        self._search_box.setFixedHeight(30)
        self._search_box.setFont(font_scale.font(font_scale.SMALL, False))
        self._style_search_box()
        self._search_box.textChanged.connect(self._on_search_changed)
        left_root.addWidget(self._search_box)

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

    def _style_search_box(self):
        t = self._theme
        self._search_box.setStyleSheet(
            f"QLineEdit{{background:{_t(t,'input_bg')};color:{_t(t,'text_primary')};"
            f"border:1px solid {_t(t,'border')};border-radius:6px;padding:0 8px;}}"
            f"QLineEdit:focus{{border-color:{_t(t,'accent')};}}"
        )

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
                # takeAt() only detaches the widget from the layout — it stays
                # a visible child at its old geometry until deleteLater()'s
                # deferred event actually runs, which can be several event-loop
                # turns away. Left alone, a fast rebuild (every keystroke in
                # the search box, now that one exists) briefly stacks stale
                # cards on top of the freshly-built ones. hide() removes it
                # from view immediately; deleteLater() still reclaims it.
                w.hide()
                w.deleteLater()

        if not self._strategies:
            empty = QLabel("No strategies yet.\nClick '+ New Strategy'.")
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._list_layout.insertWidget(0, empty)
            return

        query = self._search_query.strip().lower()
        filtered = (
            [s for s in self._strategies if query in s.get("name", "").lower()]
            if query else list(self._strategies)
        )

        if not filtered:
            empty = QLabel(f"No strategies match “{self._search_query.strip()}”.")
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setStyleSheet(f"color:{_t(self._theme,'text_secondary')};")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._list_layout.insertWidget(0, empty)
            return

        by_category: dict = {}
        for strat in filtered:
            by_category.setdefault(strat.get("category", "Daily"), []).append(strat)

        # Built-ins first, then user-added custom categories in creation
        # order (services.strategy_store.all_categories), then any
        # unexpected category value (e.g. imported/legacy data predating a
        # category that's since been renamed) still gets its own section
        # instead of silently disappearing from the list.
        known_categories = store.all_categories()
        ordered_categories = known_categories + [
            c for c in by_category if c not in known_categories
        ]
        for cat in ordered_categories:
            items = by_category.get(cat)
            if not items:
                continue
            # While actively searching, force every matching category open —
            # collapsed-by-default sections would otherwise hide the very
            # matches the search box exists to surface.
            expanded = bool(query) or cat in self._expanded_categories
            section = _CategorySection(
                cat, len(items), self._theme, expanded=expanded, parent=self,
            )
            section.toggled.connect(self._on_section_toggled)
            for strat in items:
                card = StrategyCard(strat, self._theme, parent=self)
                card.edit_requested.connect(self._open_editor)
                card.clone_requested.connect(self._clone_strategy)
                card.delete_requested.connect(self._delete_strategy)
                card.toggled.connect(self._on_toggled)
                section.add_card(card)
            self._list_layout.insertWidget(self._list_layout.count() - 1, section)

    # ── Editor ────────────────────────────────────────────────────────────

    def _open_editor(self, strategy: dict):
        while self._editor_slot.count():
            item = self._editor_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        editor = StrategyEditor(strategy, self._lmv_headers, self._theme, self)
        editor.update_lmv_data(self._lmv_first_row, self._all_lmv_data)
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

    def _field_names(self) -> list:
        """Same as StrategyEditor._field_names — the loaded LMV's real
        columns plus every Formula Builder (Data menu) field not already
        one of them, so a saved Variable can reference one too."""
        from services.formula_tokens import all_field_codes
        extra = [c for c in all_field_codes() if c not in self._lmv_headers]
        return self._lmv_headers + extra

    def _open_variables_manager(self):
        from screens.formula_editor import VariablesManagerDialog
        dlg = VariablesManagerDialog(
            self._field_names(), self._lmv_first_row, self._all_lmv_data,
            theme=self._theme, parent=self,
        )
        dlg.exec()

    def _clone_strategy(self, original: dict):
        import uuid
        cloned = copy.deepcopy(original)
        cloned["id"]   = str(uuid.uuid4())
        cloned["name"] = "Copy of " + original["name"]
        self._strategies.append(cloned)
        store.save_strategy(cloned)
        self._refresh_list()
        self._open_editor(cloned)

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
        alerts_config_store.delete_config(strategy_id)
        alerts_state_store.clear_strategy(strategy_id)
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

    def set_lmv_data(self, headers: list, data: list):
        """Store the loaded LMV sheet so formulas compile against real data."""
        self._lmv_headers   = list(headers)
        self._all_lmv_data  = [dict(zip(headers, row)) for row in data]
        self._lmv_first_row = dict(self._all_lmv_data[0]) if self._all_lmv_data else {}
        self._update_lmv_warn()
        if self._active_editor is not None:
            self._active_editor.update_lmv_headers(self._lmv_headers)
            self._active_editor.update_lmv_data(self._lmv_first_row,
                                                self._all_lmv_data)

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

    def get_all_strategies(self) -> list:
        return list(self._strategies)

    def reload_strategies(self):
        """Re-read all strategies from disk and refresh the list — used after
        an Import All Strategies replaces the underlying storage file."""
        while self._editor_slot.count():
            item = self._editor_slot.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        self._active_editor = None
        self._editor_container.hide()
        self._placeholder.show()

        self._strategies = store.load_all()
        self._refresh_list()

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
        _restyle_btn(self._vars_btn, t)
        self._style_search_box()
        self._update_lmv_warn()
        self._refresh_list()
        # Re-open editor with fresh theme if visible
        if self._editor_container.isVisible():
            self._editor_container.hide()
            self._placeholder.show()
            self._active_editor = None
