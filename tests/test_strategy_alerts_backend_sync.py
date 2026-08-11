from services.strategy_alerts import backend_sync
from services.strategy_alerts.models import EVENT_ENTRY, AlertEvent


def _signal(**overrides):
    base = {
        "id": "sig-1", "state": "open", "strategy_id": "strat-1",
        "strategy_name": "PWHBUY", "symbol": "INFY", "sector": "IT",
        "direction": "BUY", "entry_time": "2026-08-11T09:31:00",
        "entry_price": 1367.0, "metrics": {}, "risk_reward": None,
        "score": 150.0, "running_high": 1367.0, "running_low": 1367.0,
    }
    base.update(overrides)
    return base


def _event(signal):
    return AlertEvent(
        kind=EVENT_ENTRY, strategy_id="strat-1", strategy_name="PWHBUY",
        symbol="INFY", timestamp=None, payload={"_signal": signal},
    )


def test_sync_event_pushes_mapped_payload(monkeypatch):
    from api import strategy_signals_api

    calls = []
    monkeypatch.setattr(
        strategy_signals_api, "upsert_signal",
        lambda signal_id, payload: calls.append((signal_id, payload)),
    )

    future = backend_sync.sync_event(_event(_signal()))
    future.result(timeout=5)

    assert len(calls) == 1
    signal_id, payload = calls[0]
    assert signal_id == "sig-1"
    assert payload["strategy_id"] == "strat-1"
    assert payload["symbol"] == "INFY"
    assert payload["status"] == "open"   # no resolution set -> still open


def test_sync_event_maps_resolution_to_status():
    for resolution, expected_status in (
        ("stopped_out", "stopped_out"),
        ("all_targets_achieved", "all_targets_achieved"),
    ):
        payload = backend_sync._to_payload(_signal(resolution=resolution))
        assert payload["status"] == expected_status


def test_sync_event_is_noop_without_signal_snapshot():
    event = AlertEvent(
        kind=EVENT_ENTRY, strategy_id="strat-1", strategy_name="PWHBUY",
        symbol="INFY", timestamp=None, payload={},   # no "_signal" key at all
    )
    assert backend_sync.sync_event(event) is None


def test_sync_event_is_noop_without_signal_id():
    event = _event(_signal(id=None))
    assert backend_sync.sync_event(event) is None


def test_sync_event_swallows_api_error_instead_of_raising(monkeypatch):
    from api import strategy_signals_api
    from api.exceptions import ApiError

    def _raise(signal_id, payload):
        raise ApiError("boom", "unknown_error", 500)

    monkeypatch.setattr(strategy_signals_api, "upsert_signal", _raise)

    future = backend_sync.sync_event(_event(_signal()))
    future.result(timeout=5)   # must not raise, even once the background push runs


def test_sync_event_swallows_network_error_instead_of_raising(monkeypatch):
    from api import strategy_signals_api
    from api.exceptions import NetworkError

    def _raise(signal_id, payload):
        raise NetworkError("unreachable")

    monkeypatch.setattr(strategy_signals_api, "upsert_signal", _raise)

    future = backend_sync.sync_event(_event(_signal()))
    future.result(timeout=5)


def test_sync_event_does_not_block_caller(monkeypatch):
    """Same rationale as EmailChannel's equivalent test — sync_event() must
    return immediately regardless of how slow the underlying network call
    is, since it's called inline in screens/live_viewer.py's per-tick loop."""
    import time
    from api import strategy_signals_api

    def _slow_upsert(signal_id, payload):
        time.sleep(0.3)

    monkeypatch.setattr(strategy_signals_api, "upsert_signal", _slow_upsert)

    start = time.monotonic()
    future = backend_sync.sync_event(_event(_signal()))
    elapsed = time.monotonic() - start
    assert elapsed < 0.1
    future.result(timeout=5)
