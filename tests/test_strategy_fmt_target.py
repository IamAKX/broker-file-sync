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
