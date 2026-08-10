"""
Formula evaluator for strategy columns.

Given:
  - tokens: list of token dicts (see strategy_store.py)
  - row_data: dict  {col_name -> value}   (one row from LMV)
  - all_data: list of row_data dicts       (all rows, for aggregate functions)
  - self_value: float | None               (column's own computed value, for fmt rules)

Returns float | str | None.

Supported:
  Per-row  : +  -  *  /  (  )  MIN  MAX  ABS  ROUND  FLOOR  CEILING  IF/IIF
             CONCAT  LEN  LOWER  UPPER  TRIM  REPLACE  CONTAINS  STARTSWITH
             ENDSWITH  SUBSTRING  REVERSE  CHARINDEX  INSERT  REMOVE  PADLEFT
             PADRIGHT  CHAR  ASCII  EXP  LOG  LOG10  POWER  SIGN  SQR  BIGMUL
             ACOS  ASIN  ATN  ATN2  COS  COSH  SIN  SINH  TAN  TANH
             ISNULL  ISNULLOREMPTY  INRANGE  DIGITS
             TODECIMAL  TODOUBLE  TOFLOAT  TOINT  TOLONG  TOSTR
  Aggregate: SUM_ALL  MIN_ALL  MAX_ALL  AVG_ALL  COUNT_ALL  (across all rows,
             this tick)
  Historic : SUM_DAYS  MIN_DAYS  MAX_DAYS  AVG_DAYS  COUNT_DAYS  STDDEV_DAYS
             MEDIAN_DAYS  VARIANCE_DAYS  RANGE_DAYS  (per stock, over the last
             N historic trading days — see "Historic (N days) aggregates"
             below)
  Point    : VALUE_DAYS_AGO  VALUE_ON_DATE  (per stock, a single historic
             value — N trading days before today, or on one specific
             calendar date — see "Historic value (point lookup)" below)
  Extreme  : VALUE_AT_MAX_DAYS  VALUE_AT_MIN_DAYS  (per stock, another
             column's value on whichever of the last N historic trading days
             a DRIVER column was at its highest/lowest — see "Historic value
             at a window extreme" below)

DIGITS(value) returns how many digits are in the integer part of value (e.g.
DIGITS(12123.77) = 5, DIGITS(2435.22) = 4) — combine with IIF to tier a
threshold by price magnitude:
  IIF(DIGITS([Open]) >= 5, 0.998, IIF(DIGITS([Open]) >= 4, 0.919, ...))

A {"type": "var", "value": name} token ("{Name}" in the Expression Editor)
inlines a reusable formula saved via services.formula_variable_store — see
_expand_var_tokens. Handy for exactly the DIGITS/IIF tier above: build it
once, save it as a variable, then reference {ThresholdName} from every
formula that needs it instead of retyping the nested IIF each time.

── Historic (N days) aggregates ──────────────────────────────────────────────
AVG_DAYS([High], 20) and friends (see _DAYS_AGG_BASE) are a column's own
value aggregated over the last N historic trading days for the SAME stock,
e.g. "20-day average High". The column referenced can be a raw sheet column
or another of this strategy's own computed columns (any custom formula) —
services.strategy_engine.collect_day_requests resolves which. Unlike _ALL
aggregates, this can't be computed from row_data/all_data alone — it needs a
historic snapshot fetch (see services.formula_stats_engine.compute_day_history),
which is comparatively expensive, so callers precompute it once (on strategy
load/toggle, or a manual refresh — never once per live tick) into a
``day_history`` dict and pass it into evaluate()/evaluate_condition()/
apply_strategies()/get_row_fmt_colors(). Without a day_history entry for a
given (column, days), a _DAYS function evaluates to None — same "blank
rather than crash" fallback as a column missing from a row.

── Historic value (point lookup) ──────────────────────────────────────────────
VALUE_DAYS_AGO([High], 2) and VALUE_ON_DATE([High], "2026-07-15") are a
column's own value on ONE specific historic day for the SAME stock — not an
aggregate over a window, just that one day's value. VALUE_DAYS_AGO counts
back N trading days from today (N=0 is today/the most recent day);
VALUE_ON_DATE takes an exact calendar date instead. Both reuse the exact
same day_history cache/plumbing as the _DAYS family above (see
services.formula_stats_engine.compute_stats' "First" key) — VALUE_DAYS_AGO's
window is an int (N+1, so the oldest day fetched is exactly N days back);
VALUE_ON_DATE's window is a (date, date) tuple (a one-day range). Same non-
live refresh cadence, same "blank rather than crash" fallback when missing
from day_history, as _DAYS.

── Historic value at a window extreme ──────────────────────────────────────────
VALUE_AT_MAX_DAYS([High], [CWTO], 5) is "this stock's High on whichever of
the last 5 historic trading days [CWTO] (the DRIVER column) was at its
highest" — VALUE_AT_MIN_DAYS is the same for the lowest. Two columns, not
one: the first is what gets returned, the second is what decides which day.
Either can be a raw sheet column or another of this strategy's own columns
(same "any custom formula" resolution collect_day_requests gives the _DAYS
family above).

Needs BOTH columns' own day_history entries over the SAME N-day window —
collect_day_requests/scan_day_funcs request them as two ordinary _DAYS-style
fetches (col_name, N) and (driver_col_name, N), so this adds no new fetching
machinery, just a second request per call. Resolution reads each entry's
"daily" list (services.formula_stats_engine.compute_stats' chronological
[(trade_date, value), ...] — see that module's docstring) rather than one of
the pre-reduced Min/Max/Average keys the _DAYS family uses: the driver
column's daily list picks the winning date, then the value column's own
daily list is read at that exact date. None if either day_history entry is
missing, the driver has no numeric value on any day in the window, or the
value column has none on the winning date specifically — same "blank rather
than crash" fallback as everywhere else in this module.
"""

import math
import re


# ── Built-in function implementations ────────────────────────────────────────

