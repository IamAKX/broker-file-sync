"""Tests for services/inception_day_history.py — pure logic, no Qt/DB."""
from datetime import date, timedelta
from unittest.mock import patch

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
    (not a raw OHLCV field) is out of raw_day_specs' own scope — it stays
    that way even after issue #45's fix (derived_day_specs picks up VALUE_
    DAYS_AGO/VALUE_ON_DATE against a derived column instead — _DAYS-family
    aggregates like AVG_DAYS against a derived column are still out of
    scope everywhere, see derived_day_specs' own docstring) — see
    test_derived_day_specs_* below for what IS now supported."""
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
    """CWTO is a Formula Builder derived column (services.formula_engine.
    FORMULA_CODES), not a raw OHLCV field — same RAW_FIELDS-only scoping
    as raw_day_specs, applied to the driver side too. raw_extreme_specs
    itself stays this way after issue #45's fix — see
    test_extreme_specs_for_strategies_includes_mixed_kind_pairs and
    test_build_extreme_for_pairs_resolves_raw_side_of_mixed_kind_spec
    below for what a mixed raw/derived pair now resolves to instead."""
    strategies = [_strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "HIGH", "CWTO", 5)])]
    assert idh.raw_extreme_specs(strategies) == []


def test_raw_extreme_specs_excludes_when_value_col_is_derived():
    """52WH is a Group A/B derived column, not a raw OHLCV field."""
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


# ── issue #45 — Formula Builder / Group A/B columns ──────────────────────
# derived_day_specs/resolve_formula_builder_day/resolve_group_a_b_day (the
# VALUE_DAYS_AGO/VALUE_ON_DATE analogues) and extreme_specs_for_strategies/
# extreme_needed_pairs/split_extreme_pairs_by_kind/build_extreme_for_pairs/
# resolve_formula_builder_extreme/resolve_group_a_b_extreme (the VALUE_AT_
# MAX/MIN_DAYS/DATES analogues) — see the module docstring's "Formula
# Builder / Group A/B columns" section.

def test_derived_day_specs_picks_up_value_days_ago_for_formula_builder_column():
    """CWTO is a Formula Builder code (services.formula_engine.
    FORMULA_CODES) — raw_day_specs drops it (see
    test_raw_day_specs_excludes_derived_columns' sibling), derived_day_specs
    picks it up instead."""
    strategies = [_strategy([tok_days("VALUE_DAYS_AGO", "CWTO", 4)])]
    assert idh.derived_day_specs(strategies) == [("First", "CWTO", 5)]


def test_derived_day_specs_picks_up_value_on_date_for_group_ab_column():
    strategies = [_strategy([tok_on_date("52WH", "2025-01-05")])]
    assert idh.derived_day_specs(strategies) == [("First", "52WH", ("2025-01-05", "2025-01-05"))]


def test_derived_day_specs_excludes_raw_fields():
    """Raw fields stay raw_day_specs' own job — not duplicated here."""
    strategies = [_strategy([tok_days("VALUE_DAYS_AGO", "CLOSE", 4)])]
    assert idh.derived_day_specs(strategies) == []


def test_derived_day_specs_excludes_days_family_aggregates():
    """AVG_DAYS/MAX_DAYS/etc against a derived column stay out of scope —
    _DAYS_AGG_BASE never produces agg_key "First", see this fix's
    Non-goals."""
    strategies = [_strategy([tok_days("AVG_DAYS", "CWTO", 20)])]
    assert idh.derived_day_specs(strategies) == []


def test_derived_day_specs_excludes_value_before_change():
    """VALUE_BEFORE_CHANGE's own tagged window is services.
    inception_value_before_change's job, not this module's, even against a
    derived column."""
    strategies = [_strategy([tok_before_change("CWTO", 6)])]
    assert idh.derived_day_specs(strategies) == []


def test_derived_day_specs_deduped_across_strategies():
    strategies = [
        _strategy([tok_days("VALUE_DAYS_AGO", "CWTO", 4)]),
        _strategy([tok_days("VALUE_DAYS_AGO", "CWTO", 4)]),
    ]
    assert idh.derived_day_specs(strategies) == [("First", "CWTO", 5)]


def test_derived_day_specs_scans_active_and_inactive_strategies():
    strategies = [dict(_strategy([tok_days("VALUE_DAYS_AGO", "CWTO", 4)]), active=False)]
    assert idh.derived_day_specs(strategies) == [("First", "CWTO", 5)]


def test_resolve_formula_builder_day_value_days_ago_reported_case():
    """The issue's own reported case: VALUE_DAYS_AGO([CWTO], 4)."""
    bars = _bars([100, 105, 110, 90, 95, 120])   # 6 bars
    specs = [("First", "CWTO", 5)]   # VALUE_DAYS_AGO([CWTO], 4) -> window=5

    def fake_compute_for_bars(symbol, bar_slice):
        return {"CWTO": len(bar_slice) * 10}

    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        result = idh.resolve_formula_builder_day(specs, "ABB", bars)

    # idx = len(bars) - window = 6 - 5 = 1 -> slice length 2 -> value 20
    assert result == {("CWTO", 5): {"ABB": {"First": 20}}}


def test_resolve_formula_builder_day_value_on_date():
    bars = _bars([100, 105, 110])   # 2025-01-01..03
    specs = [("First", "CWTO", ("2025-01-02", "2025-01-02"))]

    def fake_compute_for_bars(symbol, bar_slice):
        return {"CWTO": len(bar_slice) * 10}

    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        result = idh.resolve_formula_builder_day(specs, "ABB", bars)

    # 2025-01-02 is bars[1] -> slice length 2 -> value 20
    assert result == {("CWTO", ("2025-01-02", "2025-01-02")): {"ABB": {"First": 20}}}


def test_resolve_formula_builder_day_not_enough_bars_is_none():
    bars = _bars([100, 105])
    specs = [("First", "CWTO", 10)]
    result = idh.resolve_formula_builder_day(specs, "ABB", bars)
    assert result == {("CWTO", 10): {"ABB": {"First": None}}}


def test_resolve_formula_builder_day_date_not_found_is_none():
    bars = _bars([100, 105, 110])
    specs = [("First", "CWTO", ("2030-01-01", "2030-01-01"))]
    result = idh.resolve_formula_builder_day(specs, "ABB", bars)
    assert result == {("CWTO", ("2030-01-01", "2030-01-01")): {"ABB": {"First": None}}}


def test_resolve_formula_builder_day_no_specs_or_bars_is_noop():
    assert idh.resolve_formula_builder_day([], "ABB", _bars([100])) == {}
    assert idh.resolve_formula_builder_day([("First", "CWTO", 5)], "ABB", []) == {}


def test_extreme_specs_for_strategies_includes_mixed_kind_pairs():
    """Superset of raw_extreme_specs — a raw driver + Formula Builder value
    column (or vice versa) IS included here, unlike raw_extreme_specs (see
    test_raw_extreme_specs_excludes_when_driver_is_derived)."""
    strategies = [_strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "CLOSE", "CWTO", 5)])]
    assert idh.extreme_specs_for_strategies(strategies) == [("CLOSE", "CWTO", 5, True)]


