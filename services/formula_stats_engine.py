"""
Recomputes a list of formula columns over historic LmvDailySnapshot days,
aggregating per stock. Two entry points:

  - compute_stats(): powers the Data menu's Formula Stats screen
    (screens/formula_stats.py) via components/formula_stats_panel.py — pick
    a strategy and a day count, see Min/Max/Average/etc. for every column,
    right-click a cell for the day-by-day values behind it.

  - compute_day_history(): powers the AVG_DAYS/MIN_DAYS/... formula
    functions and the VALUE_DAYS_AGO/VALUE_ON_DATE point lookups
    (services/strategy_engine.py's "Historic (N days) aggregates" /
    "Historic value (point lookup)") — one value per stock per (column,
    window) request, looked up by evaluate() while rendering Live Master
    View. Callers (live_viewer.py) call this once per strategy load/toggle/
    manual refresh, never per tick.

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


def compute_stats(columns: list, range_response: dict) -> dict:
    """Evaluate every formula in *columns* (a list of {"name", "formula"}
    dicts — a strategy's saved columns, or any ad-hoc one-off formula built
    just for this test, e.g. from the Expression Editor's "Test Last N
    Days…" button) for every stock on every day in range_response["days"]
    (the shape returned by api/lmv_snapshot_api.get_range), then aggregate
    per stock per column.

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
            for col in columns:
                value = evaluate_compiled(compiled_by_name[col["name"]], row_dict, all_dicts,
                                          agg_cache=agg_cache, sym_index=sym_index)
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
