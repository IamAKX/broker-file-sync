from datetime import date

from services import trading_calendar


def test_weekday_no_holiday_is_trading_day():
    monday = date(2026, 7, 20)
    assert monday.weekday() == 0
    assert trading_calendar.is_trading_day(monday, holidays=set()) is True


def test_saturday_is_not_trading_day():
    saturday = date(2026, 7, 18)
    assert saturday.weekday() == 5
    assert trading_calendar.is_trading_day(saturday, holidays=set()) is False


def test_sunday_is_not_trading_day():
    sunday = date(2026, 7, 19)
    assert sunday.weekday() == 6
    assert trading_calendar.is_trading_day(sunday, holidays=set()) is False


def test_holiday_weekday_is_not_trading_day():
    tuesday = date(2026, 7, 21)
    assert trading_calendar.is_trading_day(tuesday, holidays={tuesday}) is False


def test_previous_trading_day_skips_weekend():
    monday = date(2026, 7, 20)
    prev = trading_calendar.previous_trading_day(monday, holidays=set())
    assert prev == date(2026, 7, 17)   # Friday


def test_previous_trading_day_skips_holiday_and_weekend():
    monday = date(2026, 7, 20)
    friday = date(2026, 7, 17)
    prev = trading_calendar.previous_trading_day(monday, holidays={friday})
    assert prev == date(2026, 7, 16)   # Thursday


def test_previous_trading_day_returns_none_if_exhausted():
    d = date(2026, 7, 20)
    all_holidays = {d.fromordinal(o) for o in range(d.toordinal() - 40, d.toordinal())}
    assert trading_calendar.previous_trading_day(d, holidays=all_holidays, limit_days=30) is None
