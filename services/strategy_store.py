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
          {"condition": [...tokens...], "color": "#rrggbb"}
        ]
      }
    ]
  }

Tokens are plain dicts so JSON roundtrips cleanly:
  {"type": "col",  "value": "LTP"}
  {"type": "num",  "value": "1.05"}
  {"type": "op",   "value": "+"}
  {"type": "func", "value": "MAX("}
  {"type": "paren","value": ")"}
  {"type": "self"} — refers to the column's own computed value in fmt rules
"""

import json
import os
import uuid

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "strategies.json")


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
    return _load_raw()


def save_strategy(strategy: dict):
    all_s = _load_raw()
    for i, s in enumerate(all_s):
        if s["id"] == strategy["id"]:
            all_s[i] = strategy
            _save_raw(all_s)
            return
    all_s.append(strategy)
    _save_raw(all_s)


def delete_strategy(strategy_id: str):
    all_s = [s for s in _load_raw() if s["id"] != strategy_id]
    _save_raw(all_s)


def new_strategy(name: str) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "active": True, "columns": []}


def new_column(name: str) -> dict:
    return {"name": name, "formula": [], "fmt_rules": []}


def new_fmt_rule(color: str = "#39d353") -> dict:
    return {"condition": [], "color": color}
