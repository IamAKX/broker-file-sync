"""Resolves VALUE_DAYS_AGO/VALUE_ON_DATE/_DAYS-family historic-lookback
functions (services.strategy_engine's "Historic (N days) aggregates" /
"Historic value (point lookup)") for Inception's HMV/View by Date grids —
Inception's analogue of services.formula_stats_engine.compute_day_history,
which is built around a remote LmvDailySnapshot fetch (api.lmv_snapshot_api.
get_range) Inception has no equivalent of. Resolved instead straight from
each instrument's own locally-synced bar history (services.
inception_bars_store) — no network call, no separate fetch, just slicing
data screens.inception_hmv/inception_view_by_date's workers already pull
per symbol for services.inception_formula_builder_columns.

Deliberately scoped to RAW OHLCV fields only (services.inception_columns.
RAW_FIELDS: OPEN/HIGH/LOW/CLOSE/VOL/OPENINT) — a _DAYS/VALUE_DAYS_AGO
reference to a Group A/B (52WH, ...) or Formula Builder (MT, MB, ...)
derived column is NOT resolved here and stays unsupported (blank, via
evaluate()'s own "missing day_history entry" fallback) — those aren't
stored per-historical-bar the way raw OHLCV is, only computed as of a
single as-of-date, so answering them here would mean re-running the full
Group A/B/Formula Builder computation over every historical bar in the
window, not just slicing already-fetched data. A narrower scope than LMV's
own day_history support, not a regression — before this module existed,
EVERY _DAYS/VALUE_DAYS_AGO reference (raw field or otherwise) was silently
blank in Inception's HMV/View by Date grids, reported as "AVG_DAYS(CLOSE,
200)" (the "200 Average" strategy) computing nothing at all.

One as-of-date, one shared history: unlike Formula Stats (services.
formula_stats_engine.compute_stats), where every historic day in a range
is its own "today" and a per-day-relative history has to be rebuilt for
each one, an HMV/View by Date snapshot has exactly ONE as-of-date shared by
every row on screen — so build() is called once per symbol per Load, same
"single shared day_history" shape apply_strategies expects from a live LMV
tick's own day_history (services.strategy_engine.compute_day_history).
"""
from services.inception_columns import RAW_FIELDS
from services.strategy_engine import get_compiled

# Formula col_arg name -> services.inception_bars_store.bars_for_symbol's
# own (lowercase) bar dict key — same mapping services.inception_compute_
# service._compute_rows_for_days uses to populate a row's raw fields.
_BAR_KEY = {
    "OPEN": "open", "HIGH": "high", "LOW": "low", "CLOSE": "close",
    "VOL": "volume", "OPENINT": "open_interest",
}


def raw_day_specs(strategies: list) -> list:
    """[(agg_key, col_name, window), ...], deduped — every VALUE_DAYS_AGO/
    VALUE_ON_DATE/_DAYS-family function referenced by any of *strategies*'
    own columns' formulas whose col_arg names a raw OHLCV field. Row
    filters/fmt-rule conditions aren't scanned (unlike services.
    strategy_engine.collect_day_requests) — Inception's "Days True"/"Since"
    streak columns are already off entirely (apply_strategies'
    include_streak_columns=False, see screens.inception_hmv/inception_view_
    by_date's own docstrings), and a row-filter referencing one of these
    functions is a narrower case not covered by this fix's scope either.

    *strategies* is every saved strategy, active or not, deliberately — a
    strategy switched on later in the same session via the "⚡ Strategies"
    picker, without a fresh Load, still resolves correctly as long as it
    was already known to this list when build() ran (see this module's own
    "one as-of-date, one shared history" section); one created or edited
    since needs a fresh Load either way, same as a Formula Builder column
    edit already does (see screens.inception_hmv._merge_formula_builder_
    columns' docstring, "runs on this background thread").
    """
    seen: set = set()
    out = []
    for strat in strategies:
        for col in strat.get("columns", []):
            compiled = get_compiled(col.get("formula", []))
            if compiled is None:
                continue
            for _, agg_key, col_name, window in compiled.day_specs:
                if col_name not in RAW_FIELDS:
                    continue
                key = (agg_key, col_name, window)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def build(specs: list, symbol: str, bars: list) -> dict:
    """{(col_name, window): {symbol: {agg_key: value}}} for *specs* (from
    raw_day_specs) — the shape services.strategy_engine.evaluate_compiled's
    day_history param expects — resolved from *bars*, this ONE symbol's own
    ascending-by-trade_date bar history (services.inception_bars_store.
    bars_for_symbol's shape).

    ``window`` an int means "last N trading days ending at the as-of-date
    bars was fetched up to" (VALUE_DAYS_AGO/_DAYS-family) — resolved from
    bars[-window:], same "not enough history fetched yet" None fallback as
    services.formula_stats_engine._self_contained_day_history for a day
    too early in ITS range. A (date_from, date_to) tuple (VALUE_ON_DATE,
    date_from == date_to) is resolved by a direct scan for that trade_date
    instead — a fixed calendar date doesn't need "last N days" slicing.
    """
    out: dict = {}
    for agg_key, col_name, window in specs:
        bar_key = _BAR_KEY[col_name]
        if isinstance(window, tuple):
            target_date = window[0]
            value = None
            for bar in bars:
                if bar["trade_date"].isoformat() == target_date:
                    v = bar.get(bar_key)
                    value = v if isinstance(v, (int, float)) else None
                    break
            out[(col_name, window)] = {symbol: {"First": value}}
            continue

        if window <= 0 or len(bars) < window:
            continue
        window_bars = bars[-window:]
        if agg_key == "First":
            v = window_bars[0].get(bar_key)
            value = v if isinstance(v, (int, float)) else None
        else:
            from services.formula_stats_engine import AGGREGATES
            numeric = [b.get(bar_key) for b in window_bars if isinstance(b.get(bar_key), (int, float))]
            agg_fn = AGGREGATES.get(agg_key)
            value = agg_fn(numeric) if agg_fn and numeric else None
        out[(col_name, window)] = {symbol: {agg_key: value}}
    return out
