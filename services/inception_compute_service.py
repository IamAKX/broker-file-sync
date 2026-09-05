"""Assembles Inception's View by Date / HMV rows entirely from the local
bar cache (services.inception_bars_store) — replaces what
api.inception_api.get_snapshot/get_hmv used to fetch from the backend
before Group A/B computation moved client-side (see services.
inception_formula_engine, services.inception_sync_service).

snapshot(as_of_date) -> rows: one row per synced instrument that has a bar
on as_of_date — raw OHLCV + every Group A/B value.

hmv(date_from, date_to) -> (as_of_date, rows): as_of_date is the latest
locally-synced trading day on or before date_to; rows are the same shape as
snapshot(as_of_date), with the range gate applied (a column blanked when
[date_from, as_of_date] doesn't cover what its formula needs — same rule
the backend's now-removed _apply_range_gate used, see
services.inception_formula_engine.required_lookback_start).

── Performance ───────────────────────────────────────────────────────────
Computing one instrument's full Group A/B history (a single forward pass
over every synced bar — see inception_formula_engine) is genuinely
expensive in pure Python for a long-lived instrument: ~0.3-0.5s for ~6500
days, and this client syncs ~213 canonical instruments, so a fully cold
walk across the whole universe is tens of seconds to ~2 minutes — this is
the real cost "moving Group A/B client-side" carries (flagged when that
move was made), not something a loading spinner alone fixes.

Two things make repeat loads fast without that tradeoff:
1. _row_cache memoizes the FINAL (as-of-date) row per (symbol, as_of_date,
   data+settings fingerprint) — not the full per-day history (that would be
   ~35MB/instrument x 213 instruments, multiple GB, not viable to keep
   resident). A session's typical pattern — reload the same/recent
   as-of-date repeatedly (toggling column filters, re-opening the screen,
   switching between View by Date and HMV for the same day) — becomes an
   O(1) dict lookup after the first walk instead of a full re-walk. Any
   change to the underlying bars (a sync) or to the formula parameters
   invalidates automatically (they're part of the fingerprint), no manual
   cache-clear needed.
2. Both entry points accept an optional progress_cb(done, total), invoked
   once per instrument, so a caller running this on a background thread
   (see screens/inception_hmv.py, screens/inception_view_by_date.py) can
   show real progress instead of the UI just looking frozen for however
   long a cold walk takes.
"""

from datetime import date

from services import inception_bars_store, inception_columns, inception_settings
from services.inception_formula_engine import compute_group_a, compute_group_b, required_lookback_start

_row_cache: dict[tuple, dict] = {}


def clear_cache() -> None:
    """Drops every cached row. Not required for correctness (the cache key
    already includes a data+settings fingerprint that invalidates itself),
    but frees memory after a big change — call after a sync completes so
    entries computed from pre-sync data don't just sit there unused."""
    _row_cache.clear()


def snapshot(as_of_date: date, progress_cb=None) -> list[dict]:
    """[{"symbol": ..., "values": {code: value}}, ...] for every locally-
    synced instrument with a bar on as_of_date. progress_cb(done, total),
    when given, is called once per instrument processed."""
    settings = inception_settings.load()
    symbols = inception_bars_store.available_symbols()
    rows = _compute_all_rows(symbols, as_of_date, settings, progress_cb)
    return [{"symbol": symbol, "values": values} for symbol, values, _first_traded in rows]


def hmv(date_from: date, date_to: date, progress_cb=None) -> tuple[date | None, list[dict]]:
    """Returns (as_of_date, rows). as_of_date is the latest locally-synced
    trading day on or before date_to; (None, []) if that falls before
    date_from or nothing's synced in range at all. progress_cb(done, total),
    when given, is called once per instrument processed."""
    as_of_date = inception_bars_store.latest_synced_date_on_or_before(date_to)
    if as_of_date is None or as_of_date < date_from:
        return None, []

    settings = inception_settings.load()
    symbols = inception_bars_store.available_symbols()
    rows = _compute_all_rows(symbols, as_of_date, settings, progress_cb)
    out = []
    for symbol, values, first_traded in rows:
        _apply_range_gate(values, first_traded, as_of_date, date_from, settings["week_window_days"])
        out.append({"symbol": symbol, "values": values})
    return as_of_date, out


