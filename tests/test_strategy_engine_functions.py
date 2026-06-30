"""Tests for every function implemented in strategy_engine._FUNC_MAP / _EVAL_BUILTINS."""
import math
import pytest
from services.strategy_engine import evaluate

ROW  = {"a": "10", "b": "3", "s": "Hello World", "empty": "", "name": "INFY"}
ALL  = [ROW]


def ev(tokens):
    return evaluate(tokens, ROW, ALL)


def tok_num(v):    return {"type": "num",  "value": str(v)}
def tok_op(v):     return {"type": "op",   "value": v}
def tok_fn(name):  return {"type": "func", "value": f"{name}("}
def tok_col(name): return {"type": "col",  "value": name}
def tok_p_open():  return {"type": "paren", "value": "("}
def tok_p_close(): return {"type": "paren", "value": ")"}
def call1(fn, a):          return [tok_fn(fn), a, tok_p_close()]
def call2(fn, a, b):       return [tok_fn(fn), a, tok_op(","), b, tok_p_close()]
def call3(fn, a, b, c):    return [tok_fn(fn), a, tok_op(","), b, tok_op(","), c, tok_p_close()]


# ── Math ──────────────────────────────────────────────────────────────────────

def test_abs_positive():    assert ev(call1("Abs",  tok_num(-7)))  == 7
def test_abs_negative():    assert ev(call1("Abs",  tok_num(5)))   == 5
def test_floor():           assert ev(call1("Floor", tok_num(2.9))) == 2
def test_ceiling():         assert ev(call1("Ceiling", tok_num(2.1))) == 3
def test_round_int():       assert ev(call1("Round", tok_num(2.5))) == 2  # banker's rounding
def test_round_digits():    assert ev(call2("Round", tok_num(3.14159), tok_num(2))) == 3.14
def test_exp():             assert abs(ev(call1("Exp", tok_num(1))) - math.e) < 1e-9
def test_log_natural():     assert abs(ev(call1("Log", tok_num(math.e))) - 1.0) < 1e-9
def test_log_with_base():   assert abs(ev(call2("Log", tok_num(8), tok_num(2))) - 3.0) < 1e-9
def test_log10():           assert abs(ev(call1("Log10", tok_num(100))) - 2.0) < 1e-9
def test_max():             assert ev(call2("Max", tok_num(3), tok_num(7)))  == 7
def test_min():             assert ev(call2("Min", tok_num(3), tok_num(7)))  == 3
def test_power():           assert ev(call2("Power", tok_num(2), tok_num(10))) == 1024
def test_sign_positive():   assert ev(call1("Sign", tok_num(5)))   == 1
def test_sign_negative():   assert ev(call1("Sign", tok_num(-3)))  == -1
def test_sign_zero():       assert ev(call1("Sign", tok_num(0)))   == 0
def test_sqr():             assert abs(ev(call1("Sqr", tok_num(9))) - 3.0) < 1e-9
def test_bigmul():          assert ev(call2("BigMul", tok_num(12345), tok_num(67890))) == 12345 * 67890


# ── Trig ──────────────────────────────────────────────────────────────────────

def test_cos():     assert abs(ev(call1("Cos",  tok_num(0))) - 1.0) < 1e-9
def test_sin():     assert abs(ev(call1("Sin",  tok_num(0))) - 0.0) < 1e-9
def test_tan():     assert abs(ev(call1("Tan",  tok_num(0))) - 0.0) < 1e-9
def test_cosh():    assert abs(ev(call1("Cosh", tok_num(0))) - 1.0) < 1e-9
def test_sinh():    assert abs(ev(call1("Sinh", tok_num(0))) - 0.0) < 1e-9
def test_tanh():    assert abs(ev(call1("Tanh", tok_num(0))) - 0.0) < 1e-9
def test_acos():    assert abs(ev(call1("Acos", tok_num(1))) - 0.0) < 1e-9
def test_asin():    assert abs(ev(call1("Asin", tok_num(0))) - 0.0) < 1e-9
def test_atn():     assert abs(ev(call1("Atn",  tok_num(1))) - math.pi/4) < 1e-9
def test_atn2():    assert abs(ev(call2("Atn2", tok_num(1), tok_num(1))) - math.pi/4) < 1e-9


