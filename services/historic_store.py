"""
Persistence for the Historic Upload feature (POC).

No backend API exists yet — this module stubs the storage/query surface a
future API client would expose, backed by a local JSON file. Swap the
function bodies for real API calls later without touching callers.

File layout: {"YYYY-MM-DD": {"headers": [...], "rows": [[...], ...]}}
"""

import json
import os

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "historic_data.json")


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


def save_historic_upload(date_str: str, headers: list, rows: list):
    """Persist *headers*/*rows* for *date_str* (YYYY-MM-DD). Later: POST to API."""
    data = _load_raw()
    data[date_str] = {"headers": list(headers), "rows": [list(r) for r in rows]}
    _save_raw(data)


def fetch_historic_data(date_str: str):
    """Return (headers, rows) for *date_str*, or None if nothing saved. Later: GET from API."""
    entry = _load_raw().get(date_str)
    if entry is None:
        return None
    return list(entry.get("headers", [])), [list(r) for r in entry.get("rows", [])]


def fetch_available_dates(year: int, month: int) -> set:
    """
    Return the set of days in *year*/*month* that have historic data available,
    for calendar green-dot markers.

    STUB: always returns days 1-20 regardless of year/month. Will be replaced
    by a real API call that returns per-month availability.
    """
    return set(range(1, 21))
