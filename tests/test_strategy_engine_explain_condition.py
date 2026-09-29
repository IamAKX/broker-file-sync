from services.strategy_engine import clause_label, explain_condition


def _col(name):
    return {"type": "col", "value": name}


def _op(v):
    return {"type": "op", "value": v}


def _num(v):
    return {"type": "num", "value": str(v)}


def test_explain_condition_splits_top_level_and_into_clauses():
    # [Close] > 100 and [Volume] > 1000
    tokens = [_col("Close"), _op(">"), _num(100), _op(" and "), _col("Volume"), _op(">"), _num(1000)]
    row = {"Close": 150, "Volume": 500}

    results = explain_condition(tokens, row, [row])

    assert len(results) == 2
    assert results[0]["label"] == "[Close] > 100"
    assert results[0]["satisfied"] is True
    assert results[1]["label"] == "[Volume] > 1000"
    assert results[1]["satisfied"] is False


def test_explain_condition_does_not_split_inside_parens():
    # ([Close] > 100 and [Volume] > 1000) and [Day Top] > 50
    tokens = [
        {"type": "paren", "value": "("}, _col("Close"), _op(">"), _num(100), _op(" and "),
        _col("Volume"), _op(">"), _num(1000), {"type": "paren", "value": ")"},
        _op(" and "), _col("Day Top"), _op(">"), _num(50),
    ]
    row = {"Close": 150, "Volume": 500, "Day Top": 60}

    results = explain_condition(tokens, row, [row])

    assert len(results) == 2
    assert results[0]["satisfied"] is False   # the parenthesized AND clause as a whole
    assert results[1]["satisfied"] is True


def test_explain_condition_with_only_or_stays_one_clause():
    # Real "or" op tokens carry their own surrounding spaces (see screens.
    # formula_editor.py's {"type": "op", "value": " or "} — needed since
    # _build_compiled concatenates token values directly into real Python
    # source with no separator of its own).
    tokens = [_col("Close"), _op(">"), _num(100), _op(" or "), _col("Volume"), _op(">"), _num(1000)]
    row = {"Close": 50, "Volume": 5000}

    results = explain_condition(tokens, row, [row])

    assert len(results) == 1
    assert results[0]["satisfied"] is True


def test_explain_condition_single_comparison_is_one_clause():
    tokens = [_col("Close"), _op(">"), _num(100)]
    row = {"Close": 150}

    results = explain_condition(tokens, row, [row])

    assert len(results) == 1
    assert results[0]["label"] == "[Close] > 100"
    assert results[0]["satisfied"] is True


def test_clause_label_renders_this_and_variable_tokens():
    tokens = [{"type": "self"}, _op(">"), {"type": "var", "value": "Threshold"}]
    assert clause_label(tokens) == "THIS > {Threshold}"


def test_clause_label_renders_col_of_symbol():
    tokens = [{"type": "col", "value": "Open", "of": "Nifty"}]
    assert clause_label(tokens) == "[Open of Nifty]"


def test_explain_condition_empty_tokens_returns_empty_list():
    assert explain_condition([], {}, [{}]) == []
