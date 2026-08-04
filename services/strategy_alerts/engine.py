"""
Per-tick evaluation of every strategy that has an enabled notification
config. Pure computation (no Qt, no network): reads the already-computed
per-row dicts the Live Master View builds each tick (see
screens/live_viewer.py's _update_cells_in_place, which already builds
all_dicts/sym_index/agg_cache for conditional-formatting colors — this
module reuses the exact same inputs), mutates services.strategy_alerts.
state_store, and returns a list of AlertEvent for the caller to actually
deliver (notifications + alert history are the caller's job — see
screens/live_viewer.py's wiring).

State machine per (strategy_id, symbol):
  no signal --(trigger true)--> pending --(trigger true continuously for
  debounce_minutes)--> open --(all Target metrics achieved, or a Stop
  Loss/Trailing Exit crossing)--> resolved (moved into alert history, entry
  removed from open_signals).

Only one pending/open signal per (strategy_id, symbol) at a time — a trigger
firing again for a symbol that already has one is ignored until it resolves.
"""

from datetime import datetime, timedelta

from services.strategy_alerts import messages, state_store
from services.strategy_alerts.models import (
    DIRECTION_BUY,
    EVENT_ENTRY,
    EVENT_STOP_OUT,
    EVENT_TARGET,
    ROLE_STOP_LOSS,
    ROLE_TARGET,
    ROLE_TRAILING_EXIT,
    AlertEvent,
)
from services.strategy_engine import SYMBOL_COLUMN, evaluate, evaluate_condition

_PRICE_COLUMN = "Current"
_HIGH_COLUMN = "High"
_LOW_COLUMN = "Low"


def _to_float(value) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _find_metric_config(config: dict, metric_id: str) -> dict | None:
    for m in config.get("metrics", []):
        if m.get("id") == metric_id:
            return m
    return None


