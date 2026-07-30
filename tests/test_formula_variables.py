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