def _floor(x, *_):          return math.floor(x)
def _ceil(x, *_):           return math.ceil(x)
def _sum(*args):             return sum(args)
def _if(cond, a, b):        return a if cond else b
def _exp(x):                return math.exp(x)
def _log(x, base=None):     return math.log(x) if base is None else math.log(x, base)
def _log10(x):              return math.log10(x)
def _power(b, e):           return b ** e
def _sign(x):               return (1 if x > 0 else (-1 if x < 0 else 0))
def _sqr(x):                return math.sqrt(x)
def _bigmul(a, b):          return int(a) * int(b)
def _acos(x):               return math.acos(x)
def _asin(x):               return math.asin(x)
def _atn(x):                return math.atan(x)
def _atn2(y, x):            return math.atan2(y, x)
def _cos(x):                return math.cos(x)
def _cosh(x):               return math.cosh(x)
def _sin(x):                return math.sin(x)
def _sinh(x):               return math.sinh(x)
def _tan(x):                return math.tan(x)
def _tanh(x):               return math.tanh(x)
def _digits(x):
    # Digit count of the integer part, e.g. 12123.77 -> 5, 2435.22 -> 4.
    # String-based (not log10) so it's exact at power-of-10 boundaries —
    # log10(1000) can land a hair under 3.0 in floating point and undercount.
    return len(str(int(abs(float(x)))))
def _isnull(v):             return v is None
def _isnullorempty(v):      return v is None or str(v).strip() == ""
def _inrange(v, lo, hi):    return lo <= v <= hi
def _concat(a, b):          return str(a) + str(b)
def _ascii(c):              return ord(str(c)[0]) if c else 0
def _char(n):               return chr(int(n))
def _charindex(s, q):       return str(s).find(str(q))
def _contains(s, q):        return str(q) in str(s)
def _endswith(s, q):        return str(s).endswith(str(q))
def _insert(s, pos, v):     return str(s)[:int(pos)] + str(v) + str(s)[int(pos):]
def _len(s):                return len(str(s)) if s is not None else 0
def _lower(s):              return str(s).lower()
def _upper(s):              return str(s).upper()
def _padleft(s, w):         return str(s).rjust(int(w))
def _padright(s, w):        return str(s).ljust(int(w))
def _remove(s, q):          return str(s).replace(str(q), "")
def _replace(s, old, new):  return str(s).replace(str(old), str(new))
def _reverse(s):            return str(s)[::-1]
def _startswith(s, q):      return str(s).startswith(str(q))
def _substring(s, start, length): return str(s)[int(start):int(start) + int(length)]
def _trim(s):               return str(s).strip()
def _todecimal(v):          return float(v)
def _todouble(v):           return float(v)
def _tofloat(v):            return float(v)
def _toint(v):              return int(float(v))
def _tolong(v):             return int(float(v))
def _tostr(v):              return str(v)


_FUNC_MAP = {
    # Math
    "MIN": "min", "MAX": "max", "ABS": "abs", "ROUND": "round",
    "FLOOR": "_floor", "CEILING": "_ceil", "CEIL": "_ceil",
    "SUM": "_sum", "IF": "_if", "IIF": "_if",
    "EXP": "_exp", "LOG": "_log", "LOG10": "_log10",
    "POWER": "_power", "SIGN": "_sign", "SQR": "_sqr", "BIGMUL": "_bigmul",
    # Trig
    "ACOS": "_acos", "ASIN": "_asin", "ATN": "_atn", "ATN2": "_atn2",
    "COS": "_cos", "COSH": "_cosh", "SIN": "_sin", "SINH": "_sinh",
    "TAN": "_tan", "TANH": "_tanh",
    # Conditional / null
    "ISNULL": "_isnull", "ISNULLOREMPTY": "_isnullorempty", "INRANGE": "_inrange",
    "DIGITS": "_digits",
    # String
    "ASCII": "_ascii", "CHAR": "_char", "CHARINDEX": "_charindex",
    "CONCAT": "_concat", "CONTAINS": "_contains", "ENDSWITH": "_endswith",
    "INSERT": "_insert", "LEN": "_len", "LOWER": "_lower", "UPPER": "_upper",
    "PADLEFT": "_padleft", "PADRIGHT": "_padright",
    "REMOVE": "_remove", "REPLACE": "_replace", "REVERSE": "_reverse",
    "STARTSWITH": "_startswith", "SUBSTRING": "_substring", "TRIM": "_trim",
    # Type conversion
    "TODECIMAL": "_todecimal", "TODOUBLE": "_todouble", "TOFLOAT": "_tofloat",
    "TOINT": "_toint", "TOLONG": "_tolong", "TOSTR": "_tostr",
}

_EVAL_BUILTINS = {
    "__builtins__": {},
    "min": min, "max": max, "abs": abs, "round": round,
    "_floor": _floor, "_ceil": _ceil, "_sum": _sum, "_if": _if,
    "_exp": _exp, "_log": _log, "_log10": _log10,
    "_power": _power, "_sign": _sign, "_sqr": _sqr, "_bigmul": _bigmul,
    "_acos": _acos, "_asin": _asin, "_atn": _atn, "_atn2": _atn2,
    "_cos": _cos, "_cosh": _cosh, "_sin": _sin, "_sinh": _sinh,
    "_tan": _tan, "_tanh": _tanh,
    "_isnull": _isnull, "_isnullorempty": _isnullorempty, "_inrange": _inrange,
    "_digits": _digits,
    "_concat": _concat, "_ascii": _ascii, "_char": _char,
    "_charindex": _charindex, "_contains": _contains, "_endswith": _endswith,
    "_insert": _insert, "_len": _len, "_lower": _lower, "_upper": _upper,
    "_padleft": _padleft, "_padright": _padright,
    "_remove": _remove, "_replace": _replace, "_reverse": _reverse,
    "_startswith": _startswith, "_substring": _substring, "_trim": _trim,
    "_todecimal": _todecimal, "_todouble": _todouble, "_tofloat": _tofloat,
    "_toint": _toint, "_tolong": _tolong, "_tostr": _tostr,
    "True": True, "False": False, "None": None, "IIf": _if,
}


