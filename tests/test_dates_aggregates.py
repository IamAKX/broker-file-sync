"""Issue #114: AVG/MIN/MAX/SUM/COUNT/STDDEV/MEDIAN/VARIANCE/RANGE between
two calendar dates (AVG_DATES([col], from, to), ...) in the LMV and
Inception strategy builders."""

import statistics
from datetime import date, timedelta

import pytest

from services import strategy_engine
from services.formula_stats_engine import compute_day_history, compute_stats


def _tok(fname, col, d_from, d_to):
    return {"type": "func", "value": f"{fname}(", "col_arg": col,
            "date_from_arg": d_from, "date_to_arg": d_to}


def test_parse_and_render_round_trip():
    from screens.formula_editor import _tokens_to_text, parse_expression_text
    tokens = parse_expression_text("AVG_DATES([DAY TO], 2026-10-01, 2026-10-31) > 2")
    assert tokens[0] == _tok("AVG_DATES", "DAY TO", "2026-10-01", "2026-10-31")
    assert _tokens_to_text(tokens) == "AVG_DATES([DAY TO], 2026-10-01, 2026-10-31) > 2"


def test_every_dates_function_is_in_the_catalogue_with_a_range_picker():
    from screens.formula_editor import FUNCTION_CATALOGUE
    names = {e["name"]: e for e in FUNCTION_CATALOGUE}
    for base in ("AVG", "MIN", "MAX", "SUM", "COUNT", "STDDEV", "MEDIAN", "VARIANCE", "RANGE"):
        entry = names[f"{base}_DATES"]
        assert entry["token"]["needs_point_picker"] == "date_range"


def test_compile_uses_date_range_window():
    comp = strategy_engine.get_compiled([_tok("MAX_DATES", "Close", "2026-10-01", "2026-10-31")])
    assert comp.day_specs[0][1:] == ("Max", "Close", ("2026-10-01", "2026-10-31"))
    assert strategy_engine.scan_day_funcs([_tok("STDDEV_DATES", "Close", "2026-10-01", "2026-10-31")]) == [
        ("Close", ("2026-10-01", "2026-10-31"))]


def _range_response(closes_by_day):
    return {"days": [
        {"trade_date": d, "stocks": [{"symbol": "ABB", "metrics": {"Close": c}}]}
        for d, c in closes_by_day
    ]}


@pytest.mark.parametrize("fname,expected", [
    ("AVG_DATES", statistics.mean([20, 30, 40])),
    ("MIN_DATES", 20), ("MAX_DATES", 40), ("SUM_DATES", 90), ("COUNT_DATES", 3),
    ("STDDEV_DATES", statistics.stdev([20, 30, 40])),
    ("MEDIAN_DATES", 30), ("VARIANCE_DATES", statistics.variance([20, 30, 40])),
    ("RANGE_DATES", 20),
])
def test_lmv_day_history_aggregates_only_the_range(fname, expected):
    response = _range_response([("2026-10-01", 10), ("2026-10-02", 20), ("2026-10-03", 30),
                                ("2026-10-06", 40), ("2026-10-07", 50)])
    formula = [_tok(fname, "Close", "2026-10-02", "2026-10-06")]
    requests = strategy_engine.collect_day_requests(
        [{"name": "S", "active": True, "columns": [{"name": "X", "formula": formula}]}], {})
    dh = compute_day_history(requests, lambda days: response)
    value = strategy_engine.evaluate(formula, {"Scrip Name": "ABB"}, [], day_history=dh)
    assert value == pytest.approx(expected)


def test_formula_stats_self_contained_dates_aggregate():
    response = _range_response([("2026-10-01", 10), ("2026-10-02", 20), ("2026-10-03", 30)])
    out = compute_stats([{"name": "X", "formula": [_tok("MAX_DATES", "Close", "2026-10-01", "2026-10-02")]}],
                        response)
    # Day 1 sees only 10, day 2 and later see the max of the range so far.
    assert [v for _, v in out["ABB"]["columns"]["X"]["daily"]] == [10, 20, 20]


def test_inception_raw_build_aggregates_range():
    from services import inception_day_history as idh
    start = date(2026, 10, 1)
    bars = [{"trade_date": start + timedelta(days=i), "open": c, "high": c, "low": c, "close": c,
             "volume": 1, "open_interest": 1} for i, c in enumerate([10, 20, 30, 40])]
    window = ("2026-10-02", "2026-10-03")
    specs = [("Average", "CLOSE", window), ("Max", "CLOSE", window)]
    out = idh.build(specs, "ABB_I", bars)
    assert out[("CLOSE", window)]["ABB_I"] == {"Average": 25, "Max": 30}
