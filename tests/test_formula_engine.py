"""Tests for services.formula_engine against hand-computable synthetic data."""
import sys
import os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import formula_engine as fe


def _trading_days(start: date, count: int) -> list:
    days = []
    d = start
    while len(days) < count:
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
        d += timedelta(days=1)
    return days


def _build_history(start: date, count: int):
    """Deterministic synthetic series, indexed 0..count-1 by trading day.
    High=100+i, Low=90+i, Close=95+i, Open=94+i, pdh/pdl/PClose mirror the
    previous trading day's High/Low/Close so every value is derivable from i.
    """
    days = _trading_days(start, count)
    rows = {}
    for i, d in enumerate(days):
        rows[d] = {
            "Open": 94 + i,
            "High": 100 + i,
            "Low": 90 + i,
            "Close": 95 + i,
            "pdh": 100 + i - 1 if i > 0 else 100 + i,
            "pdl": 90 + i - 1 if i > 0 else 90 + i,
            "PClose": 95 + i - 1 if i > 0 else 95 + i,
            "AvgRate": 95 + i,
            "Quantity": 1000,
            "DiffPcnt": 1.0,
        }
    return days, fe.StockHistory(rows)


def test_current_month_high_low_to_date():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[40]  # some day well into the series
    i = 40
    month_start = target.replace(day=1)
    month_trading_indices = [j for j, d in enumerate(days) if d >= month_start and d <= target]
    expected_cmh = 100 + max(month_trading_indices)
    expected_cml = 90 + min(month_trading_indices)
    out = fe.compute_for_symbol(hist, target)
    assert out["CMH"] == expected_cmh
    assert out["CML"] == expected_cml


def test_current_week_high_low_and_open():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[40]
    week_start = target - timedelta(days=target.weekday())
    week_indices = [j for j, d in enumerate(days) if week_start <= d <= target]
    out = fe.compute_for_symbol(hist, target)
    assert out["CWH"] == 100 + max(week_indices)
    assert out["CWL"] == 90 + min(week_indices)
    assert out["CWO"] == 94 + min(week_indices)


def test_previous_week_high_low_close():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[40]
    prev_week_start = (target - timedelta(days=target.weekday())) - timedelta(days=7)
    prev_week_end = prev_week_start + timedelta(days=6)
    prev_indices = [j for j, d in enumerate(days) if prev_week_start <= d <= prev_week_end]
    out = fe.compute_for_symbol(hist, target)
    assert out["PWH"] == 100 + max(prev_indices)
    assert out["PWL"] == 90 + min(prev_indices)
    assert out["PWC"] == 95 + max(prev_indices)  # close of last trading day of that week


def test_previous_month_high_low_close():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[60]  # far enough in to have a full previous month behind it
    this_month_start = target.replace(day=1)
    prev_month_end = this_month_start - timedelta(days=1)
    prev_month_start = prev_month_end.replace(day=1)
    prev_indices = [j for j, d in enumerate(days) if prev_month_start <= d <= prev_month_end]
    assert prev_indices, "test setup must span a full previous month"
    out = fe.compute_for_symbol(hist, target)
    assert out["PMH"] == 100 + max(prev_indices)
    assert out["PML"] == 90 + min(prev_indices)
    assert out["PMC"] == 95 + max(prev_indices)


def test_daily_camarilla_pivots_pure_algebra():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[40]
    i = 40
    pdh, pdl, pclose = 100 + i - 1, 90 + i - 1, 95 + i - 1
    rng = pdh - pdl
    out = fe.compute_for_symbol(hist, target)
    assert out["DR3"] == pytest_approx(pclose + rng * 1.1 / 4)
    assert out["DR4"] == pytest_approx(pclose + rng * 1.1 / 2)
    assert out["DR6"] == pytest_approx((pdh / pdl) * pclose)
    assert out["DS3"] == pytest_approx(pclose - rng * 1.1 / 4)
    assert out["DS4"] == pytest_approx(pclose - rng * 1.1 / 2)
    assert out["DS6"] == pytest_approx(pclose - (out["DR6"] - pclose))
    assert out["DAY PIVOT"] == pytest_approx((pdh + pdl + pclose) / 3)


