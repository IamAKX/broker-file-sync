"""Tests for services/inception_value_before_change.py — pure logic, no
Qt/DB (compute_for_bars/range_rows are mocked)."""
from datetime import date, timedelta
from unittest.mock import patch

from services import inception_value_before_change as ivbc


def tok_before_change(col, months):
    return {"type": "func", "value": "VALUE_BEFORE_CHANGE(", "col_arg": col, "days_arg": months}


def tok_before_change_auto(col):
    """The no-argument "auto" form — VALUE_BEFORE_CHANGE([col]) with no
    months_back at all; day-granularity search (see this module's docstring
    and services.inception_value_before_change's)."""
    return {"type": "func", "value": "VALUE_BEFORE_CHANGE(", "col_arg": col}


def _strategy(formula, active=True):
    return {
        "id": "s1", "name": "Test", "active": active,
        "columns": [{"name": "Test Col", "formula": formula}],
        "row_filter": [],
    }


def _bars(n, start=date(2025, 1, 1)):
    return [
        {"trade_date": start + timedelta(days=i), "open": 1, "high": 1, "low": 1,
         "close": 1, "volume": 1, "open_interest": 1}
        for i in range(n)
    ]


# ── month arithmetic ─────────────────────────────────────────────────────

def test_months_before_and_month_end():
    d = date(2026, 8, 15)
    first = ivbc._month_first(d)
    assert first == date(2026, 8, 1)
    assert ivbc._months_before(first, 1) == date(2026, 7, 1)
    assert ivbc._month_end(ivbc._months_before(first, 1)) == date(2026, 7, 31)
    assert ivbc._months_before(first, 8) == date(2025, 12, 1)
    assert ivbc._month_end(ivbc._months_before(first, 8)) == date(2025, 12, 31)


def test_earliest_date_from_has_one_month_padding():
    as_of = date(2026, 8, 15)
    result = ivbc._earliest_date_from(as_of, 6)
    # 6 months back from August is February; one extra month of padding -> January
    assert result == date(2026, 1, 1)


# ── specs_for_strategies ─────────────────────────────────────────────────

def test_specs_for_strategies_extracts_value_before_change():
    strategies = [_strategy([tok_before_change("MT", 6)])]
    assert ivbc.specs_for_strategies(strategies) == [("MT", 6)]


def test_specs_for_strategies_ignores_other_day_specs():
    formula = [{"type": "func", "value": "AVG_DAYS(", "col_arg": "CLOSE", "days_arg": 20}]
    assert ivbc.specs_for_strategies([_strategy(formula)]) == []


def test_specs_for_strategies_deduped_across_strategies():
    strategies = [
        _strategy([tok_before_change("MT", 6)]),
        _strategy([tok_before_change("MT", 6)]),
    ]
    assert ivbc.specs_for_strategies(strategies) == [("MT", 6)]


def test_specs_for_strategies_scans_inactive_too():
    strategies = [_strategy([tok_before_change("MT", 6)], active=False)]
    assert ivbc.specs_for_strategies(strategies) == [("MT", 6)]


def test_specs_for_strategies_extracts_auto_form():
    """No months_back at all -> a (col_name, None) spec, distinct from the
    explicit-months (col_name, N) shape."""
    strategies = [_strategy([tok_before_change_auto("WT")])]
    assert ivbc.specs_for_strategies(strategies) == [("WT", None)]


def test_specs_for_strategies_auto_and_explicit_both_kept():
    strategies = [
        _strategy([tok_before_change_auto("WT")]),
        _strategy([tok_before_change("MT", 6)]),
    ]
    assert ivbc.specs_for_strategies(strategies) == [("WT", None), ("MT", 6)]


# ── resolve_formula_builder ──────────────────────────────────────────────

def test_resolve_formula_builder_reported_mt_example():
    """The exact reported example: MT is 400 for both August and July, but
    was 382 in June -> VALUE_BEFORE_CHANGE([MT], 6) should return 382."""
    bars = _bars(210)   # 2025-01-01 .. 2025-07-29
    as_of = bars[-1]["trade_date"]

    def fake_compute_for_bars(symbol, bar_slice):
        if not bar_slice:
            return {}
        return {"MT": 400 if bar_slice[-1]["trade_date"] >= date(2025, 6, 15) else 382}

    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        result = ivbc.resolve_formula_builder([("MT", 6)], "ABB_I", bars)

    assert result == {("MT", ("months_before_change", 6)): {"ABB_I": {"First": 382}}}


def test_resolve_formula_builder_none_when_never_changes():
    bars = _bars(210)

    with patch("services.inception_formula_builder_columns.compute_for_bars", return_value={"MT": 400}):
        result = ivbc.resolve_formula_builder([("MT", 6)], "ABB_I", bars)

    assert result[("MT", ("months_before_change", 6))]["ABB_I"]["First"] is None


def test_resolve_formula_builder_empty_bars_is_noop():
    assert ivbc.resolve_formula_builder([("MT", 6)], "ABB_I", []) == {}


def test_resolve_formula_builder_no_specs_is_noop():
    assert ivbc.resolve_formula_builder([], "ABB_I", _bars(10)) == {}


