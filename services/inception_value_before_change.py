"""Resolves VALUE_BEFORE_CHANGE(column, months_back) for Inception's HMV/
View by Date grids — "the value this column had immediately before its
CURRENT value last changed." Walks back one calendar month at a time (up
to months_back months) from the as-of-date, comparing each prior month's
own value of the column against the as-of-date's own value, and returns
the first one that's actually different (None if nothing differs within
months_back months, or there isn't that much synced history yet).

A fundamentally different kind of lookup than services.inception_day_history
(VALUE_DAYS_AGO/_DAYS-family, raw OHLCV fields only, resolved by slicing an
already-fetched bar series) — this one recomputes the column's OWN value as
of each candidate month-end, since neither Group A/B nor Formula Builder
values are stored per-historical-bar the way raw OHLCV is. Two resolution
paths, split by column kind:

  - Formula Builder codes (services.formula_engine.FORMULA_CODES, e.g. MT,
    MB, DT, DB): resolve_formula_builder() re-slices a symbol's own already-
    fetched bars (services.inception_bars_store.bars_for_symbol — no extra
    DB query) at each candidate month-end and calls services.
    inception_formula_builder_columns.compute_for_bars on that slice.
    Called once per symbol, reusing the SAME bars screens.inception_hmv/
    inception_view_by_date's workers already fetch for the Formula Builder
    merge.

  - Everything else (Group A/B, e.g. 52WH, ATH, or a raw field): resolve_
    group_a_b() uses services.inception_compute_service.range_rows ONCE for
    the whole instrument universe across the full requested date span,
    rather than recomputing Group A/B one candidate month at a time per
    symbol — that function's own docstring notes a wider date range costs
    nothing beyond the walk its own current-day computation already pays
    for, so this is one extra full-universe pass total, not months_back of
    them.

Both produce the same {(col_name, (VALUE_BEFORE_CHANGE_TAG, months_back)):
{symbol: {"First": value}}} shape services.strategy_engine.evaluate_compiled
expects from day_history — see VALUE_BEFORE_CHANGE_TAG's own docstring for
the tagged-window convention.
"""
from datetime import date, timedelta

from services.formula_engine import FORMULA_CODES
from services.strategy_engine import VALUE_BEFORE_CHANGE_TAG, get_compiled


def specs_for_strategies(strategies: list) -> list:
    """[(col_name, months_back), ...], deduped — every VALUE_BEFORE_CHANGE
    reference across *strategies*' own columns' formulas. *strategies* is
    every saved strategy, active or not — a strategy switched on later in
    the same session (via the picker), without a fresh Load, still
    resolves correctly as long as it was already known when this ran, same
    reasoning as services.inception_day_history.raw_day_specs."""
    seen: set = set()
    out = []
    for strat in strategies:
        for col in strat.get("columns", []):
            compiled = get_compiled(col.get("formula", []))
            if compiled is None:
                continue
            for _, _agg_key, col_name, window in compiled.day_specs:
                if isinstance(window, tuple) and len(window) == 2 and window[0] == VALUE_BEFORE_CHANGE_TAG:
                    key = (col_name, window[1])
                    if key not in seen:
                        seen.add(key)
                        out.append(key)
    return out


def _month_first(d: date) -> date:
    return d.replace(day=1)


def _months_before(d: date, months: int) -> date:
    """First-of-month, *months* calendar months before *d* (also first-of-
    month) — day-of-month arithmetic (28 vs 30 vs 31) is irrelevant here
    since only the month boundary matters; the actual trading day used is
    resolved separately, against real synced dates."""
    total = d.year * 12 + (d.month - 1) - months
    year, month0 = divmod(total, 12)
    return date(year, month0 + 1, 1)


def _month_end(month_first: date) -> date:
    """Last CALENDAR day of month_first's own month (not necessarily a
    trading day — see _latest_on_or_before for resolving that)."""
    next_month = _months_before(month_first, -1)
    return next_month - timedelta(days=1)


