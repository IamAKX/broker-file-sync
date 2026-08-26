"""
Recomputes a list of formula columns over historic LmvDailySnapshot days,
aggregating per stock. Two entry points:

  - compute_stats(): powers the Data menu's Formula Stats screen
    (screens/formula_stats.py) via components/formula_stats_panel.py — pick
    a strategy and a day count, see Min/Max/Average/etc. for every column,
    right-click a cell for the day-by-day values behind it. A formula
    referencing VALUE_DAYS_AGO/VALUE_ON_DATE/a _DAYS aggregate resolves
    self-contained straight from the same fetched range (see
    _self_contained_day_history) — this screen has no "live tick" for a
    real-today-anchored day_history to make sense against; every day being
    analyzed is its own "today" instead. Without this, such a formula
    (e.g. VALUE_DAYS_AGO([High], 1) > VALUE_DAYS_AGO([High], 0)) silently
    evaluated to None for every single stock/day, blanking the whole
    results table with no error.

  - compute_day_history(): powers the AVG_DAYS/MIN_DAYS/... formula
    functions and the VALUE_DAYS_AGO/VALUE_ON_DATE point lookups
    (services/strategy_engine.py's "Historic (N days) aggregates" /
    "Historic value (point lookup)") for a LIVE Master View row, where
    "today" is real/fixed and a single shared lookback genuinely is
    correct — one value per stock per (column, window) request, looked up
    by evaluate() while rendering. Callers (live_viewer.py) call this once
    per strategy load/toggle/manual refresh, never per tick.

Fetching "which dates/values" lives in api/lmv_snapshot_api.get_range();
this module is pure logic (no Qt, no network calls) so it's directly
unit-testable. fetch_range_response() is what lets a single fixed date
(VALUE_ON_DATE) reuse that same "N most recent days" endpoint (fetch enough
days, filter client-side) instead of needing a dedicated date-lookup API.
"""
from datetime import date
import statistics

from services.strategy_engine import SYMBOL_COLUMN, build_symbol_index, evaluate_compiled, get_compiled


def _average(values: list) -> float:
    return sum(values) / len(values)


def _std_dev(values: list):
    # A single data point has no spread to measure — statistics.stdev raises
    # StatisticsError below n=2, so this returns None (rendered as "-") rather
    # than propagating that as an unhandled error.
    return statistics.stdev(values) if len(values) >= 2 else None


def _variance(values: list):
    return statistics.variance(values) if len(values) >= 2 else None


def _range_span(values: list) -> float:
    return max(values) - min(values)


# Order here is the display order in screens/formula_stats.py's aggregate
# checkbox row and the results table's column grouping.
AGGREGATES = {
    "Min": min,
    "Max": max,
    "Average": _average,
    "Sum": sum,
    "Count": len,
    "Std Dev": _std_dev,
    "Median": statistics.median,
    "Variance": _variance,
    "Range": _range_span,
}

DEFAULT_AGGREGATES = ["Min", "Max", "Average", "Count"]


def _needed_int_day_specs(compiled_by_name: dict) -> list:
    """Distinct (agg_key, col_name, window) triples — every VALUE_DAYS_AGO
    or _DAYS-family function referenced by any compiled column's day_specs
    (see services.strategy_engine._Compiled) with an int (relative
    "N days back") window. Feeds _self_contained_day_history — see that
    function and compute_stats' own docstring for why these need a
    per-evaluation-day history rather than the real-"today"-anchored one
    compute_day_history builds."""
    seen: set = set()
    out = []
    for compiled in compiled_by_name.values():
        if compiled is None:
            continue
        for _, agg_key, col_name, window in compiled.day_specs:
            key = (agg_key, col_name, window)
            if isinstance(window, int) and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _needed_date_specs(compiled_by_name: dict) -> list:
    """Distinct (col_name, (date_from, date_to)) pairs — every VALUE_ON_DATE
    referenced by any compiled column's day_specs (always paired with
    agg_key "First" — see services.strategy_engine._build_compiled). A
    fixed calendar date/range needs no per-day lookback padding (unlike an
    int window it isn't relative to whichever day is currently being
    evaluated), so it's resolved directly against a stock's history-so-far,
    same as the int windows, by _self_contained_day_history."""
    seen: set = set()
    out = []
    for compiled in compiled_by_name.values():
        if compiled is None:
            continue
        for _, _agg_key, col_name, window in compiled.day_specs:
            key = (col_name, window)
            if isinstance(window, tuple) and key not in seen:
                seen.add(key)
                out.append(key)
    return out


