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
def test_digits_5_digit():  assert ev(call1("Digits", tok_num(12123.77))) == 5
def test_digits_4_digit():  assert ev(call1("Digits", tok_num(2435.22)))  == 4
def test_digits_negative(): assert ev(call1("Digits", tok_num(-87.5)))    == 2
def test_digits_zero():     assert ev(call1("Digits", tok_num(0)))        == 1
def test_digits_power_of_ten_boundary():
    # Regression guard: log10(1000) can land at 2.9999999999996 in floating
    # point, which would undercount a clean 4-digit boundary as 3.
    assert ev(call1("Digits", tok_num(1000.0))) == 4


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


def _digit_tiered_threshold(open_value):
    """IIf(Digits([Open]) >= 5, 0.998, IIf(Digits([Open]) >= 4, 0.919, 0.85))
    — the "percent that depends on how many digits [Open] has" pattern."""
    row = {"Open": str(open_value)}
    tokens = (
        [tok_fn("IIf"),
            tok_fn("Digits"), tok_col("Open"), tok_p_close(),
            tok_op(">="), tok_num(5), tok_op(","),
            tok_num(0.998), tok_op(","),
            tok_fn("IIf"),
                tok_fn("Digits"), tok_col("Open"), tok_p_close(),
                tok_op(">="), tok_num(4), tok_op(","),
                tok_num(0.919), tok_op(","),
                tok_num(0.85),
            tok_p_close(),
        tok_p_close()]
    )
    return evaluate(tokens, row, [row])


def test_digit_tiered_threshold_five_digit_open():
    assert _digit_tiered_threshold(12123.77) == 0.998


def test_digit_tiered_threshold_four_digit_open():
    assert _digit_tiered_threshold(2435.22) == 0.919


def test_digit_tiered_threshold_three_digit_open():
    assert _digit_tiered_threshold(435.5) == 0.85


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
    # A strategy with a row filter also gets its own Days True/Since
    # streak columns (see the "Row-filter streak" tests below) — assert
    # "Out" by index rather than assuming it's the last header.
    assert new_headers == ["Sector", "LTP", "Out", "Strategy — Days True", "Strategy — Since"]
    out_idx = new_headers.index("Out")
    # Only the two CG rows survive
    assert [r[0] for r in new_data] == ["CG", "CG"]
    assert [r[out_idx] for r in new_data] == [10.0, 30.0]

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

def test_apply_strategies_later_column_can_reference_earlier_own_column():
    """Regression: a column's formula used to be evaluated against the
    original row (row_dict) rather than the row enriched with this same
    strategy's own earlier-computed columns — so "Trigger Price" =
    [Floor_10D] * 1.01 (both columns of ONE strategy) silently came back
    None here even though Strategy Builder's own Test Formula (which DOES
    pre-compute sibling columns — see screens.strategy_builder.
    StrategyEditor._combined_headers_and_values) showed a real value while
    editing. Only the row filter honored this before; every column now does."""
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True, "row_filter": [],
        "columns": [
            {"name": "Floor_10D", "formula": [tok_col("Low")]},
            {"name": "Trigger Price", "formula": [tok_col("Floor_10D"), tok_op("*"), tok_num(1.01)]},
        ],
    }
    headers = ["Sector", "Low"]
    data = [["CG", "100"]]
    new_headers, new_data = apply_strategies([strat], headers, data)
    assert new_data[0][new_headers.index("Floor_10D")] == 100.0
    assert new_data[0][new_headers.index("Trigger Price")] == 101.0


# ── inception_values (HMV historical fields in LMV formulas) ─────────────────

def _inception_strat():
    return {
        "id": "i1", "active": True, "row_filter": [],
        "columns": [{"name": "Gap to 52WH",
                     "formula": [tok_col("52WH"), tok_op("-"), tok_col("Close")]}],
    }


def test_apply_strategies_resolves_inception_field_for_matched_row():
    from services.strategy_engine import apply_strategies
    headers = ["Scrip Name", "Close"]
    data = [["BAJAJ-AUTO", "9000"], ["RANDOMCASH", "50"]]
    inception_values = {"BAJAJAUTO": {"52WH": 9500.0}}
    new_headers, new_data = apply_strategies(
        [_inception_strat()], headers, data, inception_values=inception_values,
    )
    col = new_headers.index("Gap to 52WH")
    assert new_data[0][col] == 500.0          # matched by normalized symbol
    assert new_data[1][col] is None           # no inception series -> blank


def test_apply_strategies_inception_fields_not_added_as_columns():
    from services.strategy_engine import apply_strategies
    headers = ["Scrip Name", "Close"]
    data = [["BAJAJ-AUTO", "9000"]]
    new_headers, _ = apply_strategies(
        [_inception_strat()], headers, data,
        inception_values={"BAJAJAUTO": {"52WH": 9500.0}},
    )
    assert "52WH" not in new_headers          # formula-only, never a grid column


def test_apply_strategies_inception_cross_row_reference():
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "i2", "active": True, "row_filter": [],
        "columns": [{"name": "RelATH",
                     "formula": [tok_col_of("ATH", "RELIANCE")]}],
    }
    headers = ["Scrip Name", "Close"]
    data = [["INFY", "1500"], ["RELIANCE", "2900"]]
    inception_values = {"RELIANCE": {"ATH": 3100.0}}
    new_headers, new_data = apply_strategies(
        [strat], headers, data, inception_values=inception_values,
    )
    assert new_data[0][new_headers.index("RelATH")] == 3100.0


def test_apply_strategies_without_inception_values_is_unchanged():
    from services.strategy_engine import apply_strategies
    headers = ["Scrip Name", "Close"]
    data = [["BAJAJ-AUTO", "9000"]]
    a = apply_strategies([_inception_strat()], headers, [r[:] for r in data])
    b = apply_strategies([_inception_strat()], headers, [r[:] for r in data],
                         inception_values=None)
    assert a == b

def test_apply_strategies_row_filter_can_still_reference_own_column():
    """Same fix, from the row-filter side: this already worked (row filter
    was evaluated against `enriched`) — kept as a regression guard alongside
    the column-order fix above so the two don't drift apart again."""
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True,
        "row_filter": [tok_col("Trigger Price"), tok_op(">"), tok_num(100)],
        "columns": [
            {"name": "Floor_10D", "formula": [tok_col("Low")]},
            {"name": "Trigger Price", "formula": [tok_col("Floor_10D"), tok_op("*"), tok_num(1.01)]},
        ],
    }
    headers = ["Sector", "Low"]
    data = [["CG", "100"], ["CG", "1"]]
    _, new_data = apply_strategies([strat], headers, data)
    assert len(new_data) == 1
    assert float(new_data[0][headers.index("Low")]) == 100.0

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
    # A strategy with a row filter also gets its own Days True/Since
    # streak columns (see the "Row-filter streak" tests below).
    assert new_headers == ["Sector", "LTP", "Out", "Strategy — Days True", "Strategy — Since"]
    # LTP 10 and 12 pass (<=15); 20 dropped.
    assert [r[1] for r in new_data] == ["10", "12"]
    assert [r[2] for r in new_data] == [10.0, 12.0]


