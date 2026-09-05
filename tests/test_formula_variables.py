import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


@pytest.fixture
def var_store(tmp_path, monkeypatch):
    from services import formula_variable_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "vars.json"))
    return store


@pytest.fixture(autouse=True)
def _clear_compile_cache():
    # The compile cache is a module-level dict shared across tests — a
    # formula var-signature collision between tests would otherwise leak a
    # stale compiled expression from one test into another.
    from services import strategy_engine
    strategy_engine.clear_compile_cache()
    yield
    strategy_engine.clear_compile_cache()


def tok_fn(name):   return {"type": "func", "value": f"{name}("}
def tok_col(name):  return {"type": "col",  "value": name}
def tok_num(v):     return {"type": "num",  "value": str(v)}
def tok_op(v):      return {"type": "op",   "value": v}
def tok_var(name):  return {"type": "var",  "value": name}
def tok_p_close():  return {"type": "paren", "value": ")"}


# ── Store CRUD ────────────────────────────────────────────────────────────────

def test_new_variable_has_id_name_empty_formula(var_store):
    v = var_store.new_variable("Foo")
    assert v["name"] == "Foo"
    assert v["formula"] == []
    assert v["id"]


def test_save_and_get_by_name(var_store):
    v = var_store.new_variable("Threshold")
    v["formula"] = [tok_num(0.998)]
    var_store.save_variable(v)
    got = var_store.get_by_name("Threshold")
    assert got is not None
    assert got["formula"] == [tok_num(0.998)]


def test_get_by_name_missing_returns_none(var_store):
    assert var_store.get_by_name("Nope") is None


def test_save_updates_existing_by_id(var_store):
    v = var_store.new_variable("A")
    var_store.save_variable(v)
    v["formula"] = [tok_num(1)]
    var_store.save_variable(v)
    all_v = var_store.load_all()
    assert len(all_v) == 1
    assert all_v[0]["formula"] == [tok_num(1)]


def test_delete_variable(var_store):
    v = var_store.new_variable("A")
    var_store.save_variable(v)
    var_store.delete_variable(v["id"])
    assert var_store.load_all() == []


# ── Engine expansion (services.strategy_engine._expand_var_tokens) ──────────

def test_evaluate_resolves_simple_variable(var_store):
    from services.strategy_engine import evaluate
    v = var_store.new_variable("Half")
    v["formula"] = [tok_num(0.5)]
    var_store.save_variable(v)

    tokens = [tok_num(1), tok_op("+"), tok_var("Half")]
    assert evaluate(tokens, {}, []) == 1.5


def test_evaluate_variable_wraps_in_parens_for_precedence(var_store):
    from services.strategy_engine import evaluate
    v = var_store.new_variable("SumTwoThree")
    v["formula"] = [tok_num(2), tok_op("+"), tok_num(3)]
    var_store.save_variable(v)

    # 10 / (2+3) == 2, not 10/2+3 == 8 — proves the substitution is parenthesized.
    tokens = [tok_num(10), tok_op("/"), tok_var("SumTwoThree")]
    assert evaluate(tokens, {}, []) == 2.0


def test_evaluate_unknown_variable_drops_silently(var_store):
    from services.strategy_engine import evaluate
    tokens = [tok_num(1), tok_op("+"), tok_var("DoesNotExist")]
    # "1 +" with nothing after it is a syntax error -> compiled is None -> None
    assert evaluate(tokens, {}, []) is None


def test_evaluate_variable_referencing_another_variable(var_store):
    from services.strategy_engine import evaluate
    inner = var_store.new_variable("Inner")
    inner["formula"] = [tok_num(4)]
    var_store.save_variable(inner)
    outer = var_store.new_variable("Outer")
    outer["formula"] = [tok_var("Inner"), tok_op("*"), tok_num(2)]
    var_store.save_variable(outer)

    assert evaluate([tok_var("Outer")], {}, []) == 8


def test_evaluate_cyclic_variable_does_not_hang(var_store):
    from services.strategy_engine import evaluate
    a = var_store.new_variable("A")
    b = var_store.new_variable("B")
    a["formula"] = [tok_var("B")]
    b["formula"] = [tok_var("A")]
    var_store.save_variable(a)
    var_store.save_variable(b)
    # Cyclic reference resolves to nothing at the point of the cycle, leaving
    # an empty/invalid expression — must return None, not hang or crash.
    assert evaluate([tok_var("A")], {}, []) is None


