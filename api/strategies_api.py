# api/strategies_api.py
from api.client import api_client
from api.endpoints import STRATEGIES, STRATEGIES_IMPORT


def list_strategies() -> dict:
    return api_client.get(STRATEGIES)


def upsert_strategy(strategy_id: str, name: str, active: bool, category: str,
                     columns: list, row_filter: list) -> dict:
    return api_client.put(
        f"{STRATEGIES}/{strategy_id}",
        json_body={
            "name": name, "active": active, "category": category,
            "columns": columns, "row_filter": row_filter,
        },
    )


def delete_strategy(strategy_id: str) -> None:
    api_client.delete(f"{STRATEGIES}/{strategy_id}")


def import_strategies(strategies: list) -> dict:
    """Bulk merge-by-name — backs "Import All Strategies". *strategies* is
    the same list of strategy dicts the client already builds locally (each
    with id/name/active/category/columns/row_filter)."""
    return api_client.put(STRATEGIES_IMPORT, json_body={"strategies": strategies})
