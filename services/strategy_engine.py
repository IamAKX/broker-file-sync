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
             ISNULL  ISNULLOREMPTY  INRANGE
             TODECIMAL  TODOUBLE  TOFLOAT  TOINT  TOLONG  TOSTR
  Aggregate: SUM_ALL  MIN_ALL  MAX_ALL  AVG_ALL  COUNT_ALL
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


# ── token → expression string ──────────────────────────────────────────────

def _tokens_to_expr(tokens: list, row_data: dict, all_data: list,
                    self_value=None) -> str:
    parts = []
    for tok in tokens:
        t = tok.get("type")
        v = tok.get("value", "")

        if t == "col":
            parts.append(_col_literal(row_data.get(v)))

        elif t == "self":
            parts.append(_col_literal(self_value))

        elif t in ("num", "op", "paren"):
            parts.append(v)

        elif t == "func":
            # aggregate functions have _ALL suffix; map to a single computed number
            fname = v.rstrip("(").upper()
            if fname.endswith("_ALL"):
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


class _Compiled:
    """A formula's fixed structure, compiled once and reused across rows/ticks.

    ``col_vars`` maps referenced column name -> placeholder variable name
    (e.g. "_c0"). ``agg_specs`` is [(placeholder, base_op, col_name), ...]
    for _ALL aggregate functions, resolved once per tick rather than once
    per row (they don't depend on the row being evaluated).
    """
    __slots__ = ("code", "col_vars", "uses_self", "agg_specs")

    def __init__(self, code, col_vars, uses_self, agg_specs):
        self.code = code
        self.col_vars = col_vars
        self.uses_self = uses_self
        self.agg_specs = agg_specs


_compile_cache: dict = {}


def _formula_signature(tokens: list):
    return tuple((tok.get("type"), tok.get("value"), tok.get("col_arg"))
                 for tok in tokens)


def _build_compiled(tokens: list):
    parts = []
    col_vars: dict = {}
    uses_self = False
    agg_specs = []

    for tok in tokens:
        t = tok.get("type")
        v = tok.get("value", "")

        if t == "col":
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
            if fname.endswith("_ALL"):
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
    return _Compiled(code, col_vars, uses_self, agg_specs)


def _get_compiled(tokens: list):
    sig = _formula_signature(tokens)
    if sig not in _compile_cache:
        _compile_cache[sig] = _build_compiled(tokens)
    return _compile_cache[sig]


def evaluate(tokens: list, row_data: dict, all_data: list,
             self_value=None, agg_cache: dict | None = None):
    """Return numeric or string result, or None on error.

    ``agg_cache``, when provided, memoizes _ALL aggregate results by
    (base_op, col_name) for the caller's own scope (e.g. one dict per
    apply_strategies()/render pass) so an aggregate is computed once
    instead of once per row.
    """
    if not tokens:
        return None
    compiled = _get_compiled(tokens)
    if compiled is None:
        return None
    ns = _EVAL_BUILTINS.copy()
    for col_name, var in compiled.col_vars.items():
        ns[var] = _col_value(row_data.get(col_name))
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
    try:
        return eval(compiled.code, ns)   # noqa: S307
    except Exception:
        return None


def _evaluate_verbose(tokens: list, row_data: dict, all_data: list,
                      self_value=None):
    """Like evaluate() but returns (result, error). error is None on success.

    Unlike evaluate(), this surfaces the real Python exception so the compile
    test can report a specific, correct reason for failure.
    """
    if not tokens:
        return None, "Formula is empty."
    expr = _tokens_to_expr(tokens, row_data, all_data, self_value)
    if not expr.strip():
        return None, "Formula is empty."
    try:
        return eval(expr, _EVAL_BUILTINS), None   # noqa: S307
    except Exception as exc:
        return None, f"{type(exc).__name__}: {exc}"


def _referenced_columns(tokens: list) -> list:
    """Distinct column names referenced by col tokens and aggregate col_args."""
    cols = []
    for tok in tokens:
        if tok.get("type") == "col" and tok.get("value"):
            cols.append(tok["value"])
        if tok.get("col_arg"):
            cols.append(tok["col_arg"])
    # preserve order, drop dups
    seen, out = set(), []
    for c in cols:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out


def evaluate_condition(tokens: list, row_data: dict, all_data: list,
                       self_value=None, agg_cache: dict | None = None) -> bool:
    """Return True if condition is met."""
    result = evaluate(tokens, row_data, all_data, self_value, agg_cache)
    if result is None:
        return False
    return bool(result)


def apply_strategies(strategies: list, headers: list,
                     data: list[list]) -> tuple[list, list[list]]:
    """
    Append strategy columns to headers and data rows.
    Returns (new_headers, new_data).
    Only active strategies are applied.
    """
    active = [s for s in strategies if s.get("active")]
    if not active:
        return headers, data

    # Build list of all dicts for aggregate functions
    all_dicts = [dict(zip(headers, row)) for row in data]
    # Memoizes SUM_ALL/AVG_ALL/etc. by (base_op, col_name) for this call, so an
    # aggregate over all rows is computed once instead of once per row.
    agg_cache: dict = {}

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
                               agg_cache=agg_cache)
                enriched[col["name"]] = val
                values.append(val)
            row_filter = strat.get("row_filter", [])
            passed = (not row_filter) or evaluate_condition(
                row_filter, enriched, all_dicts, agg_cache=agg_cache)
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


def get_cell_color(col_def: dict, value, row_dict: dict,
                   all_dicts: list, agg_cache: dict | None = None) -> str | None:
    """Return hex color if any fmt rule matches, else None."""
    for rule in col_def.get("fmt_rules", []):
        if not rule.get("condition"):
            continue
        if evaluate_condition(rule["condition"], row_dict, all_dicts,
                              self_value=value, agg_cache=agg_cache):
            return rule.get("color")
    return None


def compile_check(tokens: list, row_data: dict, all_data: list,
                  self_value=None) -> tuple:
    """
    Validate tokens against the actual loaded LMV sheet (never dummy data).
    Returns (True, result_str) on success, (False, error_message) on failure.

    The first row of the real sheet is used as the test row. ``self_value`` is
    the column's own computed value, used to resolve the THIS token in
    conditional-format conditions. Errors are reported specifically: unknown
    columns, syntax errors, or the actual Python exception raised while
    evaluating the formula.
    """
    if not tokens:
        return False, "Formula is empty."

    row_data = row_data or {}
    all_data = all_data or []

    # 1. Structural check — does the expression even parse?
    expr = _tokens_to_expr(tokens, row_data, all_data, self_value)
    try:
        compile(expr, "<formula>", "eval")  # noqa: S307
    except SyntaxError as exc:
        return False, f"Syntax error: {exc}"

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
                       f"Check the column name against the loaded sheet.")

    # 5. Evaluate against the real first row, surfacing the actual error.
    result, err = _evaluate_verbose(tokens, row_data, all_data, self_value)
    if err:
        return False, err

    if result is None:
        # Formula ran but produced no value — usually an empty cell feeding a
        # numeric function in this particular row.
        return False, ("Formula evaluated to None on the first row "
                       "(an input cell is likely empty). "
                       "Verify the data in the loaded sheet.")

    return True, str(result)
