"""Tests for services/strategy_alerts/alert_schedule.py — the issue #31
gate ("alerts got triggered despite today being a non trading day and
time being non market hours"). See that module's own docstring for the
two independent checks (time-of-day window, trading-day) and why the
per-tick should_run_now() must never touch the network."""
import threading
from datetime import date, datetime
from datetime import time as dtime

import pytest

from services.strategy_alerts import alert_schedule


@pytest.fixture(autouse=True)
def _reset_alert_schedule():
    """Every test starts from a clean slate — alert_schedule's module-level
    caches would otherwise leak state between tests (a saved window, a
    resolved trading-day date) the same way state_store's would without
    conftest.py's own _isolate_disk_stores fixture."""
    alert_schedule.reload_cache()
    yield
    alert_schedule.reload_cache()


class _FixedDate(date):
    """Stands in for the datetime.date class alert_schedule imports, so
    date.today() (used by ensure_trading_day_known_async) returns a fixed,
    known day instead of whatever the real calendar date happens to be —
    lets a test's should_run_now(now=...) reliably line up with the day
    the background trading-day check actually resolved for."""
    _fixed: date

    @classmethod
    def today(cls):
        return cls._fixed


def _freeze_today(monkeypatch, d: date) -> None:
    fixed = type("_FixedDate", (_FixedDate,), {"_fixed": d})
    monkeypatch.setattr(alert_schedule, "date", fixed)


def _resolve_trading_day(monkeypatch, today: date, holidays: set | None = None) -> None:
    """Freezes "today" to *today* and runs ensure_trading_day_known_async
    to completion (real background thread, waited on) against a stubbed
    holiday set."""
    from services import trading_calendar
    _freeze_today(monkeypatch, today)
    monkeypatch.setattr(trading_calendar, "get_holiday_set", lambda y1, y2: holidays or set())
    done = threading.Event()
    alert_schedule.ensure_trading_day_known_async(on_ready=done.set)
    assert done.wait(timeout=2), "background trading-day check never resolved"


_TUESDAY = date(2026, 9, 8)     # an ordinary weekday, no holiday
_SUNDAY = date(2026, 9, 6)


# ── Time-of-day window: load/save/peek ───────────────────────────────────

def test_peek_before_any_load_returns_default_window():
    assert alert_schedule.peek_alert_window() == (dtime(9, 15), dtime(15, 30))


def test_load_returns_default_when_nothing_saved():
    assert alert_schedule.load_alert_window() == (dtime(9, 15), dtime(15, 30))


def test_save_then_load_round_trips():
    alert_schedule.save_alert_window(dtime(10, 0), dtime(14, 0))
    assert alert_schedule.load_alert_window() == (dtime(10, 0), dtime(14, 0))


def test_save_updates_the_cache_peek_sees_immediately():
    """save_alert_window() must not require a fresh load_alert_window()
    call afterward — should_run_now() (peek-only) has to see a just-saved
    window on its very next tick."""
    alert_schedule.save_alert_window(dtime(11, 0), dtime(13, 0))
    assert alert_schedule.peek_alert_window() == (dtime(11, 0), dtime(13, 0))


def test_load_is_cached_after_first_call(monkeypatch):
    from services import config_store

    calls = []
    real = config_store.load_json
    monkeypatch.setattr(config_store, "load_json", lambda key, default: calls.append(1) or real(key, default))

    alert_schedule.load_alert_window()
    alert_schedule.load_alert_window()
    alert_schedule.load_alert_window()

    assert calls == [1]   # only the first call actually hit config_store


def test_reload_cache_clears_the_window_cache():
    alert_schedule.save_alert_window(dtime(10, 0), dtime(14, 0))
    alert_schedule.reload_cache()
    assert alert_schedule.peek_alert_window() == (dtime(9, 15), dtime(15, 30))


# ── Trading-day gate ──────────────────────────────────────────────────────

def test_trading_day_resolves_true_on_an_ordinary_weekday(monkeypatch):
    _resolve_trading_day(monkeypatch, _TUESDAY)
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(10, 0))) is True


def test_trading_day_resolves_false_on_a_configured_holiday(monkeypatch):
    _resolve_trading_day(monkeypatch, _TUESDAY, holidays={_TUESDAY})
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(10, 0))) is False


def test_should_run_now_false_on_a_weekend_even_with_no_check_run_yet():
    # Weekday check is pure/local (no network, no async warm needed) —
    # never needs ensure_trading_day_known_async() to have run at all.
    assert alert_schedule.should_run_now(datetime.combine(_SUNDAY, dtime(10, 0))) is False


def test_should_run_now_fails_open_before_trading_day_check_resolves():
    """No ensure_trading_day_known_async() call yet for this date — must
    fail OPEN (treat as a trading day) rather than silently suppressing
    every alert because the background check hasn't run. See the module
    docstring's own rationale."""
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(10, 0))) is True


def test_ensure_trading_day_known_async_is_idempotent_same_day(monkeypatch):
    from services import trading_calendar

    _freeze_today(monkeypatch, _TUESDAY)
    calls = []
    monkeypatch.setattr(
        trading_calendar, "get_holiday_set", lambda y1, y2: calls.append(1) or set()
    )
    done1, done2 = threading.Event(), threading.Event()
    alert_schedule.ensure_trading_day_known_async(on_ready=done1.set)
    assert done1.wait(timeout=2)
    alert_schedule.ensure_trading_day_known_async(on_ready=done2.set)
    assert done2.wait(timeout=2)

    assert len(calls) == 1   # second call was a no-op, already resolved for today


def test_trading_day_check_failure_fails_open(monkeypatch):
    from services import trading_calendar

    _freeze_today(monkeypatch, _TUESDAY)

    def _boom(y1, y2):
        raise RuntimeError("offline")
    monkeypatch.setattr(trading_calendar, "get_holiday_set", _boom)

    done = threading.Event()
    alert_schedule.ensure_trading_day_known_async(on_ready=done.set)
    assert done.wait(timeout=2)

    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(10, 0))) is True


# ── should_run_now: combining both gates ─────────────────────────────────

def test_should_run_now_true_inside_window_on_trading_day(monkeypatch):
    _resolve_trading_day(monkeypatch, _TUESDAY)
    alert_schedule.save_alert_window(dtime(9, 15), dtime(15, 30))
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(12, 0))) is True


def test_should_run_now_false_before_window_start(monkeypatch):
    _resolve_trading_day(monkeypatch, _TUESDAY)
    alert_schedule.save_alert_window(dtime(9, 15), dtime(15, 30))
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(8, 0))) is False


def test_should_run_now_false_after_window_end(monkeypatch):
    _resolve_trading_day(monkeypatch, _TUESDAY)
    alert_schedule.save_alert_window(dtime(9, 15), dtime(15, 30))
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(16, 0))) is False


def test_should_run_now_respects_a_configured_custom_window(monkeypatch):
    """The whole point of issue #31 — a wider/narrower window than the
    NSE default must actually change what fires."""
    _resolve_trading_day(monkeypatch, _TUESDAY)
    alert_schedule.save_alert_window(dtime(9, 0), dtime(17, 0))   # extended hours
    # 16:30 is past the NSE default (15:30) but inside this custom window.
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(16, 30))) is True


def test_should_run_now_false_on_holiday_even_inside_the_window(monkeypatch):
    _resolve_trading_day(monkeypatch, _TUESDAY, holidays={_TUESDAY})
    alert_schedule.save_alert_window(dtime(9, 15), dtime(15, 30))
    assert alert_schedule.should_run_now(datetime.combine(_TUESDAY, dtime(12, 0))) is False
