# api/inception_api.py
from datetime import date

from api.client import api_client
from api.endpoints import (
    INCEPTION_AVAILABILITY,
    INCEPTION_BARS,
    INCEPTION_FORMULA_VARIABLES,
    INCEPTION_INSTRUMENTS,
    INCEPTION_STRATEGIES,
)


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