def pytest_approx(x):
    import pytest
    return pytest.approx(x)


def test_day_turnover_and_previous_day_turnover():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[40]
    i = 40
    expected_day_to = (1000 * (95 + i)) / 10_000_000 * (abs(1.0) / 100)
    expected_pdto = (1000 * (95 + i - 1)) / 10_000_000 * (abs(1.0) / 100)
    out = fe.compute_for_symbol(hist, target)
    assert out["DAY TO"] == pytest_approx(expected_day_to)
    assert out["PDTO"] == pytest_approx(expected_pdto)


def test_week_percentage_change():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[40]
    out = fe.compute_for_symbol(hist, target)
    close_t = 95 + 40
    pwc = out["PWC"]
    expected = (close_t - pwc) / pwc * 100
    assert out["WEEK % CHANGE"] == pytest_approx(expected)


def test_week_top_bottom_uses_last_3_completed_weeks():
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = days[60]
    out = fe.compute_for_symbol(hist, target)
    week_start = target - timedelta(days=target.weekday())
    closes = []
    for n in (1, 2, 3):
        wb_start = week_start - timedelta(days=7 * n)
        wb_end = wb_start + timedelta(days=6)
        idxs = [j for j, d in enumerate(days) if wb_start <= d <= wb_end]
        if idxs:
            closes.append(95 + max(idxs))
    assert out["WT"] == max(closes)
    assert out["WB"] == min(closes)


def test_expiry_week_holds_last_completed_week_during_this_months_expiry():
    # June 2026's expiry week (last Tuesday = 30-Jun) is 29-Jun..05-Jul.
    # July 2026's expiry week (last Tuesday = 28-Jul) is 27-Jul..02-Aug.
    # While July's own expiry week is in progress, EWH/EWL must still hold
    # June's (already-completed) week — never a to-date partial window.
    days, hist = _build_history(date(2026, 6, 1), 70)
    june_idxs = [j for j, d in enumerate(days) if date(2026, 6, 29) <= d <= date(2026, 7, 5)]
    assert june_idxs, "test setup must cover June's expiry week"
    expected_high = 100 + max(june_idxs)
    expected_low = 90 + min(june_idxs)

    for target in (date(2026, 7, 19), date(2026, 7, 27), date(2026, 8, 2)):
        out = fe.compute_for_symbol(hist, target)
        assert out["EWH"] == expected_high, target
        assert out["EWL"] == expected_low, target


def test_expiry_week_switches_over_once_this_months_fully_ends():
    days, hist = _build_history(date(2026, 6, 1), 70)
    july_idxs = [j for j, d in enumerate(days) if date(2026, 7, 27) <= d <= date(2026, 8, 2)]
    assert july_idxs, "test setup must cover July's expiry week"
    expected_high = 100 + max(july_idxs)
    expected_low = 90 + min(july_idxs)

    # The day after July's expiry week ends (03-Aug) and later — EWH/EWL
    # must now reflect July's completed week, not June's.
    for target in (date(2026, 8, 3), date(2026, 8, 10)):
        out = fe.compute_for_symbol(hist, target)
        assert out["EWH"] == expected_high, target
        assert out["EWL"] == expected_low, target


def test_expiry_week_falls_further_back_when_previous_month_also_incomplete():
    # 03-Jul falls inside June's own spillover expiry week (29-Jun..05-Jul),
    # so June's isn't "completed" relative to 03-Jul either — must fall back
    # to May's expiry week (last Tuesday 26-May -> 25-May..31-May).
    start, end = fe._expiry_week_window(date(2026, 7, 3))
    assert (start, end) == (date(2026, 5, 25), date(2026, 5, 31))


def test_rollover_week_is_the_week_right_after_expiry_week():
    # For 19-Jul, EWH/EWL hold June's expiry week (29-Jun..05-Jul), so the
    # rollover week must be the following calendar week: 06-Jul..12-Jul.
    ew_start, ew_end = fe._expiry_week_window(date(2026, 7, 19))
    rw_start, rw_end = fe._rollover_window(date(2026, 7, 19))
    assert rw_start == ew_end + timedelta(days=1)
    assert rw_end == ew_end + timedelta(days=7)
    assert (rw_start, rw_end) == (date(2026, 7, 6), date(2026, 7, 12))


