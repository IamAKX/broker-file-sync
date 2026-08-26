"""Tests for services/inception_day_history.py — pure logic, no Qt/DB."""
from datetime import date

from services import inception_day_history as idh


def _bars(closes: list, start=date(2025, 1, 1)):
    from datetime import timedelta
    return [
        {"trade_date": start + timedelta(days=i), "open": c, "high": c + 1, "low": c - 1,
         "close": c, "volume": 1000, "open_interest": 500}
        for i, c in enumerate(closes)
    ]


def _strategy(formula):
    return {
        "id": "s1", "name": "Test", "active": True,
        "columns": [{"name": "Test Col", "formula": formula}],
        "row_filter": [],
    }


def tok_days(fname, col, days):
    return {"type": "func", "value": f"{fname}(", "col_arg": col, "days_arg": days}


def tok_on_date(col, iso_date):
    return {"type": "func", "value": "VALUE_ON_DATE(", "col_arg": col, "date_arg": iso_date}


def test_raw_day_specs_picks_up_raw_field_only():
    strategies = [_strategy([tok_days("AVG_DAYS", "CLOSE", 200)])]
    specs = idh.raw_day_specs(strategies)
    assert specs == [("Average", "CLOSE", 200)]


def test_raw_day_specs_excludes_derived_columns():
    """A _DAYS reference to a Group A/B or Formula Builder derived code
    (not a raw OHLCV field) is out of this module's scope — see its
    docstring — and must not show up here."""
    strategies = [_strategy([tok_days("AVG_DAYS", "52WH", 30)])]
    assert idh.raw_day_specs(strategies) == []


def test_raw_day_specs_deduped_across_strategies():
    strategies = [
        _strategy([tok_days("AVG_DAYS", "CLOSE", 200)]),
        _strategy([tok_days("AVG_DAYS", "CLOSE", 200)]),
    ]
    assert idh.raw_day_specs(strategies) == [("Average", "CLOSE", 200)]


def test_raw_day_specs_scans_active_and_inactive_strategies():
    """Deliberately includes inactive strategies too — a strategy switched
    on later in the same session (via the picker) without a fresh Load
    still needs to have been known when build() ran."""
    strategies = [dict(_strategy([tok_days("AVG_DAYS", "CLOSE", 200)]), active=False)]
    assert idh.raw_day_specs(strategies) == [("Average", "CLOSE", 200)]


def test_build_avg_days_matches_reported_200_average_strategy():
    """The exact reported case: AVG_DAYS(CLOSE, 200) — average of the last
    200 bars' CLOSE."""
    specs = [("Average", "CLOSE", 200)]
    closes = list(range(100, 310))   # 210 values: 100..309
    bars = _bars(closes)
    result = idh.build(specs, "ABB_I", bars)
    # last 200 closes: 110..309 -> average 209.5
    assert result[("CLOSE", 200)]["ABB_I"]["Average"] == 209.5


def test_build_value_days_ago_uses_first_key():
    specs = [("First", "HIGH", 2)]   # VALUE_DAYS_AGO(HIGH, 1) -> window = days_arg+1
    bars = _bars([100, 105, 110])
    result = idh.build(specs, "TEST", bars)
    # window=2 -> last 2 bars (105,110) high values -> First = oldest = 105's high (106)
    assert result[("HIGH", 2)]["TEST"]["First"] == 106


def test_build_returns_nothing_when_not_enough_history():
    specs = [("Average", "CLOSE", 200)]
    bars = _bars([100, 105, 110])   # only 3 bars, need 200
    result = idh.build(specs, "TEST", bars)
    assert result == {}


def test_build_value_on_date_resolves_fixed_calendar_date():
    specs = [("First", "CLOSE", ("2025-01-02", "2025-01-02"))]
    bars = _bars([100, 105, 110])   # 2025-01-01, 01-02, 01-03
    result = idh.build(specs, "TEST", bars)
    assert result[("CLOSE", ("2025-01-02", "2025-01-02"))]["TEST"]["First"] == 105


def test_build_value_on_date_missing_date_is_none():
    specs = [("First", "CLOSE", ("2030-01-01", "2030-01-01"))]
    bars = _bars([100, 105, 110])
    result = idh.build(specs, "TEST", bars)
    assert result[("CLOSE", ("2030-01-01", "2030-01-01"))]["TEST"]["First"] is None


def test_build_zero_or_negative_window_skipped():
    specs = [("Average", "CLOSE", 0)]
    bars = _bars([100, 105, 110])
    assert idh.build(specs, "TEST", bars) == {}
