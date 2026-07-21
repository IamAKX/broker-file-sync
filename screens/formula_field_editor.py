"""Click-to-build formula editor for ExternalImport formulas.

Mirrors screens.strategy_builder's chip-based FormulaBuilder/TokenChip
pattern, but over the fixed domain vocabulary in services.formula_tokens
(raw fields, other formula codes, windows, timepoints) instead of arbitrary
LMV columns — there is no free-text formula cell here.
"""
import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QSizePolicy, QDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from services import formula_tokens as ft


def _scrollbar_css(theme) -> str:
    bd = _t(theme, "border")
    return (
        f"QScrollBar:horizontal{{height:8px;background:transparent;margin:0;}}"
        f"QScrollBar::handle:horizontal{{background:{bd};border-radius:4px;min-width:24px;}}"
        f"QScrollBar::add-line:horizontal,QScrollBar::sub-line:horizontal{{width:0;}}"
        f"QScrollBar:vertical{{width:8px;background:transparent;margin:0;}}"
        f"QScrollBar::handle:vertical{{background:{bd};border-radius:4px;min-height:24px;}}"
        f"QScrollBar::add-line:vertical,QScrollBar::sub-line:vertical{{height:0;}}"
    )


def _t(theme, key: str) -> str:
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "accent_hover": "#2ea043",
        "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "input_bg": "#0d1117", "destructive": "#da3633",
    }
    if theme:
        try:
            return theme.get(key)
        except Exception:
            pass
    return _FALLBACK.get(key, "#888")


class FieldTokenChip(QFrame):
    remove_requested = Signal(object)

    def __init__(self, token: dict, theme=None, parent=None):
        super().__init__(parent)
        self._token = token
        self._theme = theme
        self._build()

    def token(self) -> dict:
        return self._token

    def _build(self):
        text = ft.tokens_to_display([self._token])
        is_dark = (self._theme.current_mode == "dark") if self._theme else True
        kind = self._token.get("type", "op")
        palette_dark = {
            "field": ("#1d6fa455", "#cce5ff"), "func": ("#6f42c155", "#ede0ff"),
            "op": ("#44444466", "#cccccc"), "paren": ("#44444466", "#cccccc"),
            "num": ("#27674955", "#d1fae5"),
        }
        palette_light = {
            "field": ("#cce5ff", "#1d4e89"), "func": ("#ede0ff", "#4a1d96"),
            "op": ("#e5e7eb", "#374151"), "paren": ("#e5e7eb", "#374151"),
            "num": ("#d1fae5", "#065f46"),
        }
        bg, fg = (palette_dark if is_dark else palette_light).get(kind, ("#44444466", "#ccc"))

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


_LAST_N_TRADING_DAYS = "LAST_N_TRADING_DAYS"


class _TwoStepPickerDialog(QDialog):
    """Pick a field, then a window/timepoint — used for MAX_OF/MIN_OF/AVG_OF/SUM_OF/AT.

    Picking the LAST_N_TRADING_DAYS window adds an optional 3rd step asking
    for N (see _build_step3_n / n_value) — every other window/timepoint
    accepts immediately after step 2, unchanged.
    """

    def __init__(self, title: str, fields: list, second_label: str,
                 second_options: list, theme=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._fields = fields
        self._second_options = second_options
        self._field = fields[0] if fields else ""
        self._second = second_options[0] if second_options else ""
        self._n = None
        self._step = 0
        self.setWindowTitle(title)
        self.setFixedWidth(320)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
        )
        self._second_label = second_label
        self._build_step1()

    def _clear(self):
        while self.layout() and self.layout().count():
            item = self.layout().takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        if self.layout() is None:
            QVBoxLayout(self)

    def _build_step1(self):
        self._clear()
        lay = self.layout() or QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Field:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(220)
        inner = QWidget()
        vlay = QVBoxLayout(inner)
        vlay.setSpacing(4)
        for f in self._fields:
            b = QPushButton(f)
            b.setFlat(True)
            b.setFont(font_scale.font(font_scale.SMALL, False))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, name=f: self._pick_field(name))
            vlay.addWidget(b)
        vlay.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll)

    def _pick_field(self, name):
        self._field = name
        self._build_step2()

    def _build_step2(self):
        self._clear()
        lay = self.layout() or QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel(f"{self._second_label}:"))
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(220)
        inner = QWidget()
        vlay = QVBoxLayout(inner)
        vlay.setSpacing(4)
        for opt in self._second_options:
            b = QPushButton(opt)
            b.setFlat(True)
            b.setFont(font_scale.font(font_scale.SMALL, False))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, name=opt: self._pick_second(name))
            vlay.addWidget(b)
        vlay.addStretch()
        scroll.setWidget(inner)
        lay.addWidget(scroll)

    def _pick_second(self, name):
        self._second = name
        if name == _LAST_N_TRADING_DAYS:
            self._build_step3_n()
        else:
            self.accept()

    def _build_step3_n(self):
        self._clear()
        lay = self.layout() or QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Number of trading days (N):"))
        self._n_input = QLineEdit("5")
        lay.addWidget(self._n_input)
        confirm = QPushButton("OK")
        confirm.setCursor(Qt.CursorShape.PointingHandCursor)
        confirm.clicked.connect(self._confirm_n)
        lay.addWidget(confirm)

    def _confirm_n(self):
        text = self._n_input.text().strip()
        try:
            n = int(text)
        except ValueError:
            return
        if n < 1:
            return
        self._n = n
        self.accept()

    def selected(self):
        return self._field, self._second

    def n_value(self):
        """The N entered in step 3, or None if that step never ran."""
        return self._n


