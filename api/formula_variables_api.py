# api/formula_variables_api.py
from api.client import api_client
from api.endpoints import FORMULA_VARIABLES, FORMULA_VARIABLES_IMPORT


def list_variables() -> dict:
    return api_client.get(FORMULA_VARIABLES)


def import_variables(variables: list) -> dict:
    """Bulk merge-by-name — backs File > Import All Data's formula-
    variables section. *variables* is the same list of variable dicts the
    client already builds locally (each with id/name/formula)."""
    return api_client.put(FORMULA_VARIABLES_IMPORT, json_body={"variables": variables})


def upsert_variable(variable_id: str, name: str, formula: list) -> dict:
    return api_client.put(
        f"{FORMULA_VARIABLES}/{variable_id}",
        json_body={"name": name, "formula": formula},
    )


def delete_variable(variable_id: str) -> None:
    api_client.delete(f"{FORMULA_VARIABLES}/{variable_id}")