def test_extreme_specs_for_strategies_deduped_across_strategies():
    strategies = [
        _strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "CLOSE", "CWTO", 5)]),
        _strategy([tok_extreme_days("VALUE_AT_MAX_DAYS", "CLOSE", "CWTO", 5)]),
    ]
    assert idh.extreme_specs_for_strategies(strategies) == [("CLOSE", "CWTO", 5, True)]


def test_extreme_needed_pairs_unions_value_and_driver_sides():
    specs = [("CLOSE", "CWTO", 5, True)]
    assert idh.extreme_needed_pairs(specs) == {("CLOSE", 5), ("CWTO", 5)}


def test_extreme_needed_pairs_self_referential_collapses_to_one_pair():
    specs = [("CWTO", "CWTO", 5, True)]
    assert idh.extreme_needed_pairs(specs) == {("CWTO", 5)}


def test_split_extreme_pairs_by_kind_partitions_raw_fb_and_other():
    """An unresolvable name (SOME_STRATEGY_OUTPUT_COL — neither raw, nor
    Formula Builder, nor a real Group A/B code) lands in the "other" bucket
    alongside genuine Group A/B columns, both handled the same
    silent-blank-if-missing way by resolve_group_a_b_extreme."""
    pairs = {("CLOSE", 5), ("CWTO", 5), ("52WH", 5), ("SOME_STRATEGY_OUTPUT_COL", 5)}
    raw_pairs, fb_pairs, other_pairs = idh.split_extreme_pairs_by_kind(pairs)
    assert raw_pairs == {("CLOSE", 5)}
    assert fb_pairs == {("CWTO", 5)}
    assert other_pairs == {("52WH", 5), ("SOME_STRATEGY_OUTPUT_COL", 5)}


