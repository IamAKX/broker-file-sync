"""Resolves VALUE_BEFORE_CHANGE(column[, months_back]) for Inception's HMV/
View by Date grids — "the value this column had immediately before its
CURRENT value last changed." Two resolution modes, chosen by whether
months_back was given:

  - months_back given: walks back one calendar month at a time (up to
    months_back months) from the as-of-date, comparing each prior month's
    own value of the column against the as-of-date's own value, and
    returns the first one that's actually different (None if nothing
    differs within months_back months, or there isn't that much synced
    history yet).

  - months_back omitted ("auto"): for a field with no fixed change
    cadence (weekly, irregular, ...) naming a month count is the wrong
    question. Instead walks back TRADING DAY by trading day (not
    month-ends) — up to VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS days — and
    returns the first day whose value actually differs. Same None
    semantics if nothing differs within that span.

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

Both produce the same {(col_name, window): {symbol: {"First": value}}}
shape services.strategy_engine.evaluate_compiled expects from day_history
— window is (VALUE_BEFORE_CHANGE_TAG, months_back) for the explicit-months
form or the bare (VALUE_BEFORE_CHANGE_DAILY_TAG,) 1-tuple for the "auto"
day-granularity form — see those tags' own docstrings in services.
strategy_engine for the tagged-window convention.

VALUE_BEFORE_CHANGE_N(column, n) — a separate, related function (NOT a
third argument on VALUE_BEFORE_CHANGE itself; see services.strategy_
engine.VALUE_BEFORE_CHANGE_N_TAG's own docstring for why): "the n-th
distinct value found walking backward" rather than just the first. n=1 is
the same value the "auto" VALUE_BEFORE_CHANGE([col]) form returns; n=2 is
the value from the change before THAT one; n=3 before that; and so on.
Always day-granularity — resolve_formula_builder_n/resolve_group_a_b_n
below are this function's own analogues of resolve_formula_builder/
resolve_group_a_b's "auto" branch, just continuing past the first
difference instead of stopping there, with the SAME total
VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS cap on the whole walk (not a bigger
cap for a bigger n). n_specs_for_strategies is the VALUE_BEFORE_CHANGE_N
analogue of specs_for_strategies above.
"""
from datetime import date, timedelta

from services.formula_engine import FORMULA_CODES
from services.strategy_engine import (
    VALUE_BEFORE_CHANGE_DAILY_TAG, VALUE_BEFORE_CHANGE_N_TAG,
    VALUE_BEFORE_CHANGE_TAG, get_compiled,
)

# Cap for the "auto" (no months_back) day-granularity walk — trading days,
# not calendar days. ~1 trading year: bounds the per-lookup cost (each step
# back is a real re-resolve, not a cache hit) while comfortably covering
# "changes weekly" and every less-frequent cadence up to about a year old.
# Chosen so a column that's been constant since Inception's own history
# began still gives up in bounded time rather than walking its entire
# synced history on every single lookup.
VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS = 252

# Calendar-day span resolve_group_a_b fetches (via range_rows) to cover
# VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS trading days of history — a trading
# year is ~252 sessions out of ~365 calendar days; the extra ~35 days is
# slack for holidays/weekends plus the same "one month of padding before
# the oldest day" reasoning _earliest_date_from uses for the monthly form.
_DAILY_LOOKBACK_CALENDAR_DAYS = 400


def specs_for_strategies(strategies: list) -> list:
    """[(col_name, months_back), ...], deduped — every VALUE_BEFORE_CHANGE
    reference across *strategies*' own columns' formulas. months_back is
    None for the "auto" no-argument form (VALUE_BEFORE_CHANGE([col]) — see
    this module's docstring) or an int for the explicit
    VALUE_BEFORE_CHANGE([col], months_back) form; resolve_formula_builder/
    resolve_group_a_b below both branch on that. *strategies* is every
    saved strategy, active or not — a strategy switched on later in the
    same session (via the picker), without a fresh Load, still resolves
    correctly as long as it was already known when this ran, same
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
                elif isinstance(window, tuple) and len(window) == 1 and window[0] == VALUE_BEFORE_CHANGE_DAILY_TAG:
                    key = (col_name, None)
                else:
                    continue
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def _window_for(months_back):
    """The day_history window key for one (col_name, months_back) spec —
    see this module's docstring for the two tagged shapes."""
    if months_back is None:
        return (VALUE_BEFORE_CHANGE_DAILY_TAG,)
    return (VALUE_BEFORE_CHANGE_TAG, months_back)


