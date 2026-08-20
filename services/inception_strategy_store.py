"""
Persistence layer for Inception strategies — same local-cache-plus-server-
sync shape as services/strategy_store.py (see that module's docstring for
the token/column/fmt_rule shape, which this reuses verbatim), pointed at the
backend's separate /inception/strategies store (api/inception_api.py)
instead of /strategies, and its own local cache file — kept fully separate
from LMV's strategies per the Inception feature's "fully separate" design
(see broker-sync-api's InceptionStrategy model docstring).

Simplifications vs strategy_store.py: no import_all (Inception has no bulk
Export/Import All Strategies menu action) and no one-time local-to-server
migration push in load_all() (Inception is a brand-new store — there's no
pre-existing local-only install to migrate up).
"""

import json
import os
import uuid

from services import config_store

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "inception_strategies.json")

BUILTIN_CATEGORIES = ["Daily", "Weekly", "Monthly", "Common"]
_CUSTOM_CATEGORIES_KEY = "custom_inception_strategy_categories"
UNDEFINED_CATEGORY = "Undefined"


def load_custom_categories() -> list:
    return list(config_store.load_json(_CUSTOM_CATEGORIES_KEY, []))


def all_categories() -> list:
    return BUILTIN_CATEGORIES + load_custom_categories()


def add_custom_category(name: str) -> str:
    name = name.strip()
    if not name:
        return ""
    for existing in all_categories():
        if existing.lower() == name.lower():
            return existing
    categories = load_custom_categories()
    categories.append(name)
    config_store.save_json(_CUSTOM_CATEGORIES_KEY, categories)
    return name


def rename_custom_category(old_name: str, new_name: str) -> str:
    new_name = new_name.strip()
    if not new_name or new_name == old_name:
        return old_name
    customs = load_custom_categories()
    if old_name not in customs:
        return old_name

    collided = False
    for existing in all_categories():
        if existing != old_name and existing.lower() == new_name.lower():
            new_name = existing
            collided = True
            break

    if collided:
        config_store.save_json(_CUSTOM_CATEGORIES_KEY, [c for c in customs if c != old_name])
    else:
        config_store.save_json(
            _CUSTOM_CATEGORIES_KEY,
            [new_name if c == old_name else c for c in customs],
        )

    strategies = _load_raw()
    changed = False
    for s in strategies:
        if s.get("category") == old_name:
            s["category"] = new_name
            changed = True
    if changed:
        _save_raw(strategies)
    return new_name


def delete_custom_category(name: str) -> None:
    customs = load_custom_categories()
    if name not in customs:
        return
    config_store.save_json(_CUSTOM_CATEGORIES_KEY, [c for c in customs if c != name])

    strategies = _load_raw()
    changed = False
    for s in strategies:
        if s.get("category") == name:
            s["category"] = UNDEFINED_CATEGORY
            changed = True
    if changed:
        _save_raw(strategies)


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


def clear_local_cache() -> None:
    if os.path.exists(_STORE_FILE):
        os.remove(_STORE_FILE)


def _backfill_defaults(strategies: list) -> list:
    for s in strategies:
        s.setdefault("category", "Daily")
        s.setdefault("row_filter", [])
        for col in s.get("columns", []):
            col.setdefault("fmt_rules", [])
    return strategies


def load_all() -> list:
    """Tries the server first, refreshing the local cache on success and
    returning that. Falls back to the local cache on NetworkError/ApiError
    (offline reads) — see module docstring for why there's no migration-push
    path here, unlike services.strategy_store.load_all."""
    from api import inception_api
    from api.exceptions import ApiError, NetworkError

    local = _load_raw()
    try:
        result = inception_api.list_strategies()
    except (ApiError, NetworkError):
        return _backfill_defaults(local)

    server_strategies = result.get("strategies", [])
    _save_raw(server_strategies)
    return _backfill_defaults(server_strategies)


def save_strategy(strategy: dict):
    from api import inception_api

    inception_api.upsert_strategy(
        strategy["id"], strategy.get("name", ""), strategy.get("active", True),
        strategy.get("category", "Daily"), strategy.get("columns", []),
        strategy.get("row_filter", []),
    )

    all_s = _load_raw()
    for i, s in enumerate(all_s):
        if s["id"] == strategy["id"]:
            all_s[i] = strategy
            _save_raw(all_s)
            return
    all_s.append(strategy)
    _save_raw(all_s)


def delete_strategy(strategy_id: str):
    from api import inception_api

    inception_api.delete_strategy(strategy_id)

    all_s = [s for s in _load_raw() if s["id"] != strategy_id]
    _save_raw(all_s)


def new_strategy(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "active": True, "category": "Daily", "columns": [], "row_filter": []}


def new_column(name: str) -> dict:
    return {"name": name, "formula": [], "fmt_rules": []}


def new_fmt_rule(color: str = "#39d353") -> dict:
    return {"condition": [], "color": color, "target_column": None}
