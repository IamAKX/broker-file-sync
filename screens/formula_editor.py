"""Expression Editor — catalogues and dialog for building formula tokens."""
import datetime as _dt
import font_scale
import os
import re
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QSplitter, QWidget,
    QListWidget, QListWidgetItem, QLabel, QLineEdit, QPushButton,
    QTextEdit, QFrame, QScrollArea, QSizePolicy, QMessageBox, QSpinBox,
    QDateEdit, QCheckBox,
)
from PySide6.QtCore import Qt, Signal, QDate
from PySide6.QtGui import QFont, QColor, QTextCursor, QTextCharFormat

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
    {"name": "Digits", "signature": "Digits(value)", "description": "Digit count of value's integer part, e.g. Digits(12123.77) = 5, Digits(2435.22) = 4. Combine with IIf to tier a threshold by price magnitude.", "token": {"type": "func", "value": "Digits("}},
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
    # Aggregate (across all rows, this tick)
    {"name": "SUM_ALL",  "signature": "SUM_ALL(column)",     "description": "Sum of all row values for a column.", "token": {"type": "func", "value": "SUM_ALL("}},
    {"name": "MIN_ALL",  "signature": "MIN_ALL(column)",     "description": "Minimum across all rows.", "token": {"type": "func", "value": "MIN_ALL("}},
    {"name": "MAX_ALL",  "signature": "MAX_ALL(column)",     "description": "Maximum across all rows.", "token": {"type": "func", "value": "MAX_ALL("}},
    {"name": "AVG_ALL",  "signature": "AVG_ALL(column)",     "description": "Average across all rows.", "token": {"type": "func", "value": "AVG_ALL("}},
    {"name": "COUNT_ALL","signature": "COUNT_ALL(column)",   "description": "Count of non-empty values.", "token": {"type": "func", "value": "COUNT_ALL("}},
    # Historic (per stock, over the last N trading days)
    {"name": "AVG_DAYS",      "signature": "AVG_DAYS(column, days)",      "description": "Average of this stock's own column value over the last N historic trading days. The column can be a raw sheet column or another of this strategy's own columns (any custom formula). Refreshes on strategy load/toggle or a manual refresh — not live every tick.", "token": {"type": "func", "value": "AVG_DAYS("}},
    {"name": "MIN_DAYS",      "signature": "MIN_DAYS(column, days)",      "description": "Minimum over the last N historic trading days, per stock.", "token": {"type": "func", "value": "MIN_DAYS("}},
    {"name": "MAX_DAYS",      "signature": "MAX_DAYS(column, days)",      "description": "Maximum over the last N historic trading days, per stock.", "token": {"type": "func", "value": "MAX_DAYS("}},
    {"name": "SUM_DAYS",      "signature": "SUM_DAYS(column, days)",      "description": "Sum over the last N historic trading days, per stock.", "token": {"type": "func", "value": "SUM_DAYS("}},
    {"name": "COUNT_DAYS",    "signature": "COUNT_DAYS(column, days)",    "description": "Count of days with usable data in the last N historic trading days, per stock.", "token": {"type": "func", "value": "COUNT_DAYS("}},
    {"name": "STDDEV_DAYS",   "signature": "STDDEV_DAYS(column, days)",   "description": "Standard deviation over the last N historic trading days, per stock.", "token": {"type": "func", "value": "STDDEV_DAYS("}},
    {"name": "MEDIAN_DAYS",   "signature": "MEDIAN_DAYS(column, days)",   "description": "Median over the last N historic trading days, per stock.", "token": {"type": "func", "value": "MEDIAN_DAYS("}},
    {"name": "VARIANCE_DAYS", "signature": "VARIANCE_DAYS(column, days)", "description": "Variance over the last N historic trading days, per stock.", "token": {"type": "func", "value": "VARIANCE_DAYS("}},
    {"name": "RANGE_DAYS",    "signature": "RANGE_DAYS(column, days)",    "description": "Max minus Min over the last N historic trading days, per stock.", "token": {"type": "func", "value": "RANGE_DAYS("}},
]

# Historic value (point lookup) — a single historic value, not an aggregate.
# Own left-nav section (not folded into Functions) so it's easy to find on
# its own. Every entry's "needs_point_picker" tells _on_item_clicked to open
# a column + (N-days-back / calendar-date / a 2nd column + N) picker and
# insert the fully-built call, rather than the plain "insert bare function
# name, user fills in the rest" flow every other catalogue entry uses. See
# services.strategy_engine's "Historic value (point lookup)"/"Historic value
# at a window extreme" docstring sections.
POINT_LOOKUP_CATALOGUE = [
    {"name": "VALUE_DAYS_AGO", "signature": "VALUE_DAYS_AGO(column, days_ago)", "description": "This stock's own column value exactly N trading days before today (0 = today/most recent). Not an aggregate — just that one day's value.", "token": {"type": "func", "value": "VALUE_DAYS_AGO(", "needs_point_picker": "days_ago"}},
    {"name": "VALUE_ON_DATE",  "signature": "VALUE_ON_DATE(column, date)",      "description": "This stock's own column value on one specific calendar date you pick — e.g. the High on a particular day.", "token": {"type": "func", "value": "VALUE_ON_DATE(", "needs_point_picker": "on_date"}},
    {"name": "VALUE_AT_MAX_DAYS", "signature": "VALUE_AT_MAX_DAYS(column, driver_column, days)", "description": "This stock's own column value on whichever of the last N historic trading days a second (driver) column was at its HIGHEST — e.g. High on the day CWTO peaked in the last 5 days. Either column can be a raw sheet column or another of this strategy's own columns.", "token": {"type": "func", "value": "VALUE_AT_MAX_DAYS(", "needs_point_picker": "extreme_days"}},
    {"name": "VALUE_AT_MIN_DAYS", "signature": "VALUE_AT_MIN_DAYS(column, driver_column, days)", "description": "Same as VALUE_AT_MAX_DAYS, but for whichever day the driver column was at its LOWEST — e.g. Low on the day CWTO bottomed in the last 5 days.", "token": {"type": "func", "value": "VALUE_AT_MIN_DAYS(", "needs_point_picker": "extreme_days"}},
    {"name": "VALUE_AT_MAX_DATES", "signature": "VALUE_AT_MAX_DATES(column, driver_column, date_from, date_to)", "description": "Same as VALUE_AT_MAX_DAYS, but over an explicit calendar date range you pick instead of \"the last N trading days\" — e.g. the High on whichever day CWTO peaked during a specific week. The range is static (typed into the formula, not rolling) — re-edit it to point at a new range, e.g. every week.", "token": {"type": "func", "value": "VALUE_AT_MAX_DATES(", "needs_point_picker": "extreme_dates"}},
    {"name": "VALUE_AT_MIN_DATES", "signature": "VALUE_AT_MIN_DATES(column, driver_column, date_from, date_to)", "description": "Same as VALUE_AT_MAX_DATES, but for whichever day in the range the driver column was at its LOWEST.", "token": {"type": "func", "value": "VALUE_AT_MIN_DATES(", "needs_point_picker": "extreme_dates"}},
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
    {"name": ",",   "signature": "f(a, b)", "description": "Argument separator.",    "token": {"type": "op",    "value": ","}},
]


def FIELD_CATALOGUE_FROM_HEADERS(headers: list) -> list:
    return [
        {
            "name": f"[{h}]",
            "signature": f"[{h}]",
            "description": (f"Value of column '{h}' for the current row. "
                            f"Click a stock in the Rows section afterward to "
                            f"reference another stock's row instead."),
            "token": {"type": "col", "value": h},
        }
        for h in headers
    ]


ROW_SYMBOL_COLUMN = "Scrip Name"


def ROW_CATALOGUE_FROM_DATA(all_data: list, symbol_col: str = ROW_SYMBOL_COLUMN) -> list:
    """One entry per distinct stock present in the loaded sheet, used to turn
    a field reference into a cross-row one, e.g. [Open] -> [Open of Nifty]."""
    seen: set = set()
    out = []
    for rd in all_data:
        sym = rd.get(symbol_col)
        if not sym:
            continue
        sym = str(sym).strip()
        key = sym.upper()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "name": sym,
            "signature": f"… of {sym}",
            "description": (f"Reference {sym}'s row instead of the current one. "
                            f"Click a Field first (e.g. [Open]), then click here "
                            f"to turn it into [Open of {sym}]."),
            "row_symbol": sym,
        })
    return out