def n_specs_for_strategies(strategies: list) -> list:
    """[(col_name, n), ...], deduped — every VALUE_BEFORE_CHANGE_N
    reference across *strategies*' own columns' formulas (see this
    module's own VALUE_BEFORE_CHANGE_N section for what it means).
    Deliberately separate from specs_for_strategies above rather than
    folded into the same list — VALUE_BEFORE_CHANGE_N is a DIFFERENT
    function (services.strategy_engine.VALUE_BEFORE_CHANGE_N_TAG, not
    VALUE_BEFORE_CHANGE_TAG/VALUE_BEFORE_CHANGE_DAILY_TAG), so a shared
    list would need an extra tag on every entry anyway; two short
    functions read more clearly than one with a mixed-meaning return
    shape. Same "every saved strategy, active or not" scanning
    convention as specs_for_strategies — see its own docstring."""
    seen: set = set()
    out = []
    for strat in strategies:
        for col in strat.get("columns", []):
            compiled = get_compiled(col.get("formula", []))
            if compiled is None:
                continue
            for _, _agg_key, col_name, window in compiled.day_specs:
                if isinstance(window, tuple) and len(window) == 2 and window[0] == VALUE_BEFORE_CHANGE_N_TAG:
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
    Builder codes only (see specs_for_strategies + FORMULA_CODES).
    months_back may be None (the "auto" day-granularity form — see this
    module's docstring). *bars*: this symbol's own ascending-by-trade_date
    bar history, already fetched up to the as-of-date (services.
    inception_bars_store.bars_for_symbol's shape) — reused as-is, no extra
    query."""
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
            if months_back is None:
                # "Auto" — walk back TRADING day by trading day (every bar,
                # not just month-ends), stopping at the first differing
                # value or VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS bars back,
                # whichever comes first.
                oldest_idx = max(0, len(bars) - 1 - VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS)
                for idx in range(len(bars) - 2, oldest_idx - 1, -1):
                    value = inception_formula_builder_columns.compute_for_bars(symbol, bars[:idx + 1]).get(col_name)
                    if isinstance(value, (int, float)) and value != current:
                        found = value
                        break
            else:
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
        out[(col_name, _window_for(months_back))] = {symbol: {"First": found}}
    return out


def resolve_formula_builder_n(specs: list, symbol: str, bars: list) -> dict:
    """*specs*: [(col_name, n), ...] — VALUE_BEFORE_CHANGE_N's own spec
    shape (see n_specs_for_strategies), already filtered to Formula
    Builder codes. n is 1-based: n=1 is the same value VALUE_BEFORE_
    CHANGE([col])'s "auto" form returns (the first day walking backward
    whose value differs from today's); n=2 is the value from the change
    before THAT one; n=3 before that; and so on. Always day-granularity
    (no month-boundary variant — see this module's docstring), same
    VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS cap on how far back the WHOLE walk
    goes regardless of n (not a per-occurrence cap — finding the 3rd
    change still gives up at the same total distance the 1st change
    search would)."""
    if not specs or not bars:
        return {}
    from services import inception_formula_builder_columns

    out: dict = {}
    for col_name, n in specs:
        current = inception_formula_builder_columns.compute_for_bars(symbol, bars).get(col_name)
        found = None
        if isinstance(current, (int, float)):
            ref = current
            occurrences = 0
            oldest_idx = max(0, len(bars) - 1 - VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS)
            for idx in range(len(bars) - 2, oldest_idx - 1, -1):
                value = inception_formula_builder_columns.compute_for_bars(symbol, bars[:idx + 1]).get(col_name)
                if isinstance(value, (int, float)) and value != ref:
                    occurrences += 1
                    ref = value
                    if occurrences == n:
                        found = value
                        break
        out[(col_name, (VALUE_BEFORE_CHANGE_N_TAG, n))] = {symbol: {"First": found}}
    return out


# ── Group A/B (and raw) codes ────────────────────────────────────────────────

def resolve_group_a_b(specs: list, as_of_date: date, progress_cb=None) -> dict:
    """*specs*: [(col_name, months_back), ...] already filtered to
    NON-Formula-Builder codes (Group A/B or raw). months_back may be None
    (the "auto" day-granularity form — see this module's docstring). One
    services.inception_compute_service.range_rows call covers every symbol
    and every candidate day in a single full-universe pass — see this
    module's own docstring for why that's cheap relative to walking
    day-by-day/month-by-month per symbol."""
    if not specs:
        return {}
    from services import inception_compute_service

    month_specs = [m for _, m in specs if m is not None]
    date_from_candidates = []
    if month_specs:
        date_from_candidates.append(_earliest_date_from(as_of_date, max(month_specs)))
    if len(month_specs) < len(specs):  # at least one "auto" spec present
        date_from_candidates.append(as_of_date - timedelta(days=_DAILY_LOOKBACK_CALENDAR_DAYS))
    date_from = min(date_from_candidates)
    range_response = inception_compute_service.range_rows(date_from, as_of_date, progress_cb=progress_cb)

    by_date: dict = {}
    for day in range_response.get("days", []):
        trade_date = date.fromisoformat(day["trade_date"])
        by_date[trade_date] = {s["symbol"]: s.get("metrics", {}) for s in day.get("stocks", [])}
    sorted_dates = sorted(by_date)
    # Index of as_of_date within sorted_dates, for the "auto" walk below —
    # computed once, not per symbol. as_of_date may be absent from
    # sorted_dates (e.g. no bar for it yet); treat that as "off the end".
    as_of_idx = sorted_dates.index(as_of_date) if as_of_date in sorted_dates else len(sorted_dates)

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
            if months_back is None:
                oldest_idx = max(0, as_of_idx - VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS)
                for j in range(as_of_idx - 1, oldest_idx - 1, -1):
                    value = by_date[sorted_dates[j]].get(symbol, {}).get(col_name)
                    if isinstance(value, (int, float)) and value != current:
                        found = value
                        break
            else:
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
        out[(col_name, _window_for(months_back))] = entries
    return out


def resolve_group_a_b_n(specs: list, as_of_date: date, progress_cb=None) -> dict:
    """*specs*: [(col_name, n), ...] — VALUE_BEFORE_CHANGE_N's own spec
    shape (see n_specs_for_strategies), already filtered to NON-Formula-
    Builder codes (Group A/B or raw). n is 1-based — see resolve_
    formula_builder_n's own docstring for exactly what it means and the
    same total-walk cap. One services.inception_compute_service.range_rows
    call covers every symbol, same reasoning as resolve_group_a_b above."""
    if not specs:
        return {}
    from services import inception_compute_service

    date_from = as_of_date - timedelta(days=_DAILY_LOOKBACK_CALENDAR_DAYS)
    range_response = inception_compute_service.range_rows(date_from, as_of_date, progress_cb=progress_cb)

    by_date: dict = {}
    for day in range_response.get("days", []):
        trade_date = date.fromisoformat(day["trade_date"])
        by_date[trade_date] = {s["symbol"]: s.get("metrics", {}) for s in day.get("stocks", [])}
    sorted_dates = sorted(by_date)
    as_of_idx = sorted_dates.index(as_of_date) if as_of_date in sorted_dates else len(sorted_dates)

    out: dict = {}
    current_by_symbol = by_date.get(as_of_date, {})
    for col_name, n in specs:
        entries: dict = {}
        for symbol, metrics in current_by_symbol.items():
            current = metrics.get(col_name)
            if not isinstance(current, (int, float)):
                continue
            found = None
            ref = current
            occurrences = 0
            oldest_idx = max(0, as_of_idx - VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS)
            for j in range(as_of_idx - 1, oldest_idx - 1, -1):
                value = by_date[sorted_dates[j]].get(symbol, {}).get(col_name)
                if isinstance(value, (int, float)) and value != ref:
                    occurrences += 1
                    ref = value
                    if occurrences == n:
                        found = value
                        break
            entries[symbol] = {"First": found}
        out[(col_name, (VALUE_BEFORE_CHANGE_N_TAG, n))] = entries
    return out