def _self_contained_day_history(hist: list, int_specs: list, date_specs: list, symbol: str) -> dict:
    """Builds the {(col_name, window): {symbol: {agg_key: value}}} shape
    evaluate_compiled expects for VALUE_DAYS_AGO/VALUE_ON_DATE/_DAYS-family
    functions, entirely from *hist* — one stock's own [(trade_date,
    row_dict), ...] accumulated so far (oldest first, the day currently
    being evaluated last) within this same compute_stats() call, rather
    than a separate historic fetch anchored to real "today" — every day in
    a Formula Stats range is its own "today" for VALUE_DAYS_AGO's purposes,
    so a single shared, today-anchored history would give every day the
    SAME lookback value instead of each day's own. A window reaching before
    the first day actually fetched just isn't included here, so it
    resolves to None the same "missing input" way evaluate() already
    treats any other absent day_history entry — the day is simply too
    early in the picked range for that lookback to be answerable from what
    was fetched, not a crash.
    """
    out: dict = {}
    for agg_key, col_name, window in int_specs:
        if window <= 0 or len(hist) < window:
            continue
        window_vals = [row.get(col_name) for _, row in hist[-window:]]
        if agg_key == "First":
            value = window_vals[0] if isinstance(window_vals[0], (int, float)) else None
        else:
            numeric = [v for v in window_vals if isinstance(v, (int, float))]
            agg_fn = AGGREGATES.get(agg_key)
            value = agg_fn(numeric) if agg_fn and numeric else None
        out[(col_name, window)] = {symbol: {agg_key: value}}
    for col_name, date_window in date_specs:
        target_date = date_window[0]   # date_from == date_to for VALUE_ON_DATE
        value = None
        for trade_date, row in hist:
            if trade_date == target_date:
                v = row.get(col_name)
                value = v if isinstance(v, (int, float)) else None
                break
        out[(col_name, date_window)] = {symbol: {"First": value}}
    return out


