import os

from services.strategy_alerts import state_store


def test_empty_by_default():
    assert state_store.get_open_signals() == {}
    assert state_store.get_alert_history() == []


def test_set_and_flush_persists_to_disk():
    state_store.set_open_signal("s1::INFY", {"state": "pending"}, force_flush=True)

    path = state_store._file_path()
    assert os.path.exists(path)

    state_store.reset_for_user_switch()  # drop in-memory cache, force a reload from disk
    assert state_store.get_open_signals() == {"s1::INFY": {"state": "pending"}}


def test_clear_open_signal_removes_entry():
    state_store.set_open_signal("s1::INFY", {"state": "open"}, force_flush=True)
    state_store.clear_open_signal("s1::INFY")
    assert state_store.get_open_signals() == {}


def test_alert_history_appends_and_caps():
    for i in range(state_store._MAX_HISTORY + 10):
        state_store.append_alert_history({"i": i})

    history = state_store.get_alert_history()
    assert len(history) == state_store._MAX_HISTORY
    # Oldest entries are dropped, most recent kept.
    assert history[-1]["i"] == state_store._MAX_HISTORY + 9


def test_signal_key_normalizes_symbol_case():
    assert state_store.signal_key("strat-1", "infy") == state_store.signal_key("strat-1", "INFY ")


def test_clear_strategy_removes_only_that_strategys_signals():
    state_store.set_open_signal("strat-1::INFY", {"state": "open"}, force_flush=True)
    state_store.set_open_signal("strat-2::TCS", {"state": "open"}, force_flush=True)

    state_store.clear_strategy("strat-1")

    assert state_store.get_open_signals() == {"strat-2::TCS": {"state": "open"}}


def test_clear_all_resets_both_stores():
    state_store.set_open_signal("s1::INFY", {"state": "open"}, force_flush=True)
    state_store.append_alert_history({"i": 1})

    state_store.clear_all()

    assert state_store.get_open_signals() == {}
    assert state_store.get_alert_history() == []
