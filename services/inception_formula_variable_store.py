"""Inception's own reusable named formulas — same shape/rationale as
services/formula_variable_store.py, pointed at api/inception_api.py's
/inception/formula-variables store instead, kept fully separate from LMV's
Formula Builder variables."""

import json
import os
import uuid

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "inception_formula_variables.json")


def _load_raw() -> list:
    if not os.path.exists(_STORE_FILE):
        return []
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_raw(data: list):
    with open(_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def load_all() -> list:
    from api import inception_api
    from api.exceptions import ApiError, NetworkError

    local = _load_raw()
    try:
        result = inception_api.list_variables()
    except (ApiError, NetworkError):
        return local

    server_variables = result.get("variables", [])
    _save_raw(server_variables)
    return server_variables


def get_by_name(name: str) -> dict | None:
    for v in _load_raw():
        if v.get("name") == name:
            return v
    return None


def get_by_id(var_id: str) -> dict | None:
    for v in _load_raw():
        if v.get("id") == var_id:
            return v
    return None


def save_variable(variable: dict):
    from api import inception_api

    inception_api.upsert_variable(variable["id"], variable.get("name", ""), variable.get("formula", []))

    all_v = _load_raw()
    for i, v in enumerate(all_v):
        if v["id"] == variable["id"]:
            all_v[i] = variable
            break
    else:
        all_v.append(variable)
    _save_raw(all_v)


def delete_variable(var_id: str):
    from api import inception_api

    inception_api.delete_variable(var_id)

    all_v = [v for v in _load_raw() if v["id"] != var_id]
    _save_raw(all_v)


def new_variable(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "formula": []}
