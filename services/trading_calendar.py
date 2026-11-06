"""
Trading-day helpers shared by the background scheduler's jobs.

A "trading day" is any weekday that isn't a configured market holiday. Holiday
dates come from the server-backed Holidays screen (api.holidays_api), so
callers build a holiday set for the relevant year range and pass it in rather
than each function re-fetching it — that keeps this module free of network
calls, matching the Qt-free style of services.live_merge.LiveDataReader.
"""

from datetime import date, timedelta

from api import holidays_api

# Dates the market is open despite being a weekend (e.g. Diwali Muhurat
# trading on a Saturday/Sunday). Kept as a module-level cache so
# is_trading_day() stays pure/network-free: it is refreshed as a side effect
# of get_holiday_set(), which every caller already invokes right before
# is_trading_day()/previous_trading_day(). Empty by default, so behavior is
# unchanged until a user configures a special day.
SPECIAL_TRADING_DAYS_KEY = "special_trading_days"
_special_days: frozenset = frozenset()


def _parse_special_days(raw) -> frozenset:
    out = set()
    if isinstance(raw, list):
        for item in raw:
            try:
                out.add(date.fromisoformat(str(item)))
            except ValueError:
                continue   # ignore a malformed entry rather than lose the rest
    return frozenset(out)


def special_trading_days() -> frozenset:
    """The currently cached special trading days (no network)."""
    return _special_days


def set_special_trading_days(days) -> None:
    global _special_days
    _special_days = frozenset(days)


def load_special_trading_days() -> frozenset:
    """Refresh the cache from the settings store. Never raises: on any
    failure the previous cache is kept."""
    try:
        from services import config_store
        set_special_trading_days(_parse_special_days(config_store.load_json(SPECIAL_TRADING_DAYS_KEY, [])))
    except Exception:
        pass
    return _special_days


def save_special_trading_days(days) -> None:
    """Persist (raises ApiError/NetworkError like config_store.save_json) and
    update the cache."""
    from services import config_store
    ordered = sorted(set(days))
    config_store.save_json(SPECIAL_TRADING_DAYS_KEY, [d.isoformat() for d in ordered])
    set_special_trading_days(ordered)
    try:   # the alert gate caches today's answer; force a re-check
        from services.strategy_alerts import alert_schedule
        alert_schedule.invalidate_trading_day_cache()
    except Exception:
        pass


def get_holiday_set(year_from: int, year_to: int) -> set:
    """Return the set of holiday dates across [year_from, year_to] inclusive.

    Also refreshes the special-trading-day cache (see top of module) so a
    following is_trading_day() call honours weekend sessions."""
    holidays = {
        date.fromisoformat(h["holiday_date"])
        for year in range(year_from, year_to + 1)
        for h in holidays_api.list_holidays(year)
    }
    load_special_trading_days()
    return holidays


def is_trading_day(d: date, holidays: set) -> bool:
    if d in _special_days:
        return True   # explicitly configured session (e.g. Muhurat); overrides weekend/holiday
    return d.weekday() < 5 and d not in holidays


def previous_trading_day(d: date, holidays: set, limit_days: int = 30) -> date | None:
    """Walk backwards from the day before *d* until a trading day is found.

    Returns None if none is found within *limit_days* (guards against an
    unbounded loop if the holiday set is malformed).
    """
    cursor = d - timedelta(days=1)
    for _ in range(limit_days):
        if is_trading_day(cursor, holidays):
            return cursor
        cursor -= timedelta(days=1)
    return None
