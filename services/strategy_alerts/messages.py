"""
Renders human-readable notification text for an AlertEvent. Kept separate
from engine.py so the state machine stays pure computation — this module is
the only place that knows what the message text should look like.
"""

from datetime import datetime

from services.strategy_alerts.models import EVENT_ENTRY, EVENT_STOP_OUT, EVENT_TARGET, AlertEvent


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _fmt_time(value) -> str:
    if isinstance(value, datetime):
        return value.strftime("%d-%b-%Y %I:%M %p").lstrip("0")
    if isinstance(value, str):
        try:
            return _fmt_time(datetime.fromisoformat(value))
        except ValueError:
            return value
    return "—"


def _metric_lines(metrics: dict) -> list[str]:
    lines = []
    for m in metrics.values():
        if m.get("role") == "informational":
            continue
        lines.append(f"{m.get('name', '?')}: {_fmt_price(m.get('value'))}")
    return lines


def render_title(event: AlertEvent) -> str:
    if event.kind == EVENT_ENTRY:
        direction = event.payload.get("direction", "")
        return f"{event.strategy_name} — {direction} Signal: {event.symbol}"
    if event.kind == EVENT_TARGET:
        return f"{event.strategy_name} — {event.symbol}: Target Achieved"
    if event.kind == EVENT_STOP_OUT:
        return f"{event.strategy_name} — {event.symbol}: Stopped Out"
    return f"{event.strategy_name} — {event.symbol}"


def render_message(event: AlertEvent) -> str:
    p = event.payload
    if event.kind == EVENT_ENTRY:
        lines = [
            f"Sector: {p.get('sector') or '—'}",
            f"Entry Price: {_fmt_price(p.get('entry_price'))} @ {_fmt_time(p.get('entry_time'))}",
        ]
        lines.extend(_metric_lines(p.get("metrics", {})))
        rr = p.get("risk_reward")
        if rr and rr.get("ratio") is not None:
            lines.append(
                f"Risk:Reward = {_fmt_price(rr.get('numerator'))}:"
                f"{_fmt_price(rr.get('denominator'))} ({rr['ratio']:.2f})"
            )
        if p.get("score") is not None:
            lines.append(f"Strength/Weakness Score: {p['score']}")
        return "\n".join(lines)

    if event.kind == EVENT_TARGET:
        return (
            f'Target "{p.get("metric_name")}" achieved at {_fmt_price(p.get("price"))} '
            f'({_fmt_time(p.get("achieved_at"))}, {p.get("elapsed", "")} from signal)'
        )

    if event.kind == EVENT_STOP_OUT:
        lines = [
            f'Stopped out via "{p.get("metric_name")}" at {_fmt_price(p.get("price"))} '
            f'({_fmt_time(p.get("time"))})',
            f"High/Low since signal: {_fmt_price(p.get('running_high'))}/"
            f"{_fmt_price(p.get('running_low'))}",
        ]
        if p.get("pct_move") is not None:
            lines.append(f"% move from entry: {p['pct_move']:.2f}%")
        return "\n".join(lines)

    return ""