# ── "[Col of Symbol]" cross-row reference ────────────────────────────────────

def tok_col_of(name, symbol):
    return {"type": "col", "value": name, "of": symbol}


def test_col_of_reads_another_rows_value():
    row_a = {"Scrip Name": "NIFTY", "Open": "100"}
    row_b = {"Scrip Name": "INFY", "Open": "1500"}
    all_data = [row_a, row_b]
    result = evaluate([tok_col_of("Open", "NIFTY")], row_b, all_data)
    assert result == 100.0


def test_col_of_is_case_insensitive_and_trims_whitespace():
    row_a = {"Scrip Name": "NIFTY", "Open": "100"}
    result = evaluate([tok_col_of("Open", " nifty ")], {}, [row_a])
    assert result == 100.0


def test_col_of_unknown_symbol_returns_none():
    row_a = {"Scrip Name": "NIFTY", "Open": "100"}
    result = evaluate([tok_col_of("Open", "DOES-NOT-EXIST")], {}, [row_a])
    assert result is None


def test_col_of_combines_with_current_row_column():
    row_a = {"Scrip Name": "NIFTY", "Open": "100"}
    row_b = {"Scrip Name": "INFY", "High": "20", "Open": "1500"}
    tokens = [tok_col("High"), tok_op("/"), tok_col_of("Open", "NIFTY")]
    result = evaluate(tokens, row_b, [row_a, row_b])
    assert result == 0.2


def test_col_of_does_not_collide_with_plain_col_signature():
    # Same column name, with and without "of", must not share a compiled
    # formula (the cache key must include the "of" field).
    row_nifty = {"Scrip Name": "NIFTY", "Open": "100"}
    row_self  = {"Scrip Name": "INFY", "Open": "1500"}
    plain  = evaluate([tok_col("Open")], row_self, [row_nifty, row_self])
    of_ref = evaluate([tok_col_of("Open", "NIFTY")], row_self, [row_nifty, row_self])
    assert plain == 1500.0
    assert of_ref == 100.0


def test_apply_strategies_supports_col_of_formula():
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True, "row_filter": [],
        "columns": [{"name": "VsNifty", "formula": [tok_col("LTP"), tok_op("/"),
                                                     tok_col_of("LTP", "NIFTY")]}],
    }
    headers = ["Scrip Name", "LTP"]
    data = [["NIFTY", "100"], ["INFY", "50"]]
    new_headers, new_data = apply_strategies([strat], headers, data)
    assert new_headers == ["Scrip Name", "LTP", "VsNifty"]
    assert new_data[0][2] == 1.0    # NIFTY vs itself
    assert new_data[1][2] == 0.5    # INFY (50) / NIFTY (100)


# ── "[Col of Symbol]" with a non-default symbol_col (issue #16: Inception's
# row-identity column is "Symbol", not LMV's "Scrip Name") ───────────────────
# Regression for a real bug: evaluate_compiled built an on-demand sym_index
# via build_symbol_index(all_data) with NO symbol_col forwarded, always
# defaulting to "Scrip Name" — invisible via apply_strategies (which
# pre-builds sym_index with the right symbol_col and passes it in) but a
# bare evaluate()/compile_check() call (Strategy Builder's own Compile &
# Test) always got None for any row keyed by anything else.

def test_col_of_resolves_with_custom_symbol_col_via_bare_evaluate():
    row_a = {"Symbol": "RELIANCE_I", "Close": "2900"}
    row_b = {"Symbol": "ADANIENT_I", "Close": "2400"}
    result = evaluate([tok_col_of("Close", "RELIANCE_I")], row_b, [row_a, row_b],
                      symbol_col="Symbol")
    assert result == 2900.0


def test_col_of_with_custom_symbol_col_still_none_under_default_symbol_col():
    # Sanity check the other direction: without passing symbol_col="Symbol",
    # rows keyed by "Symbol" (not "Scrip Name") genuinely don't resolve —
    # confirms the fix is symbol_col-driven, not accidentally always-on.
    row_a = {"Symbol": "RELIANCE_I", "Close": "2900"}
    row_b = {"Symbol": "ADANIENT_I", "Close": "2400"}
    result = evaluate([tok_col_of("Close", "RELIANCE_I")], row_b, [row_a, row_b])
    assert result is None


def test_compile_check_resolves_col_of_with_custom_symbol_col():
    from services.strategy_engine import compile_check
    row_a = {"Symbol": "RELIANCE_I", "Close": "2900"}
    row_b = {"Symbol": "ADANIENT_I", "Close": "2400"}
    ok, msg = compile_check([tok_col_of("Close", "RELIANCE_I")], row_b, [row_a, row_b],
                            symbol_col="Symbol")
    assert ok is True
    assert msg == "2900.0"


def test_apply_strategies_col_of_still_works_with_default_symbol_col():
    # LMV's own default behavior (symbol_col omitted, "Scrip Name") must be
    # completely unaffected by threading symbol_col through evaluate_
    # compiled/_tokens_to_expr/compile_check.
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True, "row_filter": [],
        "columns": [{"name": "VsNifty", "formula": [tok_col_of("LTP", "NIFTY")]}],
    }
    headers = ["Scrip Name", "LTP"]
    data = [["NIFTY", "100"], ["INFY", "50"]]
    new_headers, new_data = apply_strategies([strat], headers, data)
    assert new_data[1][2] == 100.0


# ── _DAYS historic aggregates ────────────────────────────────────────────────
# Unlike _ALL, these can't be resolved from row_data/all_data alone — they
# need a caller-supplied day_history (services.formula_stats_engine.
# compute_day_history's shape). See the module docstring's "Historic (N
# days) aggregates" section.

def days_tok(fn, col, days):
    return [{"type": "func", "value": f"{fn}(", "col_arg": col, "days_arg": days}]


ROW_WITH_SYMBOL = {"Scrip Name": "INFY", "High": "100"}


