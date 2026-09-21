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

build()/build_extreme() above are scoped to RAW OHLCV fields only
(services.inception_columns.RAW_FIELDS: OPEN/HIGH/LOW/CLOSE/VOL/OPENINT) —
a reference to a Group A/B (52WH, ...) or Formula Builder (MT, MB, ...)
derived column ISN'T resolved by raw_day_specs/build/raw_extreme_specs/
build_extreme, since those aren't stored per-historical-bar the way raw
OHLCV is, only computed as of a single as-of-date. The "Formula Builder /
Group A/B columns" section further down (derived_day_specs,
resolve_formula_builder_day, resolve_group_a_b_day, and their extreme-spec
counterparts — added for issue #45) DOES resolve those, via the same
two-path split services.inception_value_before_change already established
for VALUE_BEFORE_CHANGE: re-slicing this symbol's own bars through
services.inception_formula_builder_columns.compute_for_bars for Formula
Builder codes, or one services.inception_compute_service.range_rows pass
for the whole universe for Group A/B — see that section's own module
comment for the full split. A column that's neither raw, Formula Builder,
nor Group A/B (e.g. a reference to another of the strategy's own derived
output columns) still stays unsupported (blank, via evaluate()'s own
"missing day_history entry" fallback) — before this module existed, EVERY
_DAYS/VALUE_DAYS_AGO reference (raw field or otherwise) was silently blank
in Inception's HMV/View by Date grids, reported as "AVG_DAYS(CLOSE, 200)"
(the "200 Average" strategy) computing nothing at all.

