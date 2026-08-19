# api/inception_api.py
from datetime import date

from api.client import api_client
from api.endpoints import (
    INCEPTION_AVAILABILITY,
    INCEPTION_COLUMNS,
    INCEPTION_COMPILE_CHECK,
    INCEPTION_FORMULA_VARIABLES,
    INCEPTION_HMV,
    INCEPTION_INSTRUMENTS,
    INCEPTION_RECOMPUTE,
    INCEPTION_SNAPSHOT,
    INCEPTION_STRATEGIES,
)


def get_availability(date_from: date, date_to: date) -> dict:
    return api_client.get(
        INCEPTION_AVAILABILITY,
        params={"from": date_from.isoformat(), "to": date_to.isoformat()},
    )


def list_instruments() -> dict:
    return api_client.get(INCEPTION_INSTRUMENTS)


def list_columns() -> dict:
    return api_client.get(INCEPTION_COLUMNS)


def get_snapshot(trade_date: date) -> dict:
    return api_client.get(INCEPTION_SNAPSHOT, params={"date": trade_date.isoformat()})


def get_hmv(period_type: str, period: str, metrics: list[str] | None = None) -> dict:
    params = {"period_type": period_type, "period": period}
    if metrics:
        params["metrics"] = metrics
    return api_client.get(INCEPTION_HMV, params=params)


def recompute(symbol: str | None = None) -> dict:
    return api_client.post(INCEPTION_RECOMPUTE, json_body={"symbol": symbol})


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


def compile_check(formula: list) -> dict:
    return api_client.post(INCEPTION_COMPILE_CHECK, json_body={"formula": formula})
