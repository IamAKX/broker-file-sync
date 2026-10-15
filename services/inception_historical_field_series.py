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


def _canonical_field(field: str) -> str:
    """*field* matched case-insensitively against the known codes (codes like
    "Max Pain"/"OR.High" are mixed-case, "DT"/"CLOSE" upper); an unknown name
    is returned stripped, as typed, and just resolves to blank values."""
    field = (field or "").strip()
    lookup = {c.upper(): c for c in available_fields(include_strategy_columns=False)}
    return lookup.get(field.upper(), field)


def _derived_codes() -> set:
    from services import inception_columns
    return set(inception_columns.GROUP_A) | set(inception_columns.GROUP_B)


def available_fields(include_strategy_columns: bool = True) -> list:
    """Every field code this module can build a trend for: the raw OHLCV
    fields, every services.formula_engine.FORMULA_CODES code (Day/Week/Month
    Top-Bottom, Camarilla pivots, pivot points, ...), the synced Reliable
    Software / NiftyInvest / Market Profile columns (PATP, CWTO, Max Pain,
    VAH/POC/VAL, OR.High/Low, Avg Rate, ...), Inception's own Group A/B
    columns (52WH, 52WL, ATH, CQO, gap codes, ...) and every configured
    Indicator Library output (RSI(14), ...) and — unless
    *include_strategy_columns* is False — every Inception strategy column
    ("RSC [RSC]", ...; see services.inception_strategy_series)."""
    from services import (
        formula_engine, inception_columns, inception_formula_builder_columns as ifbc, indicator_library,
    )
    codes = list(_RAW_FIELDS.keys()) + list(formula_engine.FORMULA_CODES)
    codes += list(ifbc._LMV_SYNCED_CODE_MAP) + ["Avg Rate"] + list(ifbc._LMV_SYNCED_NEW_FIELD_MAP)
    codes += inception_columns.all_derived_codes()
    try:
        codes += indicator_library.field_codes()
    except Exception:
        pass  # config store unreachable — the built-in columns still work
    if include_strategy_columns:
        try:
            from services import inception_strategy_series
            codes += inception_strategy_series.strategy_field_codes()
        except Exception:
            pass
    return list(dict.fromkeys(codes))


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
    field = _canonical_field(field)
    from services import inception_strategy_series
    strategy_field = inception_strategy_series.resolve_field(field)
    if strategy_field is not None:
        strategy, column = strategy_field
        return inception_strategy_series.column_series(symbol, strategy, column, date_from, date_to)
    raw_key = _RAW_FIELDS.get(field)
    derived = field in _derived_codes()
    # Group A/B values (52-week high, all-time high, gap areas, ...) look back
    # a year or the symbol's whole history, so they need every bar, not just
    # the short warm-up the Formula Builder codes get.
    warm_start = None if derived else date_from - timedelta(days=_WARMUP_DAYS)
    bars = inception_bars_store.bars_for_symbol(symbol, warm_start, date_to)
    if not bars:
        return []

    derived_by_date = {}
    if derived:
        from services import inception_compute_service, inception_settings
        window_bars = [b for b in bars if b["trade_date"] >= date_from]
        derived_by_date = inception_compute_service._compute_rows_for_days(
            bars, inception_settings.load(), window_bars)

    series = []
    for i, bar in enumerate(bars):
        trade_date = bar["trade_date"]
        if trade_date < date_from:
            continue
        if raw_key is not None:
            value = bar.get(raw_key)
        elif derived:
            value = (derived_by_date.get(trade_date) or {}).get(field)
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
