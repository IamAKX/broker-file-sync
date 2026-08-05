from datetime import datetime, timedelta

from services.strategy_alerts import state_store
from services.strategy_alerts.engine import evaluate_tick
from services.strategy_alerts.models import (
    EVENT_ENTRY,
    EVENT_STOP_OUT,
    EVENT_TARGET,
    new_metric,
    new_notification_config,
)

STRATEGY = {"id": "strat-1", "name": "PWHBUY", "active": True, "columns": []}
T0 = datetime(2026, 8, 3, 9, 30, 0)


def _num(v):
    return {"type": "num", "value": str(v)}


def _col(name):
    return {"type": "col", "value": name}


def _gt_condition(col_name, threshold):
    return [_col(col_name), {"type": "op", "value": ">"}, _num(threshold)]


def _row(signal=0, price=100, high=None, low=None, symbol="INFY"):
    return {
        "Scrip Name": symbol,
        "Signal": signal,
        "Current": price,
        "High": high if high is not None else price,
        "Low": low if low is not None else price,
    }


def _make_config(debounce_minutes=2, stop_loss=95, target=110, direction="BUY"):
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["direction"] = direction
    cfg["debounce_minutes"] = debounce_minutes
    cfg["trigger_condition"] = _gt_condition("Signal", 0)
    cfg["metrics"] = [
        new_metric("Stop Loss", "stop_loss", [_num(stop_loss)]),
        new_metric("Target 1", "target", [_num(target)]),
    ]
    return cfg


def test_no_events_when_condition_never_true():
    configs = {"strat-1": _make_config()}
    events = evaluate_tick([STRATEGY], configs, [_row(signal=0)], now=T0)
    assert events == []
    assert state_store.get_open_signals() == {}


def test_disabled_config_is_skipped():
    cfg = _make_config()
    cfg["enabled"] = False
    events = evaluate_tick([STRATEGY], {"strat-1": cfg}, [_row(signal=1)], now=T0)
    assert events == []
    assert state_store.get_open_signals() == {}


def test_condition_true_starts_pending_without_firing():
    configs = {"strat-1": _make_config(debounce_minutes=2)}
    events = evaluate_tick([STRATEGY], configs, [_row(signal=1)], now=T0)

    assert events == []
    signals = state_store.get_open_signals()
    assert len(signals) == 1
    signal = next(iter(signals.values()))
    assert signal["state"] == "pending"


def test_condition_false_before_debounce_clears_pending():
    configs = {"strat-1": _make_config(debounce_minutes=2)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=0)], now=T0 + timedelta(minutes=1))

    assert state_store.get_open_signals() == {}


def test_condition_true_through_debounce_fires_entry():
    configs = {"strat-1": _make_config(debounce_minutes=2, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=101)], now=T0 + timedelta(minutes=3)
    )

    assert len(events) == 1
    event = events[0]
    assert event.kind == EVENT_ENTRY
    assert event.symbol == "INFY"
    assert event.payload["entry_price"] == 101
    assert event.payload["metrics"]
    stop_loss = next(m for m in event.payload["metrics"].values() if m["role"] == "stop_loss")
    assert stop_loss["value"] == 95
    assert "title" in event.payload and "message" in event.payload

    signals = state_store.get_open_signals()
    assert len(signals) == 1
    assert next(iter(signals.values()))["state"] == "open"


def test_duplicate_trigger_while_open_is_ignored():
    configs = {"strat-1": _make_config(debounce_minutes=2)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=3))
    # Signal is now "open" — the trigger firing again for the same symbol
    # must not create a second pending/open entry.
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=4)
    )

    assert events == []
    assert len(state_store.get_open_signals()) == 1


def test_target_hit_emits_event_and_stays_open_until_resolved():
    configs = {"strat-1": _make_config(debounce_minutes=2, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=3))

    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=111, high=111)],
        now=T0 + timedelta(minutes=5),
    )

    assert len(events) == 1
    assert events[0].kind == EVENT_TARGET
    assert events[0].payload["metric_name"] == "Target 1"
    # Only one Target metric exists and it's now achieved -> signal resolves.
    assert state_store.get_open_signals() == {}
    history = state_store.get_alert_history()
    assert len(history) == 1
    assert history[0]["resolution"] == "all_targets_achieved"


