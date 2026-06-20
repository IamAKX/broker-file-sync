"""
Formula evaluator for strategy columns.

Given:
  - tokens: list of token dicts (see strategy_store.py)
  - row_data: dict  {col_name -> value}   (one row from LMV)
  - all_data: list of row_data dicts       (all rows, for aggregate functions)
  - self_value: float | None               (column's own computed value, for fmt rules)

Returns float | str | None.

Supported:
  Per-row  : +  -  *  /  (  )  MIN  MAX  ABS  ROUND  FLOOR  CEIL  IF
  Aggregate: SUM_ALL  MIN_ALL  MAX_ALL  AVG_ALL  COUNT_ALL
"""

import math
import re


# ── token → expression string ──────────────────────────────────────────────

def _tokens_to_expr(tokens: list, row_data: dict, all_data: list,
                    self_value=None) -> str:
    parts = []
    for tok in tokens:
        t = tok.get("type")
        v = tok.get("value", "")

        if t == "col":
            raw = row_data.get(v)
            try:
                parts.append(str(float(raw)) if raw not in (None, "") else "0")
            except (TypeError, ValueError):
                parts.append("0")

        elif t == "self":
            parts.append(str(float(self_value)) if self_value is not None else "0")

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
                # per-row function: emit Python-callable name + (
                _FUNC_MAP = {
                    "MIN": "min", "MAX": "max",
                    "ABS": "abs", "ROUND": "round",
                    "FLOOR": "_floor", "CEIL": "_ceil",
                    "SUM": "_sum", "IF": "_if",
                }
                parts.append(_FUNC_MAP.get(fname, fname.lower()) + "(")

    return "".join(parts)


def _floor(x, *_):  return math.floor(x)
def _ceil(x, *_):   return math.ceil(x)
def _sum(*args):     return sum(args)
def _if(cond, a, b): return a if cond else b


def evaluate(tokens: list, row_data: dict, all_data: list,
             self_value=None):
    """Return numeric result or None on error."""
    if not tokens:
        return None
    expr = _tokens_to_expr(tokens, row_data, all_data, self_value)
    if not expr.strip():
        return None
    try:
        result = eval(expr, {   # noqa: S307
            "__builtins__": {},
            "min": min, "max": max, "abs": abs, "round": round,
            "_floor": _floor, "_ceil": _ceil,
            "_sum": _sum, "_if": _if,
        })
        return result
    except Exception:
        return None


def evaluate_condition(tokens: list, row_data: dict, all_data: list,
                       self_value=None) -> bool:
    """Return True if condition is met."""
    result = evaluate(tokens, row_data, all_data, self_value)
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

    extra_headers = []
    for strat in active:
        for col in strat.get("columns", []):
            extra_headers.append(col["name"])

    new_headers = list(headers) + extra_headers

    new_data = []
    for row_idx, row in enumerate(data):
        row_dict = dict(zip(headers, row))
        extra_vals = []
        for strat in active:
            for col in strat.get("columns", []):
                val = evaluate(col["formula"], row_dict, all_dicts)
                extra_vals.append(val)
        new_data.append(list(row) + extra_vals)

    return new_headers, new_data


def get_cell_color(col_def: dict, value, row_dict: dict,
                   all_dicts: list) -> str | None:
    """Return hex color if any fmt rule matches, else None."""
    for rule in col_def.get("fmt_rules", []):
        if not rule.get("condition"):
            continue
        if evaluate_condition(rule["condition"], row_dict, all_dicts,
                              self_value=value):
            return rule.get("color")
    return None
