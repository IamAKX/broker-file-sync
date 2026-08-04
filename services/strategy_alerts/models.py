"""
Shapes used across services/strategy_alerts.

Notification config and runtime state are plain JSON-native dicts (same
convention as services/strategy_store.py's strategies) so they round-trip
through config_store/local JSON without a serialization layer. AlertEvent is
the one real dataclass here — it's transient (produced by engine.evaluate_tick,
consumed immediately by the delivery layer in screens/live_viewer.py), never
persisted as-is, so it doesn't need dict conversion.

Notification config shape (see services/strategy_alerts/config_store.py):
  {
    "enabled": bool,
    "direction": "BUY" | "SELL",
    "trigger_condition": [...tokens...],   # a fresh condition, same token
        # system as row_filter/fmt-rule conditions — deliberately NOT "pick
        # one column's existing conditional-formatting rule": a strategy can
        # have several columns, and conditional formatting is inherently
        # per-column, so there's no single well-defined "the strategy's
        # rule" to point at. A standalone condition can reference any/all of
        # the strategy's columns (AND/OR them together) via the same
        # combined-headers picker the row filter and metrics use.
    "debounce_minutes": int,
    "score": float | None,
    "risk_reward": {"numerator": [...tokens...], "denominator": [...tokens...]} | None,
    "metrics": [
      {"id": str, "name": str, "role": "stop_loss"|"target"|"trailing_exit"|"informational",
       "formula": [...tokens...]},
      ...
    ],
  }

Open-signal shape (see services/strategy_alerts/state_store.py):
  {
    "state": "pending" | "open",
    "strategy_id": str, "strategy_name": str, "symbol": str, "sector": str | None,
    "direction": "BUY" | "SELL",
    "first_true_at": iso str,                 # while "pending"
    "entry_time": iso str, "entry_price": float | None,   # once "open"
    "metrics": {metric_id: {"name": str, "role": str, "value": float | None,
                             "achieved": bool, "achieved_at": iso str | None}},
    "risk_reward": {"numerator": float|None, "denominator": float|None, "ratio": float|None} | None,
    "score": float | None,
    "running_high": float | None, "running_low": float | None,
  }
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime

ROLE_STOP_LOSS = "stop_loss"
ROLE_TARGET = "target"
ROLE_TRAILING_EXIT = "trailing_exit"
ROLE_INFORMATIONAL = "informational"
ROLES = (ROLE_STOP_LOSS, ROLE_TARGET, ROLE_TRAILING_EXIT, ROLE_INFORMATIONAL)

DIRECTION_BUY = "BUY"
DIRECTION_SELL = "SELL"

EVENT_ENTRY = "entry"
EVENT_TARGET = "target"
EVENT_STOP_OUT = "stop_out"


def new_metric(name: str, role: str = ROLE_INFORMATIONAL, formula: list | None = None) -> dict:
    return {"id": str(uuid.uuid4()), "name": name, "role": role, "formula": formula or []}


def new_notification_config() -> dict:
    return {
        "enabled": False,
        "direction": DIRECTION_BUY,
        "trigger_condition": [],
        "debounce_minutes": 2,
        "score": None,
        "risk_reward": None,
        "metrics": [],
    }


@dataclass
class AlertEvent:
    """One notification-worthy occurrence, produced by engine.evaluate_tick.
    ``payload`` carries whatever fields messages.py needs to render text for
    this ``kind`` (see messages.py for the exact keys expected per kind)."""
    kind: str
    strategy_id: str
    strategy_name: str
    symbol: str
    timestamp: datetime
    payload: dict = field(default_factory=dict)
