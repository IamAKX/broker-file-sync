"""
Recomputes a strategy's formula columns over historic LmvDailySnapshot days,
aggregating per stock — powers the Formula Stats screen
(screens/formula_stats.py). Fetching "which dates/values" lives in
api/lmv_snapshot_api.get_range(); this module is pure logic (no Qt, no
network calls) so it's directly unit-testable.
"""
import statistics

from services.strategy_engine import SYMBOL_COLUMN, build_symbol_index, evaluate


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


def compute_stats(strategy: dict, range_response: dict) -> dict:
    """Evaluate every column in strategy["columns"] for every stock on every
    day in range_response["days"] (the shape returned by
    api/lmv_snapshot_api.get_range), then aggregate per stock per column.

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
    columns = strategy.get("columns", [])
    by_symbol: dict = {}

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
                value = evaluate(col["formula"], row_dict, all_dicts,
                                 agg_cache=agg_cache, sym_index=sym_index)
                entry["columns"][col["name"]]["daily"].append((trade_date, value))

    for entry in by_symbol.values():
        for col_data in entry["columns"].values():
            numeric_values = [v for _, v in col_data["daily"] if isinstance(v, (int, float))]
            for agg_name, agg_fn in AGGREGATES.items():
                col_data[agg_name] = agg_fn(numeric_values) if numeric_values else None

    return by_symbol
