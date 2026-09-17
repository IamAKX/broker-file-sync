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
    "repeat_enabled": bool,        # issue #43: re-notify a still-open signal
    "repeat_condition": [...tokens...],   # same token shape as trigger_condition,
        # evaluated against the SAME signal's row each tick while its state is
        # "open" — see engine.py's _update_open_signal.
    "repeat_min_gap_minutes": int,  # floor between repeats of the same signal,
        # so a condition that stays true for many consecutive ticks (e.g. "%
        # change increasing") doesn't refire every tick — see engine.py.
    "alert_mode": "positional" | "intraday",   # issue #43: "positional" (default,
        # today's only behavior) leaves a still-open signal open past the day's
        # alert window close, carrying into the next day same as always;
        # "intraday" force-resolves it right at window close instead — see
        # alert_schedule.should_close_intraday_now/engine.close_intraday_signals.
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
    "repeat_armed": bool,             # issue #43: edge-trigger state for repeat
                                       # alerts — True means the next true reading
                                       # of repeat_condition fires a repeat.
    "last_repeat_at": iso str | None, # issue #43: when the last repeat fired,
                                       # for repeat_min_gap_minutes.
    "exit_price": float | None,       # issue #43: set only on an "intraday_closed"
                                       # resolution — the Current price at the
                                       # moment the alert window closed. Local-
                                       # only, never synced to the backend (see
                                       # backend_sync.py — resolved_at + status
                                       # already capture "this closed, and when").
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
EVENT_TRADE_CANCELLED = "trade_cancelled"
EVENT_REPEAT = "repeat"            # issue #43: re-notification of a still-open signal
EVENT_INTRADAY_CLOSE = "intraday_close"   # issue #43: forced close at window-end

ALERT_MODE_POSITIONAL = "positional"
ALERT_MODE_INTRADAY = "intraday"

# Resolution string stored on a resolved signal (state_store.py's
# "resolution" field, synced to the backend as StrategySignal.status — see
# services.strategy_alerts.backend_sync._status_for and the backend's
# app.schemas.strategy_signals.StrategySignalUpsertRequest, which must
# accept this same string). Issue #32: a Target (or Stop Loss) computed on
# the wrong side of the entry price for the signal's own direction (a BUY
# target at/below entry, or a SELL target at/above entry — same for stop
# loss, inverted) can never be legitimately traded; see engine.py's
# _fire_entry for the check.
RESOLUTION_TRADE_CANCELLED = "trade_cancelled"
# Issue #43: an "intraday" alert_mode strategy's still-open signal, force-
# resolved at the day's alert-window close instead of carrying into tomorrow —
# see alert_schedule.should_close_intraday_now/engine.close_intraday_signals.
RESOLUTION_INTRADAY_CLOSED = "intraday_closed"


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
        "repeat_enabled": False,
        "repeat_condition": [],
        "repeat_min_gap_minutes": 5,
        "alert_mode": ALERT_MODE_POSITIONAL,
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
