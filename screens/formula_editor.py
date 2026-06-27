"""Expression Editor — catalogues and dialog for building formula tokens."""
import font_scale
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFrame, QScrollArea, QSizePolicy, QMessageBox,
)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QFont, QColor

# ── Catalogues ────────────────────────────────────────────────────────────────

# Each entry: {"name": str, "signature": str, "description": str, "token": dict}

FUNCTION_CATALOGUE = [
    # Math
    {"name": "Abs",    "signature": "Abs(value)",          "description": "Absolute value of a number.", "token": {"type": "func", "value": "Abs("}},
    {"name": "Ceiling","signature": "Ceiling(value)",      "description": "Round up to nearest integer.", "token": {"type": "func", "value": "Ceiling("}},
    {"name": "Floor",  "signature": "Floor(value)",        "description": "Round down to nearest integer.", "token": {"type": "func", "value": "Floor("}},
    {"name": "Round",  "signature": "Round(value)",        "description": "Round to nearest integer.", "token": {"type": "func", "value": "Round("}},
    {"name": "Round",  "signature": "Round(value, digits)","description": "Round to N decimal places.", "token": {"type": "func", "value": "Round("}},
    {"name": "Exp",    "signature": "Exp(value)",          "description": "e raised to the power.", "token": {"type": "func", "value": "Exp("}},
    {"name": "Log",    "signature": "Log(value)",          "description": "Natural logarithm.", "token": {"type": "func", "value": "Log("}},
    {"name": "Log",    "signature": "Log(value, base)",    "description": "Logarithm with specified base.", "token": {"type": "func", "value": "Log("}},
    {"name": "Log10",  "signature": "Log10(value)",        "description": "Base-10 logarithm.", "token": {"type": "func", "value": "Log10("}},
    {"name": "Max",    "signature": "Max(a, b)",           "description": "Maximum of two values.", "token": {"type": "func", "value": "Max("}},
    {"name": "Min",    "signature": "Min(a, b)",           "description": "Minimum of two values.", "token": {"type": "func", "value": "Min("}},
    {"name": "Power",  "signature": "Power(base, exp)",    "description": "Raise base to a power.", "token": {"type": "func", "value": "Power("}},
    {"name": "Rnd",    "signature": "Rnd()",               "description": "Random number between 0 and 1.", "token": {"type": "func", "value": "Rnd("}},
    {"name": "Sign",   "signature": "Sign(value)",         "description": "Returns -1, 0, or 1.", "token": {"type": "func", "value": "Sign("}},
    {"name": "Sqr",    "signature": "Sqr(value)",          "description": "Square root.", "token": {"type": "func", "value": "Sqr("}},
    {"name": "BigMul", "signature": "BigMul(a, b)",        "description": "Multiply two large integers.", "token": {"type": "func", "value": "BigMul("}},
    # Trig
    {"name": "Acos",   "signature": "Acos(value)",         "description": "Arc cosine (radians).", "token": {"type": "func", "value": "Acos("}},
    {"name": "Asin",   "signature": "Asin(value)",         "description": "Arc sine (radians).", "token": {"type": "func", "value": "Asin("}},
    {"name": "Atn",    "signature": "Atn(value)",          "description": "Arc tangent (radians).", "token": {"type": "func", "value": "Atn("}},
    {"name": "Atn2",   "signature": "Atn2(y, x)",          "description": "Arc tangent of y/x.", "token": {"type": "func", "value": "Atn2("}},
    {"name": "Cos",    "signature": "Cos(value)",          "description": "Cosine (radians).", "token": {"type": "func", "value": "Cos("}},
    {"name": "Cosh",   "signature": "Cosh(value)",         "description": "Hyperbolic cosine.", "token": {"type": "func", "value": "Cosh("}},
    {"name": "Sin",    "signature": "Sin(value)",          "description": "Sine (radians).", "token": {"type": "func", "value": "Sin("}},
    {"name": "Sinh",   "signature": "Sinh(value)",         "description": "Hyperbolic sine.", "token": {"type": "func", "value": "Sinh("}},
    {"name": "Tan",    "signature": "Tan(value)",          "description": "Tangent (radians).", "token": {"type": "func", "value": "Tan("}},
    {"name": "Tanh",   "signature": "Tanh(value)",         "description": "Hyperbolic tangent.", "token": {"type": "func", "value": "Tanh("}},
    # Conditional / Logic
    {"name": "IIf",    "signature": "IIf(condition, trueVal, falseVal)", "description": "Inline if: returns trueVal when condition is true, else falseVal.", "token": {"type": "func", "value": "IIf("}},
    {"name": "IsNull", "signature": "IsNull(value)",       "description": "True if value is null/None.", "token": {"type": "func", "value": "IsNull("}},
    {"name": "IsNullOrEmpty","signature":"IsNullOrEmpty(value)","description":"True if null or empty string.", "token": {"type": "func", "value": "IsNullOrEmpty("}},
    {"name": "InRange","signature": "InRange(value, low, high)", "description": "True if low <= value <= high.", "token": {"type": "func", "value": "InRange("}},
    # String
    {"name": "Ascii",     "signature": "Ascii(char)",          "description": "ASCII code of first character.", "token": {"type": "func", "value": "Ascii("}},
    {"name": "Char",      "signature": "Char(code)",           "description": "Character from ASCII code.", "token": {"type": "func", "value": "Char("}},
    {"name": "CharIndex", "signature": "CharIndex(str, search)","description": "Index of first occurrence.", "token": {"type": "func", "value": "CharIndex("}},
    {"name": "Concat",    "signature": "Concat(a, b)",         "description": "Concatenate two strings.", "token": {"type": "func", "value": "Concat("}},
    {"name": "Contains",  "signature": "Contains(str, search)","description": "True if str contains search.", "token": {"type": "func", "value": "Contains("}},
    {"name": "EndsWith",  "signature": "EndsWith(str, suffix)","description": "True if str ends with suffix.", "token": {"type": "func", "value": "EndsWith("}},
    {"name": "Insert",    "signature": "Insert(str, pos, val)","description": "Insert val at position pos.", "token": {"type": "func", "value": "Insert("}},
    {"name": "Len",       "signature": "Len(str)",             "description": "Length of a string.", "token": {"type": "func", "value": "Len("}},
    {"name": "Lower",     "signature": "Lower(str)",           "description": "Convert to lowercase.", "token": {"type": "func", "value": "Lower("}},
    {"name": "Upper",     "signature": "Upper(str)",           "description": "Convert to uppercase.", "token": {"type": "func", "value": "Upper("}},
    {"name": "PadLeft",   "signature": "PadLeft(str, width)",  "description": "Left-pad string to width.", "token": {"type": "func", "value": "PadLeft("}},
    {"name": "PadRight",  "signature": "PadRight(str, width)", "description": "Right-pad string to width.", "token": {"type": "func", "value": "PadRight("}},
    {"name": "Remove",    "signature": "Remove(str, search)",  "description": "Remove all occurrences of search.", "token": {"type": "func", "value": "Remove("}},
    {"name": "Replace",   "signature": "Replace(str, old, new)","description": "Replace old with new in str.", "token": {"type": "func", "value": "Replace("}},
    {"name": "Reverse",   "signature": "Reverse(str)",         "description": "Reverse a string.", "token": {"type": "func", "value": "Reverse("}},
    {"name": "StartsWith","signature": "StartsWith(str, prefix)","description": "True if str starts with prefix.", "token": {"type": "func", "value": "StartsWith("}},
    {"name": "Substring", "signature": "Substring(str, start, len)","description": "Extract substring.", "token": {"type": "func", "value": "Substring("}},
    {"name": "Trim",      "signature": "Trim(str)",            "description": "Remove leading/trailing whitespace.", "token": {"type": "func", "value": "Trim("}},
    # Type conversion
    {"name": "ToDecimal","signature": "ToDecimal(value)",    "description": "Convert to decimal number.", "token": {"type": "func", "value": "ToDecimal("}},
    {"name": "ToDouble", "signature": "ToDouble(value)",     "description": "Convert to double-precision float.", "token": {"type": "func", "value": "ToDouble("}},
    {"name": "ToFloat",  "signature": "ToFloat(value)",      "description": "Convert to single-precision float.", "token": {"type": "func", "value": "ToFloat("}},
    {"name": "ToInt",    "signature": "ToInt(value)",        "description": "Convert to integer (truncates).", "token": {"type": "func", "value": "ToInt("}},
    {"name": "ToLong",   "signature": "ToLong(value)",       "description": "Convert to long integer.", "token": {"type": "func", "value": "ToLong("}},
    {"name": "ToStr",    "signature": "ToStr(value)",        "description": "Convert to string.", "token": {"type": "func", "value": "ToStr("}},
    # Aggregate (across all rows)
    {"name": "SUM_ALL",  "signature": "SUM_ALL(column)",     "description": "Sum of all row values for a column.", "token": {"type": "func", "value": "SUM_ALL("}},
    {"name": "MIN_ALL",  "signature": "MIN_ALL(column)",     "description": "Minimum across all rows.", "token": {"type": "func", "value": "MIN_ALL("}},
    {"name": "MAX_ALL",  "signature": "MAX_ALL(column)",     "description": "Maximum across all rows.", "token": {"type": "func", "value": "MAX_ALL("}},
    {"name": "AVG_ALL",  "signature": "AVG_ALL(column)",     "description": "Average across all rows.", "token": {"type": "func", "value": "AVG_ALL("}},
    {"name": "COUNT_ALL","signature": "COUNT_ALL(column)",   "description": "Count of non-empty values.", "token": {"type": "func", "value": "COUNT_ALL("}},
]