def compute_stats(columns: list, range_response: dict, day_history: dict | None = None) -> dict:
    """Evaluate every formula in *columns* (a list of {"name", "formula"}
    dicts — a strategy's saved columns, or any ad-hoc one-off formula built
    just for this test, e.g. from the Expression Editor's "Test Last N
    Days…" button) for every stock on every day in range_response["days"]
    (the shape returned by api/lmv_snapshot_api.get_range), then aggregate
    per stock per column.

    A formula referencing VALUE_DAYS_AGO/VALUE_ON_DATE or a _DAYS
    historic-aggregate function is resolved SELF-CONTAINED, straight from
    range_response itself (see _self_contained_day_history) — no separate
    fetch, and no explicit *day_history* needed from the caller for this,
    unlike services.strategy_engine.evaluate_compiled's other callers.
    This has to be built fresh per day being evaluated rather than once:
    every day in a Formula Stats range stands in as its own "today", so
    "N days ago" means N days before THAT day, not N days before real
    today — a single today-anchored day_history (what compute_day_history
    below builds, for the live-tick case where "today" really is fixed)
    would give every historic day the exact same lookback value instead of
    each one's own. A day early enough in the picked range that its own
    window reaches before the first day actually fetched just comes back
    blank for that function — not enough history was fetched to answer it,
    same "blank rather than wrong" fallback as any other missing input.
    VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES
    aren't covered by this yet (still blank here, same as before this fix)
    — pass an explicit *day_history* (real-"today"-anchored; see
    compute_day_history) if a caller needs those to resolve instead.

    *day_history*, when the caller passes one explicitly, is used as-is for
    EVERY day instead of the self-contained per-day one above — this is
    what compute_day_history's own recursive call below does (a _DAYS-of-
    _DAYS reference resolves via nesting there, not this self-contained
    path) and what any future caller wanting classic "real today" semantics
    within a Formula Stats-shaped call would opt into.

    Returns:
        {symbol: {"display_name": str,
                  "columns": {column_name: {"daily": [(trade_date, value), ...],
                                             **{agg_name: float | None}}}}}

    "daily" backs the right-click day-by-day popup; the aggregate keys back
    the results table. A day whose row is missing a column the formula
    references (e.g. Sector/OR.High aren't in historic storage) evaluates to
    None for that stock/day via evaluate()'s own dict.get() fallback — still
    recorded in "daily" (so the popup can show it as missing), but excluded
    from every aggregate, so Count directly reports how many of the requested
    days actually had usable data.
    """
    by_symbol: dict = {}

    # Pre-compile every column's formula ONCE, outside the day/stock loop
    # below, rather than calling evaluate() (which re-derives a cache-key
    # signature from the token list on every single call) once per day per
    # stock. Profiling a realistic 215-stock/7-strategy/60-day batch found
    # that per-call signature rebuild costing more than the actual formula
    # evaluation combined — this loop can run tens of thousands of times for
    # a single Formula Stats/day-history request, so the saving is real, not
    # theoretical. See services.strategy_engine.evaluate_compiled.
    compiled_by_name = {c["name"]: get_compiled(c["formula"]) for c in columns}

    # Only figure out what the self-contained path needs to track when the
    # caller hasn't already supplied its own day_history (see this
    # function's own docstring) — skips the bookkeeping below entirely for
    # every column set that doesn't reference these functions at all.
    build_self_contained = day_history is None
    int_specs = _needed_int_day_specs(compiled_by_name) if build_self_contained else []
    date_specs = _needed_date_specs(compiled_by_name) if build_self_contained else []
    build_self_contained = build_self_contained and (int_specs or date_specs)
    symbol_history: dict = {}   # symbol -> [(trade_date, row_dict), ...], oldest first

    for day in range_response.get("days", []):
        trade_date = day["trade_date"]
        stocks = day.get("stocks", [])

        # One row_data dict per stock, keyed the same way live LMV rows are
        # (raw metric columns plus a "Scrip Name" entry) so evaluate()'s
        # dict.get() calls resolve identically to how they do against live
        # data. The historic snapshot's "symbol" (the canonical resolved
        # identifier, not the raw broker display name) is what's used for
        # "Scrip Name" here — closer to what a "[Col of X]" formula token
        # would actually name.
        all_dicts = []
        for stock in stocks:
            row_dict = dict(stock.get("metrics", {}))
            row_dict[SYMBOL_COLUMN] = stock.get("symbol")
            all_dicts.append(row_dict)

        agg_cache: dict = {}
        sym_index = build_symbol_index(all_dicts)

        for stock, row_dict in zip(stocks, all_dicts):
            symbol = stock.get("symbol")
            if not symbol:
                continue
            entry = by_symbol.setdefault(symbol, {
                "display_name": stock.get("display_name") or symbol,
                "columns": {c["name"]: {"daily": []} for c in columns},
            })
            this_day_history = day_history
            if build_self_contained:
                hist = symbol_history.setdefault(symbol, [])
                hist.append((trade_date, row_dict))
                this_day_history = _self_contained_day_history(hist, int_specs, date_specs, symbol)
            for col in columns:
                value = evaluate_compiled(compiled_by_name[col["name"]], row_dict, all_dicts,
                                          agg_cache=agg_cache, sym_index=sym_index,
                                          day_history=this_day_history)
                entry["columns"][col["name"]]["daily"].append((trade_date, value))

    for entry in by_symbol.values():
        for col_data in entry["columns"].values():
            numeric_values = [v for _, v in col_data["daily"] if isinstance(v, (int, float))]
            for agg_name, agg_fn in AGGREGATES.items():
                col_data[agg_name] = agg_fn(numeric_values) if numeric_values else None
            # Not one of the user-facing AGGREGATES checkboxes (Formula Stats
            # screen ignores it) — "daily" is chronological ascending (see
            # this function's own iteration over range_response["days"]), so
            # the first entry is the OLDEST day actually fetched. This is
            # what powers VALUE_DAYS_AGO/VALUE_ON_DATE (services.
            # strategy_engine's "Historic value (point lookup)" functions):
            # both fetch a window sized/dated so the oldest day IS the exact
            # day they want, then read this key instead of aggregating.
            numeric_daily = [(d, v) for d, v in col_data["daily"] if isinstance(v, (int, float))]
            col_data["First"] = numeric_daily[0][1] if numeric_daily else None

    return by_symbol