def test_rollover_week_value_matches_high_low_in_that_week():
    days, hist = _build_history(date(2026, 6, 1), 70)
    idxs = [j for j, d in enumerate(days) if date(2026, 7, 6) <= d <= date(2026, 7, 12)]
    assert idxs, "test setup must cover the rollover week"
    out = fe.compute_for_symbol(hist, date(2026, 7, 19))
    assert out["RWH"] == 100 + max(idxs)
    assert out["RWL"] == 90 + min(idxs)


def test_rollover_week_is_to_date_while_in_progress():
    # Mid-rollover-week target must only include days up to and including
    # target — unlike expiry week, rollover week does NOT hold until complete.
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = date(2026, 7, 8)
    idxs = [j for j, d in enumerate(days) if date(2026, 7, 6) <= d <= target]
    assert idxs
    out = fe.compute_for_symbol(hist, target)
    assert out["RWH"] == 100 + max(idxs)
    assert out["RWL"] == 90 + min(idxs)


def test_rollover_week_blank_when_no_data_in_that_window():
    # Because expiry week is always "fully completed" relative to target (see
    # _expiry_week_window), its rollover week has necessarily already begun
    # by the time target is reached — RWH/RWL only comes back blank when
    # there's genuinely no uploaded data in that window, not a "too early"
    # case. Build a history with a gap covering the rollover week itself.
    days, hist = _build_history(date(2026, 6, 1), 70)
    target = date(2026, 7, 19)
    rw_start, rw_end = fe._rollover_window(target)
    assert rw_start <= target  # rollover week has always already begun
    gapped_rows = {d: v for d, v in hist._rows.items() if not (rw_start <= d <= rw_end)}
    gapped_hist = fe.StockHistory(gapped_rows)
    out = fe.compute_for_symbol(gapped_hist, target)
    assert out["RWH"] is None
    assert out["RWL"] is None


def test_missing_data_returns_none_not_crash():
    hist = fe.StockHistory({})
    out = fe.compute_for_symbol(hist, date(2026, 6, 15))
    assert all(v is None for v in out.values())
    assert set(out.keys()) == set(fe.FORMULA_CODES)


def test_compute_all_stock_universe_comes_from_latest_date_not_target():
    # target is always real "today", which may differ from the most recent
    # date with data — the stock universe must reflect whichever date is
    # latest in raw_by_date, not target itself (target only drives the
    # window math inside compute_for_symbol).
    d1, d2 = date(2026, 6, 1), date(2026, 6, 2)
    raw_by_date = {
        d1: {"AAA": {"High": 10, "Low": 5, "Close": 8, "Open": 6}},
        d2: {"AAA": {"High": 11, "Low": 6, "Close": 9, "Open": 7},
             "BBB": {"High": 20, "Low": 15, "Close": 18, "Open": 16}},
    }
    results = fe.compute_all(raw_by_date, d1)
    assert set(results.keys()) == {"AAA", "BBB"}


def test_compute_all_excludes_symbols_not_on_latest_date():
    d1, d2 = date(2026, 6, 1), date(2026, 6, 2)
    raw_by_date = {
        d1: {"AAA": {"High": 10, "Low": 5, "Close": 8, "Open": 6},
             "ZZZ": {"High": 1, "Low": 1, "Close": 1, "Open": 1}},
        d2: {"AAA": {"High": 11, "Low": 6, "Close": 9, "Open": 7}},
    }
    results = fe.compute_all(raw_by_date, d2)
    assert set(results.keys()) == {"AAA"}


def test_all_56_codes_present_in_output():
    days, hist = _build_history(date(2026, 6, 1), 70)
    out = fe.compute_for_symbol(hist, days[50])
    from services.formula_tokens import BUILTIN_CODES
    assert set(out.keys()) == set(BUILTIN_CODES)
