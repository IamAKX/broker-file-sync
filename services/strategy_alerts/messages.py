"""
Renders human-readable notification text for an AlertEvent. Kept separate
from engine.py so the state machine stays pure computation — this module is
the only place that knows what the message text should look like.

render_title/render_message are per-event (one stock). render_batch_* below
combine every AlertEvent from a single Live Master View tick into ONE
notification per channel instead of one per event — see
screens/live_viewer.py's _run_strategy_alert_checks, which is the only
caller that decides whether to batch (exactly one event still goes through
render_title/render_message unchanged, full detail as always). Batching is
purely a delivery-layer choice: it changes nothing about how/when a signal
triggers (services/strategy_alerts/engine.py's state machine has no idea
delivery is even batched).
"""

from datetime import datetime

from services.notifications.levels import NotificationLevel
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


# ── Batch rendering (several AlertEvents from one tick, one notification) ───

_KIND_ORDER = (EVENT_ENTRY, EVENT_TARGET, EVENT_STOP_OUT)
_KIND_SUMMARY_LABEL = {EVENT_ENTRY: "Entries", EVENT_TARGET: "Targets", EVENT_STOP_OUT: "Stop-Outs"}
# A tray notification has real, OS-enforced space limits — cap how many
# stocks are spelled out per kind-group line and say "+N more" past that,
# rather than let the line grow unbounded and get silently truncated by the
# OS with no indication anything was cut. The full, uncapped list is always
# in the Email digest (render_batch_email_message) and the Live Alerts
# screen, regardless of this cap.
_MAX_SUMMARIES_PER_LINE = 6


def _counts_by_kind(events: list[AlertEvent]) -> dict:
    counts = {kind: 0 for kind in _KIND_ORDER}
    for e in events:
        if e.kind in counts:
            counts[e.kind] += 1
    return counts


def _kind_count_label(kind: str, count: int) -> str:
    if kind == EVENT_ENTRY:
        return "New Entry" if count == 1 else "New Entries"
    if kind == EVENT_TARGET:
        return "Target Achieved" if count == 1 else "Targets Achieved"
    if kind == EVENT_STOP_OUT:
        return "Stopped Out"
    return kind


def render_batch_title(events: list[AlertEvent]) -> str:
    """One combined title for every AlertEvent from a single tick, e.g.
    "5 Signals — 2 New Entries, 2 Targets Achieved, 1 Stopped Out". A single
    event just gets its ordinary render_title() — nothing to summarize."""
    if len(events) == 1:
        return render_title(events[0])
    counts = _counts_by_kind(events)
    breakdown = ", ".join(
        f"{n} {_kind_count_label(kind, n)}" for kind, n in counts.items() if n
    )
    return f"{len(events)} Signals — {breakdown}" if breakdown else f"{len(events)} Signals"


def render_batch_level(events: list[AlertEvent]) -> NotificationLevel:
    """A batch containing even one Stop Out is FAILURE (the most attention-
    worthy outcome wins); else SUCCESS if it has a Target Achieved; else INFO
    (entries only). Per-event notifications never varied level (always
    INFO) — worth doing properly now that several land in one message."""
    if any(e.kind == EVENT_STOP_OUT for e in events):
        return NotificationLevel.FAILURE
    if any(e.kind == EVENT_TARGET for e in events):
        return NotificationLevel.SUCCESS
    return NotificationLevel.INFO


def render_summary_line(event: AlertEvent) -> str:
    """One compact "SYMBOL @price" fact — the unit render_batch_tray_message
    packs several of onto a line. Deliberately just symbol + the one price
    that matters for that kind, not render_message()'s full detail (sector,
    every metric, risk:reward) — that detail is what makes packing several
    stocks per line fit in a tray notification's real space limits at all.
    The full detail is still in the Email digest and the Live Alerts screen
    regardless of what the tray shows."""
    p = event.payload
    if event.kind == EVENT_ENTRY:
        return f"{event.symbol} @{_fmt_price(p.get('entry_price'))}"
    if event.kind in (EVENT_TARGET, EVENT_STOP_OUT):
        return f"{event.symbol} @{_fmt_price(p.get('price'))}"
    return event.symbol


def render_batch_tray_message(events: list[AlertEvent]) -> str:
    """Compact, space-aware body for the System tray's one combined
    notification — grouped by kind, each group a single "SYMBOL @price, ..."
    line capped at _MAX_SUMMARIES_PER_LINE stocks (+N more beyond that).
    Full per-stock detail belongs in render_batch_email_message instead —
    the tray's job here is "what happened, at a glance", not "everything"."""
    lines = []
    for kind in _KIND_ORDER:
        matching = [e for e in events if e.kind == kind]
        if not matching:
            continue
        shown = [render_summary_line(e) for e in matching[:_MAX_SUMMARIES_PER_LINE]]
        line = f"{_KIND_SUMMARY_LABEL[kind]}: " + ", ".join(shown)
        extra = len(matching) - _MAX_SUMMARIES_PER_LINE
        if extra > 0:
            line += f", +{extra} more"
        lines.append(line)
    return "\n".join(lines)


def render_batch_email_message(events: list[AlertEvent]) -> str:
    """Full per-stock detail for every event in the batch, stacked under its
    own header — Email has no meaningful space constraint, so nothing here
    is summarized or capped the way render_batch_tray_message's body is.
    Reuses each event's already-rendered title/message (set once when the
    event fired — see engine.py's _fire_entry/_update_open_signal) rather
    than re-render, falling back to render_title/render_message only if
    those are somehow missing."""
    blocks = []
    for e in events:
        header = e.payload.get("title") or render_title(e)
        body = e.payload.get("message") or render_message(e)
        blocks.append(f"{header}\n{'-' * len(header)}\n{body}")
    return "\n\n".join(blocks)
