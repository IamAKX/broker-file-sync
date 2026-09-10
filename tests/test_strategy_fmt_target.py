"""Tests for conditional-formatting "target_column" — a fmt rule's color can
paint any LMV column, not just the strategy column that owns the rule."""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def tok_op(v):     return {"type": "op",   "value": v}
def tok_col(name): return {"type": "col",  "value": name}
def tok_self():    return {"type": "self"}
def tok_num(v):    return {"type": "num", "value": str(v)}


def _gt(lhs_tokens, n):
    return lhs_tokens + [tok_op(">"), tok_num(n)]


def test_new_fmt_rule_defaults_target_column_to_none():
    from services import strategy_store as store
    rule = store.new_fmt_rule()
    assert rule["target_column"] is None


def test_get_cell_color_unchanged_when_no_rule_matches():
    from services.strategy_engine import get_cell_color
    col_def = {"fmt_rules": [{"condition": _gt([tok_self()], 100), "color": "#ff0000"}]}
    assert get_cell_color(col_def, 50, {}, [{}]) is None


def test_get_cell_color_matches_own_value_via_this():
    from services.strategy_engine import get_cell_color
    col_def = {"fmt_rules": [{"condition": _gt([tok_self()], 100), "color": "#ff0000"}]}
    assert get_cell_color(col_def, 150, {}, [{}]) == "#ff0000"


def test_get_row_fmt_colors_defaults_to_own_column_when_no_target():
    from services.strategy_engine import get_row_fmt_colors
    col_def = {
        "name": "Signal",
        "fmt_rules": [{"condition": _gt([tok_self()], 100), "color": "#ff0000", "target_column": None}],
    }
    row = ["INFY", 150]   # base col + strategy col value
    row_dict = {"Scrip Name": "INFY", "Signal": 150}
    colors = get_row_fmt_colors([col_def], row, base_col_count=1, row_dict=row_dict, all_dicts=[row_dict])
    assert colors == {"Signal": "#ff0000"}


def test_get_row_fmt_colors_paints_a_different_target_column():
    from services.strategy_engine import get_row_fmt_colors
    col_def = {
        "name": "Signal",
        "fmt_rules": [{
            "condition": _gt([tok_self()], 100), "color": "#ff0000",
            "target_column": "Current",
        }],
    }
    row = ["INFY", 250.5, 150]   # Scrip Name, Current, Signal
    row_dict = {"Scrip Name": "INFY", "Current": 250.5, "Signal": 150}
    colors = get_row_fmt_colors([col_def], row, base_col_count=2, row_dict=row_dict, all_dicts=[row_dict])
    # Painted onto "Current" (the picked target), not "Signal" (the strategy's own column).
    assert colors == {"Current": "#ff0000"}


def test_get_row_fmt_colors_no_match_returns_empty():
    from services.strategy_engine import get_row_fmt_colors
    col_def = {
        "name": "Signal",
        "fmt_rules": [{"condition": _gt([tok_self()], 100), "color": "#ff0000", "target_column": "Current"}],
    }
    row = ["INFY", 250.5, 50]   # Signal (50) fails the >100 condition
    row_dict = {"Scrip Name": "INFY", "Current": 250.5, "Signal": 50}
    colors = get_row_fmt_colors([col_def], row, base_col_count=2, row_dict=row_dict, all_dicts=[row_dict])
    assert colors == {}


def test_get_row_fmt_colors_first_strategy_column_wins_on_target_collision():
    from services.strategy_engine import get_row_fmt_colors
    col_a = {
        "name": "SignalA",
        "fmt_rules": [{"condition": _gt([tok_self()], 0), "color": "#ff0000", "target_column": "Current"}],
    }
    col_b = {
        "name": "SignalB",
        "fmt_rules": [{"condition": _gt([tok_self()], 0), "color": "#00ff00", "target_column": "Current"}],
    }
    row = ["INFY", 250.5, 10, 20]   # Scrip Name, Current, SignalA, SignalB
    row_dict = {"Scrip Name": "INFY", "Current": 250.5, "SignalA": 10, "SignalB": 20}
    colors = get_row_fmt_colors([col_a, col_b], row, base_col_count=2, row_dict=row_dict, all_dicts=[row_dict])
    assert colors == {"Current": "#ff0000"}   # col_a (earlier) wins the collision


def test_get_row_fmt_colors_condition_still_uses_owning_columns_own_value():
    """Picking a different target_column must not change what THIS refers
    to in the condition — it's still the owning strategy column's own
    computed value, never the target column's value."""
    from services.strategy_engine import get_row_fmt_colors
    col_def = {
        "name": "Signal",
        # THIS > 100 checks Signal's own value (10), not Current's (999) —
        # so this must NOT match even though Current is way over 100.
        "fmt_rules": [{"condition": _gt([tok_self()], 100), "color": "#ff0000", "target_column": "Current"}],
    }
    row = ["INFY", 999.0, 10]
    row_dict = {"Scrip Name": "INFY", "Current": 999.0, "Signal": 10}
    colors = get_row_fmt_colors([col_def], row, base_col_count=2, row_dict=row_dict, all_dicts=[row_dict])
    assert colors == {}


# ── issue #41: streak columns from an earlier filtered strategy must not
# offset a later strategy's fmt-rule value lookup ──────────────────────────

def _filter_gt(col, n):
    return [tok_col(col), tok_op(">"), tok_num(n)]


def test_two_filtered_strategies_both_fmt_rules_fire():
    """Full apply_strategies -> get_row_fmt_colors path. VAL Sell (listed
    first, has a row filter -> gets +2 streak columns) then VAH Buy. A row
    where only VAH Buy's filter passes must still get VAH Buy's Scrip-Name
    colour — before the fix its rule was matched against VAL Sell's
    'Days True' streak value and never fired (issue #41)."""
    from services.strategy_engine import apply_strategies, get_row_fmt_colors, build_symbol_index

    val_sell = {
        "id": "vs", "active": True,
        "row_filter": _filter_gt("VALflag", 0),
        "columns": [{
            "name": "VAL Sell",
            "formula": [tok_col("VALflag")],
            "fmt_rules": [{"condition": [tok_self(), tok_op("=="), tok_num(1)],
                           "color": "#ff55ff", "target_column": "Lot Size"}],
        }],
    }
    vah_buy = {
        "id": "vb", "active": True,
        "row_filter": _filter_gt("VAHflag", 0),
        "columns": [{
            "name": "VAH Buy",
            "formula": [tok_col("VAHflag")],
            "fmt_rules": [{"condition": [tok_self(), tok_op("=="), tok_num(1)],
                           "color": "#00007f", "target_column": "Scrip Name"}],
        }],
    }
    headers = ["Scrip Name", "Lot Size", "VAHflag", "VALflag"]
    # row 0: only VAH Buy true;  row 1: only VAL Sell true
    data = [["AAA", "100", "1", "0"], ["BBB", "200", "0", "1"]]

    new_headers, new_data = apply_strategies([val_sell, vah_buy], headers, data)
    base = len(headers)
    strat_col_defs = [c for s in (val_sell, vah_buy) for c in s["columns"]]
    all_dicts = [dict(zip(new_headers, r)) for r in new_data]

    c0 = get_row_fmt_colors(strat_col_defs, new_data[0], base, all_dicts[0], all_dicts)
    c1 = get_row_fmt_colors(strat_col_defs, new_data[1], base, all_dicts[1], all_dicts)

    assert c0 == {"Scrip Name": "#00007f"}   # VAH Buy row -> dark blue on Scrip Name
    assert c1 == {"Lot Size": "#ff55ff"}     # VAL Sell row -> pink on Lot Size