OPERATOR_CATALOGUE = [
    {"name": "+",   "signature": "a + b",   "description": "Addition.",             "token": {"type": "op", "value": "+"}},
    {"name": "-",   "signature": "a - b",   "description": "Subtraction.",          "token": {"type": "op", "value": "-"}},
    {"name": "*",   "signature": "a * b",   "description": "Multiplication.",       "token": {"type": "op", "value": "*"}},
    {"name": "/",   "signature": "a / b",   "description": "Division.",             "token": {"type": "op", "value": "/"}},
    {"name": "%",   "signature": "a % b",   "description": "Modulo (remainder).",   "token": {"type": "op", "value": "%"}},
    {"name": "**",  "signature": "a ** b",  "description": "Exponentiation.",       "token": {"type": "op", "value": "**"}},
    {"name": "==",  "signature": "a == b",  "description": "Equal to.",             "token": {"type": "op", "value": "=="}},
    {"name": "!=",  "signature": "a != b",  "description": "Not equal to.",         "token": {"type": "op", "value": "!="}},
    {"name": "<",   "signature": "a < b",   "description": "Less than.",            "token": {"type": "op", "value": "<"}},
    {"name": "<=",  "signature": "a <= b",  "description": "Less than or equal.",   "token": {"type": "op", "value": "<="}},
    {"name": ">",   "signature": "a > b",   "description": "Greater than.",         "token": {"type": "op", "value": ">"}},
    {"name": ">=",  "signature": "a >= b",  "description": "Greater than or equal.","token": {"type": "op", "value": ">="}},
    {"name": "And", "signature": "a And b", "description": "Logical AND.",          "token": {"type": "op", "value": " and "}},
    {"name": "Or",  "signature": "a Or b",  "description": "Logical OR.",           "token": {"type": "op", "value": " or "}},
    {"name": "Not", "signature": "Not a",   "description": "Logical NOT.",          "token": {"type": "op", "value": " not "}},
    {"name": "(",   "signature": "( ... )", "description": "Open parenthesis.",     "token": {"type": "paren", "value": "("}},
    {"name": ")",   "signature": "( ... )", "description": "Close parenthesis.",    "token": {"type": "paren", "value": ")"}},
]