CONSTANTS_CATALOGUE = [
    {"name": "True",  "signature": "True",  "description": "Boolean true.",  "token": {"type": "num", "value": "True"}},
    {"name": "False", "signature": "False", "description": "Boolean false.", "token": {"type": "num", "value": "False"}},
    {"name": "None",  "signature": "None",  "description": "Null / missing value.", "token": {"type": "num", "value": "None"}},
    # Numeric and text constants are typed by user — entries below are placeholders shown in UI
    {"name": "Number...", "signature": "e.g. 1.5", "description": "Type a numeric constant in the input box below and click Add.", "token": None},
    {"name": "Text...",   "signature": 'e.g. "INFY"', "description": "Type a text constant (with quotes) in the input box below and click Add.", "token": None},
]


def VARIABLE_CATALOGUE_FROM_STORE(variable_store=None) -> list:
    """One entry per saved formula variable (see services.formula_variable_store)
    — click one to insert "{Name}", which inlines that variable's own formula
    wherever it's used (services.strategy_engine._expand_var_tokens). Use
    VariablesManagerDialog (below) to create/edit/delete them.

    variable_store: defaults to services.formula_variable_store — added so
    screens.inception_strategy_builder can pass services.
    inception_formula_variable_store instead, keeping Inception's variables
    fully separate from LMV's (see that module's docstring)."""
    from services import formula_variable_store as _default_store
    var_store = variable_store or _default_store
    return [
        {
            "name": f"{{{v['name']}}}",
            "signature": f"{{{v['name']}}}",
            "description": "Reusable formula, defined in Manage Variables. "
                           "Inlined wherever it's referenced.",
            "token": {"type": "var", "value": v["name"]},
        }
        for v in var_store.load_all()
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


def _token_insert_text(tok: dict) -> str:
    """Text to splice into the expression at the cursor for one clicked token."""
    kind = tok.get("type", "op")
    val = tok.get("value", "")
    if kind == "col":
        of_sym = tok.get("of")
        return f"[{val} of {of_sym}]" if of_sym else f"[{val}]"
    if kind == "self":
        return "THIS"
    if kind == "var":
        return f"{{{val}}}"
    if kind == "func":
        fname = val.rstrip("(")
        col_arg = tok.get("col_arg", "")
        days_arg = tok.get("days_arg")
        date_arg = tok.get("date_arg")
        driver_col_arg = tok.get("driver_col_arg")
        date_from_arg = tok.get("date_from_arg")
        date_to_arg = tok.get("date_to_arg")
        # col_arg (and driver_col_arg) must round-trip back through the
        # parser (_DAYS_AGG_ARG_RE etc.) exactly as typed — its bare-
        # identifier alternative stops at the first space/dot/etc., so a
        # column name like "DAY TO" or "OR.High" only re-parses correctly
        # wrapped in [...], same as any other field reference. Rendering it
        # unbracketed here is what broke reopening a saved MAX_DAYS([DAY
        # TO], 10) for editing: it displayed as MAX_DAYS(DAY TO, 10), which
        # the parser then rejected.
        if driver_col_arg is not None and date_from_arg and date_to_arg:
            return f"{fname}([{col_arg}], [{driver_col_arg}], {date_from_arg}, {date_to_arg})"
        if driver_col_arg is not None and days_arg is not None:
            return f"{fname}([{col_arg}], [{driver_col_arg}], {days_arg})"
        if days_arg is not None:
            return f"{fname}([{col_arg}], {days_arg})"
        if date_arg:
            return f"{fname}([{col_arg}], {date_arg})"
        return f"{fname}([{col_arg}])" if col_arg else f"{fname}("
    if kind == "op" and val == ",":
        return ", "
    if kind == "op":
        return f" {val.strip()} "
    return val


def _tokens_to_text(tokens: list) -> str:
    """Convert an initial token list (as loaded from storage) into the
    plain-text expression shown in the editable preview box."""
    return "".join(_token_insert_text(tok) for tok in tokens).strip()


# ── Freeform text → token parser ──────────────────────────────────────────────
# The preview box is a normal editable text field (click anywhere, type,
# backspace at the cursor). services.strategy_engine and everywhere the
# formula/condition/row-filter is persisted still work in terms of the
# structured token list, so on Compile/Save we re-parse the current text.

_AGG_FUNCS = {"sum_all", "min_all", "max_all", "avg_all", "count_all"}
# Historic (N days) aggregates — same shape as _AGG_FUNCS but two args:
# AVG_DAYS(column, days). See services/strategy_engine.py's _DAYS_AGG_BASE.
_DAYS_AGG_FUNCS = {
    "sum_days", "min_days", "max_days", "avg_days", "count_days",
    "stddev_days", "median_days", "variance_days", "range_days",
}
# Historic value (point lookup) — VALUE_DAYS_AGO shares the days-arg text
# shape with the _DAYS family above (column, N); VALUE_ON_DATE takes a
# column + one calendar date instead. See services/strategy_engine.py's
# "Historic value (point lookup)" docstring section.
_POINT_DAYS_AGO_FUNCS = {"value_days_ago"}
_ON_DATE_FUNCS = {"value_on_date"}
# Same (column, N) text shape as the days-ago family above, but N means
# "months to search back" for VALUE_BEFORE_CHANGE, not "days ago" — see
# services/strategy_engine.py's VALUE_BEFORE_CHANGE_TAG docstring.
# Inception-only (services.inception_value_before_change).
_VALUE_BEFORE_CHANGE_FUNCS = {"value_before_change"}
# Historic value at a window extreme — TWO column args (the value to fetch,
# then the driver column that decides which of the last N days wins) plus a
# days count. See services/strategy_engine.py's "Historic value at a window
# extreme" docstring section.
_VALUE_AT_EXTREME_FUNCS = {"value_at_max_days", "value_at_min_days"}
# Same as above, but a "date_from, date_to" calendar range instead of a
# days count — VALUE_AT_MAX_DATES paragraph of the same docstring section.
_VALUE_AT_EXTREME_DATE_FUNCS = {"value_at_max_dates", "value_at_min_dates"}
_WORD_OPS = {"and": " and ", "or": " or ", "not": " not "}
_WORD_CONSTS = {"true": "True", "false": "False", "none": "None"}

_TOKEN_RE = re.compile(r"""
      (?P<ws>\s+)
    | (?P<field>\[[^\]]*\])
    | (?P<var>\{[^{}]*\})
    | (?P<dstring>"[^"]*")
    | (?P<sstring>'[^']*')
    | (?P<number>\d+\.\d+|\.\d+|\d+\.|\d+)
    | (?P<word>[A-Za-z_][A-Za-z0-9_]*)
    | (?P<op3>\*\*)
    | (?P<op2>==|!=|<=|>=)
    | (?P<lparen>\()
    | (?P<rparen>\))
    | (?P<comma>,)
    | (?P<op1>[+\-*/%<>])
""", re.VERBOSE)

_AGG_ARG_RE = re.compile(
    r"""\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')\s*\)"""
)

# Same column-argument shapes as _AGG_ARG_RE, plus a required ", <days>"
# before the closing paren — e.g. "[High], 20)" or "High, 20)".
_DAYS_AGG_ARG_RE = re.compile(
    r"""\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')"""
    r"""\s*,\s*(\d+)\s*\)"""
)

# Same column-argument shapes as _AGG_ARG_RE, plus a required
# ", <YYYY-MM-DD>" before the closing paren — e.g. "[High], 2026-07-15)".
_ON_DATE_ARG_RE = re.compile(
    r"""\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')"""
    r"""\s*,\s*(\d{4}-\d{2}-\d{2})\s*\)"""
)

# TWO column arguments (same shapes as _AGG_ARG_RE, each) plus a required
# ", <days>" before the closing paren — e.g. "[High], [CWTO], 5)". Used by
# VALUE_AT_MAX_DAYS(value_col, driver_col, days)/VALUE_AT_MIN_DAYS(...).
_TWO_COL_DAYS_ARG_RE = re.compile(
    r"""\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')"""
    r"""\s*,\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')"""
    r"""\s*,\s*(\d+)\s*\)"""
)

# Same TWO column arguments as _TWO_COL_DAYS_ARG_RE, but a required
# ", <date_from>, <date_to>" (each YYYY-MM-DD) before the closing paren
# instead of a days count — e.g. "[High], [CWTO], 2026-08-10, 2026-08-14)".
# Used by VALUE_AT_MAX_DATES(value_col, driver_col, date_from, date_to)/
# VALUE_AT_MIN_DATES(...).
_TWO_COL_DATE_RANGE_ARG_RE = re.compile(
    r"""\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')"""
    r"""\s*,\s*(?:\[([^\]]*)\]|([A-Za-z_][A-Za-z0-9_]*)|"([^"]*)"|'([^']*)')"""
    r"""\s*,\s*(\d{4}-\d{2}-\d{2})\s*,\s*(\d{4}-\d{2}-\d{2})\s*\)"""
)

# Splits "[Open of Nifty]" bracket content on the LAST " of " (greedy left
# group backtracks to the rightmost match), so "X of Y of Z" reads as
# column "X of Y", stock "Z" — the stock name is what trails.
_OF_SPLIT_RE = re.compile(r"^(.*\S)\s+of\s+(\S.*)$", re.IGNORECASE)


def _split_field_of(inner: str, known_headers=None):
    """Split a "[...]" bracket's inner text into (column, of_symbol|None).

    A bracket whose full text is itself a known header wins outright, so
    headers that happen to contain " of " (e.g. "% of Day Range") keep
    working unchanged. Otherwise, "Column of Symbol" splits into a
    cross-row reference; plain "Column" (no " of ") is unaffected.
    """
    if known_headers is not None and inner in known_headers:
        return inner, None
    m = _OF_SPLIT_RE.match(inner)
    if m:
        return m.group(1), m.group(2)
    return inner, None


def _try_consume_aggregate_arg(text: str, start: int, func_name_lower: str):
    """For SUM_ALL(...)-style aggregates, try to read the single column
    argument up to the matching ')'; for AVG_DAYS(...)/VALUE_DAYS_AGO(...)-
    style functions, the column argument plus a required ", <days>"; for
    VALUE_BEFORE_CHANGE(...), the column argument plus EITHER a ", <days>"
    (months_back) OR nothing at all — VALUE_BEFORE_CHANGE([col]) is the
    "auto" day-granularity form, see services.inception_value_before_change;
    for VALUE_ON_DATE(...), the column argument plus a required
    ", <YYYY-MM-DD>"; for VALUE_AT_MAX_DAYS(...)/VALUE_AT_MIN_DAYS(...), TWO
    column arguments plus a required ", <days>"; for VALUE_AT_MAX_DATES(...)/
    VALUE_AT_MIN_DATES(...), TWO column arguments plus a required
    ", <date_from>, <date_to>". Returns (pos_after_close_paren, col_name,
    extra) on success — extra is a dict of additional token fields
    ({"days_arg": N} or {"date_arg": "..."} or {"driver_col_arg": "...",
    "days_arg": N} or {"driver_col_arg": "...", "date_from_arg": "...",
    "date_to_arg": "..."} or {}) — else (start, None, {}) so the caller
    falls back to normal tokens."""
    if func_name_lower in _AGG_FUNCS:
        m = _AGG_ARG_RE.match(text, start)
        if not m:
            return start, None, {}
        col = next(g for g in m.groups() if g is not None)
        return m.end(), col, {}
    if (func_name_lower in _DAYS_AGG_FUNCS or func_name_lower in _POINT_DAYS_AGO_FUNCS
            or func_name_lower in _VALUE_BEFORE_CHANGE_FUNCS):
        m = _DAYS_AGG_ARG_RE.match(text, start)
        if m:
            *col_groups, days = m.groups()
            col = next(g for g in col_groups if g is not None)
            return m.end(), col, {"days_arg": int(days)}
        # VALUE_BEFORE_CHANGE(column) — no months_back arg at all is valid
        # too: "auto", day-granularity search until a differing value turns
        # up (see services.inception_value_before_change). AVG_DAYS/
        # VALUE_DAYS_AGO/etc keep requiring the ", <days>" form — a bare
        # AVG_DAYS([High]) still falls through to "not recognized" below.
        if func_name_lower in _VALUE_BEFORE_CHANGE_FUNCS:
            m = _AGG_ARG_RE.match(text, start)
            if m:
                col = next(g for g in m.groups() if g is not None)
                return m.end(), col, {}
        return start, None, {}
    if func_name_lower in _ON_DATE_FUNCS:
        m = _ON_DATE_ARG_RE.match(text, start)
        if not m:
            return start, None, {}
        *col_groups, when = m.groups()
        col = next(g for g in col_groups if g is not None)
        return m.end(), col, {"date_arg": when}
    if func_name_lower in _VALUE_AT_EXTREME_FUNCS:
        m = _TWO_COL_DAYS_ARG_RE.match(text, start)
        if not m:
            return start, None, {}
        *col_groups, days = m.groups()
        col = next(g for g in col_groups[:4] if g is not None)
        driver_col = next(g for g in col_groups[4:] if g is not None)
        return m.end(), col, {"driver_col_arg": driver_col, "days_arg": int(days)}
    if func_name_lower in _VALUE_AT_EXTREME_DATE_FUNCS:
        m = _TWO_COL_DATE_RANGE_ARG_RE.match(text, start)
        if not m:
            return start, None, {}
        *col_groups, date_from, date_to = m.groups()
        col = next(g for g in col_groups[:4] if g is not None)
        driver_col = next(g for g in col_groups[4:] if g is not None)
        return m.end(), col, {"driver_col_arg": driver_col, "date_from_arg": date_from, "date_to_arg": date_to}
    return start, None, {}


class FormulaParseError(ValueError):
    """A parse failure that also knows which part of the formula text is at
    fault, so the editor can point the user straight at it instead of just
    describing the problem in words. ``start``/``end`` are character offsets
    into the original text (end exclusive) suitable for highlighting."""

    def __init__(self, message: str, start: int, end: int | None = None):
        super().__init__(message)
        self.start = start
        self.end = end if end is not None else start + 1


# open char -> (matching close char, what it starts, example to show when unclosed)
_BRACKET_KINDS = {
    "[": ("]", "field", " Add a ']' right after the column name, e.g. [Open]."),
    "{": ("}", "variable reference", " Add a '}' right after the variable name, e.g. {ThresholdName}."),
    "(": (")", "group", " Add a ')' to close it."),
}
_CLOSE_TO_OPEN = {close: open_ch for open_ch, (close, _, _) in _BRACKET_KINDS.items()}


def _find_structural_error(text: str):
    """Scan the raw formula text for an unclosed/unmatched '[', ']', '{', '}',
    '(' or ')' — the single most common mistake non-technical users make —
    and report exactly where it is, in plain language.

    Returns (message, start, end) for the first problem found, or None if
    every bracket/brace/paren balances out (the rest of parsing may still
    fail for other reasons — this is just the first, cheapest check).
    """
    stack = []  # [(open_char, position), ...]
    i, n = 0, len(text)
    while i < n:
        ch = text[i]
        if ch in ('"', "'"):
            close = text.find(ch, i + 1)
            if close == -1:
                kind = "double" if ch == '"' else "single"
                return (f"There's a {kind} quote at position {i + 1} that's "
                        f"never closed. Add a matching {ch} to finish it.",
                        i, n)
            i = close + 1
            continue
        if ch in _BRACKET_KINDS:
            stack.append((ch, i))
        elif ch in _CLOSE_TO_OPEN:
            expected_open = _CLOSE_TO_OPEN[ch]
            if stack and stack[-1][0] == expected_open:
                stack.pop()
            elif stack:
                open_ch, open_pos = stack[-1]
                expected_close, _, _ = _BRACKET_KINDS[open_ch]
                return (f"The '{open_ch}' at position {open_pos + 1} is closed "
                        f"with '{ch}' instead of '{expected_close}'. Use "
                        f"'{expected_close}' to close it.", open_pos, i + 1)
            else:
                _, label, _ = _BRACKET_KINDS[expected_open]
                return (f"There's a closing '{ch}' at position {i + 1} with no "
                        f"'{expected_open}' before it to match. Remove it, or "
                        f"add a '{expected_open}' where the {label} should start.",
                        i, i + 1)
        i += 1

    if stack:
        ch, pos = stack[-1]
        close, label, hint = _BRACKET_KINDS[ch]
        return (f"The {label} starting with '{ch}' at position {pos + 1} is "
                f"missing its closing '{close}'.{hint}", pos, n)
    return None


def parse_expression_text(text: str, known_headers=None) -> list:
    """Parse the preview box's plain text into the structured token list.
    Raises FormulaParseError (a ValueError) with a human-readable message
    and the character span at fault on malformed input.

    ``known_headers``, when given, disambiguates "[Col of Symbol]" from a
    literal header that happens to contain " of " — see _split_field_of.
    """
    tokens = []
    pos, n = 0, len(text)
    while pos < n:
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise FormulaParseError(
                f"The character '{text[pos]}' at position {pos + 1} isn't "
                f"something this formula understands. Remove it or fix the typo.",
                pos, pos + 1,
            )
        kind = m.lastgroup
        val = m.group(kind)
        pos = m.end()

        if kind == "ws":
            continue
        if kind == "field":
            col, of_sym = _split_field_of(val[1:-1], known_headers)
            tok = {"type": "col", "value": col}
            if of_sym:
                tok["of"] = of_sym
            tokens.append(tok)
        elif kind == "var":
            tokens.append({"type": "var", "value": val[1:-1]})
        elif kind in ("dstring", "sstring", "number"):
            tokens.append({"type": "num", "value": val})
        elif kind == "word":
            low = val.lower()
            if low in _WORD_OPS:
                tokens.append({"type": "op", "value": _WORD_OPS[low]})
            elif low == "this":
                tokens.append({"type": "self"})
            elif low in _WORD_CONSTS:
                tokens.append({"type": "num", "value": _WORD_CONSTS[low]})
            else:
                look = pos
                while look < n and text[look].isspace():
                    look += 1
                if look < n and text[look] == "(":
                    consumed_to, col_arg, extra = _try_consume_aggregate_arg(text, look + 1, low)
                    if col_arg is not None:
                        tok = {"type": "func", "value": f"{val}(", "col_arg": col_arg, **extra}
                        tokens.append(tok)
                        pos = consumed_to
                    else:
                        tokens.append({"type": "func", "value": f"{val}("})
                        pos = look + 1
                else:
                    raise FormulaParseError(
                        f"'{val}' isn't a recognized column, function, or word. "
                        f"If you meant a column, wrap it in brackets like [{val}]. "
                        f"If you meant a function, check the spelling — a function "
                        f"name must be followed by '(', e.g. {val}(...).",
                        pos - len(val), pos,
                    )
        elif kind in ("op3", "op2", "op1"):
            tokens.append({"type": "op", "value": val})
        elif kind == "lparen":
            tokens.append({"type": "paren", "value": "("})
        elif kind == "rparen":
            tokens.append({"type": "paren", "value": ")"})
        elif kind == "comma":
            tokens.append({"type": "op", "value": ","})
    return tokens


# ── Point-lookup pickers: column, then N-days-back or a calendar date ──────

class _ColumnPickerDialog(QDialog):
    """Small searchable list to pick one column — the Fields list can run to
    100+ entries once Formula Builder fields are mixed in (see
    services.formula_tokens.all_field_codes), so this needs a filter box."""

    def __init__(self, columns: list, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._columns = list(columns)
        self._column = None
        self.setWindowTitle("Pick a Column")
        self.setFixedSize(320, 420)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
        )
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.setContentsMargins(14, 14, 14, 14)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search columns…")
        self._search.textChanged.connect(self._refresh_list)
        lay.addWidget(self._search)

        self._list = QListWidget()
        self._list.setFrameShape(QFrame.Shape.NoFrame)
        self._list.itemClicked.connect(self._on_pick)
        lay.addWidget(self._list, 1)

        self._refresh_list("")
        self._search.setFocus()

    def _refresh_list(self, query: str):
        self._list.clear()
        q = query.strip().lower()
        for c in self._columns:
            if q and q not in c.lower():
                continue
            self._list.addItem(c)

    def _on_pick(self, item):
        self._column = item.text()
        self.accept()

    def selected_column(self):
        return self._column


class _DaysAgoPickerDialog(QDialog):
    """Step 2 of building VALUE_DAYS_AGO: how many trading days back from
    today (0 = today/most recent)."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("VALUE_DAYS_AGO — Days Back")
        self.setFixedWidth(300)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Trading days before today (0 = today/most recent):"))
        self._spin = QSpinBox()
        self._spin.setRange(0, 3650)
        self._spin.setValue(1)
        lay.addWidget(self._spin)
        ok = QPushButton("OK")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)

    def selected_n(self) -> int:
        return self._spin.value()


class _DaysCountPickerDialog(QDialog):
    """Step 3 of building VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS: a plain
    window size — "the last N trading days" — not "days ago" like
    _DaysAgoPickerDialog above (N=0 would mean an empty window here, so the
    minimum is 1)."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Number of Trading Days")
        self.setFixedWidth(300)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.addWidget(QLabel("Look at the last N trading days:"))
        self._spin = QSpinBox()
        self._spin.setRange(1, 3650)
        self._spin.setValue(5)
        lay.addWidget(self._spin)
        ok = QPushButton("OK")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)

    def selected_n(self) -> int:
        return self._spin.value()