# ── Conditional / logic ───────────────────────────────────────────────────────

def test_iif_true():        assert ev(call3("IIf", tok_num(1), tok_num(42), tok_num(0))) == 42
def test_iif_false():       assert ev(call3("IIf", tok_num(0), tok_num(42), tok_num(99))) == 99
def test_isnull_none():     assert ev(call1("IsNull", tok_col("empty"))) == True   # "" → None path
def test_isnull_value():    assert ev(call1("IsNull", tok_num(5))) == False
def test_isnullorempty_empty():  assert ev(call1("IsNullOrEmpty", tok_col("empty"))) == True
def test_isnullorempty_filled(): assert ev(call1("IsNullOrEmpty", tok_num(1))) == False
def test_inrange_inside():  assert ev(call3("InRange", tok_num(5), tok_num(1), tok_num(10))) == True
def test_inrange_outside(): assert ev(call3("InRange", tok_num(15), tok_num(1), tok_num(10))) == False


# ── String ────────────────────────────────────────────────────────────────────

def test_concat():
    tokens = call2("Concat", tok_col("name"), tok_num('" Ltd"'))
    assert ev(tokens) == "INFY Ltd"

def test_len():             assert ev(call1("Len", tok_num('"Hello"'))) == 5
def test_lower():           assert ev(call1("Lower", tok_num('"HELLO"'))) == "hello"
def test_upper():           assert ev(call1("Upper", tok_num('"hello"'))) == "HELLO"
def test_trim():            assert ev(call1("Trim",  tok_num('"  hi  "'))) == "hi"
def test_replace():
    tokens = call3("Replace", tok_num('"foo bar"'), tok_num('"bar"'), tok_num('"baz"'))
    assert ev(tokens) == "foo baz"

def test_reverse():         assert ev(call1("Reverse", tok_num('"abc"'))) == "cba"
def test_startswith_true(): assert ev(call2("StartsWith", tok_num('"Hello"'), tok_num('"He"'))) == True
def test_startswith_false():assert ev(call2("StartsWith", tok_num('"Hello"'), tok_num('"Wo"'))) == False
def test_endswith_true():   assert ev(call2("EndsWith", tok_num('"Hello"'), tok_num('"lo"'))) == True
def test_endswith_false():  assert ev(call2("EndsWith", tok_num('"Hello"'), tok_num('"Hi"'))) == False
def test_contains_true():   assert ev(call2("Contains", tok_num('"Hello World"'), tok_num('"World"'))) == True
def test_contains_false():  assert ev(call2("Contains", tok_num('"Hello"'), tok_num('"xyz"'))) == False
def test_substring():       assert ev(call3("Substring", tok_num('"Hello"'), tok_num(1), tok_num(3))) == "ell"
def test_charindex():       assert ev(call2("CharIndex", tok_num('"Hello"'), tok_num('"ll"'))) == 2
def test_insert():          assert ev(call3("Insert", tok_num('"Hllo"'), tok_num(1), tok_num('"e"'))) == "Hello"
def test_remove():          assert ev(call2("Remove", tok_num('"aXbXc"'), tok_num('"X"'))) == "abc"
def test_padleft():         assert ev(call2("PadLeft",  tok_num('"hi"'), tok_num(5))) == "   hi"
def test_padright():        assert ev(call2("PadRight", tok_num('"hi"'), tok_num(5))) == "hi   "
def test_ascii():           assert ev(call1("Ascii", tok_num('"A"'))) == 65
def test_char():            assert ev(call1("Char",  tok_num(65))) == "A"


# ── Type conversion ───────────────────────────────────────────────────────────

def test_toint():           assert ev(call1("ToInt",     tok_num(3.9)))   == 3
def test_tofloat():         assert abs(ev(call1("ToFloat",   tok_num('"2.5"'))) - 2.5) < 1e-9
def test_todouble():        assert abs(ev(call1("ToDouble",  tok_num('"1.1"'))) - 1.1) < 1e-9
def test_todecimal():       assert abs(ev(call1("ToDecimal", tok_num('"3.3"'))) - 3.3) < 1e-9
def test_tolong():          assert ev(call1("ToLong", tok_num(7.8))) == 7
def test_tostr():           assert ev(call1("ToStr",  tok_num(42))) == "42"


