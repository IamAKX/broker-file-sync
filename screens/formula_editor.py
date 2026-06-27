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
