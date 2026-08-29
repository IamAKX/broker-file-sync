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


def tok_extreme_days(fname, col, driver_col, days):
    return {"type": "func", "value": f"{fname}(", "col_arg": col,
            "driver_col_arg": driver_col, "days_arg": days}


def tok_extreme_dates(fname, col, driver_col, date_from, date_to):
    return {"type": "func", "value": f"{fname}(", "col_arg": col,
            "driver_col_arg": driver_col, "date_from_arg": date_from, "date_to_arg": date_to}


def tok_before_change(col, months=None):
    tok = {"type": "func", "value": "VALUE_BEFORE_CHANGE(", "col_arg": col}
    if months is not None:
        tok["days_arg"] = months
    return tok


def test_raw_day_specs_excludes_value_before_change_auto_form():
    """Regression: VALUE_BEFORE_CHANGE([HIGH]) (no months_back — the "auto"
    form) also passes the "col_name in RAW_FIELDS" filter, but its window
    is services.strategy_engine.VALUE_BEFORE_CHANGE_DAILY_TAG's own tagged
    tuple, not a plain _DAYS/VALUE_ON_DATE window — build() would misread
    the tag string as a literal target_date to scan bars for (never
    matches) and silently produce a bogus {"First": None} entry that
    shadows the real one services.inception_value_before_change resolves
    separately. Must not appear in raw_day_specs at all."""
    strategies = [_strategy([tok_before_change("HIGH")])]
    assert idh.raw_day_specs(strategies) == []


def test_raw_day_specs_excludes_value_before_change_months_form():
    strategies = [_strategy([tok_before_change("HIGH", 6)])]
    assert idh.raw_day_specs(strategies) == []


def test_raw_day_specs_value_before_change_alongside_real_days_spec():
    """A strategy using BOTH AVG_DAYS([HIGH], 20) and VALUE_BEFORE_CHANGE(
    [HIGH]) in the same or different columns should keep the real spec and
    drop only the VALUE_BEFORE_CHANGE one."""
    strategies = [_strategy([tok_days("AVG_DAYS", "HIGH", 20), tok_before_change("HIGH")])]
    assert idh.raw_day_specs(strategies) == [("Average", "HIGH", 20)]


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


def test_build_merges_multiple_agg_keys_for_same_column_window_no_clobber():
    """Regression: previously the second spec's assignment overwrote the
    first entirely — a strategy using both AVG_DAYS(HIGH, 3) and
    MAX_DAYS(HIGH, 3) would silently lose one of the two results."""
    specs = [("Average", "HIGH", 3), ("Max", "HIGH", 3)]
    bars = _bars([100, 105, 110])   # highs: 101, 106, 111
    result = idh.build(specs, "TEST", bars)
    entry = result[("HIGH", 3)]["TEST"]
    assert entry["Average"] == 106.0
    assert entry["Max"] == 111


# ── raw_extreme_specs / build_extreme (VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/
# VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES) ─────────────────────────────────

def test_raw_extreme_specs_picks_up_raw_fields_only():
    strategies = [_strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "HIGH", "CLOSE", 5)])]
    assert idh.raw_extreme_specs(strategies) == [("HIGH", "CLOSE", 5, True)]


def test_raw_extreme_specs_min_days_wants_max_false():
    strategies = [_strategy([tok_extreme_days("VALUE_AT_MIN_DAYS", "LOW", "CLOSE", 5)])]
    assert idh.raw_extreme_specs(strategies) == [("LOW", "CLOSE", 5, False)]


def test_raw_extreme_specs_dates_variant():
    strategies = [_strategy([
        tok_extreme_dates("VALUE_AT_MAX_DATES", "HIGH", "CLOSE", "2025-01-02", "2025-01-03"),
    ])]
    assert idh.raw_extreme_specs(strategies) == [("HIGH", "CLOSE", ("2025-01-02", "2025-01-03"), True)]