def _latest_on_or_before(sorted_dates: list, target: date):
    """*sorted_dates* ascending; the latest one <= target, or None. A plain
    linear scan is fine here — sorted_dates is at most a few hundred
    trading days (one Load's own date span), and this only runs at all for
    a formula that actually uses VALUE_BEFORE_CHANGE."""
    result = None
    for d in sorted_dates:
        if d <= target:
            result = d
        else:
            break
    return result


def _earliest_date_from(as_of_date: date, months_back: int) -> date:
    """A safe date_from for range_rows covering every candidate month-end
    this walk could possibly need, plus one extra month of padding so the
    OLDEST candidate month still has a full month of bars behind it (Group
    A/B needs history before a date to compute that date's own value, not
    just a bar on that exact date)."""
    return _months_before(_month_first(as_of_date), months_back + 1)


# ── Formula Builder codes ───────────────────────────────────────────────────

def resolve_formula_builder(specs: list, symbol: str, bars: list) -> dict:
    """*specs*: [(col_name, months_back), ...] already filtered to Formula
    Builder codes only (see specs_for_strategies + FORMULA_CODES). *bars*:
    this symbol's own ascending-by-trade_date bar history, already fetched
    up to the as-of-date (services.inception_bars_store.bars_for_symbol's
    shape) — reused as-is, no extra query."""
    if not specs or not bars:
        return {}
    from services import inception_formula_builder_columns

    bar_dates = [b["trade_date"] for b in bars]
    as_of_date = bar_dates[-1]
    out: dict = {}
    for col_name, months_back in specs:
        current = inception_formula_builder_columns.compute_for_bars(symbol, bars).get(col_name)
        found = None
        if isinstance(current, (int, float)):
            month_first = _month_first(as_of_date)
            for i in range(1, months_back + 1):
                target_end = _month_end(_months_before(month_first, i))
                candidate_date = _latest_on_or_before(bar_dates, target_end)
                if candidate_date is None:
                    break
                idx = bar_dates.index(candidate_date)
                value = inception_formula_builder_columns.compute_for_bars(symbol, bars[:idx + 1]).get(col_name)
                if isinstance(value, (int, float)) and value != current:
                    found = value
                    break
        out[(col_name, (VALUE_BEFORE_CHANGE_TAG, months_back))] = {symbol: {"First": found}}
    return out


# ── Group A/B (and raw) codes ────────────────────────────────────────────────

def resolve_group_a_b(specs: list, as_of_date: date, progress_cb=None) -> dict:
    """*specs*: [(col_name, months_back), ...] already filtered to
    NON-Formula-Builder codes (Group A/B or raw). One services.
    inception_compute_service.range_rows call covers every symbol and every
    candidate month-end in a single full-universe pass — see this module's
    own docstring for why that's cheap relative to walking month-by-month
    per symbol."""
    if not specs:
        return {}
    from services import inception_compute_service

    max_months = max(months for _, months in specs)
    date_from = _earliest_date_from(as_of_date, max_months)
    range_response = inception_compute_service.range_rows(date_from, as_of_date, progress_cb=progress_cb)

    by_date: dict = {}
    for day in range_response.get("days", []):
        trade_date = date.fromisoformat(day["trade_date"])
        by_date[trade_date] = {s["symbol"]: s.get("metrics", {}) for s in day.get("stocks", [])}
    sorted_dates = sorted(by_date)

    out: dict = {}
    current_by_symbol = by_date.get(as_of_date, {})
    for col_name, months_back in specs:
        entries: dict = {}
        month_first = _month_first(as_of_date)
        for symbol, metrics in current_by_symbol.items():
            current = metrics.get(col_name)
            if not isinstance(current, (int, float)):
                continue
            found = None
            for i in range(1, months_back + 1):
                target_end = _month_end(_months_before(month_first, i))
                candidate_date = _latest_on_or_before(sorted_dates, target_end)
                if candidate_date is None:
                    break
                value = by_date[candidate_date].get(symbol, {}).get(col_name)
                if isinstance(value, (int, float)) and value != current:
                    found = value
                    break
            entries[symbol] = {"First": found}
        out[(col_name, (VALUE_BEFORE_CHANGE_TAG, months_back))] = entries
    return out
