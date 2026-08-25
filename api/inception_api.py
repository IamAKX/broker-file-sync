# api/inception_api.py
from datetime import date

from api.client import api_client
from api.endpoints import (
    INCEPTION_AVAILABILITY,
    INCEPTION_BARS,
    INCEPTION_FORMULA_VARIABLES,
    INCEPTION_INSTRUMENTS,
    INCEPTION_STRATEGIES,
    INCEPTION_VENDOR_SYNC,
)

# A real vendor fetch + DB write on the server (app/services/
# inception_vendor_sync_service.py in broker-sync-api), not a quick CRUD
# round trip — the normal 15s ceiling (api.client._TIMEOUT_SECONDS) would
# abort a legitimate multi-day/chunked catch-up before the server even
# finishes. Generous, not unbounded: screens.inception_settings' worker
# thread is what actually keeps the desktop UI responsive while this runs
# (see that screen's own docstring), this is just "don't give up too
# early" on the HTTP side.
_VENDOR_SYNC_TIMEOUT_SECONDS = 600


def get_availability(date_from: date, date_to: date) -> dict:
    return api_client.get(
        INCEPTION_AVAILABILITY,
        params={"from": date_from.isoformat(), "to": date_to.isoformat()},
    )


def list_instruments() -> dict:
    return api_client.get(INCEPTION_INSTRUMENTS)


def get_bars(date_from: date, date_to: date, symbols: list[str] | None = None) -> dict:
    """Bulk raw-bar feed (see services.inception_sync_service, the only
    caller) — replaces the old get_snapshot/get_hmv/list_columns/recompute
    calls, all removed along with their backend endpoints when Group A/B
    computation moved entirely to this client (services.
    inception_formula_engine/inception_compute_service)."""
    params = {"from": date_from.isoformat(), "to": date_to.isoformat()}
    if symbols:
        params["symbols"] = symbols
    return api_client.get(INCEPTION_BARS, params=params)


def list_strategies() -> dict:
    return api_client.get(INCEPTION_STRATEGIES)


def upsert_strategy(strategy_id: str, name: str, active: bool, category: str,
                     columns: list, row_filter: list) -> dict:
    return api_client.put(
        f"{INCEPTION_STRATEGIES}/{strategy_id}",
        json_body={
            "name": name, "active": active, "category": category,
            "columns": columns, "row_filter": row_filter,
        },
    )


def delete_strategy(strategy_id: str) -> None:
    api_client.delete(f"{INCEPTION_STRATEGIES}/{strategy_id}")


def list_variables() -> dict:
    return api_client.get(INCEPTION_FORMULA_VARIABLES)


def upsert_variable(variable_id: str, name: str, formula: list) -> dict:
    return api_client.put(
        f"{INCEPTION_FORMULA_VARIABLES}/{variable_id}",
        json_body={"name": name, "formula": formula},
    )


def delete_variable(variable_id: str) -> None:
    api_client.delete(f"{INCEPTION_FORMULA_VARIABLES}/{variable_id}")


def sync_vendor_data(email: str, password: str, exchange: str) -> dict:
    """Triggers the "fetch from Equal Solution" — see screens.
    inception_settings' "Fetch from Equal Solution" section, whose
    Username/Password/Exchange fields these three come from directly, sent
    as typed on every click. The server still determines the date range
    itself (its own last-available date through today) — that's not
    something to type in. A blank field falls back to the server's own
    env config for that piece (see app/services/
    inception_vendor_sync_service.py in broker-sync-api). Returns
    {"status", "exchange", "date_from", "date_to", "last_available_before",
    "last_available_after", "instruments_added", "bars_written"}."""
    return api_client.post(
        INCEPTION_VENDOR_SYNC,
        json_body={"email": email, "password": password, "exchange": exchange},
        timeout=_VENDOR_SYNC_TIMEOUT_SECONDS,
    )