def _col_literal(raw) -> str:
    """Represent a column value as a safe Python literal (numeric or string)."""
    if raw is None or raw == "":
        return "None"
    try:
        return str(float(raw))
    except (TypeError, ValueError):
        return repr(str(raw))


# ── cross-row lookup ("[Open of Nifty]") ─────────────────────────────────────

SYMBOL_COLUMN = "Scrip Name"


def build_symbol_index(all_data: list, symbol_col: str = SYMBOL_COLUMN) -> dict:
    """Map normalised (stripped, upper-cased) stock symbol -> that row's dict.

    Scrip Name isn't guaranteed unique (see services/master_generator.py), so
    first match wins, same "first match wins" spirit used elsewhere in this
    module.
    """
    idx: dict = {}
    for rd in all_data:
        sym = rd.get(symbol_col)
        if not sym:
            continue
        norm = str(sym).strip().upper()
        if norm and norm not in idx:
            idx[norm] = rd
    return idx


# ── formula variables ("{Name}" tokens) ──────────────────────────────────────
#
# services.formula_variable_store lets a user name a reusable formula (e.g. a
# price-tiered threshold built once with DIGITS+IIF) and reference it from any
# other formula as {"type": "var", "value": name}. Expansion is pure token
# inlining — done once wherever a raw token list is about to become an
# expression (see the two callers below) — rather than a runtime lookup, so
# the rest of this module never needs to know "var" tokens exist.

def _expand_var_tokens(tokens: list, _seen: frozenset = frozenset()) -> list:
    """Inline every {"type": "var", "value": name} token with that variable's
    own formula tokens, wrapped in parens to preserve operator precedence —
    recursively, so a variable can itself reference other variables.

    A cyclic reference is dropped (not raised) so a mistake in one variable's
    formula degrades that one spot rather than crashing every formula that
    happens to reference it. An unknown/deleted variable name is dropped the
    same way, consistent with how a missing column silently reads as None
    elsewhere in this module.
    """
    if not any(tok.get("type") == "var" for tok in tokens):
        return tokens  # common case — skip the store import/lookup entirely
    from services import formula_variable_store as var_store
    out = []
    for tok in tokens:
        if tok.get("type") != "var":
            out.append(tok)
            continue
        name = tok.get("value")
        if name in _seen:
            continue
        var = var_store.get_by_name(name)
        if var is None:
            continue
        inner = _expand_var_tokens(var.get("formula", []), _seen | {name})
        if inner:
            out.append({"type": "paren", "value": "("})
            out.extend(inner)
            out.append({"type": "paren", "value": ")"})
    return out


# ── token → expression string ──────────────────────────────────────────────

def _tokens_to_expr(tokens: list, row_data: dict, all_data: list,
                    self_value=None) -> str:
    tokens = _expand_var_tokens(tokens)
    parts = []
    sym_index = None
    for tok in tokens:
        t = tok.get("type")
        v = tok.get("value", "")

        if t == "col":
            of_sym = tok.get("of")
            if of_sym:
                if sym_index is None:
                    sym_index = build_symbol_index(all_data)
                target = sym_index.get(str(of_sym).strip().upper())
                parts.append(_col_literal(target.get(v) if target else None))
            else:
                parts.append(_col_literal(row_data.get(v)))

        elif t == "self":
            parts.append(_col_literal(self_value))

        elif t in ("num", "op", "paren"):
            parts.append(v)

        elif t == "func":
            # aggregate functions have _ALL suffix; map to a single computed number
            fname = v.rstrip("(").upper()
            if fname in _DAYS_AGG_BASE or fname in _POINT_LOOKUP_FUNCS or fname in _VALUE_AT_EXTREME_FUNCS:
                # No historic fetch happens at compile-test time (see the
                # module docstring's "Historic (N days) aggregates"/
                # "Historic value (point lookup)"/"Historic value at a
                # window extreme" sections) — a numeric placeholder lets the
                # rest of the formula's arithmetic/type-check still run
                # instead of raising. See compile_check's own handling for
                # the caveat this implies in the result it reports.
                parts.append("1.0")
            elif fname.endswith("_ALL"):
                col_name = tok.get("col_arg", "")
                nums = []
                for rd in all_data:
                    try:
                        nums.append(float(rd.get(col_name, 0) or 0))
                    except (TypeError, ValueError):
                        pass
                base = fname[:-4]
                if base == "SUM":
                    result = sum(nums)
                elif base == "MIN":
                    result = min(nums) if nums else 0
                elif base == "MAX":
                    result = max(nums) if nums else 0
                elif base == "AVG":
                    result = sum(nums) / len(nums) if nums else 0
                elif base == "COUNT":
                    result = len(nums)
                else:
                    result = 0
                parts.append(str(result))
            else:
                parts.append(_FUNC_MAP.get(fname, fname.lower()) + "(")

    return "".join(parts)


def _col_value(raw):
    """Like _col_literal, but returns the actual Python value (not source text)."""
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return str(raw)


def _compute_aggregate(base: str, col_name: str, all_data: list):
    nums = []
    for rd in all_data:
        try:
            nums.append(float(rd.get(col_name, 0) or 0))
        except (TypeError, ValueError):
            pass
    if base == "SUM":
        return sum(nums)
    elif base == "MIN":
        return min(nums) if nums else 0
    elif base == "MAX":
        return max(nums) if nums else 0
    elif base == "AVG":
        return sum(nums) / len(nums) if nums else 0
    elif base == "COUNT":
        return len(nums)
    else:
        return 0


# func name -> the formula_stats_engine.AGGREGATES key it maps to. Values
# are per-stock aggregates over the last N historic days (see the module
# docstring's "Historic (N days) aggregates" section) rather than across this
# tick's rows, so they're resolved through a caller-supplied ``day_history``
# instead of ``all_data``.
_DAYS_AGG_BASE = {
    "MIN_DAYS": "Min", "MAX_DAYS": "Max", "AVG_DAYS": "Average",
    "SUM_DAYS": "Sum", "COUNT_DAYS": "Count", "STDDEV_DAYS": "Std Dev",
    "MEDIAN_DAYS": "Median", "VARIANCE_DAYS": "Variance", "RANGE_DAYS": "Range",
}