def _compute_all_rows(symbols: list[str], as_of_date: date, settings: dict,
                      progress_cb=None) -> list[tuple[str, dict, date]]:
    """[(symbol, values, first_traded_date), ...], one entry per symbol in
    *symbols* with a bar on as_of_date (skipped entirely otherwise) — in
    *symbols*' own order, regardless of which symbols were cache hits vs.
    freshly computed or what order a parallel computation resolved them
    in. Shared by snapshot()/hmv() (see issue #25's note above for why the
    actual Group A/B walk for a cache MISS is now split off to services.
    inception_parallel_compute instead of computed inline here).

    progress_cb(done, total), when given, is called exactly once per
    symbol in *symbols* (total = len(symbols)) — as soon as that symbol's
    row is available, whether that's instantly (a bar-less/cached symbol,
    both resolved in the cheap first pass below) or whenever its
    computation completes (which, for a parallelized batch, is generally
    NOT in *symbols*' own order — this still ticks the same running
    (done, total) count either way, just not necessarily in symbol order
    for that middle stretch of ticks).
    """
    from services.inception_parallel_compute import compute_rows_parallel

    total = len(symbols)
    progress_state = {"done": 0}

    def _tick():
        progress_state["done"] += 1
        if progress_cb:
            progress_cb(progress_state["done"], total)

    # symbol -> (cache_key, first_traded_date, cached_values_or_None). Bars
    # fetching + the cache check are both cheap (an indexed SQLite query,
    # a dict lookup) — done here, sequentially, regardless of instrument
    # count; only a genuine cache MISS's Group A/B walk is expensive
    # enough to route through compute_rows_parallel below.
    prepared: dict[str, tuple] = {}
    to_compute: list[tuple] = []
    for symbol in symbols:
        bars = inception_bars_store.bars_for_symbol(symbol, date_to=as_of_date)
        if not bars or bars[-1]["trade_date"] != as_of_date:
            _tick()
            continue
        fingerprint = (
            len(bars), bars[-1]["trade_date"],
            settings["gap_threshold_pct"], settings["week_window_days"], settings["fifo_cap"],
        )
        cache_key = (symbol, fingerprint)
        cached = _row_cache.get(cache_key)
        first_traded = bars[0]["trade_date"]
        if cached is not None:
            prepared[symbol] = (cache_key, first_traded, dict(cached))   # copy — caller may mutate (range gate)
            _tick()
        else:
            prepared[symbol] = (cache_key, first_traded, None)
            to_compute.append((symbol, bars, settings))

    if to_compute:
        computed = compute_rows_parallel(to_compute, progress_cb=lambda done, tot: _tick())
        for symbol, values in computed.items():
            cache_key, first_traded, _ = prepared[symbol]
            _row_cache[cache_key] = values
            prepared[symbol] = (cache_key, first_traded, dict(values))

    return [
        (symbol, prepared[symbol][2], prepared[symbol][1])
        for symbol in symbols if symbol in prepared
    ]


def _compute_row(bars: list[dict], settings: dict) -> dict:
    last = bars[-1]
    return _compute_rows_for_days(bars, settings, [last])[last["trade_date"]]


def _compute_rows_for_days(bars: list[dict], settings: dict, target_bars: list[dict]) -> dict:
    """{trade_date: values} for every bar in *target_bars* (each must
    already be one of *bars*) — the same OHLC+Group A/B+Group B-alias
    shape _compute_row returns for a single day, generalized to several.
    Used by both _compute_row (target_bars = [the last bar]) and
    range_rows below (target_bars = every bar within the caller's
    requested date range) — compute_group_a/compute_group_b already
    return a value for EVERY date in one forward pass over *bars*
    regardless of how many dates the caller actually wants, so asking for
    more days here costs nothing beyond this dict-building loop."""
    group_a = compute_group_a(bars, week_window_days=settings["week_window_days"])
    group_b = compute_group_b(bars, threshold_pct=settings["gap_threshold_pct"], fifo_cap=settings["fifo_cap"])

    out = {}
    for bar in target_bars:
        d = bar["trade_date"]
        values = {
            "OPEN": bar["open"], "HIGH": bar["high"], "LOW": bar["low"], "CLOSE": bar["close"],
            "VOL": bar["volume"], "OPENINT": bar["open_interest"],
        }
        values.update(group_a.get(d, {}))

        for gap_code, area in group_b.get(d, {}).items():
            low_name, high_name, date_name = inception_columns.gap_metric_names(gap_code)
            if area is None:
                values[low_name] = values[high_name] = values[date_name] = None
            else:
                low, high, opened_on = area
                values[low_name] = low
                values[high_name] = high
                values[date_name] = opened_on.isoformat()

        # Bare Group B code (e.g. "DAY UF GUP 1") aliases its HIGH bound —
        # the single number most formulas want — matching what the backend
        # used to do in _build_rows before this moved client-side.
        for code in inception_columns.GROUP_B:
            high_key = f"{code} HIGH"
            if high_key in values:
                values[code] = values[high_key]

        out[d] = values
    return out


