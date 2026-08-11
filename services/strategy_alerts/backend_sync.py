"""
Pushes Strategy Notifications signal transitions to broker-sync-api's
durable, tenant-scoped StrategySignal table (see api/strategy_signals_api.py
and the backend's app/models/tenant.py::StrategySignal) — this is the
network-touching half services/strategy_alerts/engine.py deliberately stays
free of (see its own docstring: "Pure computation (no Qt, no network)").

Only called for events engine.py actually produced (entry, target achieved,
stop-out) — a "pending" signal, still inside its debounce window with no
alert fired yet, is never synced (see StrategySignal's own docstring for the
matching backend-side rationale). Each AlertEvent from the same tick already
carries the signal id + a full point-in-time state to sync in
event.payload["_signal"] (see engine.py's _fire_entry/_update_open_signal) —
this module just maps that shape onto StrategySignalUpsertRequest's fields
and dispatches the actual HTTP call to a background thread pool, mirroring
channels/email.py's "never block the GUI thread on network I/O" pattern.
screens/live_viewer.py calls sync_event() once per event, on the GUI thread,
in the same per-tick loop that also delivers the OS-tray/Email/Slack
notification — this step runs after that delivery, never gating it.

Failures are logged and swallowed, never raised — a sync hiccup (offline,
expired session) must not disrupt notification delivery, and nothing
downstream ever calls .result() on the returned Future in production.
"""

import concurrent.futures

from api import strategy_signals_api
from api.exceptions import ApiError, NetworkError
from services.error_logging import error_logger
from services.strategy_alerts.models import AlertEvent

# One shared, small pool for the app's lifetime — same rationale as
# channels/email.py's _executor: signal transitions are infrequent (only on
# an actual entry/target/stop-out, never per-tick) and not latency-sensitive
# to each other.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="signal-sync")


def _status_for(signal: dict) -> str:
    resolution = signal.get("resolution")
    if resolution == "stopped_out":
        return "stopped_out"
    if resolution == "all_targets_achieved":
        return "all_targets_achieved"
    return "open"


def _to_payload(signal: dict) -> dict:
    return {
        "strategy_id": signal["strategy_id"],
        "strategy_name": signal.get("strategy_name", ""),
        "symbol": signal["symbol"],
        "sector": signal.get("sector"),
        "direction": signal.get("direction", "BUY"),
        "status": _status_for(signal),
        "entry_time": signal.get("entry_time"),
        "entry_price": signal.get("entry_price"),
        "resolved_at": signal.get("resolved_at"),
        "running_high": signal.get("running_high"),
        "running_low": signal.get("running_low"),
        "score": signal.get("score"),
        "risk_reward": signal.get("risk_reward"),
        "metrics": signal.get("metrics", {}),
    }


def sync_event(event: AlertEvent) -> concurrent.futures.Future | None:
    """Dispatches one background push for *event*, if it carries a signal
    snapshot worth syncing (event.payload["_signal"] — absent for anything
    other than entry/target/stop_out, though those are the only kinds
    engine.py ever produces). Returns the submitted Future — ignored by
    ordinary callers, lets tests (and any other caller that cares) wait for
    the push to actually finish — or None if there was nothing to sync."""
    signal = event.payload.get("_signal")
    if not signal or not signal.get("id"):
        return None
    return _executor.submit(_push_now, signal["id"], _to_payload(signal))


def _push_now(signal_id: str, payload: dict) -> None:
    try:
        strategy_signals_api.upsert_signal(signal_id, payload)
    except (ApiError, NetworkError) as exc:
        error_logger.error("Strategy signal backend sync failed: %s", exc)
    except Exception as exc:   # noqa: BLE001
        # Deliberately broader than ApiError/NetworkError above — same
        # reasoning as EmailChannel._send_now: this runs on a background
        # thread with nothing downstream ever calling .result() on the
        # Future in production, so an unanticipated bug here would
        # otherwise vanish with zero trace.
        error_logger.exception("Strategy signal backend sync failed unexpectedly: %s", exc)