# Point lookups (one historic value, not an aggregate) — see this module's
# "Historic value (point lookup)" docstring section. Both resolve via the
# "First" key formula_stats_engine.compute_stats adds to every column
# (oldest day in whatever window was fetched).
_POINT_LOOKUP_FUNCS = {"VALUE_DAYS_AGO", "VALUE_ON_DATE"}

# Value-at-window-extreme lookups — see this module's "Historic value at a
# window extreme" docstring section. True/False = whether the driver column
# picks the day with the highest (VALUE_AT_MAX_DAYS) or lowest
# (VALUE_AT_MIN_DAYS) value.
_VALUE_AT_EXTREME_FUNCS = {"VALUE_AT_MAX_DAYS": True, "VALUE_AT_MIN_DAYS": False}


class _Compiled:
    """A formula's fixed structure, compiled once and reused across rows/ticks.

    ``col_vars`` maps referenced column name -> placeholder variable name
    (e.g. "_c0"), resolved against the row being evaluated. ``col_of_vars``
    is [(placeholder, col_name, symbol), ...] for "[Col of Symbol]" tokens,
    resolved against a different row (looked up by stock symbol) instead.
    ``agg_specs`` is [(placeholder, base_op, col_name), ...] for _ALL
    aggregate functions, resolved once per tick rather than once per row
    (they don't depend on the row being evaluated). ``day_specs`` is
    [(placeholder, agg_key, col_name, days), ...] for _DAYS historic
    aggregate functions, resolved from the row's own stock symbol against a
    caller-supplied day_history (see the module docstring). ``extreme_specs``
    is [(placeholder, col_name, driver_col_name, days, want_max), ...] for
    VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS (see the module docstring's "Historic
    value at a window extreme" section) — resolved the same way as
    day_specs, against two day_history entries instead of one.
    """
    __slots__ = ("code", "col_vars", "col_of_vars", "uses_self", "agg_specs",
                "day_specs", "extreme_specs")

    def __init__(self, code, col_vars, col_of_vars, uses_self, agg_specs, day_specs,
                extreme_specs):
        self.code = code
        self.col_vars = col_vars
        self.col_of_vars = col_of_vars
        self.uses_self = uses_self
        self.agg_specs = agg_specs
        self.day_specs = day_specs
        self.extreme_specs = extreme_specs


_compile_cache: dict = {}


def clear_compile_cache():
    """Drop every cached compiled formula. _get_compiled's cache key is the
    signature of the *raw* (un-expanded) tokens — cheap, and unaffected by a
    "var" token's own referenced variable being edited — so an edit to a
    formula variable (see services.formula_variable_store) can't invalidate
    just the entries that used it; it has to drop them all. Called from
    formula_variable_store.save_variable/delete_variable, not from
    per-row/per-tick code, so this being a full clear (cheap: recompiling is
    only ever the O(rows) evaluate() work's one-time setup) is fine."""
    _compile_cache.clear()


def _formula_signature(tokens: list):
    # date_arg matters here too — two VALUE_ON_DATE tokens differing only in
    # their date would otherwise share a signature (same type, value,
    # col_arg, days_arg=None, of=None) and incorrectly reuse each other's
    # compiled day_specs/window from the cache. driver_col_arg likewise, for
    # two VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS calls differing only in which
    # column drives the day.
    return tuple((tok.get("type"), tok.get("value"), tok.get("col_arg"),
                 tok.get("days_arg"), tok.get("of"), tok.get("date_arg"),
                 tok.get("driver_col_arg"))
                 for tok in tokens)


def _build_compiled(tokens: list):
    tokens = _expand_var_tokens(tokens)
    parts = []
    col_vars: dict = {}
    col_of_vars: list = []
    uses_self = False
    agg_specs = []
    day_specs = []
    extreme_specs = []

    for tok in tokens:
        t = tok.get("type")
        v = tok.get("value", "")

        if t == "col":
            of_sym = tok.get("of")
            if of_sym:
                var = f"_o{len(col_of_vars)}"
                col_of_vars.append((var, v, of_sym))
                parts.append(var)
            else:
                var = col_vars.get(v)
                if var is None:
                    var = f"_c{len(col_vars)}"
                    col_vars[v] = var
                parts.append(var)

        elif t == "self":
            uses_self = True
            parts.append("_self")

        elif t in ("num", "op", "paren"):
            parts.append(v)

        elif t == "func":
            fname = v.rstrip("(").upper()
            days_arg = tok.get("days_arg")
            date_arg = tok.get("date_arg")
            if fname in _DAYS_AGG_BASE and tok.get("col_arg") and days_arg is not None:
                col_name = tok.get("col_arg", "")
                agg_key = _DAYS_AGG_BASE[fname]
                var = f"_d{len(day_specs)}"
                day_specs.append((var, agg_key, col_name, int(days_arg)))
                parts.append(var)
            elif fname == "VALUE_DAYS_AGO" and tok.get("col_arg") and days_arg is not None:
                # Same day_specs list/day_history cache as the _DAYS branch
                # above — window = N+1 days so the OLDEST day in that fetch
                # is exactly N days before today; "First" (not an aggregate
                # key like "Average") picks it out — see this module's
                # "Historic value (point lookup)" docstring.
                col_name = tok.get("col_arg", "")
                var = f"_d{len(day_specs)}"
                day_specs.append((var, "First", col_name, int(days_arg) + 1))
                parts.append(var)
            elif fname == "VALUE_ON_DATE" and tok.get("col_arg") and date_arg:
                # window is a (date, date) tuple — a one-day range — rather
                # than an int; "First" is still correct since a one-day
                # fetch has at most one entry to pick.
                col_name = tok.get("col_arg", "")
                var = f"_d{len(day_specs)}"
                day_specs.append((var, "First", col_name, (date_arg, date_arg)))
                parts.append(var)
            elif (fname in _VALUE_AT_EXTREME_FUNCS and tok.get("col_arg")
                  and tok.get("driver_col_arg") and days_arg is not None):
                col_name = tok.get("col_arg", "")
                driver_col_name = tok.get("driver_col_arg", "")
                want_max = _VALUE_AT_EXTREME_FUNCS[fname]
                var = f"_e{len(extreme_specs)}"
                extreme_specs.append((var, col_name, driver_col_name, int(days_arg), want_max))
                parts.append(var)
            elif fname.endswith("_ALL"):
                col_name = tok.get("col_arg", "")
                base = fname[:-4]
                var = f"_a{len(agg_specs)}"
                agg_specs.append((var, base, col_name))
                parts.append(var)
            else:
                parts.append(_FUNC_MAP.get(fname, fname.lower()) + "(")

    expr = "".join(parts)
    if not expr.strip():
        return None
    try:
        code = compile(expr, "<formula>", "eval")  # noqa: S307
    except SyntaxError:
        return None
    return _Compiled(code, col_vars, col_of_vars, uses_self, agg_specs, day_specs, extreme_specs)