def range_rows(date_from: date, date_to: date, progress_cb=None) -> dict:
    """{"days": [{"trade_date": iso, "stocks": [{"symbol", "display_name",
    "metrics"}, ...]}, ...]} for every locally-synced instrument, for every
    trading day within [date_from, date_to] inclusive that instrument has a
    bar for — the exact shape api/lmv_snapshot_api.get_range returns, so it
    can be handed straight to services.formula_stats_engine.compute_stats
    unchanged. Powers Inception's Formula Stats screen (screens.
    inception_formula_stats): a strategy's own column formulas need a raw
    OHLC+Group A/B value PER DAY to aggregate Min/Max/Average/etc. across,
    the same way Live Master View's own Formula Stats screen aggregates
    over LmvDailySnapshot days. "display_name" is left equal to "symbol"
    (the raw, "_I"-suffixed canonical roll series name) — stripping that
    suffix for display is a screens-layer concern (screens.
    inception_view_by_date._display_symbol), not this service's.

    Reuses the SAME per-instrument compute_group_a/compute_group_b full-
    history forward pass snapshot()/hmv() already run (via
    _compute_rows_for_days) — extracting every day in the requested window
    from that already-computed date-keyed dict costs nothing extra (the
    forward pass walks every bar up to date_to regardless of how many
    days' worth of output get kept), so a wide date_from..date_to range is
    NOT N separate per-day walks, just a wider slice of a walk already
    being paid for. Not cached (unlike snapshot()/hmv()'s _row_cache) — a
    Formula Stats query's date range is arbitrary and reused far less
    predictably than "the current as-of-date", so a cache here is more
    likely to sit unused than to pay for itself. progress_cb(done, total),
    when given, is called once per instrument processed.

    No range-gate (see hmv()'s _apply_range_gate) applied here — that gate
    exists to keep a single as-of-date snapshot's shown value consistent
    with what the user's chosen window can justify; there's no equivalent
    reading of "the window" when the whole point is to aggregate a
    column's value ACROSS every day in it, so each day's value is simply
    whatever compute_group_a/b actually produced for it (None where an
    instrument's own history is too short, same as always). Flagged as a
    judgment call, not confirmed with the user, same footing as this
    module's other unconfirmed interpretations."""
    settings = inception_settings.load()
    symbols = inception_bars_store.available_symbols()
    by_date: dict = {}
    for i, symbol in enumerate(symbols):
        bars = inception_bars_store.bars_for_symbol(symbol, date_to=date_to)
        in_range = [b for b in bars if date_from <= b["trade_date"] <= date_to]
        if in_range:
            for d, values in _compute_rows_for_days(bars, settings, in_range).items():
                by_date.setdefault(d, []).append(
                    {"symbol": symbol, "display_name": symbol, "metrics": values}
                )
        if progress_cb:
            progress_cb(i + 1, len(symbols))
    return {
        "days": [
            {"trade_date": d.isoformat(), "stocks": stocks}
            for d, stocks in sorted(by_date.items())
        ]
    }


def _apply_range_gate(
    values: dict, first_traded: date, as_of_date: date, date_from: date, week_window_days: int,
) -> None:
    """Blanks out any Group A/B value in *values* whose formula needs more
    history than [date_from, as_of_date] covers. Mutates *values* in place
    — ported from the backend's (now-removed) inception_service.
    _apply_range_gate."""
    for code in inception_columns.GROUP_A:
        if code not in values:
            continue
        required_start = required_lookback_start(code, as_of_date, first_traded, week_window_days)
        if required_start is not None and date_from > required_start:
            values[code] = None

    for code in inception_columns.GROUP_B:
        raw_date = values.get(f"{code} DATE")
        if not raw_date:
            continue
        opened_on = date.fromisoformat(raw_date) if isinstance(raw_date, str) else raw_date
        if opened_on < date_from:
            values[code] = None
            values[f"{code} LOW"] = None
            values[f"{code} HIGH"] = None
            values[f"{code} DATE"] = None