def test_raw_extreme_specs_excludes_when_driver_is_derived():
    """CWTO is a Group A/B derived column, not a raw OHLCV field — same
    RAW_FIELDS-only scoping as raw_day_specs, applied to the driver side
    too."""
    strategies = [_strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "HIGH", "CWTO", 5)])]
    assert idh.raw_extreme_specs(strategies) == []


def test_raw_extreme_specs_excludes_when_value_col_is_derived():
    strategies = [_strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "52WH", "CLOSE", 5)])]
    assert idh.raw_extreme_specs(strategies) == []


def test_raw_extreme_specs_deduped_across_strategies():
    strategies = [
        _strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "HIGH", "CLOSE", 5)]),
        _strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "HIGH", "CLOSE", 5)]),
    ]
    assert idh.raw_extreme_specs(strategies) == [("HIGH", "CLOSE", 5, True)]


def test_build_extreme_returns_daily_lists_for_both_columns():
    specs = [("HIGH", "CLOSE", 3, True)]
    bars = _bars([100, 105, 110, 90])   # highs: 101,106,111,91
    result = idh.build_extreme(specs, "TEST", bars)
    assert set(result.keys()) == {("HIGH", 3), ("CLOSE", 3)}
    # last 3 bars only: closes 105,110,90 -> highs 106,111,91
    assert [v for _, v in result[("HIGH", 3)]["TEST"]["daily"]] == [106, 111, 91]
    assert [v for _, v in result[("CLOSE", 3)]["TEST"]["daily"]] == [105, 110, 90]


def test_build_extreme_date_range_scans_inclusive_range():
    specs = [("HIGH", "CLOSE", ("2025-01-02", "2025-01-03"), True)]
    bars = _bars([100, 105, 110])   # 2025-01-01, 01-02, 01-03
    result = idh.build_extreme(specs, "TEST", bars)
    window = ("2025-01-02", "2025-01-03")
    assert [v for _, v in result[("HIGH", window)]["TEST"]["daily"]] == [106, 111]


def test_build_extreme_not_enough_history_gives_empty_daily_list():
    specs = [("HIGH", "CLOSE", 10, True)]
    bars = _bars([100, 105])   # only 2 bars, need 10
    result = idh.build_extreme(specs, "TEST", bars)
    assert result[("HIGH", 10)]["TEST"]["daily"] == []


def test_build_extreme_no_specs_is_noop():
    assert idh.build_extreme([], "TEST", _bars([100])) == {}


def test_build_extreme_empty_bars_is_noop():
    assert idh.build_extreme([("HIGH", "CLOSE", 3, True)], "TEST", []) == {}


# ── merge_into ────────────────────────────────────────────────────────────

def test_merge_into_combines_agg_key_and_daily_without_clobbering():
    """The exact scenario build()/build_extreme() must coexist for: a
    formula using both AVG_DAYS([HIGH], 20) and VALUE_AT_MAX_DAYS([HIGH],
    [CLOSE], 20) needs the SAME (HIGH, 20) entry to carry both "Average"
    and "daily" — a shallow dict.update at the call site would have the
    second merge_into call replace the first's per-symbol dict wholesale."""
    day_history = {}
    idh.merge_into(day_history, {("HIGH", 20): {"TEST": {"Average": 105.0}}})
    idh.merge_into(day_history, {("HIGH", 20): {"TEST": {"daily": [("2025-01-01", 100)]}}})
    assert day_history[("HIGH", 20)]["TEST"] == {
        "Average": 105.0, "daily": [("2025-01-01", 100)],
    }


def test_merge_into_different_symbols_coexist():
    day_history = {}
    idh.merge_into(day_history, {("HIGH", 20): {"A": {"Average": 1.0}}})
    idh.merge_into(day_history, {("HIGH", 20): {"B": {"Average": 2.0}}})
    assert day_history[("HIGH", 20)] == {"A": {"Average": 1.0}, "B": {"Average": 2.0}}