def test_avg_days_resolves_from_day_history():
    day_history = {("High", 20): {"INFY": {"Average": 105.0}}}
    result = evaluate(days_tok("AVG_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                      day_history=day_history)
    assert result == 105.0


def test_days_agg_none_without_day_history():
    result = evaluate(days_tok("AVG_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL])
    assert result is None


def test_days_agg_none_when_symbol_missing_from_day_history():
    day_history = {("High", 20): {"TCS": {"Average": 105.0}}}   # no INFY entry
    result = evaluate(days_tok("AVG_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                      day_history=day_history)
    assert result is None


def test_days_agg_distinguishes_by_both_column_and_days():
    day_history = {
        ("High", 20): {"INFY": {"Average": 105.0}},
        ("High", 5):  {"INFY": {"Average": 99.0}},
    }
    assert evaluate(days_tok("AVG_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 105.0
    assert evaluate(days_tok("AVG_DAYS", "High", 5), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 99.0


def test_min_max_sum_count_days_pick_the_right_aggregate_key():
    day_history = {("High", 20): {"INFY": {
        "Min": 90.0, "Max": 120.0, "Sum": 2100.0, "Count": 20,
    }}}
    assert evaluate(days_tok("MIN_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 90.0
    assert evaluate(days_tok("MAX_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 120.0
    assert evaluate(days_tok("SUM_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 2100.0
    assert evaluate(days_tok("COUNT_DAYS", "High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 20


def test_days_agg_combines_with_other_operators():
    day_history = {("High", 20): {"INFY": {"Average": 100.0}}}
    tokens = days_tok("AVG_DAYS", "High", 20) + [tok_op("*"), tok_num(1.05)]
    result = evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history)
    assert result == 105.0


def test_apply_strategies_forwards_day_history_to_columns():
    from services.strategy_engine import apply_strategies
    strat = {
        "id": "1", "active": True, "row_filter": [],
        "columns": [{"name": "AvgHigh20", "formula": days_tok("AVG_DAYS", "High", 20)}],
    }
    headers = ["Scrip Name", "High"]
    data = [["INFY", "100"]]
    day_history = {("High", 20): {"INFY": {"Average": 111.0}}}
    _, new_data = apply_strategies([strat], headers, data, day_history)
    assert new_data[0][2] == 111.0


# ── compile_check with a _DAYS function (no historic fetch at edit time) ────

def test_compile_check_days_func_uses_placeholder_not_hard_failure():
    """No day_history exists at edit time — evaluate() would legitimately
    return None, but compile_check must not treat that as "formula produced
    no result" (which would permanently block Save)."""
    from services.strategy_engine import compile_check
    tokens = days_tok("AVG_DAYS", "High", 20)
    ok, msg = compile_check(tokens, {"High": "100"}, [{"High": "100"}])
    assert ok is True
    assert "historic" in msg.lower()


def test_compile_check_days_func_mixed_with_arithmetic_still_compiles():
    from services.strategy_engine import compile_check
    tokens = days_tok("AVG_DAYS", "High", 20) + [tok_op("+"), tok_num(1)]
    ok, msg = compile_check(tokens, {"High": "100"}, [{"High": "100"}])
    assert ok is True


def test_compile_check_days_func_unknown_column_still_reported():
    from services.strategy_engine import compile_check
    tokens = days_tok("AVG_DAYS", "TotallyMadeUp", 20)
    ok, msg = compile_check(tokens, {"High": "100"}, [{"High": "100"}])
    assert ok is False
    assert "TotallyMadeUp" in msg


# ── compile_check with VALUE_BEFORE_CHANGE (Inception-only, no day_history
# fetch at edit time either — same placeholder treatment as the _DAYS
# functions above). Regression test: _tokens_to_expr's structural
# pre-check didn't know this function name, so it fell into the generic
# "func" branch and emitted an unclosed "value_before_change(" with no
# arguments -> Python SyntaxError -> a false "isn't structured correctly"
# on a perfectly valid formula.

def test_compile_check_value_before_change_uses_placeholder_not_syntax_error():
    from services.strategy_engine import compile_check
    tokens = days_tok("VALUE_BEFORE_CHANGE", "MT", 3)
    ok, msg = compile_check(tokens, {"MT": "100"}, [{"MT": "100"}])
    assert ok is True
    assert "structured correctly" not in msg.lower()


def test_compile_check_value_before_change_no_arg_form_also_compiles():
    """The "auto" no-months_back form (a bare column arg, no days_arg at
    all) must hit the same placeholder path as the explicit-months form."""
    from services.strategy_engine import compile_check
    tokens = [{"type": "func", "value": "VALUE_BEFORE_CHANGE(", "col_arg": "WT"}]
    ok, msg = compile_check(tokens, {"WT": "100"}, [{"WT": "100"}])
    assert ok is True
    assert "structured correctly" not in msg.lower()


def test_compile_check_value_before_change_n_compiles():
    """VALUE_BEFORE_CHANGE_N — a separate function from VALUE_BEFORE_
    CHANGE (n = which occurrence, not months_back) — needs the same
    placeholder treatment in the structural pre-check."""
    from services.strategy_engine import compile_check
    tokens = days_tok("VALUE_BEFORE_CHANGE_N", "WT", 2)
    ok, msg = compile_check(tokens, {"WT": "100"}, [{"WT": "100"}])
    assert ok is True
    assert "structured correctly" not in msg.lower()


# ── compile_check's lmv_headers param (historic/derived column reference) ────
# Reproduces: [Last5Day]*1 where [Last5Day] is a Formula Builder field whose
# own formula is MAX_OF([DAY TO], LAST_5_TRADING_DAYS) — a plain "col"
# reference to a field this editor never independently resolves, not a
# _DAYS function typed directly (that case is already covered above).

def test_compile_check_historic_field_reference_uses_placeholder_when_lmv_headers_given():
    from services.strategy_engine import compile_check
    tokens = [tok_col("Last5Day"), tok_op("*"), tok_num(1)]
    # "Last5Day" is present as a key (Fields-list backfill) but None — its
    # own MAX_OF(...) formula was never evaluated here.
    row_data = {"Scrip Name": "INFY", "Last5Day": None}
    ok, msg = compile_check(tokens, row_data, [row_data],
                            lmv_headers=["Scrip Name"])
    assert ok is True
    assert "historic" in msg.lower()


def test_compile_check_lmv_headers_none_keeps_old_strict_behaviour():
    # Callers that don't pass lmv_headers (the default) get the pre-existing
    # strict behaviour — every referenced column tested for real, no
    # placeholder substitution.
    from services.strategy_engine import compile_check
    tokens = [tok_col("Last5Day"), tok_op("*"), tok_num(1)]
    row_data = {"Scrip Name": "INFY", "Last5Day": None}
    ok, msg = compile_check(tokens, row_data, [row_data])
    assert ok is False


def test_compile_check_genuinely_loaded_column_still_strict_when_blank():
    # A real LMV column (in lmv_headers) that's genuinely blank for this
    # row must still fail — only fields OUTSIDE lmv_headers get the
    # placeholder treatment. Not every blank cell is a historic-data gap.
    from services.strategy_engine import compile_check
    tokens = [tok_col("OR.High"), tok_op("*"), tok_num(1)]
    row_data = {"Scrip Name": "INFY", "OR.High": None}
    ok, msg = compile_check(tokens, row_data, [row_data],
                            lmv_headers=["Scrip Name", "OR.High"])
    assert ok is False
    assert "empty cell" in msg.lower()


def test_compile_check_historic_field_uses_real_value_when_available():
    # A referenced historic/derived field that DOES already have a real
    # value (e.g. Strategy Builder's own proactive day_history fetch
    # resolved it) is used as-is — the placeholder only stands in for a
    # still-blank one.
    from services.strategy_engine import compile_check
    tokens = [tok_col("Last5Day"), tok_op("*"), tok_num(2)]
    row_data = {"Scrip Name": "INFY", "Last5Day": 10.0}
    ok, msg = compile_check(tokens, row_data, [row_data],
                            lmv_headers=["Scrip Name"])
    assert ok is True
    assert msg == "20.0"


# ── collect_day_requests / scan_day_funcs ────────────────────────────────────

def test_scan_day_funcs_finds_column_and_days():
    from services.strategy_engine import scan_day_funcs
    tokens = days_tok("AVG_DAYS", "High", 20)
    assert scan_day_funcs(tokens) == [("High", 20)]


def test_scan_day_funcs_empty_for_ordinary_formula():
    from services.strategy_engine import scan_day_funcs
    assert scan_day_funcs([tok_col("High")]) == []


def test_collect_day_requests_resolves_own_strategy_column_formula():
    """AVG_DAYS([MyCol], 20) where MyCol is this SAME strategy's own column
    must resolve to MyCol's actual formula, not a bare [MyCol] reference —
    this is how "any custom formula over N days" works."""
    from services.strategy_engine import collect_day_requests
    inner_formula = [tok_col("High"), tok_op("-"), tok_col("Low")]
    strategy = {
        "id": "s1", "active": True,
        "columns": [
            {"name": "MyCol", "formula": inner_formula, "fmt_rules": []},
            {"name": "AvgMyCol", "formula": days_tok("AVG_DAYS", "MyCol", 20), "fmt_rules": []},
        ],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    assert requests == [("MyCol", 20, inner_formula)]


def test_collect_day_requests_resolves_nested_sibling_column_chain():
    """AVG_DAYS([TriggerPrice], 20) where TriggerPrice = [Floor_10D] * 1.01
    and Floor_10D is itself ANOTHER of this strategy's own columns (not a
    raw sheet column) — the single-level substitution used to stop at
    TriggerPrice's own formula, leaving the nested [Floor_10D] reference
    unresolved (None on every historic day, same failure mode the
    row-filter streak bug had). Must resolve the full chain."""
    from services.strategy_engine import collect_day_requests
    strategy = {
        "id": "s1", "active": True,
        "columns": [
            {"name": "Floor_10D", "formula": [tok_col("Low")], "fmt_rules": []},
            {"name": "TriggerPrice", "formula": [tok_col("Floor_10D"), tok_op("*"), tok_num(1.01)], "fmt_rules": []},
            {"name": "AvgTrigger", "formula": days_tok("AVG_DAYS", "TriggerPrice", 20), "fmt_rules": []},
        ],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    assert requests == [("TriggerPrice", 20, [tok_paren("("), tok_col("Low"), tok_paren(")"), tok_op("*"), tok_num(1.01)])]
    # And it actually evaluates correctly, not just token-shape-correct.
    formula = requests[0][2]
    assert evaluate(formula, {"Low": 100.0}, [{"Low": 100.0}]) == 101.0


def test_collect_day_requests_falls_back_to_raw_column():
    from services.strategy_engine import collect_day_requests
    strategy = {
        "id": "s1", "active": True,
        "columns": [{"name": "AvgHigh", "formula": days_tok("AVG_DAYS", "High", 20), "fmt_rules": []}],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    assert requests == [("High", 20, [tok_col("High")])]


def test_collect_day_requests_skips_inactive_strategies():
    from services.strategy_engine import collect_day_requests
    strategy = {
        "id": "s1", "active": False,
        "columns": [{"name": "AvgHigh", "formula": days_tok("AVG_DAYS", "High", 20), "fmt_rules": []}],
        "row_filter": [],
    }
    assert collect_day_requests([strategy]) == []


def test_collect_day_requests_deduplicates_across_sources():
    from services.strategy_engine import collect_day_requests
    days_formula = days_tok("AVG_DAYS", "High", 20)
    strategy = {
        "id": "s1", "active": True,
        "columns": [{"name": "AvgHigh", "formula": days_formula, "fmt_rules": [
            {"condition": days_tok("AVG_DAYS", "High", 20) + [tok_op(">"), tok_num(0)], "color": "#fff"},
        ]}],
        "row_filter": days_tok("AVG_DAYS", "High", 20) + [tok_op(">"), tok_num(0)],
    }
    requests = collect_day_requests([strategy])
    # Plus one synthetic streak request (see "Row-filter streak" tests
    # below) since this strategy also has a row filter.
    from services.strategy_engine import _streak_col_name, STREAK_LOOKBACK_DAYS
    assert requests == [
        ("High", 20, [tok_col("High")]),
        (_streak_col_name("s1"), STREAK_LOOKBACK_DAYS, strategy["row_filter"]),
    ]


def test_collect_day_requests_scans_notification_config():
    from services.strategy_engine import collect_day_requests
    strategy = {"id": "s1", "active": True, "columns": [], "row_filter": []}
    notif_configs = {
        "s1": {
            "trigger_condition": days_tok("AVG_DAYS", "High", 20) + [tok_op(">"), tok_num(0)],
            "risk_reward": {"numerator": days_tok("MIN_DAYS", "Low", 10), "denominator": []},
            "metrics": [{"formula": days_tok("MAX_DAYS", "Close", 15)}],
        }
    }
    requests = collect_day_requests([strategy], notif_configs)
    assert set((c, d) for c, d, _ in requests) == {("High", 20), ("Low", 10), ("Close", 15)}


# ── VALUE_DAYS_AGO / VALUE_ON_DATE point lookups ─────────────────────────────
# Both reuse the exact same day_history cache/plumbing as the _DAYS family
# above — VALUE_DAYS_AGO's window is an int (N+1, oldest day fetched is
# exactly N days back), VALUE_ON_DATE's is a (date, date) tuple — resolved
# via the "First" key (see services.formula_stats_engine.compute_stats)
# rather than an aggregate key like "Average".

def days_ago_tok(col, n):
    return [{"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": col, "days_arg": n}]


def on_date_tok(col, when):
    return [{"type": "func", "value": "VALUE_ON_DATE(", "col_arg": col, "date_arg": when}]


def test_value_days_ago_resolves_via_first_key_with_n_plus_1_window():
    day_history = {("High", 3): {"INFY": {"First": 97.0}}}   # window = 2+1
    result = evaluate(days_ago_tok("High", 2), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                      day_history=day_history)
    assert result == 97.0


def test_value_days_ago_zero_means_today():
    day_history = {("High", 1): {"INFY": {"First": 105.0}}}   # window = 0+1
    result = evaluate(days_ago_tok("High", 0), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                      day_history=day_history)
    assert result == 105.0


def test_value_on_date_resolves_via_first_key_with_single_date_window():
    window = ("2026-07-15", "2026-07-15")
    day_history = {("High", window): {"INFY": {"First": 101.5}}}
    result = evaluate(on_date_tok("High", "2026-07-15"), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                      day_history=day_history)
    assert result == 101.5


def test_point_lookup_none_without_day_history():
    assert evaluate(days_ago_tok("High", 2), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL]) is None
    assert evaluate(on_date_tok("High", "2026-07-15"), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL]) is None


def test_value_days_ago_and_days_aggregate_can_share_the_same_fetched_window():
    """VALUE_DAYS_AGO(col, N) and AVG_DAYS(col, N+1) intentionally use the
    SAME window (N+1, an int) — they can share one cache entry/fetch, just
    resolved via different keys ("First" vs "Average")."""
    day_history = {("High", 21): {"INFY": {"First": 90.0, "Average": 100.0}}}
    assert evaluate(days_ago_tok("High", 20), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 90.0
    assert evaluate(days_tok("AVG_DAYS", "High", 21), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 100.0


def test_value_on_date_distinguishes_by_exact_date():
    day_history = {
        ("High", ("2026-07-15", "2026-07-15")): {"INFY": {"First": 101.0}},
        ("High", ("2026-07-16", "2026-07-16")): {"INFY": {"First": 102.0}},
    }
    assert evaluate(on_date_tok("High", "2026-07-15"), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 101.0
    assert evaluate(on_date_tok("High", "2026-07-16"), ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL],
                    day_history=day_history) == 102.0


def test_compile_check_point_lookup_funcs_use_placeholder_not_hard_failure():
    from services.strategy_engine import compile_check
    ok, msg = compile_check(days_ago_tok("High", 2), {"High": "100"}, [{"High": "100"}])
    assert ok is True
    assert "historic" in msg.lower()
    ok, msg = compile_check(on_date_tok("High", "2026-07-15"), {"High": "100"}, [{"High": "100"}])
    assert ok is True
    assert "historic" in msg.lower()


def test_scan_day_funcs_finds_value_days_ago_with_n_plus_1_window():
    from services.strategy_engine import scan_day_funcs
    assert scan_day_funcs(days_ago_tok("High", 2)) == [("High", 3)]


def test_scan_day_funcs_finds_value_on_date_with_single_date_window():
    from services.strategy_engine import scan_day_funcs
    assert scan_day_funcs(on_date_tok("High", "2026-07-15")) == [
        ("High", ("2026-07-15", "2026-07-15"))
    ]


def test_collect_day_requests_resolves_point_lookups_and_days_agg_together():
    from services.strategy_engine import collect_day_requests
    strategy = {
        "id": "s1", "active": True,
        "columns": [
            {"name": "AvgHigh20", "formula": days_tok("AVG_DAYS", "High", 20), "fmt_rules": []},
            {"name": "High2DaysAgo", "formula": days_ago_tok("High", 2), "fmt_rules": []},
            {"name": "HighOnDate", "formula": on_date_tok("High", "2026-07-15"), "fmt_rules": []},
        ],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    windows = {window for _, window, _ in requests}
    assert windows == {20, 3, ("2026-07-15", "2026-07-15")}


# ── VALUE_AT_MAX_DAYS / VALUE_AT_MIN_DAYS (value-at-window-extreme) ─────────
# Two columns, not one: col_arg is what gets returned, driver_col_arg is what
# decides which of the last N historic days wins. Both need their own
# day_history entry over the SAME window — resolved via each entry's "daily"
# list (services.formula_stats_engine.compute_stats), not a pre-reduced
# agg_key like the _DAYS family above.

def extreme_tok(fn, col, driver_col, days):
    return [{"type": "func", "value": f"{fn}(", "col_arg": col,
             "driver_col_arg": driver_col, "days_arg": days}]


def test_value_at_max_days_returns_value_col_on_drivers_peak_day():
    day_history = {
        ("CWTO", 5): {"INFY": {"daily": [
            ("2026-06-08", 0.005), ("2026-06-09", 0.001),
            ("2026-06-10", 0.015), ("2026-06-11", 0.001), ("2026-06-12", 0.00125),
        ]}},
        ("High", 5): {"INFY": {"daily": [
            ("2026-06-08", 1001), ("2026-06-09", 1002),
            ("2026-06-10", 1003), ("2026-06-11", 1004), ("2026-06-12", 1005),
        ]}},
    }
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    result = evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history)
    assert result == 1003  # CWTO peaked on 2026-06-10 -> that day's High


def test_value_at_min_days_returns_value_col_on_drivers_trough_day():
    day_history = {
        ("CWTO", 5): {"INFY": {"daily": [
            ("2026-06-08", 0.005), ("2026-06-09", 0.001),
            ("2026-06-10", 0.015), ("2026-06-11", 0.001), ("2026-06-12", 0.00125),
        ]}},
        ("Low", 5): {"INFY": {"daily": [
            ("2026-06-08", 501), ("2026-06-09", 502),
            ("2026-06-10", 503), ("2026-06-11", 504), ("2026-06-12", 505),
        ]}},
    }
    tokens = extreme_tok("VALUE_AT_MIN_DAYS", "Low", "CWTO", 5)
    result = evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history)
    # CWTO troughs on 2026-06-09 (first of the two 0.001 ties) -> that day's Low
    assert result == 502


def test_value_at_extreme_none_without_day_history():
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    assert evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL]) is None


def test_value_at_extreme_none_when_driver_entry_missing():
    day_history = {("High", 5): {"INFY": {"daily": [("2026-06-08", 1001)]}}}
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    assert evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history) is None


def test_value_at_extreme_none_when_value_entry_missing():
    day_history = {("CWTO", 5): {"INFY": {"daily": [("2026-06-08", 0.005)]}}}
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    assert evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history) is None


def test_value_at_extreme_none_when_value_col_missing_on_winning_date():
    day_history = {
        ("CWTO", 5): {"INFY": {"daily": [("2026-06-08", 0.005), ("2026-06-09", 0.02)]}},
        ("High", 5): {"INFY": {"daily": [("2026-06-08", 1001)]}},  # no 06-09 entry
    }
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    assert evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history) is None


def test_value_at_extreme_ignores_non_numeric_driver_days():
    day_history = {
        ("CWTO", 5): {"INFY": {"daily": [("2026-06-08", None), ("2026-06-09", 0.02)]}},
        ("High", 5): {"INFY": {"daily": [("2026-06-08", 1001), ("2026-06-09", 1002)]}},
    }
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    result = evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history)
    assert result == 1002


def test_value_at_extreme_can_use_driver_as_own_strategys_computed_column():
    """Both columns can be raw sheet columns or another of THIS strategy's
    own computed columns — same resolution collect_day_requests gives the
    plain _DAYS family."""
    from services.strategy_engine import collect_day_requests
    inner_formula = [tok_col("High"), tok_op("-"), tok_col("Low")]
    strategy = {
        "id": "s1", "active": True,
        "columns": [
            {"name": "Spread", "formula": inner_formula, "fmt_rules": []},
            {"name": "HighAtMaxSpread",
             "formula": extreme_tok("VALUE_AT_MAX_DAYS", "High", "Spread", 5),
             "fmt_rules": []},
        ],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    resolved = {(col, days): formula for col, days, formula in requests}
    assert resolved[("Spread", 5)] == inner_formula
    assert resolved[("High", 5)] == [tok_col("High")]


def test_compile_check_value_at_extreme_uses_placeholder_not_hard_failure():
    from services.strategy_engine import compile_check
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    row_data = {"High": "100", "CWTO": "0.01"}
    ok, msg = compile_check(tokens, row_data, [row_data])
    assert ok is True
    assert "historic" in msg.lower()


def test_compile_check_value_at_extreme_unknown_driver_column_reported():
    from services.strategy_engine import compile_check
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "TotallyMadeUp", 5)
    row_data = {"High": "100"}
    ok, msg = compile_check(tokens, row_data, [row_data])
    assert ok is False
    assert "TotallyMadeUp" in msg


def test_scan_day_funcs_finds_both_columns_for_value_at_extreme():
    from services.strategy_engine import scan_day_funcs
    tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    assert scan_day_funcs(tokens) == [("High", 5), ("CWTO", 5)]
    tokens = extreme_tok("VALUE_AT_MIN_DAYS", "Low", "CWTO", 5)
    assert scan_day_funcs(tokens) == [("Low", 5), ("CWTO", 5)]


def test_collect_day_requests_resolves_both_value_at_extreme_columns():
    from services.strategy_engine import collect_day_requests
    strategy = {
        "id": "s1", "active": True,
        "columns": [
            {"name": "HighAtMaxCWTO",
             "formula": extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5),
             "fmt_rules": []},
        ],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    assert {(c, d) for c, d, _ in requests} == {("High", 5), ("CWTO", 5)}


# ── VALUE_AT_MAX_DATES / VALUE_AT_MIN_DATES (explicit calendar range) ──────
# Same resolution as VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS above, but window =
# an explicit (date_from, date_to) tuple instead of an int — for a range
# that doesn't cleanly line up to a trading-day count from today, e.g. a
# specific calendar week. day_history/_value_at_extreme already treat
# "window" as an opaque dict key either way, so this needed no new
# resolution machinery, just the compilation path (_build_compiled/
# scan_day_funcs) recognizing the new function names.

def extreme_date_tok(fn, col, driver_col, date_from, date_to):
    return [{"type": "func", "value": f"{fn}(", "col_arg": col,
             "driver_col_arg": driver_col, "date_from_arg": date_from, "date_to_arg": date_to}]


def test_value_at_max_dates_returns_value_col_on_drivers_peak_day():
    window = ("2026-06-08", "2026-06-12")
    day_history = {
        ("CWTO", window): {"INFY": {"daily": [
            ("2026-06-08", 0.005), ("2026-06-09", 0.001),
            ("2026-06-10", 0.015), ("2026-06-11", 0.001), ("2026-06-12", 0.00125),
        ]}},
        ("High", window): {"INFY": {"daily": [
            ("2026-06-08", 1001), ("2026-06-09", 1002),
            ("2026-06-10", 1003), ("2026-06-11", 1004), ("2026-06-12", 1005),
        ]}},
    }
    tokens = extreme_date_tok("VALUE_AT_MAX_DATES", "High", "CWTO", *window)
    result = evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history)
    assert result == 1003  # CWTO peaked on 2026-06-10 -> that day's High


def test_value_at_min_dates_returns_value_col_on_drivers_trough_day():
    window = ("2026-06-08", "2026-06-12")
    day_history = {
        ("CWTO", window): {"INFY": {"daily": [
            ("2026-06-08", 0.005), ("2026-06-09", 0.001),
            ("2026-06-10", 0.015), ("2026-06-11", 0.001), ("2026-06-12", 0.00125),
        ]}},
        ("Low", window): {"INFY": {"daily": [
            ("2026-06-08", 501), ("2026-06-09", 502),
            ("2026-06-10", 503), ("2026-06-11", 504), ("2026-06-12", 505),
        ]}},
    }
    tokens = extreme_date_tok("VALUE_AT_MIN_DATES", "Low", "CWTO", *window)
    result = evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history)
    assert result == 502   # CWTO troughs on 2026-06-09 (first of the ties) -> that day's Low


def test_value_at_extreme_dates_none_without_day_history():
    tokens = extreme_date_tok("VALUE_AT_MAX_DATES", "High", "CWTO", "2026-06-08", "2026-06-12")
    assert evaluate(tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL]) is None


def test_value_at_extreme_dates_and_days_windows_are_distinct_cache_entries():
    """A DAYS call and a DATES call referencing the same columns must not
    collide in day_history — different window shapes (int vs tuple) are
    different dict keys already, but the compiled-formula cache
    (_formula_signature) must also tell them apart."""
    day_history_days = {
        ("High", 5): {"INFY": {"daily": [("2026-06-12", 999)]}},
        ("CWTO", 5): {"INFY": {"daily": [("2026-06-12", 0.01)]}},
    }
    day_history_dates = {
        ("High", ("2026-06-08", "2026-06-12")): {"INFY": {"daily": [("2026-06-12", 1005)]}},
        ("CWTO", ("2026-06-08", "2026-06-12")): {"INFY": {"daily": [("2026-06-12", 0.02)]}},
    }
    days_tokens = extreme_tok("VALUE_AT_MAX_DAYS", "High", "CWTO", 5)
    dates_tokens = extreme_date_tok("VALUE_AT_MAX_DATES", "High", "CWTO", "2026-06-08", "2026-06-12")
    assert evaluate(days_tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history_days) == 999
    assert evaluate(dates_tokens, ROW_WITH_SYMBOL, [ROW_WITH_SYMBOL], day_history=day_history_dates) == 1005


def test_compile_check_value_at_extreme_dates_uses_placeholder_not_hard_failure():
    from services.strategy_engine import compile_check
    tokens = extreme_date_tok("VALUE_AT_MAX_DATES", "High", "CWTO", "2026-06-08", "2026-06-12")
    row_data = {"High": "100", "CWTO": "0.01"}
    ok, msg = compile_check(tokens, row_data, [row_data])
    assert ok is True
    assert "historic" in msg.lower()


def test_scan_day_funcs_finds_both_columns_for_value_at_extreme_dates():
    from services.strategy_engine import scan_day_funcs
    window = ("2026-06-08", "2026-06-12")
    tokens = extreme_date_tok("VALUE_AT_MAX_DATES", "High", "CWTO", *window)
    assert scan_day_funcs(tokens) == [("High", window), ("CWTO", window)]
    tokens = extreme_date_tok("VALUE_AT_MIN_DATES", "Low", "CWTO", *window)
    assert scan_day_funcs(tokens) == [("Low", window), ("CWTO", window)]


def test_collect_day_requests_resolves_both_value_at_extreme_dates_columns():
    from services.strategy_engine import collect_day_requests
    window = ("2026-06-08", "2026-06-12")
    strategy = {
        "id": "s1", "active": True,
        "columns": [
            {"name": "HighAtMaxCWTO",
             "formula": extreme_date_tok("VALUE_AT_MAX_DATES", "High", "CWTO", *window),
             "fmt_rules": []},
        ],
        "row_filter": [],
    }
    requests = collect_day_requests([strategy])
    assert {(c, d) for c, d, _ in requests} == {("High", window), ("CWTO", window)}


# ── Row-filter streak ("Days True" / "Since") ───────────────────────────────
# apply_strategies() adds two extra columns per active strategy that HAS a
# row filter: "<name> — Days True" and "<name> — Since", reporting how many
# of the most recent consecutive historic days that filter evaluated true
# and the date the current run started — driven by compute_streak over a
# synthetic day_history request collect_day_requests emits automatically.

def test_compute_streak_empty_is_zero():
    from services.strategy_engine import compute_streak
    assert compute_streak([]) == (0, None, False)


def test_compute_streak_most_recent_day_false_is_zero():
    from services.strategy_engine import compute_streak
    assert compute_streak([("d1", True), ("d2", False)]) == (0, None, False)


def test_compute_streak_counts_back_to_the_last_false():
    from services.strategy_engine import compute_streak
    daily = [("d1", False), ("d2", True), ("d3", True), ("d4", True)]
    assert compute_streak(daily) == (3, "d2", False)


def test_compute_streak_treats_none_as_not_true():
    from services.strategy_engine import compute_streak
    daily = [("d1", True), ("d2", None), ("d3", True)]
    assert compute_streak(daily) == (1, "d3", False)


def test_compute_streak_at_window_ceiling_reports_none_since():
    """Whole fetched window was true — days_true is a LOWER BOUND (display
    as "≥N"), since_date is unknown (None) since the real start is
    somewhere before what was fetched."""
    from services.strategy_engine import compute_streak
    daily = [("d1", True), ("d2", True), ("d3", True)]
    days_true, since, at_ceiling = compute_streak(daily)
    assert days_true == 3
    assert since is None
    assert at_ceiling is True


def tok_paren(v):  return {"type": "paren", "value": v}


def test_expand_col_refs_substitutes_own_column_wrapped_in_parens():
    from services.strategy_engine import _expand_col_refs
    cols_by_name = {"MyCol": [tok_col("High"), tok_op("-"), tok_col("Low")]}
    result = _expand_col_refs([tok_col("MyCol")], cols_by_name)
    assert result == [tok_paren("("), tok_col("High"), tok_op("-"), tok_col("Low"), tok_paren(")")]


def test_expand_col_refs_recurses_through_chained_columns():
    from services.strategy_engine import _expand_col_refs
    cols_by_name = {
        "A": [tok_col("B"), tok_op("+"), tok_num(1)],
        "B": [tok_col("High")],
    }
    # B (inside A's formula) is itself expanded and gets its own paren pair.
    assert _expand_col_refs([tok_col("A")], cols_by_name) == [
        tok_paren("("), tok_paren("("), tok_col("High"), tok_paren(")"), tok_op("+"), tok_num(1), tok_paren(")"),
    ]


def test_expand_col_refs_leaves_raw_columns_and_of_refs_alone():
    from services.strategy_engine import _expand_col_refs
    tokens = [tok_col("High"), tok_col_of("Open", "NIFTY")]
    # Neither "High" (not one of this strategy's own columns) nor the "of"
    # reference is touched.
    assert _expand_col_refs(tokens, {"MyCol": [tok_col("Low")]}) == tokens
    # "of" always names a raw sheet column on another row, never one of
    # this strategy's own columns, even if the names happen to collide.
    assert _expand_col_refs(tokens, {"Open": [tok_col("Low")]}) == tokens


def test_expand_col_refs_guards_against_self_reference_cycle():
    from services.strategy_engine import _expand_col_refs
    # A column whose own formula (accidentally) references itself must not
    # recurse forever.
    cols_by_name = {"A": [tok_col("A"), tok_op("+"), tok_num(1)]}
    assert _expand_col_refs([tok_col("A")], cols_by_name) == [
        tok_paren("("), tok_col("A"), tok_op("+"), tok_num(1), tok_paren(")"),
    ]


def test_expand_col_refs_parens_prevent_chained_comparison_misread():
    """The exact bug reported live: row_filter `[MTLTPBuy] == True` where
    MTLTPBuy's own formula is `[Current] > [MT]`. Naively inlining the
    substitution unparenthesized would produce the token sequence for
    `Current > MT == True` — Python reads consecutive comparison operators
    as a CHAINED comparison (`a > b == c` means `(a > b) and (b == c)`),
    not `(a > b) == c`, so it'd compare MT itself to True (almost always
    False, MT is a price) instead of the intended boolean. Parens make it
    `(Current > MT) == True`, which is what the user's formula means."""
    from services.strategy_engine import _expand_col_refs
    cols_by_name = {"MTLTPBuy": [tok_col("Current"), tok_op(">"), tok_col("MT")]}
    row_filter = [tok_col("MTLTPBuy"), tok_op("=="), tok_num("True")]
    expanded = _expand_col_refs(row_filter, cols_by_name)
    row_data = {"Current": 105.0, "MT": 100.0}   # Current > MT is True
    assert evaluate(expanded, row_data, [row_data]) is True
    row_data_false = {"Current": 95.0, "MT": 100.0}   # Current > MT is False
    assert evaluate(expanded, row_data_false, [row_data_false]) is False


def _streak_strategy(strategy_id="s1", name="Breakout"):
    return {
        "id": strategy_id, "name": name, "active": True,
        "row_filter": [tok_col("CLOSE"), tok_op(">"), tok_col("OPEN")],
        "columns": [],
    }


def test_collect_day_requests_emits_synthetic_streak_request():
    from services.strategy_engine import collect_day_requests, _streak_col_name, STREAK_LOOKBACK_DAYS
    strategy = _streak_strategy()
    reqs = collect_day_requests([strategy])
    assert reqs == [(_streak_col_name("s1"), STREAK_LOOKBACK_DAYS, strategy["row_filter"])]


def test_collect_day_requests_no_streak_request_without_row_filter():
    from services.strategy_engine import collect_day_requests
    strategy = {"id": "s1", "name": "NoFilter", "active": True, "row_filter": [], "columns": []}
    assert collect_day_requests([strategy]) == []


def test_expand_columns_for_stats_resolves_sibling_reference():
    from services.strategy_engine import expand_columns_for_stats
    columns = [
        {"name": "Floor_10D", "formula": [tok_col("Low")], "fmt_rules": []},
        {"name": "Trigger Price", "formula": [tok_col("Floor_10D"), tok_op("*"), tok_num(1.01)], "fmt_rules": []},
    ]
    expanded = expand_columns_for_stats(columns)
    assert expanded[0]["formula"] == columns[0]["formula"]   # no sibling ref — untouched
    assert expanded[1]["formula"] == [tok_paren("("), tok_col("Low"), tok_paren(")"), tok_op("*"), tok_num(1.01)]
    # original list/dicts untouched (compute_stats gets a copy, not a mutation)
    assert columns[1]["formula"] == [tok_col("Floor_10D"), tok_op("*"), tok_num(1.01)]
    assert evaluate(expanded[1]["formula"], {"Low": 100.0}, [{"Low": 100.0}]) == 101.0


def test_collect_day_requests_streak_expands_row_filter_own_column_ref():
    """Row filter is `[MyBuySignal]` — the strategy's OWN computed column,
    not a raw sheet column (the exact pattern
    test_row_filter_can_reference_strategy_own_column already covers for
    the live apply_strategies path). The synthetic streak request must
    carry MyBuySignal's actual formula, not a bare [MyBuySignal] token —
    otherwise the historic fetch resolves it to None every day (raw
    snapshot data has no notion of a strategy's own computed columns) and
    compute_streak always reports 0, regardless of the real streak."""
    from services.strategy_engine import collect_day_requests, _streak_col_name, STREAK_LOOKBACK_DAYS
    inner_formula = [tok_col("Current"), tok_op(">"), tok_col("MT")]
    strategy = {
        "id": "s1", "active": True,
        "columns": [{"name": "MyBuySignal", "formula": inner_formula, "fmt_rules": []}],
        "row_filter": [tok_col("MyBuySignal")],
    }
    requests = collect_day_requests([strategy])
    assert requests == [(_streak_col_name("s1"), STREAK_LOOKBACK_DAYS, [
        tok_paren("("), tok_col("Current"), tok_op(">"), tok_col("MT"), tok_paren(")"),
    ])]


def test_collect_day_requests_streak_expands_row_filter_with_comparison_suffix():
    """The exact reported bug: row_filter is `[MTLTPBuy] == True`, not a
    bare column reference — MTLTPBuy itself must still expand, and the
    result must stay correct once compiled/evaluated (see
    test_expand_col_refs_parens_prevent_chained_comparison_misread for the
    unparenthesized failure mode this guards against)."""
    from services.strategy_engine import collect_day_requests, _streak_col_name, STREAK_LOOKBACK_DAYS
    inner_formula = [tok_col("Current"), tok_op(">"), tok_col("MT")]
    strategy = {
        "id": "s1", "active": True,
        "columns": [{"name": "MTLTPBuy", "formula": inner_formula, "fmt_rules": []}],
        "row_filter": [tok_col("MTLTPBuy"), tok_op("=="), tok_num("True")],
    }
    requests = collect_day_requests([strategy])
    expanded_formula = requests[0][2]
    row_data = {"Current": 105.0, "MT": 100.0}
    assert evaluate(expanded_formula, row_data, [row_data]) is True
    row_data_false = {"Current": 95.0, "MT": 100.0}
    assert evaluate(expanded_formula, row_data_false, [row_data_false]) is False


def test_apply_strategies_adds_days_true_and_since_columns_for_row_filter_strategy():
    from services.strategy_engine import apply_strategies, _streak_col_name, STREAK_LOOKBACK_DAYS
    strategy = _streak_strategy()
    day_history = {
        (_streak_col_name("s1"), STREAK_LOOKBACK_DAYS): {
            "NIFTY": {"daily": [
                ("2026-08-01", 1), ("2026-08-02", 1), ("2026-08-03", 0),
                ("2026-08-04", 1), ("2026-08-05", 1),
            ]},
        },
    }
    headers = ["Scrip Name", "OPEN", "CLOSE"]
    data = [["NIFTY", 100.0, 105.0]]   # CLOSE > OPEN -> passes today
    new_headers, new_data = apply_strategies([strategy], headers, data, day_history=day_history)
    assert new_headers[-2:] == ["Breakout — Days True", "Breakout — Since"]
    # 08-04/08-05 true, 08-03 breaks the streak -> 2 days, since 08-04
    assert new_data[0][-2:] == [2, "2026-08-04"]


def test_apply_strategies_days_true_at_ceiling_shows_gte_string():
    from services.strategy_engine import apply_strategies, _streak_col_name, STREAK_LOOKBACK_DAYS
    strategy = _streak_strategy()
    day_history = {
        (_streak_col_name("s1"), STREAK_LOOKBACK_DAYS): {
            "NIFTY": {"daily": [("d1", 1), ("d2", 1), ("d3", 1)]},
        },
    }
    headers = ["Scrip Name", "OPEN", "CLOSE"]
    data = [["NIFTY", 100.0, 105.0]]
    _, new_data = apply_strategies([strategy], headers, data, day_history=day_history)
    assert new_data[0][-2:] == ["≥3", None]


def test_apply_strategies_no_streak_columns_without_row_filter():
    from services.strategy_engine import apply_strategies
    strategy = {"id": "s2", "name": "NoFilter", "active": True, "row_filter": [], "columns": []}
    headers = ["Scrip Name", "OPEN", "CLOSE"]
    data = [["NIFTY", 100.0, 105.0]]
    new_headers, new_data = apply_strategies([strategy], headers, data)
    assert new_headers == headers
    assert new_data == data


def test_apply_strategies_streak_columns_none_when_row_does_not_pass():
    """Row kept alive by a DIFFERENT (unfiltered) active strategy, but
    doesn't pass this one's filter — Days True/Since blank out, same
    convention this strategy's own computed columns already use."""
    from services.strategy_engine import apply_strategies, _streak_col_name, STREAK_LOOKBACK_DAYS
    strategy = _streak_strategy()
    catch_all = {"id": "s3", "name": "All", "active": True, "row_filter": [], "columns": []}
    day_history = {(_streak_col_name("s1"), STREAK_LOOKBACK_DAYS): {"NIFTY": {"daily": [("d1", 1)]}}}
    headers = ["Scrip Name", "OPEN", "CLOSE"]
    data = [["NIFTY", 110.0, 100.0]]   # CLOSE < OPEN -> fails s1's filter
    new_headers, new_data = apply_strategies([strategy, catch_all], headers, data, day_history=day_history)
    idx = new_headers.index("Breakout — Days True")
    assert new_data[0][idx] is None
    assert new_data[0][idx + 1] is None


def test_apply_strategies_streak_columns_none_without_day_history():
    from services.strategy_engine import apply_strategies
    strategy = _streak_strategy()
    headers = ["Scrip Name", "OPEN", "CLOSE"]
    data = [["NIFTY", 100.0, 105.0]]
    _, new_data = apply_strategies([strategy], headers, data)   # no day_history at all
    assert new_data[0][-2:] == [0, None]


def test_apply_strategies_include_streak_columns_false_suppresses_them():
    """screens.inception_hmv/inception_view_by_date pass this — Inception
    has no day_history support wired up, so these would always read
    "0"/blank there; dead weight, not a useful feature."""
    from services.strategy_engine import apply_strategies
    strategy = _streak_strategy()
    headers = ["Scrip Name", "OPEN", "CLOSE"]
    data = [["NIFTY", 100.0, 105.0]]
    new_headers, new_data = apply_strategies([strategy], headers, data, include_streak_columns=False)
    assert new_headers == headers
    assert new_data == data