def test_build_extreme_for_pairs_resolves_raw_side_of_mixed_kind_spec():
    """The mixed-kind case raw_extreme_specs itself drops entirely (see
    test_raw_extreme_specs_excludes_when_driver_is_derived) — the raw
    VALUE side must still resolve via this function."""
    bars = _bars([100, 105, 110])   # highs: 101,106,111
    result = idh.build_extreme_for_pairs({("HIGH", 3)}, "TEST", bars)
    assert [v for _, v in result[("HIGH", 3)]["TEST"]["daily"]] == [101, 106, 111]


def test_build_extreme_for_pairs_date_range():
    bars = _bars([100, 105, 110])   # 2025-01-01..03
    window = ("2025-01-02", "2025-01-03")
    result = idh.build_extreme_for_pairs({("HIGH", window)}, "TEST", bars)
    assert [v for _, v in result[("HIGH", window)]["TEST"]["daily"]] == [106, 111]


def test_build_extreme_for_pairs_skips_non_raw_column():
    result = idh.build_extreme_for_pairs({("CWTO", 3)}, "TEST", _bars([100, 105, 110]))
    assert result == {}


def test_build_extreme_for_pairs_no_pairs_or_bars_is_noop():
    assert idh.build_extreme_for_pairs(set(), "TEST", _bars([100])) == {}
    assert idh.build_extreme_for_pairs({("HIGH", 3)}, "TEST", []) == {}


def test_resolve_formula_builder_extreme_int_window_daily_list():
    bars = _bars([100, 105, 110, 90])   # 4 bars

    def fake_compute_for_bars(symbol, bar_slice):
        return {"CWTO": len(bar_slice) * 10}

    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        result = idh.resolve_formula_builder_extreme({("CWTO", 3)}, "ABB", bars)

    # last 3 bars -> indices 1,2,3 -> slice lengths 2,3,4 -> values 20,30,40
    assert [v for _, v in result[("CWTO", 3)]["ABB"]["daily"]] == [20, 30, 40]


def test_resolve_formula_builder_extreme_date_range_daily_list():
    bars = _bars([100, 105, 110])   # 2025-01-01..03

    def fake_compute_for_bars(symbol, bar_slice):
        return {"CWTO": len(bar_slice) * 10}

    window = ("2025-01-02", "2025-01-03")
    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        result = idh.resolve_formula_builder_extreme({("CWTO", window)}, "ABB", bars)

    assert [v for _, v in result[("CWTO", window)]["ABB"]["daily"]] == [20, 30]


def test_resolve_formula_builder_extreme_not_enough_bars_gives_empty_daily_list():
    result = idh.resolve_formula_builder_extreme({("CWTO", 10)}, "ABB", _bars([100, 105]))
    assert result[("CWTO", 10)]["ABB"]["daily"] == []


def test_resolve_formula_builder_extreme_no_pairs_or_bars_is_noop():
    assert idh.resolve_formula_builder_extreme(set(), "ABB", _bars([100])) == {}
    assert idh.resolve_formula_builder_extreme({("CWTO", 3)}, "ABB", []) == {}


def test_group_a_b_date_from_none_when_nothing_needed():
    assert idh.group_a_b_date_from([], set(), date(2025, 7, 29)) is None


def test_group_a_b_date_from_uses_explicit_date_tuple_directly():
    day_specs = [("First", "52WH", ("2025-01-05", "2025-01-05"))]
    assert idh.group_a_b_date_from(day_specs, set(), date(2025, 7, 29)) == date(2025, 1, 5)


def test_group_a_b_date_from_pads_int_window_by_calendar_ratio():
    from services.inception_value_before_change import (
        VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS, _DAILY_LOOKBACK_CALENDAR_DAYS,
    )
    import math
    as_of = date(2025, 7, 29)
    result = idh.group_a_b_date_from([], {("52WH", 10)}, as_of)
    calendar_days = math.ceil(10 * _DAILY_LOOKBACK_CALENDAR_DAYS / VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS) + 30
    assert result == as_of - timedelta(days=calendar_days)


def test_group_a_b_date_from_takes_min_across_day_specs_and_extreme_pairs():
    day_specs = [("First", "52WH", ("2025-01-05", "2025-01-05"))]
    extreme_pairs = {("ATH", 400)}   # a large int window pads well before Jan 5
    result = idh.group_a_b_date_from(day_specs, extreme_pairs, date(2025, 7, 29))
    assert result < date(2025, 1, 5)


def test_resolve_group_a_b_day_value_on_date_fetches_range_rows_when_not_supplied():
    def fake_range_rows(date_from, date_to, progress_cb=None):
        assert date_from == date(2025, 6, 20)   # explicit window date used directly, no padding
        return {"days": [
            {"trade_date": "2025-06-20", "stocks": [
                {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"52WH": 400}},
            ]},
        ]}

    specs = [("First", "52WH", ("2025-06-20", "2025-06-20"))]
    with patch("services.inception_compute_service.range_rows", side_effect=fake_range_rows):
        result = idh.resolve_group_a_b_day(specs, date(2025, 7, 29))

    assert result == {("52WH", ("2025-06-20", "2025-06-20")): {"ABB_I": {"First": 400}}}