def test_stop_loss_hit_resolves_as_stopped_out():
    configs = {"strat-1": _make_config(debounce_minutes=2, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=3))

    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=94, low=94)],
        now=T0 + timedelta(minutes=5),
    )

    assert len(events) == 1
    assert events[0].kind == EVENT_STOP_OUT
    assert events[0].payload["metric_name"] == "Stop Loss"
    assert state_store.get_open_signals() == {}
    history = state_store.get_alert_history()
    assert history[0]["resolution"] == "stopped_out"


def test_sell_direction_inverts_target_and_stop_loss_crossings():
    configs = {
        "strat-1": _make_config(debounce_minutes=2, stop_loss=105, target=90, direction="SELL")
    }
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=3))

    # For a SELL, price dropping to/below target is a win.
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=89, low=89)],
        now=T0 + timedelta(minutes=5),
    )
    assert len(events) == 1
    assert events[0].kind == EVENT_TARGET


def test_running_high_low_tracked_while_open():
    configs = {"strat-1": _make_config(debounce_minutes=2, stop_loss=50, target=200)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=3))

    evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=120, high=120, low=95)],
        now=T0 + timedelta(minutes=4),
    )

    signal = next(iter(state_store.get_open_signals().values()))
    assert signal["running_high"] == 120
    assert signal["running_low"] == 95


def test_multiple_targets_fire_subsequent_notifications_one_per_hit():
    # Matches the spreadsheet's "Target 1 / Target 2 / Target 3" fields:
    # each is its own metric, each gets its own follow-up notification when
    # crossed, and the signal only resolves once ALL of them are achieved —
    # not on the first one.
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["direction"] = "BUY"
    cfg["debounce_minutes"] = 0
    cfg["trigger_condition"] = _gt_condition("Signal", 0)
    cfg["metrics"] = [
        new_metric("Stop Loss", "stop_loss", [_num(90)]),
        new_metric("Target 1", "target", [_num(110)]),
        new_metric("Target 2", "target", [_num(120)]),
        new_metric("Target 3", "target", [_num(130)]),
    ]
    configs = {"strat-1": cfg}

    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    events = evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=1))
    assert len(events) == 1 and events[0].kind == EVENT_ENTRY

    # Target 1 hit — one notification, signal stays open (2 targets left).
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=111, high=111)], now=T0 + timedelta(minutes=2),
    )
    assert len(events) == 1
    assert events[0].kind == EVENT_TARGET
    assert events[0].payload["metric_name"] == "Target 1"
    assert state_store.get_open_signals()  # still open
    assert state_store.get_alert_history() == []  # not resolved yet

    # Target 2 hit — a second, distinct notification, still open (1 target left).
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=121, high=121)], now=T0 + timedelta(minutes=3),
    )
    assert len(events) == 1
    assert events[0].kind == EVENT_TARGET
    assert events[0].payload["metric_name"] == "Target 2"
    assert state_store.get_open_signals()
    assert state_store.get_alert_history() == []

    # Target 3 hit — final notification, and only now does it resolve.
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=131, high=131)], now=T0 + timedelta(minutes=4),
    )
    assert len(events) == 1
    assert events[0].kind == EVENT_TARGET
    assert events[0].payload["metric_name"] == "Target 3"
    assert state_store.get_open_signals() == {}
    history = state_store.get_alert_history()
    assert len(history) == 1
    assert history[0]["resolution"] == "all_targets_achieved"
    achieved_names = {m["name"] for m in history[0]["metrics"].values() if m.get("achieved")}
    assert achieved_names == {"Target 1", "Target 2", "Target 3"}