class _MonthsBackPickerDialog(QDialog):
    """Step 2 of building VALUE_BEFORE_CHANGE (screens.
    inception_strategy_builder, Inception-only): either a plain calendar-
    months window (same shape as _DaysCountPickerDialog, a positive N,
    minimum 1) or the "auto" no-argument form — walk back day by day
    (not month-ends) until a differing value turns up, no unit to name at
    all, capped at services.inception_value_before_change.
    VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS trading days. The auto checkbox is
    the answer to "it doesn't change monthly, it changes every week — why
    do I have to say a number of months at all": selected_n() returning
    None tells the caller to insert the bare VALUE_BEFORE_CHANGE([col])
    form (see _open_point_lookup_picker)."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("VALUE_BEFORE_CHANGE — Search Range")
        self.setFixedWidth(340)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}QCheckBox{{background:transparent;}}"
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(10)

        # Unchecked by default — reported as confusing the other way round
        # (checked by default): a user opening this picker for the first
        # time sees a pre-checked box and a greyed-out "12" and reads it as
        # "the number is stuck at 12, I can't change it" rather than "auto
        # mode is on". Defaulting to unchecked keeps the familiar "type a
        # number" behavior the spinbox always had; auto is one click away
        # for anyone who wants it.
        self._auto_check = QCheckBox("Just find the previous changed value")
        self._auto_check.toggled.connect(self._on_auto_toggled)
        lay.addWidget(self._auto_check)

        auto_hint = QLabel(
            "No month limit — searches day by day (not just month-ends), "
            "up to about a year back."
        )
        auto_hint.setWordWrap(True)  # QLabel supports this; QCheckBox does not
        lay.addWidget(auto_hint)

        self._n_label = QLabel("Or search back up to N calendar months instead:")
        lay.addWidget(self._n_label)
        self._spin = QSpinBox()
        self._spin.setRange(1, 120)
        self._spin.setValue(12)
        lay.addWidget(self._spin)

        ok = QPushButton("OK")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self.accept)
        lay.addWidget(ok)

    def _on_auto_toggled(self, checked: bool):
        self._n_label.setEnabled(not checked)
        self._spin.setEnabled(not checked)

    def selected_n(self):
        """None ("auto") for the day-granularity no-argument form, else the
        chosen months-back count."""
        if self._auto_check.isChecked():
            return None
        return self._spin.value()


class _DateRangePickerDialog(QDialog):
    """Step 3 of building VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES: an explicit
    From/To calendar range — plain QDateEdit fields (no availability dots;
    unlike _OnDatePickerDialog's single-date pick, a range doesn't need
    per-day "has data" markers to be usable) same as screens.inception_hmv's
    own From/To pickers. Static, not rolling — the resulting formula embeds
    these two exact dates and needs re-editing (this same dialog, reopened)
    to point at a different range later, e.g. every week."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setWindowTitle("Pick a Date Range")
        self.setFixedWidth(320)
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 16)

        today = QDate.currentDate()
        week_ago = today.addDays(-7)

        from_row = QHBoxLayout()
        from_row.addWidget(QLabel("From:"))
        self._from_edit = QDateEdit()
        self._from_edit.setCalendarPopup(True)
        self._from_edit.setDisplayFormat("dd-MMM-yyyy")
        self._from_edit.setDate(week_ago)
        from_row.addWidget(self._from_edit)
        lay.addLayout(from_row)

        to_row = QHBoxLayout()
        to_row.addWidget(QLabel("To:"))
        self._to_edit = QDateEdit()
        self._to_edit.setCalendarPopup(True)
        self._to_edit.setDisplayFormat("dd-MMM-yyyy")
        self._to_edit.setDate(today)
        to_row.addWidget(self._to_edit)
        lay.addLayout(to_row)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet(f"color:{_t(theme, 'status_red')};")
        self._error_lbl.setWordWrap(True)
        lay.addWidget(self._error_lbl)

        ok = QPushButton("OK")
        ok.setCursor(Qt.CursorShape.PointingHandCursor)
        ok.clicked.connect(self._on_ok)
        lay.addWidget(ok)

    def _on_ok(self):
        if self._from_edit.date() > self._to_edit.date():
            self._error_lbl.setText("From date must be on or before To date.")
            return
        self.accept()

    def selected_range(self) -> tuple[_dt.date, _dt.date]:
        f, t = self._from_edit.date(), self._to_edit.date()
        return (_dt.date(f.year(), f.month(), f.day()),
                _dt.date(t.year(), t.month(), t.day()))


