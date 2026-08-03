"""
Persistence for reusable formula "variables" — a named formula (token list)
that can be referenced from any strategy column formula, row filter, or
conditional-format condition via a {"type": "var", "value": name} token
(rendered as "{Name}" in the Expression Editor), instead of retyping the
same sub-formula everywhere it's needed. See screens.formula_editor's
Variables catalogue tab / VariablesManagerDialog and
services.strategy_engine._expand_var_tokens, which does the actual inlining
at formula-compile time.

Each variable is a dict: {"id": str (uuid), "name": str, "formula": [...tokens...]}

Global (not scoped to one strategy) — same spirit as a spreadsheet's named
range: define it once, use it from any formula anywhere in Strategy Builder.

Referenced by NAME in formula tokens, the same convention "col" tokens
already use for LMV headers, rather than by id — renaming a variable breaks
formulas that still reference the old name, same tradeoff a column rename
already has. The id exists purely so the management UI can track "which
one is this" across a rename without losing the selection.
"""

import json
import os
import uuid

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "formula_variables.json")


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
    """Tries the server first, refreshing the local cache on success and
    returning that. Falls back to the local cache on NetworkError/ApiError
    (offline reads).

    One-time migration: if the server has never seen any variables for this
    user but the local cache already has some (e.g. this install predates
    server sync), they're pushed up once — same shape as
    config_store.load_json's / strategy_store.load_all's migration.
    """
    from api import formula_variables_api
    from api.exceptions import ApiError, NetworkError

    local = _load_raw()

    try:
        result = formula_variables_api.list_variables()
    except (ApiError, NetworkError):
        return local

    server_variables = result.get("variables", [])
    if server_variables:
        _save_raw(server_variables)
        return server_variables

    if local:
        for v in local:
            try:
                formula_variables_api.upsert_variable(v["id"], v.get("name", ""), v.get("formula", []))
            except (ApiError, NetworkError):
                pass
        return local

    return []


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
    """Upserts by id, both on the server and in the local cache. Propagates
    ApiError/NetworkError from the server call — a failed save must be
    visible to the caller, not silently kept local-only."""
    from api import formula_variables_api

    formula_variables_api.upsert_variable(
        variable["id"], variable.get("name", ""), variable.get("formula", []),
    )

    all_v = _load_raw()
    for i, v in enumerate(all_v):
        if v["id"] == variable["id"]:
            all_v[i] = variable
            break
    else:
        all_v.append(variable)
    _save_raw(all_v)
    _invalidate_formula_cache()


def delete_variable(var_id: str):
    from api import formula_variables_api

    formula_variables_api.delete_variable(var_id)

    all_v = [v for v in _load_raw() if v["id"] != var_id]
    _save_raw(all_v)
    _invalidate_formula_cache()


def new_variable(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "formula": []}


def _invalidate_formula_cache():
    # A formula referencing this variable by name is cached (compiled) under
    # a signature that doesn't change when only the variable's own formula
    # does — see strategy_engine._expand_var_tokens / clear_compile_cache —
    # so every save/delete has to drop the whole cache to avoid a formula
    # silently keeping the pre-edit expansion.
    from services import strategy_engine
    strategy_engine.clear_compile_cache()