class FieldFormulaBuilder(QWidget):
    """Inline chip-based formula builder over the ExternalImport vocabulary."""

    changed = Signal()

    def __init__(self, tokens: list, theme=None, exclude_code: str = None, parent=None):
        super().__init__(parent)
        self._tokens = list(tokens)
        self._theme = theme
        self._exclude_code = exclude_code
        self._chips: list = []
        self._build()
        self._refresh_chips()

    def get_tokens(self) -> list:
        return list(self._tokens)

    def _other_codes(self) -> list:
        return [c for c in ft.BUILTIN_CODES if c != self._exclude_code]

    def _card(self, title: str, trailing: QWidget = None) -> QVBoxLayout:
        """A titled, bordered section. Returns the body layout to add content to."""
        t = self._theme
        bd, bg = _t(t, "border"), _t(t, "card_bg")
        txt, accent = _t(t, "text_primary"), _t(t, "accent")

        frame = QFrame()
        frame.setStyleSheet(f"QFrame{{background:{bg};border:1px solid {bd};border-radius:8px;}}")
        body = QVBoxLayout(frame)
        body.setContentsMargins(14, 10, 14, 14)
        body.setSpacing(8)

        header = QHBoxLayout()
        header.setSpacing(6)
        dot = QLabel("●")
        dot.setStyleSheet(f"color:{accent};background:transparent;")
        dot.setFont(font_scale.font(font_scale.SMALL, False))
        title_lbl = QLabel(title.upper())
        title_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        title_lbl.setStyleSheet(f"color:{txt};background:transparent;")
        header.addWidget(dot)
        header.addWidget(title_lbl)
        header.addStretch()
        if trailing is not None:
            header.addWidget(trailing)
        body.addLayout(header)

        self._root.addWidget(frame)
        return body

    def _sub_label(self, text: str) -> QLabel:
        lbl = QLabel(text)
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color:{_t(self._theme, 'text_secondary')};background:transparent;")
        lbl.setFixedWidth(90)
        return lbl

    def _build(self):
        t = self._theme
        bd = _t(t, "border")
        inp_bg = _t(t, "input_bg")
        accent = _t(t, "accent")

        self._root = QVBoxLayout(self)
        self._root.setContentsMargins(0, 0, 0, 0)
        self._root.setSpacing(12)

        # ── Formula: the current token sequence + live preview + Clear ──
        clr = QPushButton("Clear")
        clr.setFixedHeight(24)
        clr.setCursor(Qt.CursorShape.PointingHandCursor)
        destructive = _t(t, "destructive")
        clr.setStyleSheet(
            f"QPushButton{{background:transparent;color:{destructive};"
            f"border:1px solid {destructive}88;border-radius:4px;padding:2px 10px;}}"
            f"QPushButton:hover{{background:{destructive};color:white;}}"
        )
        clr.clicked.connect(self._clear)
        formula_body = self._card("Formula", trailing=clr)

        token_scroll = QScrollArea()
        token_scroll.setWidgetResizable(True)
        token_scroll.setFrameShape(QFrame.Shape.NoFrame)
        token_scroll.setFixedHeight(48)
        token_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        token_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        token_scroll.setStyleSheet(_scrollbar_css(self._theme))
        token_inner = QWidget()
        token_inner.setStyleSheet(f"background:{inp_bg};border:1px solid {bd};border-radius:6px;")
        self._token_layout = QHBoxLayout(token_inner)
        self._token_layout.setContentsMargins(8, 4, 8, 4)
        self._token_layout.setSpacing(4)
        self._token_layout.addStretch()
        token_scroll.setWidget(token_inner)
        formula_body.addWidget(token_scroll)

        self._preview_lbl = QLabel("—")
        self._preview_lbl.setFont(QFont("Menlo,Consolas,monospace", 10))
        self._preview_lbl.setStyleSheet(f"color:{accent};background:transparent;border:none;padding:2px 0;")
        self._preview_lbl.setWordWrap(True)
        formula_body.addWidget(self._preview_lbl)

        # ── Raw fields ──
        fields_body = self._card("Raw Fields")
        fields_row = QHBoxLayout()
        fields_row.setSpacing(6)
        for f in ft.RAW_FIELDS:
            b = self._chip_button(f, color="field")
            b.clicked.connect(lambda _, name=f: self._add_token({"type": "field", "value": name}))
            fields_row.addWidget(b)
        fields_row.addStretch()
        fields_body.addLayout(fields_row)

        # ── Functions: aggregate over a window, point-in-time lookup, ABS( ──
        func_body = self._card("Functions")

        agg_row = QHBoxLayout()
        agg_row.setSpacing(6)
        agg_row.addWidget(self._sub_label("Aggregate:"))
        for fname in ft.AGG_FUNCS:
            b = self._chip_button(fname)
            b.clicked.connect(lambda _, fn=fname: self._add_window_agg(fn))
            agg_row.addWidget(b)
        agg_row.addStretch()
        func_body.addLayout(agg_row)

        pt_row = QHBoxLayout()
        pt_row.setSpacing(6)
        pt_row.addWidget(self._sub_label("Point-in-time:"))
        at_btn = self._chip_button("AT(")
        at_btn.clicked.connect(self._add_at)
        abs_btn = self._chip_button("ABS(")
        abs_btn.clicked.connect(lambda: self._add_token({"type": "func", "value": "ABS("}))
        pt_row.addWidget(at_btn)
        pt_row.addWidget(abs_btn)
        pt_row.addStretch()
        func_body.addLayout(pt_row)

        # ── Operators & constants ──
        ops_body = self._card("Operators & Constants")

        op_row = QHBoxLayout()
        op_row.setSpacing(6)
        op_row.addWidget(self._sub_label("Operators:"))
        for v in ["+", "-", "*", "/", "(", ")"]:
            b = self._chip_button(v, color="op")
            kind = "paren" if v in ("(", ")") else "op"
            b.clicked.connect(lambda _, val=v, k=kind: self._add_token({"type": k, "value": val}))
            op_row.addWidget(b)
        op_row.addStretch()
        ops_body.addLayout(op_row)

        num_row = QHBoxLayout()
        num_row.setSpacing(6)
        num_row.addWidget(self._sub_label("Constant:"))
        self._num_input = QLineEdit()
        self._num_input.setPlaceholderText("e.g. 1.1")
        self._num_input.setFixedHeight(28)
        self._num_input.setFixedWidth(110)
        add_num = QPushButton("Add")
        add_num.setFixedHeight(28)
        add_num.setCursor(Qt.CursorShape.PointingHandCursor)
        add_num.setStyleSheet(
            f"QPushButton{{background:{accent};color:{_t(t,'background')};"
            "border:none;border-radius:4px;padding:0 10px;}"
        )
        add_num.clicked.connect(self._add_number)
        num_row.addWidget(self._num_input)
        num_row.addWidget(add_num)
        num_row.addStretch()
        ops_body.addLayout(num_row)

        # ── Reference other formulas: wraps into a scrollable grid, not one
        # long horizontally-scrolling strip ──
        other_body = self._card("Reference Other Formulas")
        other_scroll = QScrollArea()
        other_scroll.setFrameShape(QFrame.Shape.NoFrame)
        other_scroll.setFixedHeight(120)
        other_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        other_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        other_scroll.setStyleSheet(_scrollbar_css(self._theme))
        other_inner = QWidget()
        other_grid = QGridLayout(other_inner)
        other_grid.setContentsMargins(0, 0, 4, 0)
        other_grid.setSpacing(6)
        _OTHER_COLS = 6
        for idx, code in enumerate(self._other_codes()):
            b = self._chip_button(code, color="field")
            b.clicked.connect(lambda _, name=code: self._add_token({"type": "field", "value": name}))
            other_grid.addWidget(b, idx // _OTHER_COLS, idx % _OTHER_COLS, Qt.AlignmentFlag.AlignLeft)
        other_scroll.setWidget(other_inner)
        other_scroll.setWidgetResizable(True)
        other_body.addWidget(other_scroll)

        self._root.addStretch()

    def _chip_button(self, text: str, color: str = "func") -> QPushButton:
        t = self._theme
        accent = _t(t, "accent")
        bd = _t(t, "border")
        is_dark = (t.current_mode == "dark") if t else True
        dark_pal = {"field": ("#1d6fa433", "#9ecff7"), "func": ("#6f42c133", "#d8b4fe"), "op": (bd + "44", _t(t, "text_primary"))}
        light_pal = {"field": ("#dbeafe", "#1e40af"), "func": ("#f3e8ff", "#6d28d9"), "op": ("#e5e7eb", "#374151")}
        bg, fg = (dark_pal if is_dark else light_pal).get(color, (bd, _t(t, "text_primary")))
        b = QPushButton(text)
        b.setFixedHeight(26)
        b.setFont(font_scale.font(font_scale.SMALL, False))
        b.setCursor(Qt.CursorShape.PointingHandCursor)
        b.setStyleSheet(
            f"QPushButton{{background:{bg};color:{fg};border:1px solid {bd};border-radius:4px;padding:0 8px;}}"
            f"QPushButton:hover{{border-color:{accent};}}"
        )
        return b

    def _add_token(self, token: dict):
        self._tokens.append(token)
        self._refresh_chips()
        self.changed.emit()

    def _add_window_agg(self, fname: str):
        fields = ft.RAW_FIELDS + self._other_codes()
        dlg = _TwoStepPickerDialog(fname, fields, "Window", ft.WINDOWS, self._theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            field, window = dlg.selected()
            token = {"type": "func", "value": fname, "field": field, "window": window}
            n = dlg.n_value()
            if n is not None:
                token["n"] = n
            self._add_token(token)

    def _add_at(self):
        fields = ft.RAW_FIELDS + self._other_codes()
        dlg = _TwoStepPickerDialog("AT(", fields, "Timepoint", ft.TIMEPOINTS, self._theme, self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            field, timepoint = dlg.selected()
            self._add_token({"type": "func", "value": "AT(", "field": field, "timepoint": timepoint})

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

    def _clear(self):
        self._tokens.clear()
        self._refresh_chips()
        self.changed.emit()

    def _remove_chip(self, chip):
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
            chip = FieldTokenChip(tok, self._theme, self)
            chip.remove_requested.connect(self._remove_chip)
            self._token_layout.insertWidget(self._token_layout.count() - 1, chip)
            self._chips.append(chip)
        self._preview_lbl.setText(ft.tokens_to_display(self._tokens))


class FormulaFieldEditorDialog(QDialog):
    """Modal wrapper around FieldFormulaBuilder with Save/Cancel."""

    def __init__(self, tokens: list, theme=None, exclude_code: str = None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Edit Formula")
        self.resize(760, 660)
        self.setMinimumSize(620, 480)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
            f"QLineEdit{{background:{_t(theme,'input_bg')};color:{txt};"
            f"border:1px solid {_t(theme,'border')};border-radius:4px;padding:4px 8px;}}"
            f"QPushButton{{background:{_t(theme,'button_bg')};color:{txt};"
            f"border:1px solid {_t(theme,'border')};border-radius:4px;padding:4px 10px;}}"
            f"QPushButton:hover{{border-color:{_t(theme,'accent')};color:{_t(theme,'accent')};}}"
            f"QScrollArea{{background:transparent;border:none;}}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        outer_scroll = QScrollArea()
        outer_scroll.setWidgetResizable(True)
        outer_scroll.setFrameShape(QFrame.Shape.NoFrame)
        outer_scroll.setStyleSheet(_scrollbar_css(theme))
        self._builder = FieldFormulaBuilder(tokens, theme, exclude_code=exclude_code, parent=self)
        outer_scroll.setWidget(self._builder)
        root.addWidget(outer_scroll, 1)

        btn_row = QHBoxLayout()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setStyleSheet(
            f"QPushButton{{background:{_t(theme,'accent')};color:{_t(theme,'background')};"
            "border:none;border-radius:4px;padding:6px 20px;}"
        )
        save_btn.clicked.connect(self.accept)
        btn_row.addStretch()
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        root.addLayout(btn_row)

    def get_tokens(self) -> list:
        return self._builder.get_tokens()