class _OnDatePickerDialog(QDialog):
    """Step 2 of building VALUE_ON_DATE: pick one calendar date. Uses the
    same dotted-availability calendar as historic_upload.py's Browse tab
    (components.availability_calendar) so the user can see which dates
    actually have saved data before picking one."""

    def __init__(self, theme, availability_fetcher, parent=None):
        super().__init__(parent)
        from components.availability_calendar import AvailabilityCalendar, themed_calendar_stylesheet
        self._theme = theme
        self._fetch_availability = availability_fetcher
        self._date = _dt.date.today()
        self.setWindowTitle("VALUE_ON_DATE — Pick a Date")
        bg, txt = _t(theme, "background"), _t(theme, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
        )
        lay = QVBoxLayout(self)
        lay.setSpacing(10)
        lay.setContentsMargins(16, 16, 16, 16)

        self._cal = AvailabilityCalendar(theme)
        self._cal.setStyleSheet(themed_calendar_stylesheet(theme))
        self._cal.clicked.connect(self._on_date_picked)
        self._cal.currentPageChanged.connect(self._on_page_changed)
        lay.addWidget(self._cal)

        self._status_lbl = QLabel("")
        self._status_lbl.setStyleSheet(f"color:{_t(theme, 'text_secondary')};")
        lay.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        ok_btn = QPushButton("OK")
        ok_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        ok_btn.setStyleSheet(
            f"QPushButton{{background:{_t(theme,'accent')};color:{_t(theme,'background')};"
            f"border:none;border-radius:4px;padding:6px 16px;}}"
        )
        ok_btn.clicked.connect(self.accept)
        btn_row.addWidget(ok_btn)
        lay.addLayout(btn_row)

        today = _dt.date.today()
        self._refresh_availability(today.year, today.month)

    def _on_date_picked(self, qdate):
        self._date = _dt.date(qdate.year(), qdate.month(), qdate.day())

    def _on_page_changed(self, year, month):
        self._refresh_availability(year, month)

    def _refresh_availability(self, year: int, month: int):
        import calendar as _cal_mod
        last_day = _cal_mod.monthrange(year, month)[1]
        from api.exceptions import ApiError, NetworkError
        try:
            result = self._fetch_availability(_dt.date(year, month, 1), _dt.date(year, month, last_day))
            days = {
                _dt.date.fromisoformat(d["trade_date"]).day
                for d in result.get("dates", []) if d.get("has_data")
            }
        except (ApiError, NetworkError, KeyError, ValueError, TypeError):
            self._cal.set_available_days(set())
            self._status_lbl.setText("Couldn't load data availability for this month.")
            return
        self._cal.set_available_days(days)

    def selected_date(self) -> _dt.date:
        return self._date