def test_evaluate_variable_referencing_column(var_store):
    from services.strategy_engine import evaluate
    v = var_store.new_variable("DoubleOpen")
    v["formula"] = [tok_col("Open"), tok_op("*"), tok_num(2)]
    var_store.save_variable(v)
    row = {"Open": "50"}
    assert evaluate([tok_var("DoubleOpen")], row, [row]) == 100.0


def test_editing_variable_invalidates_compile_cache(var_store):
    """A formula that references {Name} must pick up an edit to Name's own
    formula on the very next evaluate() call — the compile cache's key is
    the raw (un-expanded) token signature, which doesn't change just because
    the variable's definition did, so save_variable() must bust it."""
    from services.strategy_engine import evaluate
    v = var_store.new_variable("Threshold")
    v["formula"] = [tok_num(1)]
    var_store.save_variable(v)

    tokens = [tok_var("Threshold")]
    assert evaluate(tokens, {}, []) == 1

    v["formula"] = [tok_num(2)]
    var_store.save_variable(v)
    assert evaluate(tokens, {}, []) == 2


def test_compile_check_reports_unknown_column_inside_variable(var_store):
    from services.strategy_engine import compile_check
    v = var_store.new_variable("UsesGhost")
    v["formula"] = [tok_col("GhostColumn")]
    var_store.save_variable(v)
    ok, msg = compile_check([tok_var("UsesGhost")], {"Open": "1"}, [{"Open": "1"}])
    assert ok is False
    assert "GhostColumn" in msg


# ── End-to-end: the digit-tiered threshold as a variable ────────────────────

def test_digit_tiered_threshold_variable_five_digit(var_store):
    from services.strategy_engine import evaluate
    v = var_store.new_variable("ClosenessThreshold")
    v["formula"] = [
        tok_fn("IIf"),
            tok_fn("Digits"), tok_col("Open"), tok_p_close(),
            tok_op(">="), tok_num(5), tok_op(","),
            tok_num(0.998), tok_op(","),
            tok_num(0.919),
        tok_p_close(),
    ]
    var_store.save_variable(v)

    row = {"Open": "12123.77"}
    assert evaluate([tok_var("ClosenessThreshold")], row, [row]) == 0.998


def test_digit_tiered_threshold_variable_used_in_comparison(var_store):
    from services.strategy_engine import evaluate_condition
    v = var_store.new_variable("ClosenessThreshold")
    v["formula"] = [
        tok_fn("IIf"),
            tok_fn("Digits"), tok_col("Open"), tok_p_close(),
            tok_op(">="), tok_num(5), tok_op(","),
            tok_num(0.998), tok_op(","),
            tok_num(0.919),
        tok_p_close(),
    ]
    var_store.save_variable(v)

    row = {"Open": "2435.22", "PMH": "2400"}
    # Min(Open,PMH) / Max(Open,PMH) >= {ClosenessThreshold}
    tokens = [
        tok_fn("Min"), tok_col("Open"), tok_op(","), tok_col("PMH"), tok_p_close(),
        tok_op("/"),
        tok_fn("Max"), tok_col("Open"), tok_op(","), tok_col("PMH"), tok_p_close(),
        tok_op(">="), tok_var("ClosenessThreshold"),
    ]
    assert evaluate_condition(tokens, row, [row]) is True


# ── Inception's own variable store (issue #21) ───────────────────────────────
# services.strategy_engine used to hardcode services.formula_variable_store
# (LMV's own) everywhere a "{Name}" token got expanded — screens.
# inception_strategy_builder's Variables tab reads/writes a SEPARATE store
# (services.inception_formula_variable_store), so any variable used in an
# Inception formula silently resolved against the wrong (LMV) store: found
# nothing, got dropped, and either evaluated as if it were never there or
# (for a formula that was JUST the variable) failed compile_check outright
# with "The variable(s) this formula refers to are empty or missing."

@pytest.fixture
def inception_var_store(tmp_path, monkeypatch):
    from services import inception_formula_variable_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "inception_vars.json"))
    from api import inception_api
    monkeypatch.setattr(inception_api, "upsert_variable", lambda *a, **k: None)
    monkeypatch.setattr(inception_api, "delete_variable", lambda *a, **k: None)
    return store


