"""
Fetches ExternalImport's data table from the "database" source mode —
stored historic uploads run through services.formula_engine — in the exact
same (headers, rows) shape services.file_reader.read_external_import()
returns for the "file" source mode.

Keeping both source modes' output shape identical lets any caller (the
ExternalImport View popup, the Live Master View merge) treat "file" and
"database" interchangeably without knowing which one is active.
"""

import threading
import time
from datetime import date, timedelta

from api import historic_api, holidays_api
from api.exceptions import ApiError, NetworkError
from services import config_store, formula_engine, formula_tokens
from services.error_logging import error_logger

FORMULA_LOOKBACK_DAYS = 100

# ── Reliability for the LMV "database" source ─────────────────────────────
# services.live_merge calls read_external_import_db_with_live_baseline on
# every slow-source refresh (~1s while COM is live). Three backend calls
# hide in _fetch: get_availability, list_holidays, get_range. The first two
# barely change (a new daily upload finalizes ~once/day; holidays for a
# past year never change), yet were re-fetched every tick — so one slow
# response (the 13.206.231.240 EC2 under load) surfaced as a "Read error:
# Read timed out" and an interrupted tick. Now: cache those two, use a
# short timeout so a stall fails fast, and on any API/network failure serve
# the last good result instead of blanking the whole merge.
_HOT_PATH_TIMEOUT_S = 8
_AVAILABILITY_TTL_S = 180        # a new daily upload lands ~once a day
_HOLIDAYS_TTL_S = 6 * 3600

_cache_lock = threading.Lock()
_availability_cache: dict = {}   # (date_from_iso, target_iso) -> (response, monotonic_ts)
_holidays_cache: dict = {}       # year -> (set[date], monotonic_ts)
_last_good: dict = {}            # target_iso -> (headers, rows, live_baselines)


def _reset_caches() -> None:
    """Drop every in-memory cache here — for tests (see tests/conftest.py's
    autouse fixture) and login/logout, so one user's cached availability/
    holidays/last-good result can't leak into the next."""
    with _cache_lock:
        _availability_cache.clear()
        _holidays_cache.clear()
        _last_good.clear()


def _cached_availability(date_from: date, target: date) -> dict:
    key = (date_from.isoformat(), target.isoformat())
    now = time.monotonic()
    with _cache_lock:
        hit = _availability_cache.get(key)
    if hit is not None and now - hit[1] < _AVAILABILITY_TTL_S:
        return hit[0]
    resp = historic_api.get_availability(date_from, target, timeout=_HOT_PATH_TIMEOUT_S)
    with _cache_lock:
        _availability_cache[key] = (resp, now)
    return resp


def _cached_holidays(year_from: int, year_to: int) -> set:
    now = time.monotonic()
    out: set = set()
    for year in range(year_from, year_to + 1):
        with _cache_lock:
            hit = _holidays_cache.get(year)
        if hit is not None and now - hit[1] < _HOLIDAYS_TTL_S:
            out |= hit[0]
            continue
        hs = {
            date.fromisoformat(h["holiday_date"])
            for h in holidays_api.list_holidays(year, timeout=_HOT_PATH_TIMEOUT_S)
        }
        with _cache_lock:
            _holidays_cache[year] = (hs, now)
        out |= hs
    return out


def _load_custom_defs() -> dict:
    """{code: tokens} for user-defined formulas (screens.formula_builder)
    that are actually computable (see
    formula_engine.is_computable_custom_formula) and don't collide with a
    built-in code — built-ins always go through the trusted, tested
    per-code path in formula_engine.py, never this one. First occurrence
    wins on duplicate codes.
    """
    formulas = config_store.load_json(formula_tokens.STORE_KEY, [])
    custom_defs = {}
    for f in formulas:
        code = (f.get("code") or "").strip()
        if not code or code in formula_engine.FORMULA_CODES or code in custom_defs:
            continue
        tokens = f.get("tokens") or []
        if formula_engine.is_computable_custom_formula(tokens):
            custom_defs[code] = tokens
    return custom_defs


def read_external_import_db(target: date = None,
                            snapshot_cache: dict | None = None) -> tuple[list, list]:
    """Return (headers, rows) computed as of ``target`` (default: today).

    Returns ([], []) if no historic data has been uploaded yet. Network/API
    errors propagate to the caller — this function has no UI concerns.
    """
    headers, rows, _ = _fetch(target, snapshot_cache)
    return headers, rows


def read_external_import_db_with_live_baseline(
        target: date = None, snapshot_cache: dict | None = None) -> tuple[list, list, dict]:
    """Like read_external_import_db, but also returns the per-symbol live-
    overlay baseline (see formula_engine.compute_live_baseline_for_symbol),
    keyed by the same ``symbol`` string as each row's own first column.

    Used only by the LMV's live source (services.live_merge) and the
    one-shot historical LMV (services.historic_lmv_merge) — never the static
    preview popup, which uses read_external_import_db and wants errors
    surfaced. On an API/network failure this serves the last good result
    for the same target date if there is one (an occasional slow backend
    then just means "these columns don't refresh this tick" rather than a
    "Read error" and an interrupted merge); the failure still raises if
    nothing has ever succeeded for that date.
    """
    target = target or date.today()
    try:
        result = _fetch(target, snapshot_cache)
    except (ApiError, NetworkError) as exc:
        with _cache_lock:
            stale = _last_good.get(target.isoformat())
        if stale is None:
            raise
        error_logger.warning(
            "ExternalImport DB fetch failed (%s) — serving last good result for %s",
            exc, target,
        )
        return stale
    with _cache_lock:
        _last_good.clear()
        _last_good[target.isoformat()] = result
    return result


