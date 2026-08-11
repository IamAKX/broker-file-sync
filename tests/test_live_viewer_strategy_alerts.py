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


def test_multiple_events_on_one_tick_batch_into_one_notification_per_channel(lmv):
    """Two stocks triggering on the same tick must not become two separate
    notifications per channel — see services/strategy_alerts/messages.py's
    render_batch_* and this method's own docstring for why (this was the
    literal cause of the app going "Not Responding" before Email's send()
    moved off the GUI thread, and is unpleasant even off-thread: N tray
    toasts and N sounds back to back for one market move)."""
    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()
    rows = [_row(signal=1, symbol="INFY"), _row(signal=1, symbol="TCS")]

    lmv._run_strategy_alert_checks([STRATEGY], rows, {}, {})   # tick 1: both go "pending"
    lmv._run_strategy_alert_checks([STRATEGY], rows, {}, {})   # tick 2: both fire ENTRY

    calls = lmv._controller._notifier.calls
    # Default enabled channels are {"system", "email"} — one batched notify()
    # call per channel group, not one per event (would have been 2 x 2 = 4).
    assert len(calls) == 2
    channel_sets = [c["channels"] for c in calls]
    assert {"system"} in channel_sets
    assert {"email"} in channel_sets

    system_call = next(c for c in calls if c["channels"] == {"system"})
    email_call = next(c for c in calls if c["channels"] == {"email"})

    assert system_call["title"] == email_call["title"] == "2 Signals — 2 New Entries"
    # System's body is the compact per-kind summary line — both symbols, no
    # per-stock detail (that's what makes it fit the tray's space limits).
    assert "INFY" in system_call["message"] and "TCS" in system_call["message"]
    assert "Sector" not in system_call["message"]
    # Email's body is the full, unabridged per-stock detail for both.
    assert "INFY" in email_call["message"] and "TCS" in email_call["message"]
    assert email_call["message"].count("Sector:") == 2


def test_single_event_is_not_batched(lmv):
    """Exactly one event still goes out via the plain single-event path —
    same title/message as before batching existed, no "1 Signals —" framing."""
    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})
    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})

    calls = lmv._controller._notifier.calls
    assert len(calls) == 1
    assert "Signals —" not in calls[0]["title"]
    assert calls[0]["channels"] == {"system", "email"}


def test_events_flush_state_to_disk(lmv):
    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})

    alerts_state_store.reset_for_user_switch()  # drop in-memory cache, force reload from disk
    assert alerts_state_store.get_open_signals()  # the "open" entry signal survived a flush


def test_entry_event_dispatches_backend_sync(lmv, monkeypatch):
    """Each real event this tick must be pushed to the durable backend store
    (services/strategy_alerts/backend_sync.py) — independent of, and in
    addition to, the notifier delivery covered by the tests above."""
    from services.strategy_alerts import backend_sync

    calls = []
    monkeypatch.setattr(backend_sync, "sync_event", lambda event: calls.append(event))

    alerts_config_store.save_config("strat-1", _config())
    lmv._controller = _FakeController()

    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})   # tick 1: pending
    lmv._run_strategy_alert_checks([STRATEGY], [_row(signal=1)], {}, {})   # tick 2: entry fires

    assert len(calls) == 1
    assert calls[0].kind == "entry"
