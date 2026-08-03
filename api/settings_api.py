# api/settings_api.py
"""Generic per-user key/value settings — mirrors services/config_store.py's
own load_json(key, default)/save_json(key, value) shape exactly, so this is
the one API module backing config-editor tables, LMV highlight colors,
custom strategy categories, and notification trigger config."""
from api.client import api_client
from api.endpoints import SETTINGS


def get_setting(key: str) -> dict:
    """Returns {"key": key, "value": None} if nothing's been saved yet —
    not an error, matches config_store.load_json's own "no saved value"
    non-error shape."""
    return api_client.get(f"{SETTINGS}/{key}")


def put_setting(key: str, value) -> dict:
    return api_client.put(f"{SETTINGS}/{key}", json_body={"value": value})
