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


def get_holiday_set(year_from: int, year_to: int) -> set:
    """Return the set of holiday dates across [year_from, year_to] inclusive."""
    return {
        date.fromisoformat(h["holiday_date"])
        for year in range(year_from, year_to + 1)
        for h in holidays_api.list_holidays(year)
    }


def is_trading_day(d: date, holidays: set) -> bool:
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