# ── Expression Editor Dialog ──────────────────────────────────────────────────

class ExpressionEditorDialog(QDialog):
    """
    Full-screen expression editor matching the reference screenshots.
    Left nav selects section; center list shows searchable items;
    right panel shows description; top area shows live expression preview.
    """

    #: Full nav order — every existing (LMV) caller gets exactly this list
    #: since sections defaults to None. See screens.inception_strategy_builder
    #: for a caller that trims it ("Rows" doesn't apply there; "Historic
    #: Value" stays but is scoped down via historic_value_catalogue).
    _ALL_SECTIONS = ["Functions", "Historic Value", "Operators", "Fields", "Rows", "Constants", "Variables"]

    def __init__(self, tokens: list, lmv_headers: list,
                 strategy_col_headers: list, lmv_first_row: dict,
                 all_lmv_data: list = None,
                 theme=None, mode: str = "value", self_value=None,
                 allow_self: bool = None, extra_row_values: dict = None,
                 real_lmv_headers: list = None,
                 sections: list = None, variable_store=None,
                 extra_functions: list = None,
                 historic_value_catalogue: list = None,
                 parent=None):
        """sections/variable_store: added for screens.inception_strategy_builder's
        reuse of this dialog with Inception's own field set — both default to
        the exact prior behavior (full 7-section nav, services.
        formula_variable_store), so every existing (LMV) call site is
        unaffected. sections lets a caller drop nav entries that don't apply
        to it (Inception has no cross-row "of Symbol" support, so it drops
        "Rows"); variable_store swaps which store's variables the Variables
        tab/"Save as Variable" reads and writes.

        historic_value_catalogue: overrides what the "Historic Value" nav
        entry lists (defaults to the full POINT_LOOKUP_CATALOGUE, i.e. every
        existing LMV call site is unaffected) — for a caller whose engine
        can't resolve every POINT_LOOKUP_CATALOGUE entry, e.g. screens.
        inception_strategy_builder's INCEPTION_HISTORIC_VALUE_CATALOGUE,
        which keeps VALUE_DAYS_AGO/VALUE_ON_DATE (services.
        inception_day_history resolves these for raw OHLCV fields, same
        "blank on an unresolvable column" convention as Functions' own
        AVG_DAYS/etc already carry for Inception) and adds Inception-only
        VALUE_BEFORE_CHANGE (services.inception_value_before_change; LMV's
        engine can't resolve it at all — see services.strategy_engine.
        VALUE_BEFORE_CHANGE_TAG), while dropping VALUE_AT_MAX_DAYS/
        VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES, which
        Inception's day_history has no driver-column-extreme resolution for
        at all and would always evaluate to None.

        extra_functions: additional entries (same {"name", "signature",
        "description", "token"} shape as FUNCTION_CATALOGUE) appended to the
        "Functions" section for just this instance, rather than mutating the
        shared FUNCTION_CATALOGUE list every caller (including LMV's) draws
        from — for a function only ONE caller's engine can actually resolve,
        so it isn't offered somewhere it would silently always evaluate to
        None. Defaults to None (nothing extra), the exact prior behavior.
        """
        super().__init__(parent)
        self._initial_tokens = list(tokens)
        self._lmv_headers = list(lmv_headers)
        self._strategy_col_headers = list(strategy_col_headers)
        self._sections = list(sections) if sections is not None else list(self._ALL_SECTIONS)
        self._variable_store = variable_store
        self._extra_functions = list(extra_functions) if extra_functions else []
        self._historic_value_catalogue = (
            list(historic_value_catalogue) if historic_value_catalogue is not None
            else POINT_LOOKUP_CATALOGUE
        )
        # The sheet's OWN currently-loaded columns — a strict subset of
        # self._lmv_headers above, which is really "every name offered in
        # the Fields list" (Formula Builder fields, other strategy columns,
        # ...). Passed separately so _compile_and_test can tell "this cell
        # is blank" (a real data problem, held to a strict value) apart
        # from "this field's value depends on historic/network data this
        # editor doesn't always have fetched" (see compile_check's
        # lmv_headers param) — falls back to lmv_headers (no distinction,
        # the old stricter behaviour) for any caller that doesn't pass it.
        self._real_lmv_headers = (
            list(real_lmv_headers) if real_lmv_headers is not None
            else list(lmv_headers)
        )
        # Computed strategy-column values (name -> value) merged into the test
        # row so a row filter can be compiled against the columns it references.
        self._extra_row_values = dict(extra_row_values or {})
        # A copy, not the caller's own dict — self._lmv_headers can include
        # Fields list entries the caller doesn't have a real value for yet
        # (e.g. a Formula Builder field not currently produced by External
        # Import — see StrategyEditor._field_names), backfilled to None
        # below so compile_check's "unknown column" check (key presence,
        # not value) doesn't reject a reference to one. Mutating the
        # caller's own row dict in place would leak those None-valued keys
        # into whatever else it's shared with (e.g. StrategyEditor's own
        # column-value evaluation).
        self._lmv_first_row = dict(lmv_first_row or {})
        for h in self._lmv_headers:
            self._lmv_first_row.setdefault(h, None)
        self._all_lmv_data  = all_lmv_data or ([lmv_first_row] if lmv_first_row else [])
        self._theme = theme
        self._mode  = mode
        self._self_value = self_value
        # THIS (own value) only makes sense for a single column's fmt rule.
        # Row filters span multiple columns, so they reference columns by name
        # instead — allow_self defaults to on for conditions unless disabled.
        self._allow_self = (mode == "condition") if allow_self is None else allow_self
        self._compiled_ok = False
        self._compiled_tokens = None
        self.setWindowTitle("Expression Editor")
        self.setFixedSize(900, 620)
        self._build()
        self._preview_edit.setPlainText(_tokens_to_text(self._initial_tokens))
        # Start editing at the end of any pre-loaded formula, not position 0,
        # so typing/Backspace/toolbar clicks continue naturally from there.
        end_cursor = self._preview_edit.textCursor()
        end_cursor.movePosition(QTextCursor.MoveOperation.End)
        self._preview_edit.setTextCursor(end_cursor)

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
        # A normal editable text field: click anywhere to place the cursor,
        # type or Backspace like any text box. Catalogue/toolbar clicks insert
        # their token text at the cursor instead of always appending at the end.
        self._preview_edit = QTextEdit()
        self._preview_edit.setFixedHeight(110)
        self._preview_edit.setPlaceholderText("Expression preview…")
        self._preview_edit.setAcceptRichText(False)
        self._preview_edit.setFont(QFont("Menlo,Consolas,monospace", 11))
        self._preview_edit.textChanged.connect(self._on_text_changed)

        self._preview_ibg = ibg
        self._preview_acc = acc
        self._preview_bd = bd
        self._set_preview_style(compiled=False)
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
        for section in self._sections:
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

        # Right: description — scrollable, since a long entry (e.g.
        # VALUE_BEFORE_CHANGE's multi-paragraph description) can easily run
        # taller than the dialog's own height; without a scroll area the
        # text just gets clipped at the bottom with no way to read the
        # rest (reported: the "months_back" walkthrough was cut off
        # mid-sentence). setWidgetResizable(True) lets the inner widget
        # size itself to its content (so short descriptions still just sit
        # at the top, no dead scroll space) while the QScrollArea itself
        # stays fixed to the panel's allotted height.
        right = QWidget()
        right.setFixedWidth(220)
        right.setStyleSheet(f"background:{cbd};border-left:1px solid {bd};")
        right_outer_lay = QVBoxLayout(right)
        right_outer_lay.setContentsMargins(0, 0, 0, 0)
        right_outer_lay.setSpacing(0)

        desc_scroll = QScrollArea()
        desc_scroll.setWidgetResizable(True)
        desc_scroll.setFrameShape(QFrame.Shape.NoFrame)
        desc_scroll.setStyleSheet("background:transparent;")
        # A word-wrapping QLabel inside setWidgetResizable(True) has no
        # inherent width limit of its own — left alone, it reports its
        # UNWRAPPED preferred width as its size hint, so the scroll area
        # grows sideways to fit instead of wrapping. Disable horizontal
        # scrolling entirely; the explicit setMaximumWidth on the labels
        # below is what actually makes them wrap.
        desc_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        desc_inner = QWidget()
        desc_inner.setStyleSheet("background:transparent;")
        right_lay = QVBoxLayout(desc_inner)
        right_lay.setContentsMargins(12, 12, 12, 12)
        right_lay.setSpacing(8)

        # right's own fixed width (220) minus its layout margins (12+12)
        # and a little slack for the panel's vertical scrollbar when one
        # is showing — without this cap the labels below default to their
        # unwrapped natural width (see desc_scroll's own comment above).
        _desc_label_max_width = 220 - 24 - 12

        self._desc_sig = QLabel()
        self._desc_sig.setFont(QFont("Menlo,Consolas,monospace", 10))
        self._desc_sig.setStyleSheet(f"color:{acc};font-weight:bold;")
        self._desc_sig.setWordWrap(True)
        self._desc_sig.setMaximumWidth(_desc_label_max_width)

        self._desc_body = QLabel()
        self._desc_body.setFont(font_scale.font(font_scale.SMALL, False))
        self._desc_body.setStyleSheet(f"color:{txts};")
        self._desc_body.setWordWrap(True)
        self._desc_body.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._desc_body.setMaximumWidth(_desc_label_max_width)

        right_lay.addWidget(self._desc_sig)
        right_lay.addWidget(self._desc_body)
        right_lay.addStretch()

        desc_scroll.setWidget(desc_inner)
        right_outer_lay.addWidget(desc_scroll)
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
        self._this_btn.setVisible(self._allow_self)

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
            (",",  {"type":"op","value":","}),
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

        # Saves the whole current (compiled) formula as a reusable named
        # variable — see services.formula_variable_store — so it can be
        # inserted into other formulas from the Variables tab instead of
        # retyped. Gated on a successful compile the same as Save, since an
        # unresolved formula shouldn't be reusable elsewhere either.
        self._save_var_btn = QPushButton("Save as Variable…")
        self._save_var_btn.setFixedHeight(30)
        self._save_var_btn.setEnabled(False)
        self._save_var_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{acc};"
            f"border:1px solid {acc};border-radius:4px;padding:0 14px;}}"
            f"QPushButton:hover{{background:{acc}22;}}"
            f"QPushButton:disabled{{background:transparent;color:#666;border:1px solid #333;}}"
        )
        self._save_var_btn.clicked.connect(self._save_as_variable)

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
        btn_row_lay.addWidget(self._save_var_btn)
        btn_row_lay.addWidget(cancel_btn)
        btn_row_lay.addWidget(self._save_btn)
        root.addWidget(btn_row_w)

        # Select "Functions" by default
        self._current_catalogue = []
        self._nav_list.setCurrentRow(0)

    # ── Nav / Search ──────────────────────────────────────────────────────────

    def _catalogue_for_section(self, section: str) -> list:
        all_headers = self._lmv_headers + self._strategy_col_headers
        if section == "Functions":
            return FUNCTION_CATALOGUE + self._extra_functions
        if section == "Historic Value":
            return self._historic_value_catalogue
        if section == "Operators":
            return OPERATOR_CATALOGUE
        if section == "Fields":
            return FIELD_CATALOGUE_FROM_HEADERS(all_headers)
        if section == "Rows":
            return ROW_CATALOGUE_FROM_DATA(self._all_lmv_data)
        if section == "Constants":
            return CONSTANTS_CATALOGUE
        if section == "Variables":
            return VARIABLE_CATALOGUE_FROM_STORE(self._variable_store)
        return []

    def _on_nav_changed(self, row: int):
        self._search_box.clear()
        section = self._sections[row] if 0 <= row < len(self._sections) else None
        self._current_catalogue = self._catalogue_for_section(section) if section else []
        self._populate_item_list(self._current_catalogue)

    def _on_search(self, text: str):
        q = text.strip().lower()
        # Match on name/signature only, not "description": the Fields and
        # Rows catalogues give every entry the same boilerplate description
        # text (e.g. "...for the current row"), so matching against it made
        # any query that happened to be a substring of that boilerplate
        # (e.g. "cur") match every entry and effectively disable the filter.
        filtered = [
            e for e in self._current_catalogue
            if q in e["name"].lower() or q in e.get("signature", "").lower()
        ] if q else self._current_catalogue
        self._populate_item_list(filtered)

    def _populate_item_list(self, entries: list):
        # A few functions (Round, Log, ...) list more than one overload as
        # separate entries sharing the same name — bare names alone would
        # render as visually-identical duplicate rows. Whenever a name
        # repeats in this list, show its signature instead so each overload
        # is distinguishable; unique names keep the shorter bare-name label.
        name_counts: dict = {}
        for entry in entries:
            name_counts[entry["name"]] = name_counts.get(entry["name"], 0) + 1

        self._item_list.clear()
        for entry in entries:
            label = entry["signature"] if name_counts[entry["name"]] > 1 else entry["name"]
            item = QListWidgetItem(label)
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
        if not entry:
            return
        if entry.get("row_symbol") is not None:
            self._add_row_symbol(entry["row_symbol"])
        elif entry.get("token") is not None:
            picker = entry["token"].get("needs_point_picker")
            if picker:
                self._open_point_lookup_picker(entry["token"]["value"].rstrip("("), picker)
            else:
                self._add_token(entry["token"])

    def _open_point_lookup_picker(self, fname: str, picker: str):
        """Column + (N-days-back / a calendar date / a 2nd driver column +
        N / a 2nd driver column + a date range) picker for a
        POINT_LOOKUP_CATALOGUE entry — builds and inserts the complete call
        in one shot, e.g. VALUE_DAYS_AGO([High], 2), VALUE_ON_DATE([High],
        2026-07-15), VALUE_AT_MAX_DAYS([High], [CWTO], 5), or
        VALUE_AT_MAX_DATES([High], [CWTO], 2026-08-10, 2026-08-14), instead
        of the plain "insert bare function name, fill in the rest by hand"
        flow every other catalogue entry uses. *picker* is "days_ago",
        "on_date", "extreme_days", "extreme_dates", or "months_back" (see
        POINT_LOOKUP_CATALOGUE / screens.inception_strategy_builder's
        INCEPTION_HISTORIC_VALUE_CATALOGUE)."""
        columns = self._lmv_headers + self._strategy_col_headers
        if not columns:
            QMessageBox.information(
                self, "No columns available",
                "Load an LMV sheet first so there's a column to look up.")
            return

        col_dlg = _ColumnPickerDialog(columns, self._theme, self)
        if col_dlg.exec() != QDialog.DialogCode.Accepted:
            return
        column = col_dlg.selected_column()

        if picker == "days_ago":
            n_dlg = _DaysAgoPickerDialog(self._theme, self)
            if n_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self._insert_at_cursor(f"{fname}([{column}], {n_dlg.selected_n()})")
        elif picker == "months_back":
            n_dlg = _MonthsBackPickerDialog(self._theme, self)
            if n_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            n = n_dlg.selected_n()
            # None = "auto" (no months_back arg) — day-granularity search,
            # see _MonthsBackPickerDialog and _try_consume_aggregate_arg's
            # single-column fallback for VALUE_BEFORE_CHANGE.
            if n is None:
                self._insert_at_cursor(f"{fname}([{column}])")
            else:
                self._insert_at_cursor(f"{fname}([{column}], {n})")
        elif picker == "extreme_days":
            # Same full column list for the driver — any raw sheet column or
            # this/another strategy's own computed column is fair game (see
            # services.strategy_engine's "Historic value at a window
            # extreme" docstring: both columns resolve the same way).
            driver_dlg = _ColumnPickerDialog(columns, self._theme, self)
            driver_dlg.setWindowTitle("Pick the Driver Column (decides which day)")
            if driver_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            driver_column = driver_dlg.selected_column()
            n_dlg = _DaysCountPickerDialog(self._theme, self)
            if n_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self._insert_at_cursor(
                f"{fname}([{column}], [{driver_column}], {n_dlg.selected_n()})")
        elif picker == "extreme_dates":
            driver_dlg = _ColumnPickerDialog(columns, self._theme, self)
            driver_dlg.setWindowTitle("Pick the Driver Column (decides which day)")
            if driver_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            driver_column = driver_dlg.selected_column()
            range_dlg = _DateRangePickerDialog(self._theme, self)
            if range_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            date_from, date_to = range_dlg.selected_range()
            self._insert_at_cursor(
                f"{fname}([{column}], [{driver_column}], {date_from.isoformat()}, {date_to.isoformat()})")
        else:
            from api import lmv_snapshot_api
            date_dlg = _OnDatePickerDialog(self._theme, lmv_snapshot_api.get_availability, self)
            if date_dlg.exec() != QDialog.DialogCode.Accepted:
                return
            self._insert_at_cursor(f"{fname}([{column}], {date_dlg.selected_date().isoformat()})")

    # ── Token management ──────────────────────────────────────────────────────
    # The preview box holds the real, editable text; these just splice a
    # token's text in at the current cursor position.

    def _insert_at_cursor(self, text: str):
        cursor = self._preview_edit.textCursor()
        cursor.insertText(text)
        self._preview_edit.setTextCursor(cursor)
        self._preview_edit.setFocus()

    def _add_token(self, token: dict):
        self._insert_at_cursor(_token_insert_text(token))

    _TRAILING_FIELD_RE = re.compile(r"\[([^\[\]]*)\]$")

    def _add_row_symbol(self, symbol: str):
        """Turn the [Field] the cursor is in or just after into
        [Field of Symbol] — click a Field, then click a Row to attach it."""
        text = self._preview_edit.toPlainText()
        pos = self._preview_edit.textCursor().position()
        before, after = text[:pos], text[pos:]

        last_open, last_close = before.rfind("["), before.rfind("]")
        if last_open > last_close and after.startswith("]"):
            # Cursor sits inside an still-open "[...]" — splice " of Symbol" here.
            new_text = before + f" of {symbol}" + after
            new_pos = pos + len(f" of {symbol}")
        else:
            m = self._TRAILING_FIELD_RE.search(before)
            if m and " of " not in m.group(1).lower():
                # Cursor sits right after a just-inserted "[Field]" — extend it.
                head = before[:m.start()]
                new_text = head + f"[{m.group(1)} of {symbol}]" + after
                new_pos = len(head) + len(f"[{m.group(1)} of {symbol}]")
            else:
                QMessageBox.information(
                    self, "Pick a Field first",
                    "Click a Field (e.g. [Open]) first, then click a stock "
                    "here to reference that stock's row — e.g. [Open of Nifty].")
                return

        self._preview_edit.setPlainText(new_text)
        cursor = self._preview_edit.textCursor()
        cursor.setPosition(new_pos)
        self._preview_edit.setTextCursor(cursor)
        self._preview_edit.setFocus()

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
        self._preview_edit.clear()

    def _backspace(self):
        cursor = self._preview_edit.textCursor()
        cursor.deletePreviousChar()
        self._preview_edit.setTextCursor(cursor)
        self._preview_edit.setFocus()

    # ── Preview ───────────────────────────────────────────────────────────────

    def _set_preview_style(self, compiled: bool):
        bg = "#0d2116" if compiled else self._preview_ibg
        fg = "#39d353" if compiled else self._preview_acc
        self._preview_edit.setStyleSheet(
            f"QTextEdit{{background:{bg};color:{fg};border:none;"
            f"border-bottom:1px solid {self._preview_bd};border-radius:0;padding:8px 12px;}}"
        )

    def _on_text_changed(self):
        self._compiled_ok = False
        self._save_btn.setEnabled(False)
        self._save_var_btn.setEnabled(False)
        self._set_preview_style(compiled=False)
        self._clear_error_highlight()

    # ── Error highlighting ───────────────────────────────────────────────────
    # Points the user at exactly the part of the formula that's wrong instead
    # of leaving them to hunt for it — a red highlight under the offending
    # text in the preview box, alongside the plain-language message.

    def _clear_error_highlight(self):
        self._preview_edit.setExtraSelections([])

    def _highlight_error_span(self, start: int, end: int):
        text_len = len(self._preview_edit.toPlainText())
        start = max(0, min(start, text_len))
        end = max(start, min(end, text_len))
        if start == end:
            self._clear_error_highlight()
            return
        cursor = self._preview_edit.textCursor()
        cursor.setPosition(start)
        cursor.setPosition(end, QTextCursor.MoveMode.KeepAnchor)
        fmt = QTextCharFormat()
        fmt.setBackground(QColor("#c0392b"))
        fmt.setForeground(QColor("#ffffff"))
        sel = QTextEdit.ExtraSelection()
        sel.cursor = cursor
        sel.format = fmt
        self._preview_edit.setExtraSelections([sel])

    _UNKNOWN_COL_RE = re.compile(r"^Unknown column\(s\):\s*(.+?)\.")

    def _highlight_named_column(self, msg: str, text: str):
        """Best-effort: compile_check's "Unknown column(s): [X], [Y]." names
        the offending column(s) but not their text position (it only sees
        tokens, not the original text) — find the first one in the preview
        and highlight it there."""
        m = self._UNKNOWN_COL_RE.match(msg)
        if not m:
            return
        first = m.group(1).split(",")[0].strip()
        idx = text.find(first)
        if idx != -1:
            self._highlight_error_span(idx, idx + len(first))

    # ── Compile & Test ────────────────────────────────────────────────────────

    def _compile_and_test(self):
        from services.strategy_engine import compile_check
        self._clear_error_highlight()
        text = self._preview_edit.toPlainText()
        known_headers = self._lmv_headers + self._strategy_col_headers

        struct_err = _find_structural_error(text)
        if struct_err:
            msg, start, end = struct_err
            self._compiled_ok = False
            self._save_btn.setEnabled(False)
            self._save_var_btn.setEnabled(False)
            self._highlight_error_span(start, end)
            QMessageBox.warning(self, "Formula needs a fix", msg)
            return

        try:
            tokens = parse_expression_text(text, known_headers)
        except FormulaParseError as exc:
            self._compiled_ok = False
            self._save_btn.setEnabled(False)
            self._save_var_btn.setEnabled(False)
            self._highlight_error_span(exc.start, exc.end)
            QMessageBox.warning(self, "Formula needs a fix", str(exc))
            return
        except ValueError as exc:
            self._compiled_ok = False
            self._save_btn.setEnabled(False)
            self._save_var_btn.setEnabled(False)
            QMessageBox.warning(self, "Formula needs a fix", str(exc))
            return

        # Merge computed strategy-column values into the test row so a row
        # filter referencing those columns can be evaluated.
        test_row = dict(self._lmv_first_row)
        test_row.update(self._extra_row_values)
        test_all = self._all_lmv_data
        if self._extra_row_values and test_all:
            test_all = [dict(test_all[0], **self._extra_row_values)] + list(test_all[1:])
        ok, msg = compile_check(tokens, test_row, test_all,
                                self_value=self._self_value,
                                lmv_headers=self._real_lmv_headers)
        if ok:
            self._compiled_tokens = tokens
            self._compiled_ok = True
            self._save_btn.setEnabled(True)
            self._save_var_btn.setEnabled(True)
            self._set_preview_style(compiled=True)
            QMessageBox.information(self, "Formula looks good",
                                    f"This formula works. For the first row in "
                                    f"your sheet, it works out to: {msg}")
        else:
            self._compiled_ok = False
            self._save_btn.setEnabled(False)
            self._save_var_btn.setEnabled(False)
            self._highlight_named_column(msg, text)
            QMessageBox.warning(self, "Formula needs a fix", msg)

    # ── Save as Variable ─────────────────────────────────────────────────────

    def _save_as_variable(self):
        if not (self._compiled_ok and self._compiled_tokens):
            return
        from PySide6.QtWidgets import QInputDialog
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store

        name, ok = QInputDialog.getText(self, "Save as Variable", "Variable name:")
        name = name.strip()
        if not ok or not name:
            return
        if any(c in name for c in "{}[]"):
            QMessageBox.warning(self, "Invalid name",
                                "Variable names can't contain { } [ ] characters.")
            return

        existing = var_store.get_by_name(name)
        if existing is not None:
            reply = QMessageBox.question(
                self, "Variable exists",
                f"A variable named '{name}' already exists. Overwrite it with "
                f"the current formula?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
            if reply != QMessageBox.StandardButton.Yes:
                return
            variable = dict(existing, formula=list(self._compiled_tokens))
        else:
            variable = var_store.new_variable(name)
            variable["formula"] = list(self._compiled_tokens)

        var_store.save_variable(variable)
        QMessageBox.information(
            self, "Variable saved",
            f"Saved as {{{name}}}. Insert it into any formula from the "
            f"Variables tab instead of retyping it.")

    # ── Public API ────────────────────────────────────────────────────────────

    def get_tokens(self) -> list:
        if self._compiled_ok and self._compiled_tokens is not None:
            return list(self._compiled_tokens)
        try:
            known_headers = self._lmv_headers + self._strategy_col_headers
            return parse_expression_text(self._preview_edit.toPlainText(), known_headers)
        except ValueError:
            return []


# ── Variables manager ───────────────────────────────────────────────────────

class VariablesManagerDialog(QDialog):
    """List / create / rename / delete reusable formula variables (see
    services.formula_variable_store). Each variable's own formula is edited
    with the same ExpressionEditorDialog used for strategy columns, so it
    gets the full catalogue — including referencing other variables."""

    def __init__(self, lmv_headers: list, lmv_first_row: dict,
                 all_lmv_data: list = None, theme=None,
                 sections: list = None, variable_store=None,
                 extra_functions: list = None,
                 historic_value_catalogue: list = None, parent=None):
        """sections/variable_store/extra_functions/historic_value_catalogue:
        see ExpressionEditorDialog — all default to prior (LMV) behavior and
        are forwarded to every ExpressionEditorDialog this dialog opens."""
        super().__init__(parent)
        self._lmv_headers   = list(lmv_headers)
        self._lmv_first_row = lmv_first_row or {}
        self._all_lmv_data  = all_lmv_data or []
        self._theme = theme
        self._sections = sections
        self._variable_store = variable_store
        self._extra_functions = extra_functions
        self._historic_value_catalogue = historic_value_catalogue
        self.setWindowTitle("Manage Variables")
        self.setFixedSize(520, 440)
        self._build()
        self._refresh_list()

    def _build(self):
        t    = self._theme
        bg   = _t(t, "background")
        cbd  = _t(t, "card_bg")
        bd   = _t(t, "border")
        txt  = _t(t, "text_primary")
        txts = _t(t, "text_secondary")
        acc  = _t(t, "accent")
        dst  = _t(t, "destructive")

        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}"
            f"QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
            f"QPushButton{{background:{_t(t,'button_bg')};color:{txt};"
            f"border:1px solid {bd};border-radius:4px;padding:4px 12px;}}"
            f"QPushButton:hover{{border-color:{acc};color:{acc};}}"
            f"QListWidget{{background:{cbd};color:{txt};border:1px solid {bd};outline:none;}}"
            f"QListWidget::item{{padding:6px 10px;}}"
            f"QListWidget::item:selected{{background:{acc};color:{bg};}}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Formula Variables")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        root.addWidget(title)

        hint = QLabel("Reusable named formulas — build one in the Expression "
                      "Editor and click “Save as Variable…”, or "
                      "create one directly here. Reference it from any formula "
                      "via the Variables tab.")
        hint.setWordWrap(True)
        hint.setStyleSheet(f"color:{txts};")
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.itemDoubleClicked.connect(lambda _: self._edit_selected())
        root.addWidget(self._list, 1)

        btn_row = QHBoxLayout()
        new_btn = QPushButton("+ New")
        new_btn.clicked.connect(self._new_variable)
        edit_btn = QPushButton("Edit Formula")
        edit_btn.clicked.connect(self._edit_selected)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_selected)
        del_btn = QPushButton("Delete")
        del_btn.setStyleSheet(
            f"QPushButton{{background:transparent;color:{dst};"
            f"border:1px solid {dst};border-radius:4px;padding:4px 12px;}}"
            f"QPushButton:hover{{background:{dst};color:#fff;}}"
        )
        del_btn.clicked.connect(self._delete_selected)
        btn_row.addWidget(new_btn)
        btn_row.addWidget(edit_btn)
        btn_row.addWidget(rename_btn)
        btn_row.addWidget(del_btn)
        btn_row.addStretch()
        root.addLayout(btn_row)

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"QPushButton{{background:{acc};color:{bg};"
            f"border:none;border-radius:4px;padding:4px 20px;}}"
        )
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _refresh_list(self):
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store
        selected_id = None
        current = self._list.currentItem()
        if current is not None:
            selected_id = current.data(Qt.ItemDataRole.UserRole)["id"]
        self._list.clear()
        for v in var_store.load_all():
            item = QListWidgetItem(f"{{{v['name']}}}")
            item.setData(Qt.ItemDataRole.UserRole, v)
            self._list.addItem(item)
            if v["id"] == selected_id:
                self._list.setCurrentItem(item)

    def _selected_variable(self):
        item = self._list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _valid_name(self, name: str, exclude_id: str = None) -> bool:
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store
        if not name:
            QMessageBox.warning(self, "Invalid name", "Variable name can't be empty.")
            return False
        if any(c in name for c in "{}[]"):
            QMessageBox.warning(self, "Invalid name",
                                "Variable names can't contain { } [ ] characters.")
            return False
        existing = var_store.get_by_name(name)
        if existing is not None and existing.get("id") != exclude_id:
            QMessageBox.warning(self, "Name in use",
                                f"A variable named '{name}' already exists.")
            return False
        return True

    def _new_variable(self):
        from PySide6.QtWidgets import QInputDialog
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store
        name, ok = QInputDialog.getText(self, "New Variable", "Variable name:")
        name = name.strip()
        if not ok or not self._valid_name(name):
            return
        variable = var_store.new_variable(name)
        dlg = ExpressionEditorDialog(
            [], self._lmv_headers, [], self._lmv_first_row,
            all_lmv_data=self._all_lmv_data, theme=self._theme,
            mode="value", allow_self=False,
            real_lmv_headers=list(self._lmv_first_row.keys()),
            sections=self._sections, variable_store=self._variable_store,
            extra_functions=self._extra_functions,
            historic_value_catalogue=self._historic_value_catalogue, parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            variable["formula"] = dlg.get_tokens()
            var_store.save_variable(variable)
            self._refresh_list()

    def _edit_selected(self):
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store
        variable = self._selected_variable()
        if variable is None:
            return
        dlg = ExpressionEditorDialog(
            variable.get("formula", []), self._lmv_headers, [], self._lmv_first_row,
            all_lmv_data=self._all_lmv_data, theme=self._theme,
            mode="value", allow_self=False,
            real_lmv_headers=list(self._lmv_first_row.keys()),
            sections=self._sections, variable_store=self._variable_store,
            extra_functions=self._extra_functions,
            historic_value_catalogue=self._historic_value_catalogue, parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            variable["formula"] = dlg.get_tokens()
            var_store.save_variable(variable)
            self._refresh_list()

    def _rename_selected(self):
        from PySide6.QtWidgets import QInputDialog
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store
        variable = self._selected_variable()
        if variable is None:
            return
        name, ok = QInputDialog.getText(self, "Rename Variable", "Variable name:",
                                        text=variable["name"])
        name = name.strip()
        if not ok or not self._valid_name(name, exclude_id=variable["id"]):
            return
        variable["name"] = name
        var_store.save_variable(variable)
        self._refresh_list()

    def _delete_selected(self):
        from services import formula_variable_store as _default_store
        var_store = self._variable_store or _default_store
        variable = self._selected_variable()
        if variable is None:
            return
        reply = QMessageBox.question(
            self, "Delete Variable",
            f"Delete '{{{variable['name']}}}'? Any formula still referencing "
            f"it will silently drop that reference instead of failing outright "
            f"— you'll want to fix those formulas afterward.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel)
        if reply == QMessageBox.StandardButton.Yes:
            var_store.delete_variable(variable["id"])
            self._refresh_list()
