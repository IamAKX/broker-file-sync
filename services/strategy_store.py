"""
Persistence layer for strategies.
Each strategy is a dict:
  {
    "id": str (uuid),
    "name": str,
    "active": bool,
    "columns": [
      {
        "name": str,
        "formula": [...tokens...],
        "fmt_rules": [
          {"condition": [...tokens...], "color": "#rrggbb", "target_column": str | None}
        ]
      }
    ]
  }

Tokens are plain dicts so JSON roundtrips cleanly:
  {"type": "col",  "value": "LTP"}
  {"type": "col",  "value": "Open", "of": "Nifty"} — "Open" from the row
      whose Scrip Name is "Nifty" instead of the current row, entered as
      "[Open of Nifty]" in the Expression Editor
  {"type": "num",  "value": "1.05"}
  {"type": "op",   "value": "+"}
  {"type": "func", "value": "MAX("}
  {"type": "paren","value": ")"}
  {"type": "self"} — refers to the column's own computed value in fmt rules
  {"type": "var",  "value": "ThresholdName"} — inlines a reusable formula
      saved via services.formula_variable_store (a separate store, not part
      of this strategy), entered as "{ThresholdName}" in the Expression
      Editor — see services.strategy_engine._expand_var_tokens

A fmt rule's "target_column" is the LMV column its color paints onto when
the condition matches — None (the default) means the strategy column's own
cell, same as before this field existed; any other value is the exact
header text of an LMV column the user picked in Strategy Builder. The
condition itself is unaffected by target_column — THIS still refers to the
owning strategy column's own computed value either way.
"""

import json
import os
import uuid

from services import config_store

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategies.json")

# The 4 built-in categories are always shown, in this order, even if empty;
# user-added ones (see add_custom_category) are appended after them.
BUILTIN_CATEGORIES = ["Daily", "Weekly", "Monthly", "Common"]
_CUSTOM_CATEGORIES_KEY = "custom_strategy_categories"


def load_custom_categories() -> list:
    return list(config_store.load_json(_CUSTOM_CATEGORIES_KEY, []))


def all_categories() -> list:
    """Every category a strategy can be filed under: the 4 built-ins, in
    their fixed order, followed by user-added ones in the order they were
    created."""
    return BUILTIN_CATEGORIES + load_custom_categories()


def add_custom_category(name: str) -> str:
    """Persists *name* as a new category unless it already matches an
    existing one (built-in or custom) case-insensitively, in which case the
    existing category's name is returned instead of creating a near-duplicate.
    Returns the canonical name to select afterward, or "" if *name* is blank.
    """
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


# Where a strategy lands when the category it was filed under gets deleted —
# never the strategy itself, just its category, so nothing silently
# disappears; the user re-files it from the strategy editor.
UNDEFINED_CATEGORY = "Undefined"


def rename_custom_category(old_name: str, new_name: str) -> str:
    """Renames a user-added category, cascading the new name to every
    strategy currently filed under it. A no-op (returns *old_name*) if
    *old_name* isn't a custom category — built-ins can't be renamed this
    way. Collides case-insensitively with an existing category the same
    way add_custom_category does: the existing name wins instead of
    creating a near-duplicate."""
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
        # Merging into an already-existing category (built-in or custom) —
        # drop the old custom entry rather than inserting a duplicate of
        # the name it now resolves to.
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
    """Removes a user-added category. Strategies filed under it are
    reassigned to UNDEFINED_CATEGORY, never deleted. A no-op if *name*
    isn't a custom category — built-ins can't be deleted this way."""
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
    """Deletes strategies.json, the local read-cache behind load_all() —
    used by File > Clear Cache (see app_window.py._clear_cache). Safe to
    call any time: load_all() always tries the server first regardless of
    whether this file exists, so removing it only matters for whatever a
    stale/corrupted local copy would otherwise serve the next time the app
    is offline. A no-op if the file isn't there.
    """
    if os.path.exists(_STORE_FILE):
        os.remove(_STORE_FILE)


def _backfill_defaults(strategies: list) -> list:
    for s in strategies:
        s.setdefault("category", "Daily")
        s.setdefault("row_filter", [])
    return strategies


def load_all() -> list:
    """Tries the server first, refreshing the local cache on success and
    returning that. Falls back to the local cache on NetworkError/ApiError
    (offline reads).

    One-time migration: if the server has never seen any strategies for
    this user but the local cache already has some (e.g. this install
    predates server sync), they're pushed up once via import_all's
    merge-by-name path — same shape as config_store.load_json's migration.
    """
    from api import strategies_api
    from api.exceptions import ApiError, NetworkError

    local = _load_raw()

    try:
        result = strategies_api.list_strategies()
    except (ApiError, NetworkError):
        return _backfill_defaults(local)

    server_strategies = result.get("strategies", [])
    if server_strategies:
        _save_raw(server_strategies)
        return _backfill_defaults(server_strategies)

    if local:
        try:
            import_all(local)
        except (ApiError, NetworkError):
            pass
        return _backfill_defaults(local)

    return []


def save_strategy(strategy: dict):
    """Upserts by id, both on the server and in the local cache. Propagates
    ApiError/NetworkError from the server call — a failed save must be
    visible to the caller, not silently kept local-only with no guarantee
    it'll ever reach the server."""
    from api import strategies_api

    strategies_api.upsert_strategy(
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
    from api import strategies_api

    strategies_api.delete_strategy(strategy_id)

    all_s = [s for s in _load_raw() if s["id"] != strategy_id]
    _save_raw(all_s)


def import_all(strategies: list) -> tuple:
    """Merges *strategies* into the persisted list by name (used by the
    File > Import All Strategies menu action) — an imported strategy whose
    name matches an existing one overwrites it in place (imported data wins,
    including its id); one with a new name is added; any existing strategy
    not present in the import is left untouched. First-match-wins if the
    existing list already has duplicate names (only id is unique).

    Pushes the same merge to the server first (raises on failure — this is
    an explicit, deliberate user action, so it fails loudly rather than
    silently importing local-only); the local merge below is this
    function's own already-proven logic rather than trusting a re-fetch of
    the server's independently-computed result.

    Returns (overwritten_count, added_count).
    """
    from api import strategies_api

    strategies_api.import_strategies(strategies)

    existing = _load_raw()
    index_by_name = {}
    for i, s in enumerate(existing):
        index_by_name.setdefault(s.get("name"), i)

    overwritten = 0
    added = 0
    for imp in strategies:
        name = imp.get("name")
        if name in index_by_name:
            existing[index_by_name[name]] = imp
            overwritten += 1
        else:
            index_by_name[name] = len(existing)
            existing.append(imp)
            added += 1

    _save_raw(existing)
    return overwritten, added


def new_strategy(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "active": True, "category": "Daily", "columns": [], "row_filter": []}


def new_column(name: str) -> dict:
    return {"name": name, "formula": [], "fmt_rules": []}


def new_fmt_rule(color: str = "#39d353") -> dict:
    return {"condition": [], "color": color, "target_column": None}