def _get_compiled(tokens: list):
    sig = _formula_signature(tokens)
    if sig not in _compile_cache:
        _compile_cache[sig] = _build_compiled(tokens)
    return _compile_cache[sig]


def _value_at_extreme(day_history, symbol, col_name: str, driver_col_name: str,
                      days: int, want_max: bool):
    """VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS resolution — see this module's
    "Historic value at a window extreme" docstring section. None if
    day_history/symbol is missing, either (col_name, days)/(driver_col_name,
    days) entry is missing its "daily" list, the driver has no numeric value
    on any day, or the value column has none on the winning date."""
    if day_history is None or not symbol:
        return None
    driver_entry = day_history.get((driver_col_name, days), {}).get(symbol)
    value_entry = day_history.get((col_name, days), {}).get(symbol)
    if not driver_entry or not value_entry:
        return None
    driver_daily = driver_entry.get("daily") or []
    value_daily = value_entry.get("daily") or []

    best_date, best_val = None, None
    for d, v in driver_daily:
        if not isinstance(v, (int, float)):
            continue
        if best_val is None or (v > best_val if want_max else v < best_val):
            best_val, best_date = v, d
    if best_date is None:
        return None

    for d, v in value_daily:
        if d == best_date:
            return v
    return None


def evaluate(tokens: list, row_data: dict, all_data: list,
             self_value=None, agg_cache: dict | None = None,
             sym_index: dict | None = None, day_history: dict | None = None):
    """Return numeric or string result, or None on error.

    ``agg_cache``, when provided, memoizes _ALL aggregate results by
    (base_op, col_name) for the caller's own scope (e.g. one dict per
    apply_strategies()/render pass) so an aggregate is computed once
    instead of once per row.

    ``sym_index``, when provided, is a build_symbol_index(all_data) result
    reused across every row in the caller's scope, so "[Col of Symbol]"
    tokens don't rebuild the index once per row. If omitted it's built
    on demand from all_data (only when the formula actually uses one).

    ``day_history``, when provided, resolves _DAYS historic aggregate
    functions and the VALUE_DAYS_AGO/VALUE_ON_DATE point lookups:
    {(col_name, window): {symbol: {agg_key: value}}}, as built by
    services.formula_stats_engine.compute_day_history — window is an int
    (last N days) or a (date, date) tuple (one fixed date), as the token
    itself determines. The row's own stock symbol (row_data[SYMBOL_COLUMN])
    picks which entry applies. Missing entirely (None), or missing this
    (col_name, window)/symbol/agg_key, all resolve to None for that function
    call — same "blank rather than crash" fallback as everything else in
    this module — rather than pass day_history at every call site, most
    callers get away with never populating it: a formula with no _DAYS/
    VALUE_DAYS_AGO/VALUE_ON_DATE functions never looks it up.
    """
    if not tokens:
        return None
    compiled = _get_compiled(tokens)
    if compiled is None:
        return None
    ns = _EVAL_BUILTINS.copy()
    for col_name, var in compiled.col_vars.items():
        ns[var] = _col_value(row_data.get(col_name))
    if compiled.col_of_vars:
        idx = sym_index if sym_index is not None else build_symbol_index(all_data)
        for var, col_name, symbol in compiled.col_of_vars:
            target = idx.get(str(symbol).strip().upper())
            ns[var] = _col_value(target.get(col_name)) if target else None
    if compiled.uses_self:
        ns["_self"] = _col_value(self_value)
    for var, base, col_name in compiled.agg_specs:
        if agg_cache is not None:
            key = (base, col_name)
            if key in agg_cache:
                val = agg_cache[key]
            else:
                val = _compute_aggregate(base, col_name, all_data)
                agg_cache[key] = val
        else:
            val = _compute_aggregate(base, col_name, all_data)
        ns[var] = val
    if compiled.day_specs:
        # Keyed by the row's own stock symbol, exactly as stored in
        # day_history (see compute_day_history — the historic snapshot's own
        # "symbol" field, same identifier SYMBOL_COLUMN carries live).
        # ``window`` is either an int (last N days — the _DAYS family and
        # VALUE_DAYS_AGO) or a (date, date) tuple (one fixed date —
        # VALUE_ON_DATE) — both are valid dict keys, so this lookup needs no
        # branching between the two.
        symbol = row_data.get(SYMBOL_COLUMN)
        for var, agg_key, col_name, window in compiled.day_specs:
            val = None
            if day_history is not None and symbol:
                entry = day_history.get((col_name, window), {}).get(symbol)
                if entry:
                    val = entry.get(agg_key)
            ns[var] = val
    if compiled.extreme_specs:
        # VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS: unlike day_specs above, this
        # reads each entry's own "daily" list (see
        # services.formula_stats_engine.compute_stats) rather than a
        # pre-reduced agg_key — the driver column's daily list picks the
        # winning date, then the value column's own daily list is read at
        # that exact date. Same symbol-keyed day_history dict as day_specs;
        # just two entries (col_name, driver_col_name) at the same window
        # instead of one.
        symbol = row_data.get(SYMBOL_COLUMN)
        for var, col_name, driver_col_name, days, want_max in compiled.extreme_specs:
            ns[var] = _value_at_extreme(day_history, symbol, col_name, driver_col_name,
                                        days, want_max)
    try:
        return eval(compiled.code, ns)   # noqa: S307
    except Exception:
        return None


