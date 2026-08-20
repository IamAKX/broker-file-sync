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
    rows = []
    for i, symbol in enumerate(symbols):
        values, _first_traded = _row_for_symbol(symbol, as_of_date, settings)
        if values is not None:
            rows.append({"symbol": symbol, "values": values})
        if progress_cb:
            progress_cb(i + 1, len(symbols))
    return rows


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
    rows = []
    for i, symbol in enumerate(symbols):
        values, first_traded = _row_for_symbol(symbol, as_of_date, settings)
        if values is not None:
            _apply_range_gate(values, first_traded, as_of_date, date_from, settings["week_window_days"])
            rows.append({"symbol": symbol, "values": values})
        if progress_cb:
            progress_cb(i + 1, len(symbols))
    return as_of_date, rows


def _row_for_symbol(symbol: str, as_of_date: date, settings: dict) -> tuple[dict | None, date | None]:
    """(values, first_traded_date) for *symbol* as of *as_of_date*, or
    (None, None) if it has no bar on that date. Fetching bars is a cheap
    indexed query either way; what's cached is the expensive part (the
    compute_group_a/compute_group_b walk) — see module docstring."""
    bars = inception_bars_store.bars_for_symbol(symbol, date_to=as_of_date)
    if not bars or bars[-1]["trade_date"] != as_of_date:
        return None, None

    fingerprint = (
        len(bars), bars[-1]["trade_date"],
        settings["gap_threshold_pct"], settings["week_window_days"], settings["fifo_cap"],
    )
    cache_key = (symbol, fingerprint)
    cached = _row_cache.get(cache_key)
    if cached is not None:
        return dict(cached), bars[0]["trade_date"]   # copy — caller may mutate (range gate)

    values = _compute_row(bars, settings)
    _row_cache[cache_key] = values
    return dict(values), bars[0]["trade_date"]


def _compute_row(bars: list[dict], settings: dict) -> dict:
    last = bars[-1]
    values = {
        "OPEN": last["open"], "HIGH": last["high"], "LOW": last["low"], "CLOSE": last["close"],
        "VOL": last["volume"], "OPENINT": last["open_interest"],
    }

    group_a = compute_group_a(bars, week_window_days=settings["week_window_days"])
    group_b = compute_group_b(bars, threshold_pct=settings["gap_threshold_pct"], fifo_cap=settings["fifo_cap"])
    d = last["trade_date"]
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

    # Bare Group B code (e.g. "DAY UF GUP 1") aliases its HIGH bound — the
    # single number most formulas want — matching what the backend used to
    # do in _build_rows before this moved client-side.
    for code in inception_columns.GROUP_B:
        high_key = f"{code} HIGH"
        if high_key in values:
            values[code] = values[high_key]

    return values


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
