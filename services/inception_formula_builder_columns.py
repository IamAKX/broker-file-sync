"""Ports LMV's ~56 built-in "Formula Builder" columns (services.
formula_engine — MT, MB, DT, DB, PMH/PML/PMC, the camarilla pivot ladders,
week/month tops-bottoms, the 3 pivot points, ...) onto Inception's
historical EOD bars, so HMV can show the same technical columns LMV's
Formula Builder screen computes for live/uploaded data, over the historical
dataset instead.

services.formula_engine.compute_for_symbol is already pure/offline — it just
needs history shaped as {trade_date: {metric_name: value}} using its own
metric names (Open/High/Low/Close/AvgRate/Quantity/DiffPcnt). Inception bars
(services.inception_bars_store) only carry OHLCV + open interest — no
AvgRate (average traded price) or DiffPcnt, so the handful of codes that
need those (PATP/CWATP/PWATP/CMATP/PMATP, DAY TO/PDTO/CWTO/PWTO — turnover
and average-traded-price figures) come back None here, the exact same
"blank rather than crash" fallback formula_engine already uses for any
missing input. Not a bug — this dataset just doesn't carry that field.
Every other code (the large majority: high/low/close-only period
tops/bottoms, camarilla pivots, week/month % change, the 3 pivot points)
computes for real from Inception's own OHLC bars.

── Holiday-awareness ────────────────────────────────────────────────────────
formula_engine.StockHistory needs a *holidays* set to tell an expected
non-trading day apart from a genuine data gap (see its own docstring) —
Inception has no separate holiday-calendar table wired up on this client, so
it's derived here instead, per instrument, straight from that instrument's
own bars: any weekday between its first and last synced bar with no bar on
it is treated as a holiday. That's exactly right for this purpose (Inception
bars only exist on real NSE trading days to begin with), and costs nothing
extra worth worrying about — a linear walk over one instrument's own date
range, far cheaper than the Group A/B forward pass already paid for the
same bars (see services.inception_formula_engine).

── Caching ───────────────────────────────────────────────────────────────────
Same shape as services.inception_compute_service._row_cache (see that
module's docstring for the rationale) — memoizes by (symbol, len(bars),
latest trade_date) so repeat HMV loads for the same as-of-date are an O(1)
lookup instead of a re-walk. clear_cache() is wired into the same
sync-success path that clears inception_compute_service's cache (screens.
inception_settings) since both go stale the same way.
"""

from datetime import timedelta

from services import formula_engine

_cache: dict[tuple, dict] = {}


def clear_cache() -> None:
    _cache.clear()


def _holidays_for(bars: list[dict]) -> set:
    if not bars:
        return set()
    bar_dates = {b["trade_date"] for b in bars}
    first, last = bars[0]["trade_date"], bars[-1]["trade_date"]
    holidays = set()
    d = first
    while d <= last:
        if d.weekday() < 5 and d not in bar_dates:
            holidays.add(d)
        d += timedelta(days=1)
    return holidays


# Codes services.formula_engine can't compute from Inception's own bars at
# all — see this module's own docstring: no AvgRate/DiffPcnt input, since
# rows_by_date below never sets them. Admin Controls > Inception Sync
# (services.inception_bars_store.LMV_METRIC_COLUMNS) can populate these
# directly on the bar itself instead, copied from LMV's own archive
# (hari_dss.LmvDailySnapshot) rather than recomputed here — a different
# instrument's own daily turnover/ATP figure isn't something Inception's
# bars have the inputs to derive independently, so this takes LMV's
# already-computed answer as-is (see app/services/
# inception_admin_sync_service.py in the backend repo) instead of trying
# to reproduce it and risking drift from two slightly different
# implementations of the same math. code -> bar dict key.
_LMV_SYNCED_CODE_MAP = {
    "PATP": "patp", "CWATP": "cwatp", "PWATP": "pwatp",
    "CMATP": "cmatp", "PMATP": "pmatp",
    "DAY TO": "day_to", "PDTO": "pdto", "CWTO": "cwto", "PWTO": "pwto",
}


def compute_for_bars(symbol: str, bars: list[dict]) -> dict:
    """{code: value} for every services.formula_engine.FORMULA_CODES code,
    as of the LAST bar in *bars* — ascending-by-trade_date, same shape
    services.inception_bars_store.bars_for_symbol returns. {} for no bars.

    _LMV_SYNCED_CODE_MAP's own codes (PATP/CWATP/etc.) are overridden
    with that same last bar's own synced value (None if Admin Controls >
    Inception Sync hasn't run for this instrument/date, same "blank
    rather than crash" convention as everywhere else here) AFTER
    formula_engine's own computation, not instead of calling it — the
    override always wins for these specific codes regardless of what
    formula_engine returned for them. "Avg Rate" is added the same way —
    a new field, not a FORMULA_CODES override, since formula_engine has
    no output of that name to collide with.
    """
    if not bars:
        return {}

    target = bars[-1]["trade_date"]
    cache_key = (symbol, len(bars), target)
    cached = _cache.get(cache_key)
    if cached is not None:
        return dict(cached)

    rows_by_date = {
        b["trade_date"]: {
            "Open": b["open"], "High": b["high"], "Low": b["low"],
            "Close": b["close"], "Quantity": b["volume"],
        }
        for b in bars
    }
    hist = formula_engine.StockHistory(rows_by_date, _holidays_for(bars))
    values = formula_engine.compute_for_symbol(hist, target)
    for code, bar_key in _LMV_SYNCED_CODE_MAP.items():
        values[code] = bars[-1].get(bar_key)
    values["Avg Rate"] = bars[-1].get("avg_rate")
    _cache[cache_key] = values
    return dict(values)