One as-of-date, one shared history: unlike Formula Stats (services.
formula_stats_engine.compute_stats), where every historic day in a range
is its own "today" and a per-day-relative history has to be rebuilt for
each one, an HMV/View by Date snapshot has exactly ONE as-of-date shared by
every row on screen — so build()/build_extreme() are each called once per
symbol per Load, same "single shared day_history" shape apply_strategies
expects from a live LMV tick's own day_history (services.strategy_engine.
compute_day_history).
"""
import math
from datetime import date, timedelta

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


# ── Formula Builder / Group A/B columns (issue #45) ─────────────────────────
# raw_day_specs/build and raw_extreme_specs/build_extreme above stay exactly
# as they were — every function below is purely additive, resolving the
# SAME VALUE_DAYS_AGO/VALUE_ON_DATE/VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/
# VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES functions against a column that
# ISN'T a raw OHLCV field: a Formula Builder code (services.formula_engine.
# FORMULA_CODES, e.g. CWTO, MT, MB, DT, DB) or a Group A/B (Inception)
# column (services.inception_columns.GROUP_A/GROUP_B, e.g. 52WH, ATH).
# Mirrors the two-path split services.inception_value_before_change already
# established for VALUE_BEFORE_CHANGE/VALUE_BEFORE_CHANGE_N: Formula
# Builder columns re-slice this symbol's own already-fetched bars and call
# services.inception_formula_builder_columns.compute_for_bars; Group A/B
# columns are resolved from ONE services.inception_compute_service.
# range_rows call for the whole instrument universe per Load, not a
# per-symbol recompute. See docs/PLAN or the issue #45 fix commit message
# for the full design rationale.

def derived_day_specs(strategies: list) -> list:
    """[(agg_key, col_name, window), ...], deduped — raw_day_specs' own
    complement: every VALUE_DAYS_AGO/VALUE_ON_DATE reference (agg_key ==
    "First" — the only agg_key either function ever produces, see
    services.strategy_engine._build_compiled) whose col_arg does NOT name a
    raw OHLCV field. Deliberately excludes the _DAYS-family aggregates
    (AVG_DAYS/MAX_DAYS/...) even against a derived column — services.
    strategy_engine._DAYS_AGG_BASE never produces agg_key "First", so this
    filter already excludes them for free; extending those to derived
    columns is out of this fix's scope. Also excludes VALUE_BEFORE_CHANGE's
    own tagged windows, same _VALUE_BEFORE_CHANGE_TAGS check raw_day_specs
    uses above (services.inception_value_before_change's job, unchanged).

    *strategies*: every saved strategy, active or not — same reasoning as
    raw_day_specs' own docstring."""
    seen: set = set()
    out = []
    for strat in strategies:
        for col in strat.get("columns", []):
            compiled = get_compiled(col.get("formula", []))
            if compiled is None:
                continue
            for _, agg_key, col_name, window in compiled.day_specs:
                if col_name in RAW_FIELDS or agg_key != "First":
                    continue
                if isinstance(window, tuple) and window and window[0] in _VALUE_BEFORE_CHANGE_TAGS:
                    continue
                key = (agg_key, col_name, window)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def resolve_formula_builder_day(specs: list, symbol: str, bars: list) -> dict:
    """{(col_name, window): {symbol: {"First": value}}} for *specs*
    (derived_day_specs' output, pre-filtered by the caller to services.
    formula_engine.FORMULA_CODES only) — the Formula Builder analogue of
    build() above, resolved the way services.inception_value_before_change.
    resolve_formula_builder resolves its own per-symbol lookups: re-slicing
    *bars* (this ONE symbol's own ascending bar history, already fetched —
    no extra query) and calling services.inception_formula_builder_columns.
    compute_for_bars on that slice (reusing that module's own per-(symbol,
    slice-length) memoization for free).

    int window (VALUE_DAYS_AGO, already N+1 per services.strategy_engine.
    _build_compiled) -> the value at bars[len(bars) - window] — the OLDEST
    bar in a last-*window*-days slice, same indexing build()'s own
    int-window branch uses for a raw column — None if there isn't that
    much history fetched yet. (date, date) window (VALUE_ON_DATE) -> a
    linear scan for that exact trade_date, None if absent, same "not
    found" convention build()'s own tuple-window branch uses."""
    if not specs or not bars:
        return {}
    from services import inception_formula_builder_columns

    out: dict = {}
    for agg_key, col_name, window in specs:
        value = None
        if isinstance(window, tuple):
            target_date = window[0]
            idx = None
            for i, bar in enumerate(bars):
                if bar["trade_date"].isoformat() == target_date:
                    idx = i
                    break
            if idx is not None:
                v = inception_formula_builder_columns.compute_for_bars(symbol, bars[:idx + 1]).get(col_name)
                value = v if isinstance(v, (int, float)) else None
        elif window > 0 and len(bars) >= window:
            idx = len(bars) - window
            v = inception_formula_builder_columns.compute_for_bars(symbol, bars[:idx + 1]).get(col_name)
            value = v if isinstance(v, (int, float)) else None
        out.setdefault((col_name, window), {}).setdefault(symbol, {})[agg_key] = value
    return out


def extreme_specs_for_strategies(strategies: list) -> list:
    """[(col_name, driver_col_name, window, want_max), ...], deduped —
    raw_extreme_specs' own superset: every VALUE_AT_MAX_DAYS/VALUE_AT_MIN_
    DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES reference across
    *strategies*, WITHOUT raw_extreme_specs' "both sides raw" filter — a
    mixed-kind pair (e.g. a raw driver against a Formula Builder value
    column, or vice versa — confirmed in-scope by screens.formula_editor's
    own column-picker copy: "Either column can be a raw sheet column or
    another of this strategy's own columns") is included here. See
    extreme_needed_pairs/split_extreme_pairs_by_kind below for how a
    caller turns this into per-kind resolution work. *strategies*: every
    saved strategy, active or not, same reasoning as raw_extreme_specs'
    own docstring."""
    seen: set = set()
    out = []
    for strat in strategies:
        for col in strat.get("columns", []):
            compiled = get_compiled(col.get("formula", []))
            if compiled is None:
                continue
            for _, col_name, driver_col_name, window, want_max in compiled.extreme_specs:
                key = (col_name, driver_col_name, window, want_max)
                if key not in seen:
                    seen.add(key)
                    out.append(key)
    return out


def extreme_needed_pairs(specs: list) -> set:
    """{(col_name, window), ...} — every DISTINCT column+window a "daily"
    list is needed for across *specs* (raw_extreme_specs' or
    extreme_specs_for_strategies' own shape — the value side AND the
    driver side of each spec each contribute their own pair), mirroring
    the same `needed` set build_extreme already computes internally.
    Exposed so a caller can compute this ONCE, diff it against
    raw_extreme_specs' own (already-covered) pairs, and only resolve the
    REMAINDER via the per-kind resolvers below — see
    build_extreme_for_pairs/resolve_formula_builder_extreme/
    resolve_group_a_b_extreme."""
    needed: set = set()
    for col_name, driver_col_name, window, _want_max in specs:
        needed.add((col_name, window))
        needed.add((driver_col_name, window))
    return needed


def split_extreme_pairs_by_kind(pairs: set) -> tuple:
    """(raw_pairs, formula_builder_pairs, other_pairs) — partitions *pairs*
    ({(col_name, window), ...}, extreme_needed_pairs' own shape) by column
    kind: raw OHLCV (RAW_FIELDS), Formula Builder (services.formula_engine.
    FORMULA_CODES), or "everything else" — Group A/B, or a genuinely
    unresolvable name (e.g. a reference to another of the strategy's own
    output columns), both handled the same way by resolve_group_a_b_
    extreme below (an unresolvable name simply never appears in a day's
    metrics dict, producing an empty "daily" list — the same silent-blank
    fallback services.strategy_engine.evaluate_compiled already applies
    for a missing day_history entry, never a crash)."""
    from services.formula_engine import FORMULA_CODES

    raw_pairs, fb_pairs, other_pairs = set(), set(), set()
    for col_name, window in pairs:
        if col_name in RAW_FIELDS:
            raw_pairs.add((col_name, window))
        elif col_name in FORMULA_CODES:
            fb_pairs.add((col_name, window))
        else:
            other_pairs.add((col_name, window))
    return raw_pairs, fb_pairs, other_pairs


def build_extreme_for_pairs(pairs: set, symbol: str, bars: list) -> dict:
    """{(col_name, window): {symbol: {"daily": [(date_iso, value), ...]}}}
    for an EXPLICIT set of raw (col_name, window) *pairs* — not a spec
    list. Needed because a MIXED-kind extreme spec (e.g. VALUE_AT_MAX_DAYS(
    [CLOSE], [CWTO], N) — a raw value column driven by a Formula Builder
    column) means the raw SIDE of that spec must still resolve even though
    raw_extreme_specs' "both sides raw" filter drops the spec entirely —
    see extreme_needed_pairs/split_extreme_pairs_by_kind above for how a
    caller isolates just this remainder. Same per-pair int/date-tuple
    slicing build_extreme uses internally, duplicated (not shared/called)
    so build_extreme itself stays completely untouched by this fix."""
    if not pairs or not bars:
        return {}
    out: dict = {}
    for col_name, window in pairs:
        if col_name not in RAW_FIELDS:
            continue
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


def resolve_formula_builder_extreme(pairs: set, symbol: str, bars: list) -> dict:
    """{(col_name, window): {symbol: {"daily": [(date_iso, value), ...]}}}
    for Formula Builder (col_name, window) *pairs* (split_extreme_pairs_
    by_kind's own output) — the Formula Builder analogue of
    build_extreme_for_pairs above. int window -> every bar index in the
    last *window* bars; (date_from, date_to) window -> every bar index
    whose trade_date falls in that inclusive range. One services.
    inception_formula_builder_columns.compute_for_bars(symbol,
    bars[:idx + 1]) call per day IN the window — cost bounded by the
    window the user themselves chose, same cost model services.
    inception_value_before_change.resolve_formula_builder's own "auto"
    walk already has (no new unbounded cost)."""
    if not pairs or not bars:
        return {}
    from services import inception_formula_builder_columns

    out: dict = {}
    for col_name, window in pairs:
        if isinstance(window, tuple):
            date_from_s, date_to_s = window
            indices = [
                i for i, b in enumerate(bars)
                if date_from_s <= b["trade_date"].isoformat() <= date_to_s
            ]
        elif window > 0 and len(bars) >= window:
            indices = list(range(len(bars) - window, len(bars)))
        else:
            indices = []
        daily = []
        for idx in indices:
            v = inception_formula_builder_columns.compute_for_bars(symbol, bars[:idx + 1]).get(col_name)
            if isinstance(v, (int, float)):
                daily.append((bars[idx]["trade_date"].isoformat(), v))
        out[(col_name, window)] = {symbol: {"daily": daily}}
    return out


def group_a_b_date_from(day_specs: list, extreme_pairs, as_of_date: date):
    """The earliest date_from a SINGLE range_rows call needs to cover every
    Group A/B *day_specs* (derived_day_specs' own shape, already filtered
    by the caller to non-Formula-Builder columns) and *extreme_pairs*
    ({(col_name, window), ...}, split_extreme_pairs_by_kind's "other"
    bucket) — analogous to services.inception_value_before_change's own
    group_a_b_date_from, generalized for a window the user chose directly
    (VALUE_DAYS_AGO/VALUE_AT_MAX_DAYS's int N) rather than that module's
    fixed VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS cap. A (date, date) or
    (date_from, date_to) window's own date_from is used directly —
    trivial, no padding needed. An int window N is padded to calendar days
    using the SAME ratio services.inception_value_before_change already
    establishes for its own 252-trading-day/400-calendar-day cap (holiday/
    weekend density), plus the same slack so the OLDEST candidate day
    still has bars behind it. Returns None when neither *day_specs* nor
    *extreme_pairs* has anything needing a fetch."""
    if not day_specs and not extreme_pairs:
        return None
    from services.inception_value_before_change import (
        VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS, _DAILY_LOOKBACK_CALENDAR_DAYS,
    )

    windows = [window for _, _, window in day_specs] + [window for _, window in extreme_pairs]
    candidates = []
    for window in windows:
        if isinstance(window, tuple) and window:
            candidates.append(date.fromisoformat(window[0]))
        elif isinstance(window, int) and window > 0:
            calendar_days = math.ceil(
                window * _DAILY_LOOKBACK_CALENDAR_DAYS / VALUE_BEFORE_CHANGE_DAILY_MAX_DAYS
            ) + 30
            candidates.append(as_of_date - timedelta(days=calendar_days))
    return min(candidates) if candidates else None


def resolve_group_a_b_day(specs: list, as_of_date: date, range_response: dict = None, progress_cb=None) -> dict:
    """{(col_name, window): {symbol: {"First": value}}} for Group A/B
    *specs* (derived_day_specs' own shape, already filtered by the caller
    to non-Formula-Builder columns) — the Group A/B analogue of build()
    above, resolved the way services.inception_value_before_change.
    resolve_group_a_b resolves its own lookups: ONE services.
    inception_compute_service.range_rows call for the WHOLE instrument
    universe (reused via *range_response* when the caller already has one
    covering the needed span — see group_a_b_date_from above — or fetched
    fresh, sized via group_a_b_date_from, when omitted), then cheap
    in-memory dict lookups per symbol/day.

    A (date, date) window (VALUE_ON_DATE) is a direct by_date[date][symbol]
    lookup. An int window (VALUE_DAYS_AGO) means "N entries back in the
    GLOBAL sorted list of every trading day range_rows returned" — the
    SAME sorted-trading-day-index convention services.inception_value_
    before_change.resolve_group_a_b's own "auto" walk already establishes
    (not a per-symbol calendar, since Group A/B has no per-symbol bars
    list to slice the way raw/Formula Builder columns do)."""
    if not specs:
        return {}
    from services import inception_compute_service

    if range_response is None:
        date_from = group_a_b_date_from(specs, set(), as_of_date)
        range_response = inception_compute_service.range_rows(date_from, as_of_date, progress_cb=progress_cb)

    by_date: dict = {}
    for day in range_response.get("days", []):
        trade_date = date.fromisoformat(day["trade_date"])
        by_date[trade_date] = {s["symbol"]: s.get("metrics", {}) for s in day.get("stocks", [])}
    sorted_dates = sorted(by_date)
    as_of_idx = sorted_dates.index(as_of_date) if as_of_date in sorted_dates else len(sorted_dates)

    out: dict = {}
    for agg_key, col_name, window in specs:
        entries: dict = {}
        if isinstance(window, tuple):
            target_date = date.fromisoformat(window[0])
            for symbol, metrics in by_date.get(target_date, {}).items():
                v = metrics.get(col_name)
                entries[symbol] = {agg_key: v if isinstance(v, (int, float)) else None}
        elif window > 0:
            # Same indexing build()'s own int-window branch uses for a raw
            # column (bars[-window:][0]) — see this function's docstring.
            target_idx = as_of_idx - window + 1
            if 0 <= target_idx < len(sorted_dates):
                for symbol, metrics in by_date.get(sorted_dates[target_idx], {}).items():
                    v = metrics.get(col_name)
                    entries[symbol] = {agg_key: v if isinstance(v, (int, float)) else None}
        out[(col_name, window)] = entries
    return out


def resolve_group_a_b_extreme(pairs, as_of_date: date, range_response: dict = None, progress_cb=None) -> dict:
    """{(col_name, window): {symbol: {"daily": [(date_iso, value), ...]}}}
    for Group A/B (col_name, window) *pairs* (split_extreme_pairs_by_kind's
    "other" bucket) — same range_response reuse convention as
    resolve_group_a_b_day above. int window -> the last *window* entries
    of the GLOBAL sorted-trading-day list ending at as_of_date (same
    indexing resolve_group_a_b_day's own int-window branch uses); a
    (date_from, date_to) window -> every trading day in that inclusive
    range. Both read straight from the shared by_date/sorted_dates built
    from ONE range_rows response, iterating the symbol universe present on
    as_of_date (same convention services.inception_value_before_change.
    resolve_group_a_b's own current_by_symbol iteration uses)."""
    if not pairs:
        return {}
    from services import inception_compute_service

    if range_response is None:
        date_from = group_a_b_date_from([], pairs, as_of_date)
        range_response = inception_compute_service.range_rows(date_from, as_of_date, progress_cb=progress_cb)

    by_date: dict = {}
    for day in range_response.get("days", []):
        trade_date = date.fromisoformat(day["trade_date"])
        by_date[trade_date] = {s["symbol"]: s.get("metrics", {}) for s in day.get("stocks", [])}
    sorted_dates = sorted(by_date)
    as_of_idx = sorted_dates.index(as_of_date) if as_of_date in sorted_dates else len(sorted_dates)
    current_by_symbol = by_date.get(as_of_date, {})

    out: dict = {}
    for col_name, window in pairs:
        if isinstance(window, tuple):
            date_from_s, date_to_s = window
            window_dates = [d for d in sorted_dates if date_from_s <= d.isoformat() <= date_to_s]
        elif window > 0:
            start_idx = max(0, as_of_idx - window + 1)
            window_dates = sorted_dates[start_idx:as_of_idx + 1]
        else:
            window_dates = []
        entries: dict = {}
        for symbol in current_by_symbol:
            daily = []
            for d in window_dates:
                v = by_date.get(d, {}).get(symbol, {}).get(col_name)
                if isinstance(v, (int, float)):
                    daily.append((d.isoformat(), v))
            entries[symbol] = {"daily": daily}
        out[(col_name, window)] = entries
    return out
