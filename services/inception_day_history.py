"""Resolves VALUE_DAYS_AGO/VALUE_ON_DATE/_DAYS-family/VALUE_AT_MAX_DAYS/
VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES historic-lookback
functions (services.strategy_engine's "Historic (N days) aggregates" /
"Historic value (point lookup)" / "Historic value at a window extreme")
for Inception's HMV/View by Date grids — Inception's analogue of services.
formula_stats_engine.compute_day_history, which is built around a remote
LmvDailySnapshot fetch (api.lmv_snapshot_api.get_range) Inception has no
equivalent of. Resolved instead straight from each instrument's own
locally-synced bar history (services.inception_bars_store) — no network
call, no separate fetch, just slicing data screens.inception_hmv/
inception_view_by_date's workers already pull per symbol for services.
inception_formula_builder_columns. Two resolvers, both consumed the same
way: build() for the plain _DAYS-family/VALUE_DAYS_AGO/VALUE_ON_DATE
functions (a single reduced value per (col, window)), build_extreme() for
VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES
(a chronological "daily" list per (col, window) instead — see
build_extreme's own docstring). Combine their output into one shared
day_history dict via merge_into (not a bare dict.update — see its
docstring for why a shallow merge would clobber instead).

Deliberately scoped to RAW OHLCV fields only (services.inception_columns.
RAW_FIELDS: OPEN/HIGH/LOW/CLOSE/VOL/OPENINT) — a reference to a Group A/B
(52WH, ...) or Formula Builder (MT, MB, ...) derived column is NOT
resolved here and stays unsupported (blank, via evaluate()'s own "missing
day_history entry" fallback) — those aren't stored per-historical-bar the
way raw OHLCV is, only computed as of a single as-of-date, so answering
them here would mean re-running the full Group A/B/Formula Builder
computation over every historical bar in the window, not just slicing
already-fetched data. A narrower scope than LMV's own day_history support,
not a regression — before this module existed, EVERY _DAYS/VALUE_DAYS_AGO
reference (raw field or otherwise) was silently blank in Inception's HMV/
View by Date grids, reported as "AVG_DAYS(CLOSE, 200)" (the "200 Average"
strategy) computing nothing at all.

One as-of-date, one shared history: unlike Formula Stats (services.
formula_stats_engine.compute_stats), where every historic day in a range
is its own "today" and a per-day-relative history has to be rebuilt for
each one, an HMV/View by Date snapshot has exactly ONE as-of-date shared by
every row on screen — so build()/build_extreme() are each called once per
symbol per Load, same "single shared day_history" shape apply_strategies
expects from a live LMV tick's own day_history (services.strategy_engine.
compute_day_history).
"""
from services.inception_columns import RAW_FIELDS
from services.strategy_engine import (
    VALUE_BEFORE_CHANGE_DAILY_TAG, VALUE_BEFORE_CHANGE_N_TAG,
    VALUE_BEFORE_CHANGE_TAG, get_compiled,
)

# window shapes raw_day_specs/build below actually understand: a plain int
# (_DAYS-family/VALUE_DAYS_AGO) or a (date, date) string tuple (VALUE_ON_
# DATE). VALUE_BEFORE_CHANGE's own window is ALSO a tuple — (VALUE_BEFORE_
# CHANGE_TAG, months_back) or the bare (VALUE_BEFORE_CHANGE_DAILY_TAG,) —
# but resolved entirely differently (services.inception_value_before_
# change's build_extreme-style walk, not a date/window slice of bars). A
# VALUE_BEFORE_CHANGE reference to a raw field (e.g. VALUE_BEFORE_CHANGE(
# [HIGH])) would otherwise ALSO pass raw_day_specs' "col_name in RAW_
# FIELDS" filter and get handed to build(), which would misread the tag
# string itself as a literal target_date to scan bars for (never matches
# any real date) and silently write a bogus {"First": None} entry for the
# correct symbol — clobbering nothing (different key shape) but shadowing
# what should have been resolved separately, since day_history lookups
# key on (col_name, window) and this bogus window IS the real one.
_VALUE_BEFORE_CHANGE_TAGS = (
    VALUE_BEFORE_CHANGE_TAG, VALUE_BEFORE_CHANGE_DAILY_TAG, VALUE_BEFORE_CHANGE_N_TAG,
)

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
                if isinstance(window, tuple) and window and window[0] in _VALUE_BEFORE_CHANGE_TAGS:
                    # VALUE_BEFORE_CHANGE's own tagged window — resolved by
                    # services.inception_value_before_change (raw_extreme_
                    # specs' sibling, effectively) instead, not here. See
                    # _VALUE_BEFORE_CHANGE_TAGS' own comment above.
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

    Merges per (col_name, window, symbol) rather than overwriting — two
    specs sharing the same (col_name, window) but a different agg_key
    (e.g. both AVG_DAYS([HIGH], 20) and MAX_DAYS([HIGH], 20) in the same
    strategy) both need to survive in the one entry, not have the second
    spec's assignment clobber the first's. See also build_extreme/
    merge_into below, for the same (col_name, window) key shared with a
    VALUE_AT_MAX_DAYS/etc reference to the identical column+window.
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
            out.setdefault((col_name, window), {}).setdefault(symbol, {})["First"] = value
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
        out.setdefault((col_name, window), {}).setdefault(symbol, {})[agg_key] = value
    return out


# ── VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES ──
# Same RAW_FIELDS-only scoping as raw_day_specs/build above, for the same
# reason: services.strategy_engine._value_at_extreme needs a chronological
# "daily" list (not a single reduced value) for BOTH the value column and
# the driver column over the SAME window, and only raw OHLCV is stored
# per-historical-bar cheaply enough to answer that without re-running a
# full Group A/B/Formula Builder computation once per historic day.

def raw_extreme_specs(strategies: list) -> list:
    """[(col_name, driver_col_name, window, want_max), ...], deduped —
    every VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/
    VALUE_AT_MIN_DATES reference across *strategies*' own columns' formulas
    whose col_arg AND driver_col_arg BOTH name a raw OHLCV field (a call
    mixing a raw field with a Group A/B or Formula Builder column on
    either side isn't resolved here and stays unsupported — same "blank,
    not broken" convention raw_day_specs already documents). window is an
    int (VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS — last N trading days) or a
    (date_from, date_to) string tuple (VALUE_AT_MAX_DATES/VALUE_AT_MIN_
    DATES). want_max is True for the _MAX_ variant, False for _MIN_ — see
    services.strategy_engine's _VALUE_AT_EXTREME_FUNCS/_VALUE_AT_EXTREME_
    DATE_FUNCS. *strategies*: every saved strategy, active or not, same
    reasoning as raw_day_specs."""
    seen: set = set()
    out = []
    for strat in strategies:
        for col in strat.get("columns", []):
            compiled = get_compiled(col.get("formula", []))
            if compiled is None:
                continue
            for _, col_name, driver_col_name, window, want_max in compiled.extreme_specs:
                if col_name not in RAW_FIELDS or driver_col_name not in RAW_FIELDS:
                    continue
                key = (col_name, driver_col_name, window, want_max)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def build_extreme(specs: list, symbol: str, bars: list) -> dict:
    """{(col_name, window): {symbol: {"daily": [(date_iso, value), ...]}}}
    for *specs* (from raw_extreme_specs) — services.strategy_engine.
    _value_at_extreme's own expected shape: a chronological "daily" list,
    no aggregate keys (extremes only ever read "daily", picking the
    driver's winning date then reading the value column at that same
    date). One entry per DISTINCT (col_name, window) actually needed:
    both the value side and the driver side of each spec get their own
    "daily" list, deduped since the same column/window can appear on
    either side of more than one call. window shape mirrors build()'s
    own: an int slices bars[-window:]; a (date_from, date_to) string
    tuple scans every bar whose trade_date falls in that inclusive range.
    Use merge_into (not a bare dict.update) to combine this with build()'s
    own output for the shared day_history dict — see merge_into's
    docstring for why a shallow update would clobber instead of merge."""
    if not specs or not bars:
        return {}
    needed: set = set()
    for col_name, driver_col_name, window, _want_max in specs:
        needed.add((col_name, window))
        needed.add((driver_col_name, window))

    out: dict = {}
    for col_name, window in needed:
        bar_key = _BAR_KEY[col_name]
        if isinstance(window, tuple):
            date_from_s, date_to_s = window
            daily = [
                (b["trade_date"].isoformat(), b.get(bar_key))
                for b in bars
                if date_from_s <= b["trade_date"].isoformat() <= date_to_s
                and isinstance(b.get(bar_key), (int, float))
            ]
        elif window > 0 and len(bars) >= window:
            daily = [
                (b["trade_date"].isoformat(), b.get(bar_key))
                for b in bars[-window:]
                if isinstance(b.get(bar_key), (int, float))
            ]
        else:
            daily = []
        out[(col_name, window)] = {symbol: {"daily": daily}}
    return out


def merge_into(day_history: dict, source: dict):
    """Merges *source* — one resolver's own {(col_name, window): {symbol:
    {...}}} output (build()/build_extreme() here, or services.
    inception_value_before_change's resolve_formula_builder/resolve_
    group_a_b) — into the shared *day_history* dict for one Load, WITHOUT
    clobbering another resolver's data for the same (col_name, window)/
    symbol pair. E.g. a formula referencing both AVG_DAYS([HIGH], 20) and
    VALUE_AT_MAX_DAYS([HIGH], [CWTO], 20) needs build()'s {"Average": v}
    AND build_extreme()'s {"daily": [...]} to both survive under the
    identical (col_name, window) key. A bare `day_history.setdefault(key,
    {}).update(entry)` — merging only one level deep — replaces the WHOLE
    per-symbol value on a collision instead of merging into it; this
    merges one level deeper (per-symbol, not just per-key) instead."""
    for key, entry in source.items():
        per_symbol = day_history.setdefault(key, {})
        for symbol, values in entry.items():
            per_symbol.setdefault(symbol, {}).update(values)
