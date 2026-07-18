"""Click-to-build formula editor for ExternalImport formulas.

Mirrors screens.strategy_builder's chip-based FormulaBuilder/TokenChip
pattern, but over the fixed domain vocabulary in services.formula_tokens
(raw fields, other formula codes, windows, timepoints) instead of arbitrary
LMV columns — there is no free-text formula cell here.
"""
import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QScrollArea, QLineEdit, QSizePolicy, QDialog
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont

from services import formula_tokens as ft


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


class _TwoStepPickerDialog(QDialog):
    """Pick a field, then a window/timepoint — used for MAX_OF/MIN_OF/AVG_OF/SUM_OF/AT."""

    def __init__(self, title: str, fields: list, second_label: str,
                 second_options: list, theme=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._fields = fields
        self._second_options = second_options
        self._field = fields[0] if fields else ""
        self._second = second_options[0] if second_options else ""
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
        self.accept()

    def selected(self):
        return self._field, self._second


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

    def _build(self):
        t = self._theme
        bd = _t(t, "border")
        inp_bg = _t(t, "input_bg")
        txts = _t(t, "text_secondary")
        accent = _t(t, "accent")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)

        token_frame = QFrame()
        token_frame.setMinimumHeight(44)
        token_frame.setStyleSheet(f"QFrame{{background:{inp_bg};border:1px solid {bd};border-radius:6px;}}")
        self._token_layout = QHBoxLayout(token_frame)
        self._token_layout.setContentsMargins(8, 4, 8, 4)
        self._token_layout.setSpacing(4)
        self._token_layout.addStretch()
        root.addWidget(token_frame)

        self._preview_lbl = QLabel("—")
        self._preview_lbl.setFont(QFont("Menlo,Consolas,monospace", 10))
        self._preview_lbl.setStyleSheet(f"color:{accent};background:transparent;border:none;padding:2px 0;")
        self._preview_lbl.setWordWrap(True)
        root.addWidget(self._preview_lbl)

        # Number + Clear
        num_row = QHBoxLayout()
        self._num_input = QLineEdit()
        self._num_input.setPlaceholderText("Constant…")
        self._num_input.setFixedHeight(30)
        self._num_input.setFixedWidth(110)
        add_num = QPushButton("Add")
        add_num.setFixedHeight(30)
        add_num.setCursor(Qt.CursorShape.PointingHandCursor)
        add_num.setStyleSheet(f"QPushButton{{background:{accent};color:{_t(t,'background')};border:none;border-radius:4px;padding:0 10px;}}")
        add_num.clicked.connect(self._add_number)
        clr = QPushButton("Clear")
        clr.setFixedHeight(30)
        clr.setCursor(Qt.CursorShape.PointingHandCursor)
        clr.clicked.connect(self._clear)
        num_row.addWidget(QLabel("Number:"))
        num_row.addWidget(self._num_input)
        num_row.addWidget(add_num)
        num_row.addSpacing(8)
        num_row.addWidget(clr)
        num_row.addStretch()
        root.addLayout(num_row)

        # Operators
        self._add_chip_row(root, "Operators", ["+", "-", "*", "/", "(", ")"],
                            lambda v: self._add_token({"type": "op" if v not in ("(", ")") else "paren", "value": v}))

        # Window aggregate functions
        agg_row = QHBoxLayout()
        agg_lbl = QLabel("Aggregate over a window:")
        agg_lbl.setStyleSheet(f"color:{txts};")
        agg_row.addWidget(agg_lbl)
        for fname in ft.AGG_FUNCS:
            b = self._chip_button(fname)
            b.clicked.connect(lambda _, fn=fname: self._add_window_agg(fn))
            agg_row.addWidget(b)
        agg_row.addStretch()
        root.addLayout(agg_row)

        # AT() point lookup + ABS(
        pt_row = QHBoxLayout()
        pt_lbl = QLabel("Value at a point in time:")
        pt_lbl.setStyleSheet(f"color:{txts};")
        at_btn = self._chip_button("AT(")
        at_btn.clicked.connect(self._add_at)
        abs_btn = self._chip_button("ABS(")
        abs_btn.clicked.connect(lambda: self._add_token({"type": "func", "value": "ABS("}))
        pt_row.addWidget(pt_lbl)
        pt_row.addWidget(at_btn)
        pt_row.addSpacing(8)
        pt_row.addWidget(abs_btn)
        pt_row.addStretch()
        root.addLayout(pt_row)

        # Raw fields
        raw_lbl = QLabel("Raw fields (click to insert):")
        raw_lbl.setStyleSheet(f"color:{txts};")
        root.addWidget(raw_lbl)
        raw_row = QHBoxLayout()
        for f in ft.RAW_FIELDS:
            b = self._chip_button(f, color="field")
            b.clicked.connect(lambda _, name=f: self._add_token({"type": "field", "value": name}))
            raw_row.addWidget(b)
        raw_row.addStretch()
        root.addLayout(raw_row)

        # Other formulas
        other_lbl = QLabel("Other formulas (click to insert):")
        other_lbl.setStyleSheet(f"color:{txts};")
        root.addWidget(other_lbl)
        other_scroll = QScrollArea()
        other_scroll.setFrameShape(QFrame.Shape.NoFrame)
        other_scroll.setFixedHeight(70)
        other_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAsNeeded)
        other_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        other_inner = QWidget()
        other_row = QHBoxLayout(other_inner)
        other_row.setContentsMargins(0, 4, 0, 4)
        other_row.setSpacing(6)
        for code in self._other_codes():
            b = self._chip_button(code, color="field")
            b.clicked.connect(lambda _, name=code: self._add_token({"type": "field", "value": name}))
            other_row.addWidget(b)
        other_row.addStretch()
        other_scroll.setWidget(other_inner)
        other_scroll.setWidgetResizable(True)
        root.addWidget(other_scroll)

    def _add_chip_row(self, layout, label_text, items, on_click):
        txts = _t(self._theme, "text_secondary")
        lbl = QLabel(f"{label_text}:")
        lbl.setStyleSheet(f"color:{txts};")
        layout.addWidget(lbl)
        row_w = QWidget()
        row_lay = QHBoxLayout(row_w)
        row_lay.setContentsMargins(0, 0, 0, 0)
        row_lay.setSpacing(6)
        for item in items:
            b = self._chip_button(item)
            b.clicked.connect(lambda _, v=item: on_click(v))
            row_lay.addWidget(b)
        row_lay.addStretch()
        layout.addWidget(row_w)

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
            self._add_token({"type": "func", "value": fname, "field": field, "window": window})

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
        self.resize(720, 560)
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

        self._builder = FieldFormulaBuilder(tokens, theme, exclude_code=exclude_code, parent=self)
        root.addWidget(self._builder, 1)

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
