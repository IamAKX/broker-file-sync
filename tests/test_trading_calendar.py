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


# ── special trading days (e.g. Muhurat on a weekend) ─────────────────────

import pytest


@pytest.fixture
def special_days():
    trading_calendar.set_special_trading_days(set())
    yield trading_calendar.set_special_trading_days
    trading_calendar.set_special_trading_days(set())


def test_special_day_makes_weekend_a_trading_day(special_days):
    sunday = date(2026, 11, 8)
    assert sunday.weekday() == 6
    assert trading_calendar.is_trading_day(sunday, set()) is False
    special_days({sunday})
    assert trading_calendar.is_trading_day(sunday, set()) is True


def test_special_day_overrides_holiday_row(special_days):
    tuesday = date(2026, 7, 21)
    special_days({tuesday})
    assert trading_calendar.is_trading_day(tuesday, {tuesday}) is True


def test_special_day_does_not_affect_other_days(special_days):
    special_days({date(2026, 11, 8)})
    assert trading_calendar.is_trading_day(date(2026, 11, 7), set()) is False
    assert trading_calendar.is_trading_day(date(2026, 11, 9), set()) is True


def test_previous_trading_day_lands_on_special_sunday(special_days):
    special_days({date(2026, 11, 8)})
    assert trading_calendar.previous_trading_day(date(2026, 11, 9), set()) == date(2026, 11, 8)


def test_parse_ignores_malformed_entries():
    parsed = trading_calendar._parse_special_days(["2026-11-08", "garbage", None, 5])
    assert parsed == frozenset({date(2026, 11, 8)})
    assert trading_calendar._parse_special_days("nope") == frozenset()


def test_load_failure_keeps_previous_cache(special_days, monkeypatch):
    special_days({date(2026, 11, 8)})
    from services import config_store
    monkeypatch.setattr(config_store, "load_json", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")))
    assert trading_calendar.load_special_trading_days() == frozenset({date(2026, 11, 8)})


def test_get_holiday_set_refreshes_special_days(special_days, monkeypatch):
    from services import config_store
    monkeypatch.setattr(trading_calendar.holidays_api, "list_holidays", lambda y: [])
    monkeypatch.setattr(config_store, "load_json", lambda key, default: ["2026-11-07"])
    trading_calendar.get_holiday_set(2026, 2026)
    assert trading_calendar.is_trading_day(date(2026, 11, 7), set()) is True


def test_alert_gate_open_on_special_weekend(special_days):
    from datetime import datetime
    from services.strategy_alerts import alert_schedule
    sat = date(2026, 11, 7)
    assert alert_schedule._is_trading_day_peek(sat) is False
    special_days({sat})
    assert alert_schedule._is_trading_day_peek(sat) is True