def test_resolve_formula_builder_auto_walks_daily_not_monthly():
    """The no-months_back "auto" spec (months_back=None) should find a
    value that changed only a few TRADING days ago, walking bar by bar
    rather than sampling only month-ends."""
    bars = _bars(10)

    def fake_compute_for_bars(symbol, bar_slice):
        return {"WT": 100 if len(bar_slice) >= 8 else 50}

    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars):
        result = ivbc.resolve_formula_builder([("WT", None)], "ABB_I", bars)

    assert result == {("WT", ("daily_before_change",)): {"ABB_I": {"First": 50}}}


def test_resolve_formula_builder_auto_respects_cap():
    """Nothing differs within VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS -> None,
    even though an earlier bar (beyond the cap) really does differ."""
    bars = _bars(20)

    def fake_compute_for_bars(symbol, bar_slice):
        return {"WT": 100 if len(bar_slice) >= 3 else 50}

    with patch("services.inception_formula_builder_columns.compute_for_bars", side_effect=fake_compute_for_bars), \
         patch.object(ivbc, "VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS", 5):
        result = ivbc.resolve_formula_builder([("WT", None)], "ABB_I", bars)

    assert result[("WT", ("daily_before_change",))]["ABB_I"]["First"] is None


# ── resolve_group_a_b ─────────────────────────────────────────────────────

def test_resolve_group_a_b_reported_style_example():
    as_of = date(2025, 7, 29)

    def fake_range_rows(date_from, date_to, progress_cb=None):
        days = []
        d = date_from
        while d <= date_to:
            value = 400 if d >= date(2025, 6, 15) else 382
            days.append({"trade_date": d.isoformat(), "stocks": [
                {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"52WH": value}},
            ]})
            d += timedelta(days=1)
        return {"days": days}

    with patch("services.inception_compute_service.range_rows", side_effect=fake_range_rows):
        result = ivbc.resolve_group_a_b([("52WH", 6)], as_of)

    assert result == {("52WH", ("months_before_change", 6)): {"ABB_I": {"First": 382}}}


def test_resolve_group_a_b_no_specs_is_noop():
    assert ivbc.resolve_group_a_b([], date(2025, 7, 29)) == {}


def test_resolve_group_a_b_missing_current_day_skips_symbol():
    with patch("services.inception_compute_service.range_rows", return_value={"days": []}):
        result = ivbc.resolve_group_a_b([("52WH", 6)], date(2025, 7, 29))
    assert result == {("52WH", ("months_before_change", 6)): {}}


def test_resolve_group_a_b_auto_walks_daily_not_monthly():
    """The no-months_back "auto" spec should find a value that changed only
    a few days ago (2025-01-14, six days before as-of), not just whatever
    the most recent month-end happens to be."""
    as_of = date(2025, 1, 20)

    def fake_range_rows(date_from, date_to, progress_cb=None):
        days = []
        d = date_from
        while d <= date_to:
            value = 100 if d >= date(2025, 1, 15) else 50
            days.append({"trade_date": d.isoformat(), "stocks": [
                {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"WT": value}},
            ]})
            d += timedelta(days=1)
        return {"days": days}

    with patch("services.inception_compute_service.range_rows", side_effect=fake_range_rows):
        result = ivbc.resolve_group_a_b([("WT", None)], as_of)

    assert result == {("WT", ("daily_before_change",)): {"ABB_I": {"First": 50}}}


def test_resolve_group_a_b_auto_respects_cap():
    """The real change (2025-01-10, ten days back) is outside a 3-day cap
    -> None, not 50."""
    as_of = date(2025, 1, 20)

    def fake_range_rows(date_from, date_to, progress_cb=None):
        days = []
        d = date_from
        while d <= date_to:
            value = 100 if d >= date(2025, 1, 10) else 50
            days.append({"trade_date": d.isoformat(), "stocks": [
                {"symbol": "ABB_I", "display_name": "ABB_I", "metrics": {"WT": value}},
            ]})
            d += timedelta(days=1)
        return {"days": days}

    with patch("services.inception_compute_service.range_rows", side_effect=fake_range_rows), \
         patch.object(ivbc, "VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS", 3), \
         patch.object(ivbc, "_DAILY_LOOKBACK_CALENDAR_DAYS", 30):
        result = ivbc.resolve_group_a_b([("WT", None)], as_of)

    assert result[("WT", ("daily_before_change",))]["ABB_I"]["First"] is None


def test_resolve_group_a_b_auto_and_explicit_specs_combined_date_from():
    """Mixing an "auto" spec with an explicit-months spec in one call should
    still fetch a wide-enough date_from to cover whichever need is larger,
    without crashing on the None entry."""
    as_of = date(2025, 7, 29)

    def fake_range_rows(date_from, date_to, progress_cb=None):
        days = []
        d = date_from
        while d <= date_to:
            days.append({"trade_date": d.isoformat(), "stocks": [
                {"symbol": "ABB_I", "display_name": "ABB_I",
                 "metrics": {"WT": 1, "52WH": 400 if d >= date(2025, 6, 15) else 382}},
            ]})
            d += timedelta(days=1)
        return {"days": days}

    with patch("services.inception_compute_service.range_rows", side_effect=fake_range_rows):
        result = ivbc.resolve_group_a_b([("WT", None), ("52WH", 6)], as_of)

    assert result[("WT", ("daily_before_change",))]["ABB_I"]["First"] is None  # WT never changes
    assert result[("52WH", ("months_before_change", 6))]["ABB_I"]["First"] == 382