def _elapsed_str(start: datetime, end: datetime) -> str:
    minutes = max(0, int((end - start).total_seconds() // 60))
    return f"{minutes} minute{'s' if minutes != 1 else ''}"


def evaluate_tick(
    strategies: list,
    configs: dict,
    all_dicts: list,
    sym_index: dict | None = None,
    agg_cache: dict | None = None,
    now: datetime | None = None,
) -> list[AlertEvent]:
    """Evaluate every enabled notification config against this tick's rows.
    ``strategies`` is the full active-strategy list (same shape as passed to
    strategy_engine.apply_strategies) — used to skip configs whose strategy
    is no longer active. ``configs`` is
    strategy_alerts.config_store.load_configs()'s result. Returns events in
    the order they were detected; callers deliver
    them and persist alert history."""
    now = now or datetime.now()
    if agg_cache is None:
        agg_cache = {}
    events: list[AlertEvent] = []

    strategies_by_id = {s["id"]: s for s in strategies if s.get("active")}
    for strategy_id, config in configs.items():
        if not config.get("enabled"):
            continue
        strategy = strategies_by_id.get(strategy_id)
        if strategy is None:
            continue
        events.extend(
            _evaluate_strategy(strategy, config, all_dicts, sym_index, agg_cache, now)
        )
    return events


def _evaluate_strategy(
    strategy: dict, config: dict, all_dicts: list, sym_index: dict | None,
    agg_cache: dict, now: datetime,
) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    condition_tokens = config.get("trigger_condition", [])
    if not condition_tokens:
        return events

    strategy_id = strategy["id"]
    strategy_name = strategy.get("name", "")
    direction = config.get("direction", DIRECTION_BUY)
    debounce_minutes = config.get("debounce_minutes", 2)
    open_signals = state_store.get_open_signals()

    for row in all_dicts:
        symbol = row.get(SYMBOL_COLUMN)
        if not symbol:
            continue
        key = state_store.signal_key(strategy_id, symbol)
        signal = open_signals.get(key)
        is_true = evaluate_condition(
            condition_tokens, row, all_dicts, agg_cache=agg_cache, sym_index=sym_index
        )

        if signal is None:
            if is_true:
                state_store.set_open_signal(
                    key,
                    {
                        "state": "pending",
                        "strategy_id": strategy_id,
                        "strategy_name": strategy_name,
                        "symbol": symbol,
                        "direction": direction,
                        "first_true_at": now.isoformat(),
                    },
                    force_flush=True,
                )
            continue

        if signal.get("state") == "pending":
            if not is_true:
                state_store.clear_open_signal(key)
                continue
            first_true_at = datetime.fromisoformat(signal["first_true_at"])
            if now - first_true_at >= timedelta(minutes=debounce_minutes):
                events.append(
                    _fire_entry(
                        strategy, config, row, all_dicts, sym_index, agg_cache,
                        symbol, direction, now, key,
                    )
                )
            continue

        if signal.get("state") == "open":
            events.extend(
                _update_open_signal(
                    config, signal, row, all_dicts, sym_index, agg_cache, now, key
                )
            )

    return events


def _fire_entry(
    strategy: dict, config: dict, row: dict, all_dicts: list, sym_index, agg_cache,
    symbol: str, direction: str, now: datetime, key: str,
) -> AlertEvent:
    entry_price = _to_float(row.get(_PRICE_COLUMN))
    metrics_state: dict = {}
    for m in config.get("metrics", []):
        value = evaluate(
            m.get("formula", []), row, all_dicts, agg_cache=agg_cache, sym_index=sym_index
        )
        entry = {"name": m.get("name", ""), "role": m.get("role"), "value": _to_float(value)}
        if m.get("role") == ROLE_TARGET:
            entry["achieved"] = False
            entry["achieved_at"] = None
        metrics_state[m["id"]] = entry

    risk_reward = None
    rr_cfg = config.get("risk_reward")
    if rr_cfg:
        numerator = _to_float(
            evaluate(rr_cfg.get("numerator", []), row, all_dicts, agg_cache=agg_cache, sym_index=sym_index)
        )
        denominator = _to_float(
            evaluate(rr_cfg.get("denominator", []), row, all_dicts, agg_cache=agg_cache, sym_index=sym_index)
        )
        ratio = (numerator / denominator) if (numerator is not None and denominator) else None
        risk_reward = {"numerator": numerator, "denominator": denominator, "ratio": ratio}

    high = _to_float(row.get(_HIGH_COLUMN))
    low = _to_float(row.get(_LOW_COLUMN))

    signal = {
        "state": "open",
        "strategy_id": strategy["id"],
        "strategy_name": strategy.get("name", ""),
        "symbol": symbol,
        "sector": row.get("Sector"),
        "direction": direction,
        "entry_time": now.isoformat(),
        "entry_price": entry_price,
        "metrics": metrics_state,
        "risk_reward": risk_reward,
        "score": config.get("score"),
        "running_high": high,
        "running_low": low,
    }
    state_store.set_open_signal(key, signal, force_flush=True)

    event = AlertEvent(
        kind=EVENT_ENTRY, strategy_id=strategy["id"], strategy_name=strategy.get("name", ""),
        symbol=symbol, timestamp=now, payload=dict(signal),
    )
    event.payload["title"] = messages.render_title(event)
    event.payload["message"] = messages.render_message(event)
    return event


def _pct_move(entry_price, extreme) -> float | None:
    if entry_price in (None, 0) or extreme is None:
        return None
    return (extreme - entry_price) / entry_price * 100


def _update_open_signal(
    config: dict, signal: dict, row: dict, all_dicts: list, sym_index, agg_cache,
    now: datetime, key: str,
) -> list[AlertEvent]:
    events: list[AlertEvent] = []
    price = _to_float(row.get(_PRICE_COLUMN))
    high = _to_float(row.get(_HIGH_COLUMN))
    low = _to_float(row.get(_LOW_COLUMN))
    if high is not None:
        signal["running_high"] = max(signal.get("running_high"), high) if signal.get("running_high") is not None else high
    if low is not None:
        signal["running_low"] = min(signal.get("running_low"), low) if signal.get("running_low") is not None else low

    direction = signal.get("direction", DIRECTION_BUY)
    entry_time = datetime.fromisoformat(signal["entry_time"])
    strategy_id = signal["strategy_id"]
    strategy_name = signal["strategy_name"]
    symbol = signal["symbol"]
    stopped_out = False

    # Re-evaluate trailing_exit metrics fresh every tick — they're expected
    # to move as price moves, unlike Stop Loss/Target which are frozen at entry.
    for metric_id, m in signal["metrics"].items():
        if m.get("role") != ROLE_TRAILING_EXIT:
            continue
        cfg_metric = _find_metric_config(config, metric_id)
        if cfg_metric is None:
            continue
        m["value"] = _to_float(
            evaluate(cfg_metric.get("formula", []), row, all_dicts, agg_cache=agg_cache, sym_index=sym_index)
        )

    if price is not None:
        for metric_id, m in signal["metrics"].items():
            if m.get("role") != ROLE_TARGET or m.get("achieved") or m.get("value") is None:
                continue
            hit = price >= m["value"] if direction == DIRECTION_BUY else price <= m["value"]
            if not hit:
                continue
            m["achieved"] = True
            m["achieved_at"] = now.isoformat()
            event = AlertEvent(
                kind=EVENT_TARGET, strategy_id=strategy_id, strategy_name=strategy_name,
                symbol=symbol, timestamp=now,
                payload={
                    "metric_name": m["name"], "price": price, "achieved_at": now,
                    "elapsed": _elapsed_str(entry_time, now),
                },
            )
            event.payload["title"] = messages.render_title(event)
            event.payload["message"] = messages.render_message(event)
            events.append(event)

        for metric_id, m in signal["metrics"].items():
            if m.get("role") not in (ROLE_STOP_LOSS, ROLE_TRAILING_EXIT) or m.get("value") is None:
                continue
            hit = price <= m["value"] if direction == DIRECTION_BUY else price >= m["value"]
            if not hit:
                continue
            stopped_out = True
            event = AlertEvent(
                kind=EVENT_STOP_OUT, strategy_id=strategy_id, strategy_name=strategy_name,
                symbol=symbol, timestamp=now,
                payload={
                    "metric_name": m["name"], "price": price, "time": now,
                    "running_high": signal.get("running_high"), "running_low": signal.get("running_low"),
                    "pct_move": _pct_move(
                        signal.get("entry_price"),
                        signal.get("running_high") if direction == DIRECTION_BUY else signal.get("running_low"),
                    ),
                },
            )
            event.payload["title"] = messages.render_title(event)
            event.payload["message"] = messages.render_message(event)
            events.append(event)
            break

    targets = [m for m in signal["metrics"].values() if m.get("role") == ROLE_TARGET]
    all_targets_hit = bool(targets) and all(m.get("achieved") for m in targets)

    if stopped_out or all_targets_hit:
        signal["resolved_at"] = now.isoformat()
        signal["resolution"] = "stopped_out" if stopped_out else "all_targets_achieved"
        state_store.append_alert_history(signal)
        state_store.clear_open_signal(key)
    else:
        state_store.set_open_signal(key, signal, force_flush=bool(events))

    return events