# ── Aggregate ─────────────────────────────────────────────────────────────────

MULTI_ROW = [{"v": "10"}, {"v": "20"}, {"v": "30"}]

def ev_agg(tokens):
    return evaluate(tokens, MULTI_ROW[0], MULTI_ROW)

def agg_tok(fn, col):
    # Aggregate tokens carry col_arg inline; the engine pre-computes them to a
    # scalar so no separate closing-paren token should follow.
    return [{"type": "func", "value": f"{fn}(", "col_arg": col}]

def test_sum_all():     assert ev_agg(agg_tok("SUM_ALL",   "v")) == 60
def test_min_all():     assert ev_agg(agg_tok("MIN_ALL",   "v")) == 10
def test_max_all():     assert ev_agg(agg_tok("MAX_ALL",   "v")) == 30
def test_avg_all():     assert ev_agg(agg_tok("AVG_ALL",   "v")) == 20
def test_count_all():   assert ev_agg(agg_tok("COUNT_ALL", "v")) == 3


# ── Column value handling ─────────────────────────────────────────────────────

def test_col_numeric_in_math():
    # [a] + [b] = 10 + 3 = 13
    tokens = [tok_col("a"), tok_op("+"), tok_col("b")]
    assert ev(tokens) == 13

def test_col_string_in_concat():
    tokens = call2("Concat", tok_col("name"), tok_num('" Corp"'))
    assert ev(tokens) == "INFY Corp"

def test_col_empty_is_none():
    # IsNull([empty]) should be True because empty string → None literal
    tokens = call1("IsNull", tok_col("empty"))
    assert ev(tokens) == True


# ── compile_check against the real loaded LMV sheet (no dummy data) ─────────────

def test_compile_check_succeeds_on_real_data():
    from services.strategy_engine import compile_check
    tokens = call2("Max", tok_col("High"), tok_col("Low"))
    row = {"High": "100", "Low": "50"}
    ok, msg = compile_check(tokens, row, [row])
    assert ok, msg
    assert msg == "100.0"

def test_compile_check_unknown_column_named_in_error():
    # Referenced column does not exist in the loaded sheet → specific error.
    from services.strategy_engine import compile_check
    tokens = call2("Max", tok_col("High"), tok_col("Low"))
    row = {"Low": "50"}                       # no "High" column
    ok, msg = compile_check(tokens, row, [row])
    assert not ok
    assert "[High]" in msg
    assert "Unknown column" in msg

def test_compile_check_empty_cell_reports_none_not_dummy():
    # High present but empty: evaluate on real data, report a real reason,
    # never substitute dummy 1.0 values.
    from services.strategy_engine import compile_check
    tokens = call2("Max", tok_col("High"), tok_col("Low"))
    row = {"High": "", "Low": "50"}
    ok, msg = compile_check(tokens, row, [row])
    assert not ok
    assert "dummy" not in msg.lower()
    assert "None" in msg or "empty" in msg.lower()

def test_compile_check_no_sheet_loaded():
    from services.strategy_engine import compile_check
    tokens = call2("Max", tok_col("High"), tok_col("Low"))
    ok, msg = compile_check(tokens, {}, [])
    assert not ok
    assert "loaded" in msg.lower()

def test_compile_check_empty_tokens():
    from services.strategy_engine import compile_check
    ok, msg = compile_check([], {"High": "1"}, [{"High": "1"}])
    assert not ok
    assert "empty" in msg.lower()


# ── compile_check with THIS / self_value (conditional-format conditions) ───────

def tok_self():    return {"type": "self"}

def test_compile_check_this_resolves_to_self_value():
    # THIS <= 10000 with the column's own value supplied → compiles.
    from services.strategy_engine import compile_check
    tokens = [tok_self(), tok_op("<="), {"type": "num", "value": "10000"}]
    ok, msg = compile_check(tokens, {"LTP": "5"}, [{"LTP": "5"}], self_value=5000)
    assert ok, msg
    assert msg == "True"

