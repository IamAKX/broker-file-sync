"""Issue #128: VALUE_DAYS_AGO of a strategy column that itself uses
AVG_DAYS/STDDEV_DAYS (UPPER SD 1 = AVG_DAYS([VAH], 20) + STDDEV_DAYS([VAH],
20); PRE USD 1 = VALUE_DAYS_AGO([UPPER SD 1], 1)) came back blank in LMV."""
import statistics
from datetime import date, timedelta

import pytest

from services import strategy_engine as se
from services.formula_stats_engine import compute_day_history


def _func(fn, col, n):
    return {"type": "func", "value": f"{fn}(", "col_arg": col, "days_arg": n}


def _col(c):
    return {"type": "col", "value": c}


STRATEGY = {"id": "sd", "name": "SD UPPER VAH", "active": True, "row_filter": [], "columns": [
    {"name": "AVG VAH", "formula": [_func("AVG_DAYS", "VAH", 5)]},
    {"name": "1 SD", "formula": [_func("STDDEV_DAYS", "VAH", 5)]},
    {"name": "UPPER SD 1", "formula": [_col("AVG VAH"), {"type": "op", "value": "+"}, _col("1 SD")]},
    {"name": "PRE USD 1", "formula": [_func("VALUE_DAYS_AGO", "UPPER SD 1", 1)]},
]}


def _response(vahs):
    start = date(2026, 11, 1)
    # LMV daily snapshots carry many metrics as numeric STRINGS.
    return {"days": [{"trade_date": (start + timedelta(days=i)).isoformat(),
                      "stocks": [{"symbol": "SBIN", "metrics": {"VAH": f"{v:.2f}"}}]}
                     for i, v in enumerate(vahs)]}


def test_value_days_ago_of_a_column_with_its_own_look_back():
    vahs = [100, 104, 98, 110, 107, 115, 120, 118, 125, 130]
    response = _response(vahs)

    def fetch(days):
        return {"days": response["days"][-days:]}

    day_history = compute_day_history(se.collect_day_requests([STRATEGY], {}), fetch)
    headers, rows = se.apply_strategies([STRATEGY], ["Scrip Name"], [["SBIN"]], day_history=day_history,
                                        include_streak_columns=False)
    row = dict(zip(headers, rows[0]))
    prev = vahs[-6:-1]                               # 5 saved days ending the 2nd-latest saved day
    assert row["PRE USD 1"] == pytest.approx(statistics.mean(prev) + statistics.stdev(prev))
    last5 = vahs[-5:]
    assert row["UPPER SD 1"] == pytest.approx(statistics.mean(last5) + statistics.stdev(last5))


def test_two_aggregates_of_the_same_column_and_window_both_survive():
    from services.formula_stats_engine import _self_contained_day_history
    hist = [(f"2026-11-0{i}", {"VAH": str(v)}) for i, v in enumerate([10, 20, 30], start=1)]
    out = _self_contained_day_history(hist, [("Average", "VAH", 3), ("Std Dev", "VAH", 3)], [], "SBIN")
    assert out[("VAH", 3)]["SBIN"] == {"Average": 20, "Std Dev": pytest.approx(10)}
