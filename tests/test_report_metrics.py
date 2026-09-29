from services import report_metrics as rm


def test_directional_yield_buy_profit():
    assert rm.directional_yield(100, 110, "BUY") == 10.0


def test_directional_yield_buy_loss():
    assert round(rm.directional_yield(100, 95, "BUY"), 4) == -5.0


def test_directional_yield_sell_profit_on_price_drop():
    assert rm.directional_yield(100, 95, "SELL") == 5.0


def test_directional_yield_sell_loss_on_price_rise():
    assert rm.directional_yield(100, 110, "SELL") == -10.0


def test_directional_yield_none_when_entry_zero_or_missing():
    assert rm.directional_yield(0, 100, "BUY") is None
    assert rm.directional_yield(None, 100, "BUY") is None
    assert rm.directional_yield(100, None, "BUY") is None


def test_blended_yield_matches_spec_example():
    # ALKEM SELL +1.00, TATASTEEL BUY +3.00, DELIVERY BUY -1.00 -> average +1.00
    assert rm.blended_yield([1.0, 3.0, -1.0]) == 1.0


def test_blended_yield_ignores_none():
    assert rm.blended_yield([2.0, None, 4.0]) == 3.0


def test_blended_yield_empty_is_none():
    assert rm.blended_yield([]) is None
    assert rm.blended_yield([None]) is None


def test_win_rate():
    assert rm.win_rate([1.0, -1.0, 2.0, -3.0]) == 50.0


def test_sharpe_ratio_positive_for_consistent_gains():
    assert rm.sharpe_ratio([1.0, 1.0, 1.0]) is None  # zero stdev -> undefined
    assert rm.sharpe_ratio([1.0, 2.0, 3.0]) > 0


def test_sharpe_ratio_requires_at_least_two_points():
    assert rm.sharpe_ratio([1.0]) is None
    assert rm.sharpe_ratio([]) is None


def test_sortino_ratio_ignores_upside_deviation():
    # All gains, no downside deviation -> None (undefined, not zero)
    assert rm.sortino_ratio([1.0, 2.0, 3.0]) is None


def test_sortino_ratio_penalizes_losses():
    assert rm.sortino_ratio([2.0, -1.0, 3.0]) is not None


def test_max_drawdown_from_cumulative_curve():
    # peak 10 -> trough 4 -> drawdown 6
    assert rm.max_drawdown([0, 5, 10, 6, 4, 8]) == 6


def test_max_drawdown_empty():
    assert rm.max_drawdown([]) is None


def test_calmar_ratio():
    # returns +5, -2, +3 -> cumulative [5, 3, 6], drawdown = 5-3 = 2, total = 6
    assert rm.calmar_ratio([5.0, -2.0, 3.0]) == 3.0


def test_alpha_vs_benchmark():
    assert rm.alpha([5.0, 5.0], [2.0, 2.0]) == 3.0


def test_investment_simulation_matches_spec_example():
    result = rm.investment_simulation(5000, 12.0)
    assert round(result["ending"], 2) == 5600.0
    assert round(result["profit"], 2) == 600.0


def test_investment_simulation_none_return():
    result = rm.investment_simulation(5000, None)
    assert result["ending"] is None


def test_investment_equity_curve_compounds():
    curve = rm.investment_equity_curve(1000, [10.0, 10.0])
    assert curve == [1100.0, 1210.0]


def test_investment_equity_curve_carries_forward_on_none():
    curve = rm.investment_equity_curve(1000, [10.0, None, 10.0])
    assert curve == [1100.0, 1100.0, 1210.0]


def test_bucket_key_daily_weekly_monthly_quarterly():
    assert rm.bucket_key("2026-03-05", rm.TIMEFRAME_DAILY) == "2026-03-05"
    assert rm.bucket_key("2026-03-05", rm.TIMEFRAME_MONTHLY) == "2026-3"[:4] + "-03"
    assert rm.bucket_key("2026-01-15", rm.TIMEFRAME_QUARTERLY) == "2026-Q1"
    assert rm.bucket_key("2026-07-01", rm.TIMEFRAME_QUARTERLY) == "2026-Q3"


def test_bucket_range_covers_full_span_inclusive():
    keys = rm.bucket_range("2026-01-01", "2026-01-03", rm.TIMEFRAME_DAILY)
    assert keys == ["2026-01-01", "2026-01-02", "2026-01-03"]


def test_bucketed_series_averages_within_bucket_and_none_elsewhere():
    items = [
        {"date": "2026-01-01", "yield": 2.0},
        {"date": "2026-01-01", "yield": 4.0},
        {"date": "2026-01-03", "yield": 1.0},
    ]
    keys = rm.bucket_range("2026-01-01", "2026-01-03", rm.TIMEFRAME_DAILY)
    series = rm.bucketed_series(items, "date", "yield", keys, rm.TIMEFRAME_DAILY)
    assert series == [3.0, None, 1.0]


def test_cumulative_carries_forward_on_none():
    assert rm.cumulative([1.0, None, 2.0]) == [1.0, 1.0, 3.0]


def test_resolve_preset_range_daily_is_today_only():
    from datetime import date
    today = date(2026, 3, 10)
    assert rm.resolve_preset_range(rm.TIMEFRAME_DAILY, today=today) == (today, today)


def test_resolve_preset_range_weekly_and_monthly_and_quarterly():
    from datetime import date, timedelta
    today = date(2026, 3, 10)
    assert rm.resolve_preset_range(rm.TIMEFRAME_WEEKLY, today=today) == (today - timedelta(days=6), today)
    assert rm.resolve_preset_range(rm.TIMEFRAME_MONTHLY, today=today) == (today - timedelta(days=29), today)
    assert rm.resolve_preset_range(rm.TIMEFRAME_QUARTERLY, today=today) == (today - timedelta(days=89), today)


def test_resolve_preset_range_custom_uses_given_dates_and_swaps_if_reversed():
    from datetime import date
    a, b = date(2026, 1, 1), date(2026, 1, 31)
    assert rm.resolve_preset_range(rm.TIMEFRAME_CUSTOM, custom_from=a, custom_to=b) == (a, b)
    assert rm.resolve_preset_range(rm.TIMEFRAME_CUSTOM, custom_from=b, custom_to=a) == (a, b)


def test_resolve_preset_range_custom_without_dates_falls_back_to_today():
    from datetime import date
    today = date(2026, 3, 10)
    assert rm.resolve_preset_range(rm.TIMEFRAME_CUSTOM, today=today) == (today, today)