def test_inception_variable_resolves_via_explicit_variable_store(inception_var_store):
    """Direct repro of issue #21: a variable saved in Inception's OWN store
    must resolve when that store is passed explicitly — and must NOT
    resolve (dropped, same as any unknown/deleted variable) against LMV's
    default store, confirming the fix is store-driven, not accidentally
    always-on."""
    from services.strategy_engine import evaluate, compile_check

    v = inception_var_store.new_variable("MyVar")
    v["formula"] = [tok_num(42)]
    inception_var_store.save_variable(v)

    tokens = [tok_var("MyVar")]
    assert evaluate(tokens, {}, [], variable_store=inception_var_store) == 42
    assert evaluate(tokens, {}, []) is None   # LMV's default store — not found

    ok, msg = compile_check(tokens, {}, [{}], variable_store=inception_var_store)
    assert ok is True
    assert msg == "42"
    ok2, msg2 = compile_check(tokens, {}, [{}])
    assert ok2 is False
    assert "empty or missing" in msg2


def test_lmv_and_inception_variables_of_the_same_name_do_not_collide(var_store, inception_var_store):
    """LMV and Inception variables are independent user data — a user could
    name one "Threshold" in each store with completely different formulas.
    get_compiled's cache key must include which store resolved a "var"
    token, or whichever store compiled a given raw-token shape FIRST would
    silently win the cache for the other store's later caller."""
    from services.strategy_engine import evaluate

    lmv_v = var_store.new_variable("Threshold")
    lmv_v["formula"] = [tok_num(1)]
    var_store.save_variable(lmv_v)

    inc_v = inception_var_store.new_variable("Threshold")
    inc_v["formula"] = [tok_num(2)]
    inception_var_store.save_variable(inc_v)

    tokens = [tok_var("Threshold")]
    assert evaluate(tokens, {}, []) == 1                                  # LMV default
    assert evaluate(tokens, {}, [], variable_store=inception_var_store) == 2
    # Re-check LMV's own resolution AFTER the Inception one ran — proves the
    # cache didn't get clobbered by the other store's compile.
    assert evaluate(tokens, {}, []) == 1


def test_editing_inception_variable_invalidates_compile_cache(inception_var_store):
    """Mirrors test_editing_variable_invalidates_compile_cache above —
    inception_formula_variable_store never had this fix at all (a separate
    module from formula_variable_store, so it never inherited it)."""
    from services.strategy_engine import evaluate

    v = inception_var_store.new_variable("Threshold")
    v["formula"] = [tok_num(1)]
    inception_var_store.save_variable(v)

    tokens = [tok_var("Threshold")]
    assert evaluate(tokens, {}, [], variable_store=inception_var_store) == 1

    v["formula"] = [tok_num(2)]
    inception_var_store.save_variable(v)
    assert evaluate(tokens, {}, [], variable_store=inception_var_store) == 2


def test_apply_strategies_resolves_variable_via_variable_store(inception_var_store):
    """End-to-end through apply_strategies (the real HMV/View by Date render
    path, not just a bare evaluate() call) — screens.inception_hmv/
    inception_view_by_date pass variable_store=inception_formula_variable_
    store to exactly this function."""
    from services.strategy_engine import apply_strategies

    v = inception_var_store.new_variable("Bump")
    v["formula"] = [tok_num(10)]
    inception_var_store.save_variable(v)

    strat = {
        "id": "s1", "active": True, "row_filter": [],
        "columns": [{"name": "Bumped", "formula": [tok_col("Close"), tok_op("+"), tok_var("Bump")]}],
    }
    headers = ["Scrip Name", "Close"]
    data = [["INFY", 100.0]]
    new_headers, new_data = apply_strategies(
        [strat], headers, data, variable_store=inception_var_store,
    )
    assert new_headers == ["Scrip Name", "Close", "Bumped"]
    assert new_data[0][2] == 110.0


def test_get_row_fmt_colors_resolves_variable_via_variable_store(inception_var_store):
    """Conditional Formatting's own condition can reference a variable too
    — get_row_fmt_colors/get_cell_color/_match_fmt_rule all needed the same
    variable_store threading as the column-formula/row-filter path."""
    from services.strategy_engine import get_row_fmt_colors

    v = inception_var_store.new_variable("MinGood")
    v["formula"] = [tok_num(50)]
    inception_var_store.save_variable(v)

    col_def = {
        "name": "Score",
        "fmt_rules": [
            {"condition": [{"type": "self"}, tok_op(">="), tok_var("MinGood")],
             "color": "#00ff00", "target_column": None},
        ],
    }
    row = ["INFY", 75]
    row_dict = {"Scrip Name": "INFY", "Score": 75}
    colors = get_row_fmt_colors([col_def], row, 1, row_dict, [row_dict],
                                variable_store=inception_var_store)
    assert colors == {"Score": "#00ff00"}