def FIELD_CATALOGUE_FROM_HEADERS(headers: list) -> list:
    return [
        {
            "name": f"[{h}]",
            "signature": f"[{h}]",
            "description": f"Value of column '{h}' for the current row.",
            "token": {"type": "col", "value": h},
        }
        for h in headers
    ]


CONSTANTS_CATALOGUE = [
    {"name": "True",  "signature": "True",  "description": "Boolean true.",  "token": {"type": "num", "value": "True"}},
    {"name": "False", "signature": "False", "description": "Boolean false.", "token": {"type": "num", "value": "False"}},
    {"name": "None",  "signature": "None",  "description": "Null / missing value.", "token": {"type": "num", "value": "None"}},
    # Numeric and text constants are typed by user — entries below are placeholders shown in UI
    {"name": "Number...", "signature": "e.g. 1.5", "description": "Type a numeric constant in the input box below and click Add.", "token": None},
    {"name": "Text...",   "signature": 'e.g. "INFY"', "description": "Type a text constant (with quotes) in the input box below and click Add.", "token": None},
]


# ── Theme helper ──────────────────────────────────────────────────────────────

def _t(theme, key: str) -> str:
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "input_bg": "#0d1117", "destructive": "#da3633",
        "divider": "#2a2f36",
    }
    if theme:
        try:
            return theme.get(key)
        except Exception:
            pass
    return _FALLBACK.get(key, "#888")


