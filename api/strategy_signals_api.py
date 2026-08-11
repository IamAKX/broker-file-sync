# api/strategy_signals_api.py
"""Backend client for durable, tenant-scoped Strategy Notifications signal
storage (see broker-sync-api's app/models/tenant.py::StrategySignal). Mirrors
the client-local shape in services/strategy_alerts/state_store.py/engine.py,
but this is a plain HTTP client module — the actual sync decision (when to
call upsert_signal, dispatched off the GUI thread) lives in
services/strategy_alerts/backend_sync.py, same separation as
notifications_api.py vs channels/email.py.
"""
from api.client import api_client
from api.endpoints import STRATEGY_SIGNALS


def upsert_signal(signal_id: str, payload: dict) -> dict:
    """*payload* keys mirror StrategySignalUpsertRequest: strategy_id,
    strategy_name, symbol, sector, direction, status ("open" |
    "stopped_out" | "all_targets_achieved" — "pending" is never synced, see
    services/strategy_alerts/backend_sync.py), entry_time, entry_price,
    resolved_at, running_high, running_low, score, risk_reward, metrics."""
    return api_client.put(f"{STRATEGY_SIGNALS}/{signal_id}", json_body=payload)


def list_signals(*, strategy_id: str | None = None, direction: str | None = None,
                  symbol: str | None = None, sector: str | None = None,
                  status: str | None = None, start_time: str | None = None,
                  end_time: str | None = None, page: int = 1,
                  page_size: int = 25) -> dict:
    """Every filter is combined with AND server-side; omitting one (leaving
    it None) drops it from the query entirely rather than matching nothing.
    start_time/end_time are ISO 8601 datetime strings. Returns
    {"items": [...], "total": int, "page": int, "page_size": int,
    "total_pages": int}."""
    params = {
        "strategy_id": strategy_id, "direction": direction, "symbol": symbol,
        "sector": sector, "status": status, "start_time": start_time,
        "end_time": end_time, "page": page, "page_size": page_size,
    }
    return api_client.get(STRATEGY_SIGNALS, params={k: v for k, v in params.items() if v is not None})


def clear_signals() -> None:
    api_client.delete(STRATEGY_SIGNALS)