def _evaluate_verbose(tokens: list, row_data: dict, all_data: list,
                      self_value=None):
    """Like evaluate() but returns (result, error). error is None on success.

    Unlike evaluate(), this surfaces the real exception object (rather than
    swallowing it) so the compile test can translate it into a plain-language
    reason for failure — see _friendly_exception.
    """
    if not tokens:
        return None, "Formula is empty."
    expr = _tokens_to_expr(tokens, row_data, all_data, self_value)
    if not expr.strip():
        return None, "Formula is empty."
    try:
        return eval(expr, _EVAL_BUILTINS), None   # noqa: S307
    except Exception as exc:
        return None, exc


def _friendly_exception(exc) -> str:
    """Translate a raw Python exception from evaluating a formula into a
    plain-language explanation a non-technical user can act on."""
    if isinstance(exc, ZeroDivisionError):
        return ("The formula divides by zero somewhere. Check the column or "
                "value used as the divisor — it's zero (or empty) for this row.")
    if isinstance(exc, TypeError):
        if "NoneType" in str(exc):
            return ("The formula tried to do math with an empty cell — one "
                    "of the columns it uses has no value for this row. "
                    "Check the data in that row of your sheet.")
        return ("The formula combines values that don't work together — for "
                "example mixing text with a number. Check the columns and "
                "operators (+, -, *, /) you're using.")
    if isinstance(exc, ValueError):
        return ("One of the values isn't in a format the formula expects — "
                "for example text where a number was needed. Check the data "
                "in the columns this formula uses.")
    if isinstance(exc, (KeyError, IndexError)):
        return "The formula refers to something that isn't available in the data."
    return f"Something went wrong while calculating the formula: {exc}"


def _referenced_columns(tokens: list) -> list:
    """Distinct column names referenced by col tokens and aggregate col_args
    (including driver_col_arg — VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS's second
    column)."""
    cols = []
    for tok in tokens:
        if tok.get("type") == "col" and tok.get("value"):
            cols.append(tok["value"])
        if tok.get("col_arg"):
            cols.append(tok["col_arg"])
        if tok.get("driver_col_arg"):
            cols.append(tok["driver_col_arg"])
    # preserve order, drop dups
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def _uses_day_funcs(tokens: list) -> bool:
    """True if any _DAYS historic aggregate function, VALUE_DAYS_AGO/
    VALUE_ON_DATE point lookup, or VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS
    window-extreme lookup appears in *tokens*."""
    return any(
        tok.get("type") == "func"
        and tok.get("value", "").rstrip("(").upper() in (
            _DAYS_AGG_BASE.keys() | _POINT_LOOKUP_FUNCS | _VALUE_AT_EXTREME_FUNCS.keys()
        )
        for tok in tokens
    )


def scan_day_funcs(tokens: list) -> list:
    """[(col_name, window), ...] for every well-formed _DAYS, VALUE_DAYS_AGO,
    VALUE_ON_DATE, or VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS function call in
    *tokens* (col_arg + days_arg, or col_arg + date_arg — see
    _build_compiled). window is an int for a _DAYS/VALUE_DAYS_AGO/
    VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS call, or a (date, date) tuple for a
    VALUE_ON_DATE call. A VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS call yields TWO
    entries — (col_arg, days) and (driver_col_arg, days) — since both
    columns need their own day_history entry over the same window (see
    services.strategy_engine's "Historic value at a window extreme"
    docstring). Used to figure out which historic data a formula needs
    (collect_day_requests) and, for Live Master View, which (column,
    window) a clicked cell should drill into (screens/live_viewer.py's
    _on_cell_clicked)."""
    out = []
    for tok in tokens:
        if tok.get("type") != "func":
            continue
        fname = tok.get("value", "").rstrip("(").upper()
        col_arg = tok.get("col_arg")
        days_arg = tok.get("days_arg")
        date_arg = tok.get("date_arg")
        driver_col_arg = tok.get("driver_col_arg")
        if fname in _DAYS_AGG_BASE and col_arg and days_arg is not None:
            out.append((col_arg, int(days_arg)))
        elif fname == "VALUE_DAYS_AGO" and col_arg and days_arg is not None:
            out.append((col_arg, int(days_arg) + 1))
        elif fname == "VALUE_ON_DATE" and col_arg and date_arg:
            out.append((col_arg, (date_arg, date_arg)))
        elif (fname in _VALUE_AT_EXTREME_FUNCS and col_arg and driver_col_arg
              and days_arg is not None):
            out.append((col_arg, int(days_arg)))
            out.append((driver_col_arg, int(days_arg)))
    return out


def collect_day_requests(strategies: list, notif_configs: dict | None = None) -> list:
    """Distinct (col_name, window, formula_tokens) triples referenced by any
    _DAYS, VALUE_DAYS_AGO, or VALUE_ON_DATE function across every ACTIVE
    strategy's columns, row filter, and conditional-formatting conditions,
    plus (if given) that strategy's notification config's trigger
    condition, risk:reward formulas, and metric formulas
    (services.strategy_alerts — a separate store, keyed by strategy id, so
    it isn't reachable from *strategies* alone). ``window`` is an int
    (_DAYS/VALUE_DAYS_AGO: last N days) or a (date, date) tuple
    (VALUE_ON_DATE: one fixed date) — see scan_day_funcs.

    *col_name* resolves to that SAME strategy's own column's formula when it
    names one of that strategy's columns — this is how "any custom formula
    over the last N days" works: AVG_DAYS([MyComputedCol], 20) aggregates
    MyComputedCol's own (arbitrary) formula, not a literal column named
    "MyComputedCol". Anything else is assumed to be a raw sheet/historic
    column and passed through as a bare column reference.

    ``formula_tokens`` is what services.formula_stats_engine.compute_stats
    should evaluate per historic day to answer this request.
    """
    notif_configs = notif_configs or {}
    seen: set = set()
    out = []
    for strat in strategies:
        if not strat.get("active"):
            continue
        cols_by_name = {c["name"]: c.get("formula", []) for c in strat.get("columns", [])}

        token_sources = [c.get("formula", []) for c in strat.get("columns", [])]
        token_sources.append(strat.get("row_filter", []))
        for c in strat.get("columns", []):
            for rule in c.get("fmt_rules", []):
                token_sources.append(rule.get("condition", []))

        notif = notif_configs.get(strat.get("id"))
        if notif:
            token_sources.append(notif.get("trigger_condition", []))
            rr = notif.get("risk_reward") or {}
            token_sources.append(rr.get("numerator", []))
            token_sources.append(rr.get("denominator", []))
            for metric in notif.get("metrics", []):
                token_sources.append(metric.get("formula", []))

        for src in token_sources:
            for col_name, window in scan_day_funcs(src):
                key = (col_name, window)
                if key in seen:
                    continue
                seen.add(key)
                formula = cols_by_name.get(col_name, [{"type": "col", "value": col_name}])
                out.append((col_name, window, formula))
    return out


