import sys
from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    return config_store


class _FakeClock:
    def __init__(self, dt):
        self.dt = dt

    def __call__(self):
        return self.dt


def _make_scheduler(qapp, clock, fired_log):
    from services.scheduler import Scheduler
    jobs = {
        tid: (lambda tid=tid: fired_log.append(tid))
        for tid in ("availability_check", "lmv_check", "historic_save")
    }
    return Scheduler(jobs=jobs, now_provider=clock)


def test_does_not_fire_before_configured_time(qapp, store):
    fired = []
    clock = _FakeClock(datetime(2026, 7, 20, 8, 0))
    sched = _make_scheduler(qapp, clock, fired)
    sched._tick()
    assert fired == []


def test_fires_once_when_time_passes(qapp, store):
    fired = []
    clock = _FakeClock(datetime(2026, 7, 20, 8, 56))
    sched = _make_scheduler(qapp, clock, fired)
    sched._tick()
    assert fired == ["availability_check"]

    sched._tick()   # same tick again shortly after — must not re-fire
    assert fired == ["availability_check"]


def test_fires_each_trigger_as_its_time_passes(qapp, store):
    fired = []
    clock = _FakeClock(datetime(2026, 7, 20, 8, 0))
    sched = _make_scheduler(qapp, clock, fired)

    sched._tick()
    assert fired == []

    clock.dt = datetime(2026, 7, 20, 8, 56)
    sched._tick()
    assert fired == ["availability_check"]

    clock.dt = datetime(2026, 7, 20, 15, 41)
    sched._tick()
    assert fired == ["availability_check", "lmv_check"]

    clock.dt = datetime(2026, 7, 20, 15, 46)
    sched._tick()
    assert fired == ["availability_check", "lmv_check", "historic_save"]

    clock.dt = datetime(2026, 7, 20, 23, 0)
    sched._tick()
    assert fired == ["availability_check", "lmv_check", "historic_save"]   # no re-fires


def test_restart_does_not_refire_already_fired_trigger(qapp, store):
    fired = []
    clock = _FakeClock(datetime(2026, 7, 20, 9, 0))
    sched1 = _make_scheduler(qapp, clock, fired)
    sched1._tick()
    assert fired == ["availability_check"]

    # Simulate an app restart: a brand new Scheduler loads persisted last_fired
    sched2 = _make_scheduler(qapp, clock, fired)
    sched2._tick()
    assert fired == ["availability_check"]   # unchanged — no duplicate fire


def test_fires_again_on_a_new_day(qapp, store):
    fired = []
    clock = _FakeClock(datetime(2026, 7, 20, 9, 0))
    sched = _make_scheduler(qapp, clock, fired)
    sched._tick()
    assert fired == ["availability_check"]

    clock.dt = datetime(2026, 7, 21, 9, 0)
    sched._tick()
    assert fired == ["availability_check", "availability_check"]


def test_disabled_trigger_does_not_fire(qapp, store):
    from services import trigger_config
    configs = trigger_config.load_trigger_configs()
    for c in configs:
        if c.id == "availability_check":
            c.system_enabled = False
    trigger_config.save_trigger_configs(configs)

    fired = []
    clock = _FakeClock(datetime(2026, 7, 20, 9, 0))
    sched = _make_scheduler(qapp, clock, fired)
    sched._tick()
    assert fired == []
