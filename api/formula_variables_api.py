# api/formula_variables_api.py
from api.client import api_client
from api.endpoints import FORMULA_VARIABLES


def list_variables() -> dict:
    return api_client.get(FORMULA_VARIABLES)


def upsert_variable(variable_id: str, name: str, formula: list) -> dict:
    return api_client.put(
        f"{FORMULA_VARIABLES}/{variable_id}",
        json_body={"name": name, "formula": formula},
    )


def delete_variable(variable_id: str) -> None:
    api_client.delete(f"{FORMULA_VARIABLES}/{variable_id}")