def _fetch(target: date = None, snapshot_cache: dict | None = None) -> tuple[list, list, dict]:
    target = target or date.today()
    date_from = target - timedelta(days=FORMULA_LOOKBACK_DAYS)

    availability = _cached_availability(date_from, target)
    holidays = _cached_holidays(date_from.year, target.year)

    available_dates = sorted(
        date.fromisoformat(d["trade_date"])
        for d in availability.get("dates", []) if d.get("has_data")
    )
    if not available_dates:
        return [], [], {}

    latest_available = available_dates[-1]

    # Every date except the latest is a finalized historic upload that won't
    # change tick to tick — reuse it from the caller-owned cache (e.g. one
    # per live LiveDataReader session) instead of re-fetching over HTTP on
    # every ~1s slow-source refresh. The latest date is always re-fetched
    # fresh, same as before, in case it's still being amended.
    to_fetch = [
        d for d in available_dates
        if d == latest_available or snapshot_cache is None or d not in snapshot_cache
    ]
    fetched = {}
    if to_fetch:
        # ONE bulk request instead of one GET per missing date — issue #30:
        # on a cold cache (e.g. the first fetch of an LMV session), the old
        # per-date fan-out (up to 8 in flight at once, cycling through
        # every missing date in FORMULA_LOOKBACK_DAYS) meant up to ~70
        # individual HTTP round trips, which saturated the backend's small
        # gunicorn worker pool and starved whatever else was in flight at
        # that same moment (the live read itself, an N-Day strategy's own
        # day-history fetch) into a "Read timed out".
        #
        # get_range(N) returns the N MOST RECENT trade dates with data —
        # sized down to just len(to_fetch) whenever *to_fetch* is exactly
        # that trailing slice of *available_dates* (the overwhelming
        # common case: once the cache is warm, only the latest date is
        # ever missing, so this is a small, cheap request every tick, not
        # the full lookback window re-sent on every single one). Only a
        # genuinely cold cache — to_fetch equals available_dates in full —
        # falls back to requesting the whole window, which is exactly the
        # ~70-days-in-one-call trade this fix makes instead of ~70 separate
        # requests. If *to_fetch* were ever NOT a trailing slice (a mid-
        # window gap — not expected given the cache is only ever missing
        # dates that fell out of a previous, narrower lookback window or
        # were never fetched at all, but not guaranteed by construction),
        # the full-window request still covers it correctly.
        if to_fetch == available_dates[-len(to_fetch):]:
            range_days = len(to_fetch)
        else:
            range_days = len(available_dates)
        range_response = historic_api.get_range(range_days)
        to_fetch_set = set(to_fetch)
        for day_entry in range_response.get("days", []):
            d = date.fromisoformat(day_entry["trade_date"])
            if d in to_fetch_set:
                fetched[d] = day_entry

    raw_by_date = {}
    display_names = {}
    for d in available_dates:
        if d in fetched:
            snapshot = fetched[d]
            if snapshot_cache is not None and d != latest_available:
                snapshot_cache[d] = snapshot
        elif d in to_fetch:
            # Requested from get_range but not present in its response —
            # shouldn't happen (get_availability and get_range read the
            # same underlying table), but a date that was never cached AND
            # never came back is a snapshot_cache[d] KeyError below
            # otherwise. Same "blank rather than crash" convention as
            # everywhere else here — an empty day is what get_snapshot(d)
            # would have returned for a genuinely dataless date anyway.
            snapshot = {"stocks": []}
        else:
            snapshot = snapshot_cache[d]
        stocks = snapshot.get("stocks", [])
        raw_by_date[d] = {s["symbol"]: s.get("metrics", {}) for s in stocks}
        if d == latest_available:
            display_names = {s["symbol"]: s.get("display_name") or "" for s in stocks}

    custom_defs = _load_custom_defs()
    results, live_baselines, custom_results = formula_engine.compute_all_with_live_baseline(
        raw_by_date, target, holidays, custom_defs
    )
    if not results:
        return [], [], {}

    headers = ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES + list(custom_defs.keys())
    rows = []
    for symbol in sorted(results.keys()):
        values = results[symbol]
        custom_values = custom_results.get(symbol, {})
        row = [symbol, display_names.get(symbol, "")]
        row += [_rounded_or_blank(values.get(code)) for code in formula_engine.FORMULA_CODES]
        row += [_rounded_or_blank(custom_values.get(code)) for code in custom_defs]
        rows.append(row)
    return headers, rows, live_baselines


def _rounded_or_blank(v):
    return "" if v is None else round(v, 4)