def evaluate_condition(tokens: list, row_data: dict, all_data: list,
                       self_value=None, agg_cache: dict | None = None,
                       sym_index: dict | None = None,
                       day_history: dict | None = None) -> bool:
    """Return True if condition is met."""
    result = evaluate(tokens, row_data, all_data, self_value, agg_cache,
                      sym_index, day_history)
    if result is None:
        return False
    return bool(result)


def apply_strategies(strategies: list, headers: list, data: list[list],
                     day_history: dict | None = None) -> tuple[list, list[list]]:
    """
    Append strategy columns to headers and data rows.
    Returns (new_headers, new_data).
    Only active strategies are applied.

    ``day_history``, forwarded to every evaluate()/evaluate_condition() call,
    resolves _DAYS historic aggregate functions — see evaluate()'s docstring.
    Callers precompute it (services.formula_stats_engine.compute_day_history)
    on their own cadence (e.g. strategy load/toggle, not every tick) rather
    than this function fetching it itself.
    """
    active = [s for s in strategies if s.get("active")]
    if not active:
        return headers, data

    # Build list of all dicts for aggregate functions
    all_dicts = [dict(zip(headers, row)) for row in data]
    # Memoizes SUM_ALL/AVG_ALL/etc. by (base_op, col_name) for this call, so an
    # aggregate over all rows is computed once instead of once per row.
    agg_cache: dict = {}
    # Symbol -> row-dict lookup for "[Col of Symbol]" tokens, built once per
    # call instead of once per row.
    sym_index = build_symbol_index(all_dicts)

    extra_headers = []
    for strat in active:
        for col in strat.get("columns", []):
            extra_headers.append(col["name"])

    new_headers = list(headers) + extra_headers

    # A strategy with no row_filter includes every row.  When filters are
    # present, a row is kept if it passes ANY active strategy's filter (union).
    any_unfiltered = any(not s.get("row_filter") for s in active)

    new_data = []
    for row in data:
        row_dict = dict(zip(headers, row))

        # Compute each active strategy's columns first, then evaluate its row
        # filter against a row enriched with those computed values — so a filter
        # can reference the strategy's own columns by name.
        per_strat = []   # (passed, [computed values in column order])
        for strat in active:
            enriched = dict(row_dict)
            values = []
            for col in strat.get("columns", []):
                val = evaluate(col["formula"], row_dict, all_dicts,
                               agg_cache=agg_cache, sym_index=sym_index,
                               day_history=day_history)
                enriched[col["name"]] = val
                values.append(val)
            row_filter = strat.get("row_filter", [])
            passed = (not row_filter) or evaluate_condition(
                row_filter, enriched, all_dicts, agg_cache=agg_cache,
                sym_index=sym_index, day_history=day_history)
            per_strat.append((passed, values))

        # Drop rows excluded by every active filter (union of filters).
        if not any_unfiltered and not any(passed for passed, _ in per_strat):
            continue

        extra_vals = []
        for (passed, values), strat in zip(per_strat, active):
            if passed:
                extra_vals.extend(values)
            else:
                # Row is shown (matched another strategy) but this strategy's
                # columns don't apply to it.
                extra_vals.extend([None] * len(strat.get("columns", [])))
        new_data.append(list(row) + extra_vals)

    return new_headers, new_data


def _match_fmt_rule(col_def: dict, value, row_dict: dict,
                    all_dicts: list, agg_cache: dict | None = None,
                    sym_index: dict | None = None,
                    day_history: dict | None = None) -> dict | None:
    """Return the first fmt rule whose condition matches (THIS = value,
    this column's own computed value), else None. First match wins."""
    for rule in col_def.get("fmt_rules", []):
        if not rule.get("condition"):
            continue
        if evaluate_condition(rule["condition"], row_dict, all_dicts,
                              self_value=value, agg_cache=agg_cache,
                              sym_index=sym_index, day_history=day_history):
            return rule
    return None


def get_cell_color(col_def: dict, value, row_dict: dict,
                   all_dicts: list, agg_cache: dict | None = None,
                   sym_index: dict | None = None,
                   day_history: dict | None = None) -> str | None:
    """Return hex color if any fmt rule matches, else None."""
    rule = _match_fmt_rule(col_def, value, row_dict, all_dicts, agg_cache,
                           sym_index, day_history)
    return rule.get("color") if rule else None


