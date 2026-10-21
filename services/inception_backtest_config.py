"""Per-strategy back-test rules for Inception (EMV) strategies (issue #83): the
direction (Buy / Sell), an ENTRY condition, an EXIT condition and optional
informational metrics (named formulas shown next to every back-tested trade).
No targets / stop-loss / trailing exit — an EMV trade opens when the entry
condition turns true and closes when the exit condition does (services.
emv_backtest).

Stored as one JSON blob keyed by strategy id through services.config_store —
the same pattern services.strategy_alerts.config_store uses for LMV's
notification rules — so it syncs through the generic per-user settings
endpoint and the Inception strategy schema (and its backend) stays untouched.

A config:
  {
    "direction": "BUY" | "SELL",
    "entry_condition": [...tokens...],   # empty -> the strategy's row filter
    "exit_condition":  [...tokens...],   # empty -> exit once the entry condition stops holding
    "metrics": [{"id", "name", "formula": [...tokens...]}],   # informational
  }
"""
import copy
import uuid

from services import config_store

_KEY = "inception_backtest_configs"
DIRECTION_BUY = "BUY"
DIRECTION_SELL = "SELL"


def new_config() -> dict:
    return {"direction": DIRECTION_BUY, "entry_condition": [], "exit_condition": [], "metrics": []}


def new_metric(name: str, formula: list | None = None) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "formula": list(formula or [])}


def _normalized(raw) -> dict:
    cfg = new_config()
    if isinstance(raw, dict):
        cfg["direction"] = DIRECTION_SELL if str(raw.get("direction", "")).upper() == DIRECTION_SELL else DIRECTION_BUY
        cfg["entry_condition"] = list(raw.get("entry_condition") or [])
        cfg["exit_condition"] = list(raw.get("exit_condition") or [])
        cfg["metrics"] = [dict(m) for m in (raw.get("metrics") or []) if isinstance(m, dict) and m.get("name")]
        for m in cfg["metrics"]:
            m.setdefault("id", str(uuid.uuid4()))
            m["formula"] = list(m.get("formula") or [])
    return cfg


def load_all() -> dict:
    data = config_store.load_json(_KEY, {})
    return dict(data) if isinstance(data, dict) else {}


def load_config(strategy_id: str) -> dict:
    """The strategy's back-test rules (a default Buy config when none saved)."""
    return _normalized(load_all().get(strategy_id))


def has_rules(strategy_id: str) -> bool:
    """True once the strategy has an entry or an exit condition configured."""
    cfg = load_config(strategy_id)
    return bool(cfg["entry_condition"] or cfg["exit_condition"])


def save_config(strategy_id: str, config: dict) -> None:
    data = load_all()
    data[strategy_id] = _normalized(copy.deepcopy(config))
    config_store.save_json(_KEY, data)


def delete_config(strategy_id: str) -> None:
    data = load_all()
    if strategy_id in data:
        del data[strategy_id]
        config_store.save_json(_KEY, data)
