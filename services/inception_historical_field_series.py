"""
Historical trend series for one Inception field/code (Day/Week/Month Top-
Bottom, Camarilla pivots, or raw OHLCV) — the EMV EOD Report's core "DIVISLAB
Day Top for 20 days" primitive (resources/report/EMV_EOD_Report_
Requirements...). Neither services.inception_formula_builder_columns.
compute_for_bars nor services.formula_engine compute a TREND of a derived
field on their own — both only ever answer "what is this field as of the
LAST bar given" (a single as-of-date value; see compute_for_bars' own
docstring). This module gets a trend by re-slicing one symbol's own bar
history to end at each historical date in turn and calling compute_for_bars
once per date — cheap enough for a report's N-period window (tens to low
hundreds of dates), not something to reach for on a live-ticking screen.
"""

from datetime import date, timedelta

from services import inception_bars_store
from services.inception_formula_builder_columns import compute_for_bars

_RAW_FIELDS = {
    "OPEN": "open", "HIGH": "high", "LOW": "low",
    "CLOSE": "close", "VOL": "volume", "OPENINT": "open_interest",
}

# Generous warmup before the requested window's start so period-lookback
# codes (MT/MB look back ~2 months, WT/WB ~3 weeks) have enough prior bars
# to compute correctly at the FIRST requested date, not just the last.
_WARMUP_DAYS = 150


def available_fields() -> list:
    """Every field code this module can build a trend for: the raw OHLCV
    fields plus every services.formula_engine.FORMULA_CODES code (Day/Week/
    Month Top-Bottom, Camarilla pivots, pivot points, ...)."""
    from services import formula_engine
    return list(_RAW_FIELDS.keys()) + list(formula_engine.FORMULA_CODES)


def historical_field_series(symbol: str, field: str, date_from: date, date_to: date) -> list:
    """Returns one {"date", "value", "close"} entry per trading day with a
    synced bar in [date_from, date_to] (chronological) — "value" is *field*
    resolved as of that date; "close" is that date's own Close (for the
    report's "selected level vs Close" comparison chart). A date this
    symbol has no bar for is simply absent (never a None-filled gap row) —
    every spec's "missing values must be visibly distinguished" concern
    doesn't apply here since a genuinely missing trading day is excluded,
    not silently zero.
    """
    field = (field or "").strip().upper()
    warm_start = date_from - timedelta(days=_WARMUP_DAYS)
    bars = inception_bars_store.bars_for_symbol(symbol, warm_start, date_to)
    if not bars:
        return []

    raw_key = _RAW_FIELDS.get(field)
    series = []
    for i, bar in enumerate(bars):
        trade_date = bar["trade_date"]
        if trade_date < date_from:
            continue
        if raw_key is not None:
            value = bar.get(raw_key)
        else:
            value = compute_for_bars(symbol, bars[: i + 1]).get(field)
        series.append({"date": trade_date, "value": value, "close": bar.get("close")})
    return series


def condition_stats(series: list) -> dict:
    """Periods-above/below, current state/streak, longest streak, and
    level-change stats comparing each entry's Close against its own *value*
    — EMV spec section 3.1's "Historical condition metrics", e.g. "DIVISLAB
    has closed above Day Top for 7 of the last 20 days, currently on a
    4-day streak"."""
    above = below = 0
    current_state = None
    current_streak = 0
    longest_streak = 0
    run = 0
    run_state = None

    for entry in series:
        value, close = entry["value"], entry["close"]
        if value is None or close is None:
            run = 0
            run_state = None
            continue
        state = "above" if close >= value else "below"
        if state == "above":
            above += 1
        else:
            below += 1
        run = run + 1 if state == run_state else 1
        run_state = state
        longest_streak = max(longest_streak, run)
        current_state = state
        current_streak = run

    first_value = next((e["value"] for e in series if e["value"] is not None), None)
    last_value = next((e["value"] for e in reversed(series) if e["value"] is not None), None)
    level_change = level_change_pct = None
    if first_value is not None and last_value is not None:
        level_change = last_value - first_value
        if first_value != 0:
            level_change_pct = level_change / first_value * 100

    return {
        "periods_above": above,
        "periods_below": below,
        "current_state": current_state,
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "level_change": level_change,
        "level_change_pct": level_change_pct,
    }