def _days_needed_for_date(target: date) -> int:
    """Calendar-day upper bound on how many *available* trade dates could
    exist between target and today, inclusive. get_range(N) returns the N
    most recent dates WITH data — requesting this many calendar days' worth
    guarantees the response reaches back through target (weekends/holidays
    just mean most of those N slots come back with no matching date, which
    is fine, if target isn't in the future). Clamped to at least 1."""
    return max((date.today() - target).days + 1, 1)


def fetch_range_response(range_fetcher, window) -> dict:
    """Resolve one *window* — a plain int (last N days) or a (date_from,
    date_to) ISO-date-string tuple (a fixed range, date_from == date_to for
    a single specific date — see VALUE_ON_DATE) — into the same
    {"days": [...]} shape api/lmv_snapshot_api.get_range returns, so every
    caller downstream (compute_stats via compute_day_history below, and
    components/formula_stats_panel.py's click-through history popup) can
    treat both window kinds identically.

    An int just calls range_fetcher(window) directly, unchanged. A tuple
    fetches enough days to cover date_from..today via the same
    range_fetcher, then filters the response down to date_from <=
    trade_date <= date_to — no separate "fetch a date range" API needed.
    """
    if isinstance(window, tuple):
        date_from_str, date_to_str = window
        days = _days_needed_for_date(date.fromisoformat(date_from_str))
        response = range_fetcher(days)
        filtered_days = [
            d for d in response.get("days", [])
            if date_from_str <= d.get("trade_date", "") <= date_to_str
        ]
        return {**response, "days": filtered_days}
    return range_fetcher(window)


def compute_day_history(requests: list, range_fetcher) -> dict:
    """Resolve every (col_name, window, formula_tokens) request — as built
    by services.strategy_engine.collect_day_requests — into the lookup
    evaluate() needs for _DAYS functions and the VALUE_DAYS_AGO/VALUE_ON_DATE
    point lookups:

        {(col_name, window): {symbol: {agg_name: float | None}}}

    ``window`` is an int (_DAYS family, and VALUE_DAYS_AGO — both "last N
    days ending today") or a (date_from, date_to) tuple (VALUE_ON_DATE — a
    single fixed date, date_from == date_to) — see fetch_range_response,
    which resolves either into the same {"days": [...]} shape.

    *range_fetcher* is api/lmv_snapshot_api.get_range (injected so this stays
    network-free/unit-testable) — called once per DISTINCT ``window`` value
    across every request, not once per request, since compute_stats can
    already evaluate several columns against the same day range in one pass.
    """
    by_window: dict = {}
    for col_name, window, formula in requests:
        by_window.setdefault(window, []).append((col_name, formula))

    out: dict = {}
    for window, entries in by_window.items():
        range_response = fetch_range_response(range_fetcher, window)
        columns = [{"name": col_name, "formula": formula} for col_name, formula in entries]
        computed = compute_stats(columns, range_response)
        for col_name, _formula in entries:
            out[(col_name, window)] = {
                symbol: entry["columns"].get(col_name, {})
                for symbol, entry in computed.items()
            }
    return out