def test_multiple_targets_hit_in_the_same_tick_both_notify():
    # A price gap can clear more than one target level in a single tick —
    # both should still be reported, not just the first.
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["direction"] = "BUY"
    cfg["debounce_minutes"] = 0
    cfg["trigger_condition"] = _gt_condition("Signal", 0)
    cfg["metrics"] = [
        new_metric("Target 1", "target", [_num(110)]),
        new_metric("Target 2", "target", [_num(120)]),
    ]
    configs = {"strat-1": cfg}

    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=1))

    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=125, high=125)], now=T0 + timedelta(minutes=2),
    )

    assert len(events) == 2
    assert {e.payload["metric_name"] for e in events} == {"Target 1", "Target 2"}
    assert state_store.get_open_signals() == {}
    assert state_store.get_alert_history()[0]["resolution"] == "all_targets_achieved"


# ── Cooldown after resolution ─────────────────────────────────────────────────
# A signal resolving (target achieved or stopped out) while its trigger is
# STILL true — very often exactly why it resolved, e.g. price is still above
# the breakout level that triggered entry in the first place — must not
# immediately start a brand new pending→open→resolved cycle for what is
# really the same one continuous price move.

def test_resolved_target_does_not_immediately_restart_while_condition_still_true():
    configs = {"strat-1": _make_config(debounce_minutes=0, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)                 # pending
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=1))  # entry
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=111, high=111)], now=T0 + timedelta(minutes=2),
    )
    assert events and events[0].kind == EVENT_TARGET
    assert state_store.get_open_signals() == {}

    # Trigger ("Signal" > 0) is still true — price hasn't dropped. Without
    # the cooldown, this tick would start a brand new pending signal.
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=111, high=111)], now=T0 + timedelta(minutes=3),
    )
    assert events == []
    assert state_store.get_open_signals() == {}


def test_resolved_stop_out_does_not_immediately_restart_while_condition_still_true():
    configs = {"strat-1": _make_config(debounce_minutes=0, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=1))
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=94, low=94)], now=T0 + timedelta(minutes=2),
    )
    assert events and events[0].kind == EVENT_STOP_OUT

    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=94, low=94)], now=T0 + timedelta(minutes=3),
    )
    assert events == []
    assert state_store.get_open_signals() == {}


def test_cooldown_clears_once_condition_goes_false_and_rearms_on_next_true():
    configs = {"strat-1": _make_config(debounce_minutes=0, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0)
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=1))
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=111, high=111)], now=T0 + timedelta(minutes=2),
    )
    assert events and events[0].kind == EVENT_TARGET

    # Condition goes false — cooldown clears, but that alone doesn't start
    # anything (nothing is true yet).
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=0, price=105)], now=T0 + timedelta(minutes=3),
    )
    assert events == []
    assert state_store.get_open_signals() == {}

    # A genuinely new true is a legitimate new signal — must fire normally.
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=100)], now=T0 + timedelta(minutes=4),
    )
    assert events == []   # debounce_minutes=0 still needs to see it true on a later tick
    signals = state_store.get_open_signals()
    assert len(signals) == 1
    assert next(iter(signals.values()))["state"] == "pending"


def test_cooldown_is_per_symbol_not_per_strategy():
    configs = {"strat-1": _make_config(debounce_minutes=0, stop_loss=95, target=110)}
    evaluate_tick([STRATEGY], configs, [_row(signal=1, price=100, symbol="INFY")], now=T0)
    evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=100, symbol="INFY")],
        now=T0 + timedelta(minutes=1),
    )
    events = evaluate_tick(
        [STRATEGY], configs,
        [_row(signal=1, price=111, high=111, symbol="INFY")],
        now=T0 + timedelta(minutes=2),
    )
    assert events and events[0].kind == EVENT_TARGET

    # A different stock hitting the same strategy's trigger is unaffected —
    # INFY's cooldown must not block TCS.
    events = evaluate_tick(
        [STRATEGY], configs, [_row(signal=1, price=100, symbol="TCS")],
        now=T0 + timedelta(minutes=3),
    )
    assert events == []
    signals = state_store.get_open_signals()
    assert len(signals) == 1
    assert next(iter(signals.values()))["symbol"] == "TCS"