def get_row_fmt_colors(strat_col_defs: list, row: list, base_col_count: int,
                       row_dict: dict, all_dicts: list,
                       agg_cache: dict | None = None,
                       sym_index: dict | None = None,
                       day_history: dict | None = None) -> dict:
    """One row's resolved {target_column_name: color} map, combining every
    active strategy column's conditional formatting.

    A fmt rule's condition is always evaluated against its OWNING strategy
    column's own computed value (THIS) — only WHERE the resulting color
    paints changes: a rule's "target_column" (see services.strategy_store)
    is the LMV column the user picked in Strategy Builder, defaulting to the
    owning strategy column's own cell when none was picked. When two
    matching rules (from different strategy columns) target the same column
    for this row, the earlier one in strat_col_defs order wins — same
    "first match wins" spirit get_cell_color already uses per-column.
    """
    colors: dict = {}
    for strat_idx, col_def in enumerate(strat_col_defs):
        idx = base_col_count + strat_idx
        if idx >= len(row):
            continue
        rule = _match_fmt_rule(col_def, row[idx], row_dict, all_dicts,
                               agg_cache, sym_index, day_history)
        if rule is None:
            continue
        target = rule.get("target_column") or col_def.get("name")
        colors.setdefault(target, rule.get("color"))
    return colors


def compile_check(tokens: list, row_data: dict, all_data: list,
                  self_value=None, lmv_headers: list | None = None) -> tuple:
    """
    Validate tokens against the actual loaded LMV sheet (never dummy data).
    Returns (True, result_str) on success, (False, error_message) on failure.

    ``row_data``/``all_data`` are the caller-chosen test row and full sheet
    (see screens.strategy_builder._pick_compile_test_row — callers avoid
    handing this an index row like NIFTY, which is missing live-overlay
    columns such as DAY TO/CWTO and would otherwise fail every formula that
    touches them). ``self_value`` is the column's own computed value, used
    to resolve the THIS token in conditional-format conditions. Errors are
    reported specifically: unknown columns, syntax errors, or the actual
    Python exception raised while evaluating the formula.

    ``lmv_headers``, when given, is the set of columns genuinely on the
    loaded LMV sheet right now (as opposed to every name offered in the
    Fields list — a strategy's other columns, Formula Builder fields —
    which also appear as keys in row_data, backfilled to None, so the
    "unknown column" check above doesn't reject a reference to one). Any
    referenced field NOT in lmv_headers that's still None gets a numeric
    placeholder instead of being evaluated strictly — see the
    used_placeholder block below. Omit it (None) to test every referenced
    field strictly, historic or not — the old, stricter behaviour.
    """
    if not tokens:
        return False, "Formula is empty."

    # Expand {"type": "var"} references up front so every check below (the
    # unknown-column scan included) sees the referenced variable's own
    # tokens, not an opaque placeholder.
    tokens = _expand_var_tokens(tokens)
    if not tokens:
        return False, "The variable(s) this formula refers to are empty or missing."

    row_data = row_data or {}
    all_data = all_data or []

    # 1. Structural check — does the expression even parse? (The Expression
    # Editor already checks brackets/parentheses against the raw text before
    # reaching here, so this is mainly a safety net for tokens built some
    # other way, e.g. a JSON import.)
    expr = _tokens_to_expr(tokens, row_data, all_data, self_value)
    try:
        compile(expr, "<formula>", "eval")  # noqa: S307
    except SyntaxError:
        return False, ("This formula isn't structured correctly. Check that "
                       "every '(' has a matching ')', every '[' has a "
                       "matching ']', and that every operator (+, -, *, /) "
                       "has a value on both sides.")

    # 2. A THIS token needs the column's own value to test against.
    uses_self = any(tok.get("type") == "self" for tok in tokens)
    if uses_self and self_value is None:
        return False, ("THIS has no value to test against. Define the column's "
                       "value formula first (and ensure it produces a result "
                       "on the loaded sheet) before using THIS in a condition.")

    # 3. Column-referencing formulas need a loaded sheet to test against.
    referenced = _referenced_columns(tokens)
    if referenced and not row_data:
        return False, ("No LMV sheet is loaded. Load a sheet before "
                       "running the compile test.")

    # 4. Every referenced column must exist in the loaded sheet.
    unknown = [c for c in referenced if c not in row_data]
    if unknown:
        names = ", ".join(f"[{c}]" for c in unknown)
        return False, (f"Unknown column(s): {names}. "
                       f"This name doesn't match any column in your data — "
                       f"check the spelling, spaces and capitalization, or "
                       f"pick it from the Fields list instead of typing it.")

    # 4.5. A referenced field that isn't one of the sheet's own currently-
    # loaded columns — another strategy column, a Formula Builder field
    # like a historic MAX_OF/_DAYS lookup ("[Last5Day]" = MAX_OF([DAY TO],
    # LAST_5_TRADING_DAYS)), etc. — can't be reliably resolved here: its
    # real value depends on network/historic data this editor doesn't
    # always have fetched (see StrategyEditor._fetch_own_day_history).
    # Testing it strictly would mean a perfectly good formula can only ever
    # compile-test successfully once that data happens to be cached — the
    # exact "tried to do math with an empty cell" false negative this
    # guards against. Stand in a numeric placeholder for any such field
    # that's still blank; only genuinely-loaded LMV columns are held to a
    # strict, real value from here on.
    used_placeholder = False
    if lmv_headers is not None:
        substituted = dict(row_data)
        for c in referenced:
            if c not in lmv_headers and substituted.get(c) is None:
                substituted[c] = 1.0
                used_placeholder = True
        row_data = substituted

    # 5. Evaluate against the real first row, surfacing the actual error.
    result, err = _evaluate_verbose(tokens, row_data, all_data, self_value)
    if err:
        return False, (_friendly_exception(err) if isinstance(err, Exception) else err)

    if result is None:
        # Formula ran but produced no value — usually an empty cell feeding a
        # numeric function in this particular row.
        return False, ("This formula didn't produce a result for the first "
                       "row — usually because one of the cells it uses is "
                       "empty. Check the data in that row of your sheet.")

    if used_placeholder or _uses_day_funcs(tokens):
        # _tokens_to_expr stood in a numeric placeholder for every _DAYS/
        # VALUE_DAYS_AGO/VALUE_ON_DATE function typed directly here, and/or
        # step 4.5 above did the same for a referenced historic/derived
        # field — either way *result* isn't the real value. Say so instead
        # of implying it's live.
        return True, (f"{result} (using a placeholder for the historic/"
                      f"derived value(s) while editing — Save, then reload "
                      f"Live Master View to see the real value)")

    return True, str(result)