def test_compile_check_this_false_branch_still_compiles():
    from services.strategy_engine import compile_check
    tokens = [tok_self(), tok_op("<="), {"type": "num", "value": "10000"}]
    ok, msg = compile_check(tokens, {"LTP": "5"}, [{"LTP": "5"}], self_value=20000)
    assert ok, msg
    assert msg == "False"

def test_compile_check_this_without_value_reports_clearly():
    # No self_value provided → THIS is None; report a clear reason, not a raw
    # TypeError about NoneType.
    from services.strategy_engine import compile_check
    tokens = [tok_self(), tok_op("<="), {"type": "num", "value": "10000"}]
    ok, msg = compile_check(tokens, {"LTP": "5"}, [{"LTP": "5"}])
    assert not ok
    assert "THIS" in msg


# ── apply_strategies row filtering (filtered rows are dropped) ──────────────────

def _eq(col, val):
    return [tok_col(col), tok_op("=="), {"type": "num", "value": repr(val)}]

def test_apply_strategies_drops_filtered_rows():
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True, "row_filter": _eq("Sector", "CG"),
        "columns": [{"name": "Out", "formula": [tok_col("LTP")]}],
    }
    headers = ["Sector", "LTP"]
    data = [["CG", "10"], ["IT", "20"], ["CG", "30"]]
    new_headers, new_data = apply_strategies([strat], headers, data)
    assert new_headers == ["Sector", "LTP", "Out"]
    # Only the two CG rows survive
    assert [r[0] for r in new_data] == ["CG", "CG"]
    assert [r[2] for r in new_data] == [10.0, 30.0]

def test_apply_strategies_no_filter_keeps_all_rows():
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True, "row_filter": [],
        "columns": [{"name": "Out", "formula": [tok_col("LTP")]}],
    }
    headers = ["Sector", "LTP"]
    data = [["CG", "10"], ["IT", "20"]]
    _, new_data = apply_strategies([strat], headers, data)
    assert len(new_data) == 2

def test_apply_strategies_row_kept_if_any_active_strategy_matches():
    # Union semantics: a row visible if it passes ANY active strategy's filter.
    from services.strategy_engine import apply_strategies
    s_cg = {"id": "1", "active": True, "row_filter": _eq("Sector", "CG"),
            "columns": [{"name": "A", "formula": [tok_col("LTP")]}]}
    s_it = {"id": "2", "active": True, "row_filter": _eq("Sector", "IT"),
            "columns": [{"name": "B", "formula": [tok_col("LTP")]}]}
    headers = ["Sector", "LTP"]
    data = [["CG", "10"], ["IT", "20"], ["FIN", "30"]]
    _, new_data = apply_strategies([s_cg, s_it], headers, data)
    # CG and IT rows survive (each matches one strategy); FIN dropped.
    assert [r[0] for r in new_data] == ["CG", "IT"]

def test_apply_strategies_unfiltered_strategy_keeps_all_rows():
    # If any active strategy has no filter, every row is included.
    from services.strategy_engine import apply_strategies
    s_cg  = {"id": "1", "active": True, "row_filter": _eq("Sector", "CG"),
             "columns": [{"name": "A", "formula": [tok_col("LTP")]}]}
    s_all = {"id": "2", "active": True, "row_filter": [],
             "columns": [{"name": "B", "formula": [tok_col("LTP")]}]}
    headers = ["Sector", "LTP"]
    data = [["CG", "10"], ["IT", "20"]]
    _, new_data = apply_strategies([s_cg, s_all], headers, data)
    assert len(new_data) == 2

def test_row_filter_can_reference_strategy_own_column():
    # Filter on the strategy's computed column (not a raw LMV column).
    # Column "Out" = LTP; keep rows where Out <= 15.
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True,
        "row_filter": [tok_col("Out"), tok_op("<="), {"type": "num", "value": "15"}],
        "columns": [{"name": "Out", "formula": [tok_col("LTP")]}],
    }
    headers = ["Sector", "LTP"]
    data = [["CG", "10"], ["IT", "20"], ["FIN", "12"]]
    new_headers, new_data = apply_strategies([strat], headers, data)
    assert new_headers == ["Sector", "LTP", "Out"]
    # LTP 10 and 12 pass (<=15); 20 dropped.
    assert [r[1] for r in new_data] == ["10", "12"]
    assert [r[2] for r in new_data] == [10.0, 12.0]
