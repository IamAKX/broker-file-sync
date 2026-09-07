"""Gates services.strategy_alerts.engine.evaluate_tick to real trading
hours on a real trading day (issue #31: "the alerts got triggered despite
today being a non trading day and time being non market hours" — the live
feed itself (Excel/DDE, or a broker file left sitting there) can keep
"ticking" with stale/leftover data well outside market hours or on a
weekend/holiday; apply_strategies/evaluate_tick have no idea what day or
time it actually is, they just evaluate whatever row data they're handed).

The only caller (screens.live_viewer.LiveViewerWindow.
_run_strategy_alert_checks) runs on the GUI thread on every live tick
(every ~200ms), so should_run_now() below must be pure, cheap, in-memory —
never a network call, same rule services.strategy_alerts.config_store's
peek_configs() exists to enforce for notification configs.

Two independent gates, both must pass for an alert to fire:

1. A user-configurable time-of-day window (load_alert_window/
   save_alert_window) — "in the future if the market timings get extended
   we should be able to configure it" (issue #31) — defaults to NSE's
   regular equity/futures session, 09:15-15:30. Cached in-memory after the
   first load (peek_alert_window() never touches the network), same
   load/peek split as config_store.load_configs()/peek_configs() and for
   the identical reason — this is read on every tick too.

2. Today being a real trading day (a weekday that isn't a configured
   market holiday) — never user-configurable, just correctness. Whether
   today is a trading day is fetched from the server (api.holidays_api,
   via services.trading_calendar — the same source services.
   scheduled_jobs already uses for its own "is today a trading day" gate)
   by ensure_trading_day_known_async(), using the same "one-time
   background load, GUI thread only ever peeks the cached result" idiom
   services.lmv_inception_fields.ensure_loaded_async uses — see that
   module's docstring for the full rationale. A weekend never needs that
   background load at all (it's a pure, local, always-known fact); until
   the load resolves for *today* specifically on a weekDAY (or if it
   fails), should_run_now() fails OPEN there — treats today as a trading
   day. One tick's worth of alert coverage on an actual holiday before the
   real answer arrives is a far
   smaller problem than silently suppressing every real alert on an
   actual trading day because of a slow/offline holiday fetch.
"""

import threading
from datetime import date, datetime
from datetime import time as dtime

from services import config_store

_WINDOW_KEY = "strategy_alert_active_window"
_DEFAULT_START = dtime(9, 15)
_DEFAULT_END = dtime(15, 30)

_window_cache: tuple | None = None   # (start: dtime, end: dtime) once loaded

_lock = threading.Lock()
_checked_date: date | None = None    # the date the trading-day check last resolved for
_is_trading_day = True               # fail-open until/unless proven otherwise (see module docstring)
_loading = False


def _parse_hhmm(value, default: dtime) -> dtime:
    if not value:
        return default
    try:
        hh, mm = str(value).split(":")
        return dtime(int(hh), int(mm))
    except (ValueError, TypeError):
        return default


# ── Time-of-day window ───────────────────────────────────────────────────

def load_alert_window() -> tuple:
    """Return (start, end) as datetime.time — from the server on first
    call, cached in-memory afterward (see module docstring)."""
    global _window_cache
    if _window_cache is None:
        saved = config_store.load_json(_WINDOW_KEY, {})
        _window_cache = (
            _parse_hhmm(saved.get("start"), _DEFAULT_START),
            _parse_hhmm(saved.get("end"), _DEFAULT_END),
        )
    return _window_cache


def peek_alert_window() -> tuple:
    """Like load_alert_window(), but NEVER touches the network — the
    default window if the cache hasn't been warmed yet. Safe to call from
    the GUI thread on every tick."""
    return _window_cache if _window_cache is not None else (_DEFAULT_START, _DEFAULT_END)


def save_alert_window(start: dtime, end: dtime) -> None:
    global _window_cache
    _window_cache = (start, end)
    config_store.save_json(_WINDOW_KEY, {
        "start": start.strftime("%H:%M"), "end": end.strftime("%H:%M"),
    })


# ── Trading-day gate ──────────────────────────────────────────────────────

def _safe_call(fn) -> None:
    try:
        fn()
    except Exception:
        pass


def _do_check(today: date, on_ready) -> None:
    global _is_trading_day, _checked_date, _loading
    from services import trading_calendar
    try:
        holidays = trading_calendar.get_holiday_set(today.year, today.year)
        result = trading_calendar.is_trading_day(today, holidays)
    except Exception:
        result = True   # fail open — see module docstring
    with _lock:
        _is_trading_day = result
        _checked_date = today
        _loading = False
    if on_ready:
        _safe_call(on_ready)


def ensure_trading_day_known_async(on_ready=None) -> None:
    """Kicks a one-time (per calendar date) background check of whether
    *today* is a real trading day. Idempotent for the same date — a second
    call the same day, or after the first has already resolved, is a
    no-op (but still fires on_ready if already known, so a caller can rely
    on it). on_ready() runs on the daemon thread — marshal to the GUI
    thread yourself, same convention as services.lmv_inception_fields.
    ensure_loaded_async (e.g. connect a Qt Signal's .emit as on_ready)."""
    global _loading
    today = date.today()
    with _lock:
        if _checked_date == today:
            if on_ready:
                _safe_call(on_ready)
            return
        if _loading:
            return
        _loading = True
    threading.Thread(
        target=_do_check, args=(today, on_ready), name="alert-trading-day-check", daemon=True,
    ).start()


def _is_trading_day_peek(today: date) -> bool:
    # A weekend never needs the background holiday fetch to have resolved —
    # it's a pure, local, always-available fact, unlike "is this weekday a
    # configured holiday". Checking it first means the fail-open default
    # below only ever has to cover the genuinely uncertain case (a weekday
    # whose holiday status isn't known yet), not "the app just started and
    # today happens to be a Saturday".
    if today.weekday() >= 5:
        return False
    with _lock:
        return _is_trading_day if _checked_date == today else True   # fail open — see module docstring


# ── The gate itself ───────────────────────────────────────────────────────

def should_run_now(now: datetime | None = None) -> bool:
    """True if alerts should evaluate right now — pure, cheap, safe to
    call on the GUI thread on every tick. Call
    ensure_trading_day_known_async() separately (once, e.g. when the Live
    Master View is set up) to keep gate #2 current."""
    now = now or datetime.now()
    if not _is_trading_day_peek(now.date()):
        return False
    start, end = peek_alert_window()
    return start <= now.time() <= end


def reload_cache() -> None:
    """Drop every in-memory cache here so the next check re-fetches —
    call on login/logout (services.strategy_alerts.config_store.
    reload_cache's own call site, app_window.py's reload_per_user_data)
    so a second user on the same running app instance doesn't keep
    evaluating alerts against the first user's saved window."""
    global _window_cache, _checked_date, _is_trading_day, _loading
    _window_cache = None
    with _lock:
        _checked_date = None
        _is_trading_day = True
        _loading = False
