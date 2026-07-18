"""
Persistence for Config Editor tab data.

Each tab's rows are stored under a string key in a single JSON file. A row is a
list of cell strings (matching ConfigTabWidget.get_data() tuples). When a tab
has no saved entry, callers fall back to the defaults in config_defaults.py.

Tab keys (stable identifiers, independent of UI labels):
  "sector_stock"      — (Sector, Stock)
  "script_name"       — (Stock, Initial)
  "main_column_name"  — (Actual, Renamed)
  "main_column_order" — (Column Name,)
  "theme"             — "dark" | "light"
"""

import json
import os

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_data.json")

MAIN_COLUMN_NAME  = "main_column_name"
MAIN_COLUMN_ORDER = "main_column_order"
THEME             = "theme"


def _load_raw() -> dict:
    if not os.path.exists(_STORE_FILE):
        return {}
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(data: dict):
    with open(_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def save_json(key: str, value) -> None:
    """Persist any JSON-serializable value under *key* (for data that isn't
    a flat row-table, e.g. the ExternalImport formula list)."""
    data = _load_raw()
    data[key] = value
    _save_raw(data)


def load_json(key: str, default):
    """Return the saved value for *key*, or *default* when none saved."""
    data = _load_raw()
    return data.get(key, default)


def load_tab(key: str, default: list) -> list:
    """Return saved rows for *key*, or *default* (as lists) when none saved."""
    data = _load_raw()
    rows = data.get(key)
    if rows is None:
        return [list(r) for r in default]
    return [list(r) for r in rows]


def save_tab(key: str, rows: list):
    """Persist *rows* (iterable of cell sequences) under *key*."""
    data = _load_raw()
    data[key] = [list(r) for r in rows]
    _save_raw(data)


def save_column_order(ordered_names: list):
    """Persist the user's column order as a list of column names."""
    data = _load_raw()
    data[MAIN_COLUMN_ORDER] = list(ordered_names)
    _save_raw(data)


def load_column_order() -> list:
    """Return saved column order (list of names), or [] if none saved."""
    data = _load_raw()
    order = data.get(MAIN_COLUMN_ORDER)
    return list(order) if isinstance(order, list) else []


def save_theme(mode: str):
    """Persist the selected theme mode ("dark" or "light")."""
    data = _load_raw()
    data[THEME] = mode
    _save_raw(data)


def load_theme(default: str = "light") -> str:
    """Return the saved theme mode, or *default* if none saved."""
    data = _load_raw()
    mode = data.get(THEME)
    return mode if mode in ("dark", "light") else default


def get_rename_map() -> dict:
    """
    Mapping of {actual_column_name -> renamed_column_name} from the
    'Main Column Name' tab. Only entries with a non-empty renamed value that
    differs from the actual name are included.
    """
    from config_defaults import MAIN_COLUMN_NAME_DATA
    rows = load_tab(MAIN_COLUMN_NAME, MAIN_COLUMN_NAME_DATA)
    mapping = {}
    for row in rows:
        if len(row) < 2:
            continue
        actual, renamed = (row[0] or "").strip(), (row[1] or "").strip()
        if actual and renamed and actual != renamed:
            mapping[actual] = renamed
    return mapping
