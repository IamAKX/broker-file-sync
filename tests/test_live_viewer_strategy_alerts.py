"""
Tests for LiveViewerWindow._run_strategy_alert_checks — the glue between
services.strategy_alerts.engine and NotificationService. The engine's own
state machine (trigger/debounce/lifecycle) is exhaustively covered in
tests/test_strategy_alerts_engine.py; these tests only check the wiring:
configs get loaded, events get delivered through the controller's notifier
with the right channel filter, and state gets flushed.
"""
import sys

import pytest
from PySide6.QtWidgets import QApplication

from services.strategy_alerts import config_store as alerts_config_store
from services.strategy_alerts import state_store as alerts_state_store
from services.strategy_alerts.models import new_metric, new_notification_config


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp):
    from screens.live_viewer import LiveViewerWindow
    return LiveViewerWindow("", "", "", [])


STRATEGY = {"id": "strat-1", "name": "PWHBUY", "active": True, "columns": []}


def _row(signal=0, symbol="INFY"):
    return {"Scrip Name": symbol, "Signal": signal, "Current": 100, "High": 100, "Low": 100}


def _config():
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["debounce_minutes"] = 0  # fires on the very first true tick for this test
    cfg["trigger_condition"] = [
        {"type": "col", "value": "Signal"}, {"type": "op", "value": ">"}, {"type": "num", "value": "0"},
    ]
    cfg["metrics"] = [new_metric("Stop Loss", "stop_loss", [{"type": "num", "value": "90"}])]
    return cfg


class _FakeNotifier:
    def __init__(self):
        self.calls = []

    def notify(self, title, message, action=None, level=None, timeout_ms=10_000, channels=None):
        self.calls.append({"title": title, "message": message, "channels": channels})


class _FakeController:
    def __init__(self):
        self._notifier = _FakeNotifier()


def test_no_configs_is_a_noop(lmv):
    lmv._controller = _FakeController()
    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})
    assert lmv._controller._notifier.calls == []


def test_no_controller_does_not_raise(lmv):
    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = None
    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})  # must not raise


def test_entry_event_delivered_through_controller_notifier(lmv):
    # debounce_minutes=0 still requires the trigger to be seen true on one
    # tick (starts "pending") before a *later* tick can fire the entry — see
    # services/strategy_alerts/engine.py's state machine — so this calls
    # twice, matching how test_strategy_alerts_engine.py exercises it.
    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})
    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})

    calls = lmv._controller._notifier.calls
    assert len(calls) == 1
    assert "PWHBUY" in calls[0]["title"]
    assert calls[0]["message"]


def test_delivery_respects_enabled_channels(lmv, monkeypatch):
    from services import notification_channels
    monkeypatch.setattr(notification_channels, "enabled_channel_ids", lambda: {"system"})

    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})
    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})

    assert lmv._controller._notifier.calls[0]["channels"] == {"system"}


def test_disabled_config_produces_no_notification(lmv):
    cfg = _config()
    cfg["enabled"] = False
    alerts_config_store.save_config("strat-1", cfg)
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})

    assert lmv._controller._notifier.calls == []


def test_events_flush_state_to_disk(lmv):
    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})

    alerts_state_store.reset_for_user_switch()  # drop in-memory cache, force reload from disk
    assert alerts_state_store.get_open_signals()  # the "open" entry signal survived a flush