def _tokens_to_text(tokens: list) -> str:
    """Convert token list to human-readable expression string."""
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
            parts.append(f"{fname}({col_arg})" if col_arg else f"{fname}(")
        else:
            parts.append(f" {val} " if kind == "op" else val)
    return "".join(parts).strip() or ""


# ── Expression Editor Dialog ──────────────────────────────────────────────────

class ExpressionEditorDialog(QDialog):
    """
    Full-screen expression editor matching the reference screenshots.
    Left nav selects section; center list shows searchable items;
    right panel shows description; top area shows live expression preview.
    """

    def __init__(self, tokens: list, lmv_headers: list,
                 strategy_col_headers: list, lmv_first_row: dict,
                 all_lmv_data: list = None,
                 theme=None, mode: str = "value", parent=None):
        super().__init__(parent)
        self._tokens = list(tokens)
        self._lmv_headers = list(lmv_headers)
        self._strategy_col_headers = list(strategy_col_headers)
        self._lmv_first_row = lmv_first_row or {}
        self._all_lmv_data  = all_lmv_data or ([lmv_first_row] if lmv_first_row else [])
        self._theme = theme
        self._mode  = mode
        self._compiled_ok = False
        self.setWindowTitle("Expression Editor")
        self.setFixedSize(900, 620)
        self._build()
        self._refresh_preview()

    # ── Build ─────────────────────────────────────────────────────────────────

    def _build(self):
        t   = self._theme
        bg  = _t(t, "background")
        cbd = _t(t, "card_bg")
        bd  = _t(t, "border")
        txt = _t(t, "text_primary")
        txts= _t(t, "text_secondary")
        acc = _t(t, "accent")
        ibg = _t(t, "input_bg")
        bbg = _t(t, "button_bg")

        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}"
            f"QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
            f"QLineEdit{{background:{ibg};color:{txt};border:1px solid {bd};"
            f"border-radius:4px;padding:4px 8px;}}"
            f"QPushButton{{background:{bbg};color:{txt};border:1px solid {bd};"
            f"border-radius:4px;padding:4px 10px;}}"
            f"QPushButton:hover{{border-color:{acc};color:{acc};}}"
            f"QListWidget{{background:{cbd};color:{txt};border:1px solid {bd};"
            f"outline:none;}}"
            f"QListWidget::item:hover{{background:{bd};}}"
            f"QListWidget::item:selected{{background:{acc};color:{bg};}}"
            f"QTextEdit{{background:{ibg};color:{txt};border:1px solid {bd};"
            f"border-radius:4px;font-family:Menlo,Consolas,monospace;}}"
            f"QScrollBar:vertical{{background:{cbd};width:6px;}}"
            f"QScrollBar::handle:vertical{{background:{bd};border-radius:3px;}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Preview area ──────────────────────────────────────────────────────
        self._preview_edit = QTextEdit()
        self._preview_edit.setReadOnly(True)
        self._preview_edit.setFixedHeight(110)
        self._preview_edit.setPlaceholderText("Expression preview…")
        self._preview_edit.setFont(QFont("Menlo,Consolas,monospace", 11))
        self._preview_edit.setStyleSheet(
            f"QTextEdit{{background:{ibg};color:{acc};border:none;"
            f"border-bottom:1px solid {bd};border-radius:0;padding:8px 12px;}}"
        )
        root.addWidget(self._preview_edit)

        # ── Three-panel body ──────────────────────────────────────────────────
        body_frame = QFrame()
        body_lay   = QHBoxLayout(body_frame)
        body_lay.setContentsMargins(0, 0, 0, 0)
        body_lay.setSpacing(0)

        # Left nav list
        self._nav_list = QListWidget()
        self._nav_list.setFixedWidth(160)
        self._nav_list.setFrameShape(QFrame.Shape.NoFrame)
        self._nav_list.setStyleSheet(
            f"QListWidget{{background:{cbd};border-right:1px solid {bd};"
            f"border-radius:0;padding:4px 0;}}"
            f"QListWidget::item{{padding:8px 14px;}}"
            f"QListWidget::item:selected{{background:{bd};color:{txt};"
            f"border-left:3px solid {acc};}}"
        )
        for section in ["Functions", "Operators", "Fields", "Constants"]:
            self._nav_list.addItem(section)
        self._nav_list.currentRowChanged.connect(self._on_nav_changed)
        body_lay.addWidget(self._nav_list)

        # Center: search + item list
        center = QWidget()
        center_lay = QVBoxLayout(center)
        center_lay.setContentsMargins(0, 0, 0, 0)
        center_lay.setSpacing(0)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search…")
        self._search_box.setFixedHeight(32)
        self._search_box.setStyleSheet(
            f"QLineEdit{{background:{ibg};border:none;border-bottom:1px solid {bd};"
            f"border-radius:0;padding:4px 10px;}}"
        )
        self._search_box.textChanged.connect(self._on_search)
        center_lay.addWidget(self._search_box)

        self._item_list = QListWidget()
        self._item_list.setFrameShape(QFrame.Shape.NoFrame)
        self._item_list.setStyleSheet(
            f"QListWidget{{background:{bg};border:none;padding:4px 0;}}"
            f"QListWidget::item{{padding:5px 10px;}}"
            f"QListWidget::item:hover{{background:{cbd};}}"
            f"QListWidget::item:selected{{background:{acc};color:{bg};}}"
        )
        self._item_list.itemClicked.connect(self._on_item_clicked)
        self._item_list.currentItemChanged.connect(self._on_item_hovered)
        center_lay.addWidget(self._item_list, 1)
        body_lay.addWidget(center, 1)

        # Right: description
        right = QWidget()
        right.setFixedWidth(220)
        right.setStyleSheet(f"background:{cbd};border-left:1px solid {bd};")
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(12, 12, 12, 12)
        right_lay.setSpacing(8)

        self._desc_sig = QLabel()
        self._desc_sig.setFont(QFont("Menlo,Consolas,monospace", 10))
        self._desc_sig.setStyleSheet(f"color:{acc};font-weight:bold;")
        self._desc_sig.setWordWrap(True)

        self._desc_body = QLabel()
        self._desc_body.setFont(font_scale.font(font_scale.SMALL, False))
        self._desc_body.setStyleSheet(f"color:{txts};")
        self._desc_body.setWordWrap(True)
        self._desc_body.setAlignment(Qt.AlignmentFlag.AlignTop)

        right_lay.addWidget(self._desc_sig)
        right_lay.addWidget(self._desc_body)
        right_lay.addStretch()
        body_lay.addWidget(right)

        root.addWidget(body_frame, 1)

        # ── Constant input row ────────────────────────────────────────────────
        const_row_w = QFrame()
        const_row_w.setFixedHeight(40)
        const_row_w.setStyleSheet(f"background:{cbd};border-top:1px solid {bd};")
        const_lay = QHBoxLayout(const_row_w)
        const_lay.setContentsMargins(12, 4, 12, 4)
        const_lay.setSpacing(8)

        lbl = QLabel("Constant:")
        lbl.setFixedWidth(70)

        self._const_input = QLineEdit()
        self._const_input.setPlaceholderText('Number or "text"…')
        self._const_input.setFixedHeight(28)
        self._const_input.setFixedWidth(180)
        self._const_input.returnPressed.connect(self._add_constant)

        add_const_btn = QPushButton("Add")
        add_const_btn.setFixedHeight(28)
        add_const_btn.setStyleSheet(
            f"QPushButton{{background:{acc};color:{bg};border:none;border-radius:4px;padding:0 12px;}}"
        )
        add_const_btn.clicked.connect(self._add_constant)

        # THIS button (only in condition mode)
        self._this_btn = QPushButton("THIS (own value)")
        self._this_btn.setFixedHeight(28)
        self._this_btn.setStyleSheet(
            "QPushButton{background:#9a670033;color:#fbbf24;"
            "border:1px solid #9a670066;border-radius:4px;padding:0 10px;}"
            "QPushButton:hover{background:#9a670066;}"
        )
        self._this_btn.clicked.connect(lambda: self._add_token({"type": "self"}))
        self._this_btn.setVisible(self._mode == "condition")

        const_lay.addWidget(lbl)
        const_lay.addWidget(self._const_input)
        const_lay.addWidget(add_const_btn)
        const_lay.addSpacing(16)
        const_lay.addWidget(self._this_btn)
        const_lay.addStretch()
        root.addWidget(const_row_w)

        # ── Quick operator toolbar ────────────────────────────────────────────
        toolbar_w = QFrame()
        toolbar_w.setFixedHeight(40)
        toolbar_w.setStyleSheet(f"background:{cbd};border-top:1px solid {bd};")
        toolbar_lay = QHBoxLayout(toolbar_w)
        toolbar_lay.setContentsMargins(12, 4, 12, 4)
        toolbar_lay.setSpacing(4)

        _QUICK_OPS = [
            ("+", {"type":"op","value":"+"}),
            ("−", {"type":"op","value":"-"}),
            ("×", {"type":"op","value":"*"}),
            ("÷", {"type":"op","value":"/"}),
            ("%", {"type":"op","value":"%"}),
            ("**",{"type":"op","value":"**"}),
            ("=", {"type":"op","value":"=="}),
            ("≠", {"type":"op","value":"!="}),
            ("<", {"type":"op","value":"<"}),
            ("≤", {"type":"op","value":"<="}),
            (">", {"type":"op","value":">"}),
            ("≥", {"type":"op","value":">="}),
            ("(",  {"type":"paren","value":"("}),
            (")",  {"type":"paren","value":")"}),
            ("And",{"type":"op","value":" and "}),
            ("Or", {"type":"op","value":" or "}),
            ("Not",{"type":"op","value":" not "}),
        ]
        for label, token in _QUICK_OPS:
            b = QPushButton(label)
            b.setFixedHeight(28)
            b.setFixedWidth(36 if len(label) <= 2 else 44)
            b.setFont(font_scale.font(font_scale.SMALL, False))
            b.setCursor(Qt.CursorShape.PointingHandCursor)
            b.clicked.connect(lambda _, tok=token: self._add_token(tok))
            toolbar_lay.addWidget(b)
        toolbar_lay.addStretch()
        root.addWidget(toolbar_w)

        # ── Bottom button row ─────────────────────────────────────────────────
        btn_row_w = QFrame()
        btn_row_w.setFixedHeight(48)
        btn_row_w.setStyleSheet(f"background:{cbd};border-top:1px solid {bd};")
        btn_row_lay = QHBoxLayout(btn_row_w)
        btn_row_lay.setContentsMargins(12, 8, 12, 8)
        btn_row_lay.setSpacing(8)

        clr_btn = QPushButton("Clear All")
        clr_btn.setFixedHeight(30)
        clr_btn.clicked.connect(self._clear)

        back_btn = QPushButton("← Backspace")
        back_btn.setFixedHeight(30)
        back_btn.clicked.connect(self._backspace)

        self._compile_btn = QPushButton("Compile & Test")
        self._compile_btn.setFixedHeight(30)
        self._compile_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{acc};"
            f"border:1px solid {acc};border-radius:4px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{acc}22;}}"
        )
        self._compile_btn.clicked.connect(self._compile_and_test)

        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedHeight(30)
        self._save_btn.setEnabled(False)
        self._save_btn.setStyleSheet(
            f"QPushButton{{background:{acc};color:{bg};"
            f"border:none;border-radius:4px;padding:0 20px;}}"
            f"QPushButton:hover{{opacity:0.9;}}"
            f"QPushButton:disabled{{background:#333;color:#666;border:none;}}"
        )
        self._save_btn.clicked.connect(self.accept)

        cancel_btn = QPushButton("Cancel")
        cancel_btn.setFixedHeight(30)
        cancel_btn.clicked.connect(self.reject)

        btn_row_lay.addWidget(clr_btn)
        btn_row_lay.addWidget(back_btn)
        btn_row_lay.addStretch()
        btn_row_lay.addWidget(self._compile_btn)
        btn_row_lay.addWidget(cancel_btn)
        btn_row_lay.addWidget(self._save_btn)
        root.addWidget(btn_row_w)

        # Select "Functions" by default
        self._current_catalogue = []
        self._nav_list.setCurrentRow(0)

    # ── Nav / Search ──────────────────────────────────────────────────────────

    def _on_nav_changed(self, row: int):
        self._search_box.clear()
        all_headers = self._lmv_headers + self._strategy_col_headers
        catalogues = [
            FUNCTION_CATALOGUE,
            OPERATOR_CATALOGUE,
            FIELD_CATALOGUE_FROM_HEADERS(all_headers),
            CONSTANTS_CATALOGUE,
        ]
        self._current_catalogue = catalogues[row] if 0 <= row < 4 else []
        self._populate_item_list(self._current_catalogue)

    def _on_search(self, text: str):
        q = text.strip().lower()
        filtered = [
            e for e in self._current_catalogue
            if q in e["name"].lower() or q in e.get("description", "").lower()
        ] if q else self._current_catalogue
        self._populate_item_list(filtered)

    def _populate_item_list(self, entries: list):
        self._item_list.clear()
        for entry in entries:
            item = QListWidgetItem(entry["name"])
            item.setData(Qt.ItemDataRole.UserRole, entry)
            self._item_list.addItem(item)

    def _on_item_hovered(self, current, _previous):
        if current is None:
            self._desc_sig.setText("")
            self._desc_body.setText("")
            return
        entry = current.data(Qt.ItemDataRole.UserRole)
        if entry:
            self._desc_sig.setText(entry.get("signature", ""))
            self._desc_body.setText(entry.get("description", ""))

    def _on_item_clicked(self, item):
        entry = item.data(Qt.ItemDataRole.UserRole)
        if entry and entry.get("token") is not None:
            self._add_token(entry["token"])

    # ── Token management ──────────────────────────────────────────────────────

    def _add_token(self, token: dict):
        self._tokens.append(dict(token))
        self._compiled_ok = False
        self._save_btn.setEnabled(False)
        self._refresh_preview()

    def _add_constant(self):
        text = self._const_input.text().strip()
        if not text:
            return
        # Detect type: quoted string → str token, else numeric
        if (text.startswith('"') and text.endswith('"')) or \
           (text.startswith("'") and text.endswith("'")):
            self._add_token({"type": "num", "value": text})
        else:
            try:
                float(text)
                self._add_token({"type": "num", "value": text})
            except ValueError:
                # Treat as a bare string constant
                self._add_token({"type": "num", "value": repr(text)})
        self._const_input.clear()

    def _clear(self):
        self._tokens.clear()
        self._compiled_ok = False
        self._save_btn.setEnabled(False)
        self._refresh_preview()

    def _backspace(self):
        if self._tokens:
            self._tokens.pop()
        self._compiled_ok = False
        self._save_btn.setEnabled(False)
        self._refresh_preview()

    # ── Preview ───────────────────────────────────────────────────────────────

    def _refresh_preview(self):
        self._preview_edit.setPlainText(_tokens_to_text(self._tokens))

    # ── Compile & Test ────────────────────────────────────────────────────────

    def _compile_and_test(self):
        from services.strategy_engine import compile_check
        ok, msg = compile_check(self._tokens, self._lmv_first_row, self._all_lmv_data)
        if ok:
            self._compiled_ok = True
            self._save_btn.setEnabled(True)
            self._preview_edit.setStyleSheet(
                f"QTextEdit{{background:#0d2116;color:#39d353;border:none;"
                f"border-bottom:1px solid {_t(self._theme,'border')};border-radius:0;padding:8px 12px;}}"
            )
            QMessageBox.information(self, "Compile OK",
                                    f"Formula compiled successfully.\n\nResult on first row: {msg}")
        else:
            self._compiled_ok = False
            self._save_btn.setEnabled(False)
            QMessageBox.warning(self, "Compile Error", f"Formula error:\n\n{msg}")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_tokens(self) -> list:
        return list(self._tokens)