def test_resolve_group_a_b_day_value_days_ago_uses_global_trading_day_index():
    """A caller-supplied range_response (the shared-fetch convention) means
    range_rows is never called, and int windows count back through the
    GLOBAL sorted trading-day list, not a per-symbol calendar."""
    range_response = {"days": [
        {"trade_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "stocks": [
            {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"52WH": i}},
        ]}
        for i in range(20)
    ]}
    as_of = date(2025, 1, 20)   # index 19 of 20 daily entries
    specs = [("First", "52WH", 5)]   # VALUE_DAYS_AGO([52WH], 4) -> window=5
    with patch("services.inception_compute_service.range_rows") as mock_range_rows:
        result = idh.resolve_group_a_b_day(specs, as_of, range_response=range_response)

    mock_range_rows.assert_not_called()
    # target_idx = as_of_idx - window + 1 = 19 - 5 + 1 = 15
    assert result[("52WH", 5)]["ABB_I"]["First"] == 15


def test_resolve_group_a_b_day_no_specs_is_noop():
    assert idh.resolve_group_a_b_day([], date(2025, 7, 29)) == {}


def test_resolve_group_a_b_extreme_int_window_daily_list():
    range_response = {"days": [
        {"trade_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "stocks": [
            {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"52WH": i * 10}},
        ]}
        for i in range(20)
    ]}
    as_of = date(2025, 1, 20)   # index 19
    with patch("services.inception_compute_service.range_rows") as mock_range_rows:
        result = idh.resolve_group_a_b_extreme({("52WH", 3)}, as_of, range_response=range_response)

    mock_range_rows.assert_not_called()
    # last 3 sorted dates ending at index 19 -> indices 17,18,19 -> 170,180,190
    assert [v for _, v in result[("52WH", 3)]["ABB_I"]["daily"]] == [170, 180, 190]


def test_resolve_group_a_b_extreme_date_range_window():
    range_response = {"days": [
        {"trade_date": (date(2025, 1, 1) + timedelta(days=i)).isoformat(), "stocks": [
            {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"52WH": i * 10}},
        ]}
        for i in range(20)
    ]}
    window = ("2025-01-05", "2025-01-06")
    with patch("services.inception_compute_service.range_rows") as mock_range_rows:
        result = idh.resolve_group_a_b_extreme({("52WH", window)}, date(2025, 1, 20), range_response=range_response)

    mock_range_rows.assert_not_called()
    assert [v for _, v in result[("52WH", window)]["ABB_I"]["daily"]] == [40, 50]


def test_resolve_group_a_b_extreme_no_pairs_is_noop():
    assert idh.resolve_group_a_b_extreme(set(), date(2025, 7, 29)) == {}


def test_mixed_kind_extreme_resolves_end_to_end_via_evaluate_compiled():
    """The concrete regression for issue #45's mixed-kind case: VALUE_AT_
    MAX_DAYS([CLOSE], [CWTO], 3) — a raw value column driven by a Formula
    Builder column. raw_extreme_specs/build_extreme alone can't resolve
    this (see test_raw_extreme_specs_excludes_when_driver_is_derived) —
    build_extreme_for_pairs (raw side) + resolve_formula_builder_extreme
    (Formula Builder side), merged via merge_into, must together produce a
    day_history services.strategy_engine.evaluate can actually use."""
    from services import strategy_engine

    bars = _bars([100, 105, 110, 90])   # closes; CWTO mocked below

    def fake_compute_for_bars(symbol, bar_slice):
        return {"CWTO": len(bar_slice) * 10}

    day_history = {}
    idh.merge_into(day_history, idh.build_extreme_for_pairs({("CLOSE", 3)}, "ABB", bars))
    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        idh.merge_into(day_history, idh.resolve_formula_builder_extreme({("CWTO", 3)}, "ABB", bars))

    tokens = [tok_extreme_days("VALUE_AT_MAX_DAYS", "CLOSE", "CWTO", 3)]
    result = strategy_engine.evaluate(
        tokens, {"Symbol": "ABB"}, [{"Symbol": "ABB"}],
        day_history=day_history, symbol_col="Symbol",
    )
    # CWTO peaks (40) on the last bar (2025-01-04) -> CLOSE on that same
    # date is 90.
    assert result == 90
