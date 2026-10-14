"""
Data layer for the Fuku Live Report (resources/report/Fuku_Live_Report_
Requirements...) — turns one live-alert signal (open or resolved) into the
spec's "ALERT -> SCORE -> WHY -> WHERE -> WHAT NEXT -> OUTCOME" narrative:
Fuku Score, trigger explanation, support/resistance levels, target/SL
progress, and lifecycle status.

Sources the signal from services.strategy_alerts.state_store (local, no
network) — an OPEN signal first, falling back to the most recent RESOLVED
one in alert_history for the same (strategy_id, symbol). Support/
resistance levels come from services.inception_bars_store (see services.
support_resistance's own docstring for why that's local-only, not a live
network fetch).
"""

from datetime import datetime

from services import emv_report_data, fuku_score, strategy_store, support_resistance
from services.report_engine import charts, templates
from services.strategy_alerts import config_store as alerts_config_store
from services.strategy_alerts import state_store
from services.strategy_engine import clause_label, split_top_level_and

_STATUS_LABELS = {
    None: "OPEN",
    "all_targets_achieved": "TARGETS ACHIEVED",
    "stopped_out": "STOPPED OUT",
    "trade_cancelled": "TRADE CANCELLED",
    "intraday_closed": "INTRADAY CLOSED",
}


def _fmt_price(value) -> str:
    return f"{value:,.2f}" if value is not None else "—"


def list_available_signals() -> list:
    """[{"strategy_id","strategy_name","symbol","state","resolution"}, ...]
    for every OPEN signal plus the 50 most recently resolved ones — enough
    for a wizard picker without listing the full ~500-record history."""
    out = []
    seen = set()
    for signal in state_store.get_open_signals().values():
        key = (signal.get("strategy_id"), signal.get("symbol"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "strategy_id": signal.get("strategy_id"),
            "strategy_name": signal.get("strategy_name", ""),
            "symbol": signal.get("symbol"), "state": "open", "resolution": None,
        })
    for signal in reversed(state_store.get_alert_history()[-50:]):
        key = (signal.get("strategy_id"), signal.get("symbol"))
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "strategy_id": signal.get("strategy_id"),
            "strategy_name": signal.get("strategy_name", ""),
            "symbol": signal.get("symbol"), "state": "resolved", "resolution": signal.get("resolution"),
        })
    return out


def get_signal(strategy_id: str, symbol: str) -> dict | None:
    key = state_store.signal_key(strategy_id, symbol)
    open_signals = state_store.get_open_signals()
    if key in open_signals:
        return open_signals[key]
    for signal in reversed(state_store.get_alert_history()):
        if signal.get("strategy_id") == strategy_id and signal.get("symbol") == symbol:
            return signal
    return None


def trigger_explanation(strategy_id: str) -> list:
    """Best-effort "why this fired" checklist — each top-level clause of
    the strategy's trigger_condition, shown as informational text and
    marked satisfied: the signal existing at all means the FULL compound
    trigger_condition was true at entry (frozen then); this report has no
    re-evaluable row snapshot from that moment to test each clause
    independently against, and re-evaluating against CURRENT data would
    risk a misleading false ✕ for a clause that's since gone false but was
    true at entry."""
    config = alerts_config_store.load_config(strategy_id)
    if not config or not config.get("trigger_condition"):
        return []
    clauses = split_top_level_and(config["trigger_condition"])
    return [{"label": clause_label(c), "satisfied": True} for c in clauses]


def compute_score(signal: dict | None = None, strategy_id: str | None = None) -> dict:
    """Fuku Score for *signal* against the strategy's configured score
    config (screens.fuku_score_config), falling back to services.fuku_score.
    default_config()'s single always-true rule (100/100) when none exists
    or no signal is given."""
    if signal is None:
        return fuku_score.compute_score(fuku_score.default_config(), {}, [{}])
    return fuku_score.score_signal(signal, strategy_id)


def support_resistance_data(symbol: str, direction: str, current_price: float | None) -> dict:
    from services import emv_report_data, inception_bars_store

    resolved_symbol = emv_report_data.resolve_symbol(symbol)
    raw_bars = inception_bars_store.bars_for_symbol(resolved_symbol)
    bars = [
        {"date": b["trade_date"], "high": b["high"], "low": b["low"], "close": b["close"]}
        for b in raw_bars
    ]
    sources = support_resistance.level_sources(bars)
    levels = support_resistance.nearby_levels(sources, current_price, direction) if (sources and current_price) else []
    zones = support_resistance.confluence_zones(sources) if sources else []
    return {"sources": sources, "levels": levels, "confluence": zones}


def elapsed_label(entry_time_iso: str | None, end_iso: str | None = None) -> str:
    if not entry_time_iso:
        return "—"
    entry = datetime.fromisoformat(entry_time_iso)
    end = datetime.fromisoformat(end_iso) if end_iso else datetime.now()
    delta = end - entry
    if delta.days >= 1:
        return f"{delta.days} Day" if delta.days == 1 else f"{delta.days} Days"
    hours, remainder = divmod(delta.seconds, 3600)
    minutes = remainder // 60
    return f"{hours}h {minutes}m"


def current_price_of(signal: dict) -> float | None:
    """Best available "current" price: the live tick last seen while the
    signal was open (engine stores last_price), else the price it resolved
    at, else entry. Never running_high/low — those are extremes, not "now"."""
    for key in ("last_price", "exit_price", "entry_price"):
        if signal.get(key) is not None:
            return signal[key]
    return None


def pct_move(signal: dict) -> float | None:
    """Direction-adjusted % move since entry (positive = in the signal's
    favour): BUY up / SELL down."""
    entry, cur = signal.get("entry_price"), current_price_of(signal)
    if not entry or cur is None:
        return None
    pct = (cur - entry) / entry * 100
    return pct if signal.get("direction", "BUY") == "BUY" else -pct


def _targets(signal: dict) -> list:
    """[{"name","value","achieved","achieved_at","progress","valid"}] for
    every target metric, in the strategy's own order. *progress* is 0..1
    toward the target; *valid* is False when the target sits on the wrong
    side of entry for the direction (the Trade Cancelled case)."""
    entry = signal.get("entry_price")
    cur = current_price_of(signal)
    direction = signal.get("direction", "BUY")
    out = []
    for m in (signal.get("metrics") or {}).values():
        if m.get("role") != "target":
            continue
        value = m.get("value")
        valid = value is not None and entry is not None and (
            value > entry if direction == "BUY" else value < entry
        )
        if m.get("achieved"):
            progress = 1.0
        elif valid and cur is not None:
            progress = max(0.0, min(1.0, (cur - entry) / (value - entry)))
        else:
            progress = 0.0
        out.append({
            "name": m.get("name", "Target"), "value": value, "achieved": bool(m.get("achieved")),
            "achieved_at": m.get("achieved_at"), "progress": progress, "valid": valid,
        })
    return out


def _stop_loss(signal: dict) -> float | None:
    metrics = (signal.get("metrics") or {}).values()
    for m in metrics:
        if m.get("role") in ("stop_loss", "trailing_exit") and m.get("value") is not None:
            return m["value"]
    for m in metrics:  # strategies that model SL as an informational metric
        name = str(m.get("name", "")).strip().lower()
        if name in ("sl", "stop loss", "stoploss", "stop-loss") and m.get("value") is not None:
            return m["value"]
    return None


def _fmt_time(iso: str | None) -> str:
    try:
        return datetime.fromisoformat(iso).strftime("%d-%b %H:%M")
    except (TypeError, ValueError):
        return "—"


def timeline_events(data: dict) -> list:
    """[{"title","detail","kind"}] in time order: signal opened, each target
    achieved (with its time), High/Low since signal, then the outcome — or
    a PENDING marker while the signal is still open."""
    signal = data["signal"]
    direction = data["direction"]
    events = [{
        "when": signal.get("entry_time"), "title": _fmt_time(signal.get("entry_time")),
        "detail": f'SIGNAL @ {_fmt_price(signal.get("entry_price"))}', "kind": "info",
    }]
    for t in data["targets"]:
        if t["achieved"]:
            events.append({
                "when": t["achieved_at"], "title": _fmt_time(t["achieved_at"]),
                "detail": f'{t["name"].upper()} ACHIEVED {_fmt_price(t["value"])}', "kind": "good",
            })
    extreme = signal.get("running_high") if direction == "BUY" else signal.get("running_low")
    if extreme is not None:
        events.append({
            "when": None, "title": "HIGH" if direction == "BUY" else "LOW",
            "detail": _fmt_price(extreme), "kind": "info",
        })
    events.sort(key=lambda e: (e["when"] is None, e["when"] or ""))
    resolution = signal.get("resolution")
    if resolution:
        kind = "good" if resolution == "all_targets_achieved" else "bad" if resolution == "stopped_out" else "pending"
        events.append({
            "when": signal.get("resolved_at"), "title": _fmt_time(signal.get("resolved_at")),
            "detail": data["status"], "kind": kind,
        })
    else:
        events.append({"when": None, "title": "NOW", "detail": f'{_fmt_price(data["current_price"])} — pending target / SL', "kind": "pending"})
    return events


def build_report_data(strategy_id: str, symbol: str, signal: dict | None = None) -> dict:
    """*signal* lets a caller that already holds the signal (Live Alerts'
    backend-sourced row, or the strategy-wide report's own scan) bypass the
    local state_store lookup."""
    strategies_by_id = {s["id"]: s for s in strategy_store.load_all()}
    signal = signal or get_signal(strategy_id, symbol)
    if signal is None:
        return {"found": False, "strategy_id": strategy_id, "symbol": symbol}

    config = alerts_config_store.load_config(strategy_id) or {}
    direction = signal.get("direction", "BUY")
    entry_price = signal.get("entry_price")
    current_price = current_price_of(signal)

    status = _STATUS_LABELS.get(signal.get("resolution"), signal.get("resolution") or "OPEN")

    data = {
        "found": True,
        "signal": signal,
        "strategy_id": strategy_id,
        "strategy_name": strategies_by_id.get(strategy_id, {}).get("name", signal.get("strategy_name", "")),
        "alert_mode": config.get("alert_mode", "positional"),
        "direction": direction,
        "symbol": symbol,
        "sector": signal.get("sector"),
        "entry_price": entry_price,
        "current_price": current_price,
        "status": status,
        "score": compute_score(signal, strategy_id),
        "trigger": trigger_explanation(strategy_id),
        "sr": support_resistance_data(symbol, direction, current_price),
        "elapsed": elapsed_label(signal.get("entry_time"), signal.get("resolved_at")),
        "metrics": signal.get("metrics", {}),
        "pct_move": pct_move(signal),
        "targets": _targets(signal),
        "stop_loss": _stop_loss(signal),
    }
    data["timeline"] = timeline_events(data)
    return data


# ── Strategy-wide report ─────────────────────────────────────────────────

def strategy_signals(strategy_id: str, include_stopped: bool = False, include_cancelled: bool = False,
                     include_achieved: bool = False) -> list:
    """Every OPEN signal of *strategy_id*, plus — per the toggles — the most
    recent resolved signal of each symbol that has no open one: stopped-out
    (include_stopped), trade-cancelled (include_cancelled: entry already on
    the wrong side of a target) and all-targets-achieved (include_achieved).
    Local state only (no network)."""
    wanted = set()
    if include_stopped:
        wanted.add("stopped_out")
    if include_cancelled:
        wanted.add("trade_cancelled")
    if include_achieved:
        wanted.update({"all_targets_achieved", "intraday_closed"})

    # "pending" = trigger true but no entry has happened yet (no price/time/
    # sector) — not a trade, and Live Alerts doesn't list it either.
    signals = [s for s in state_store.get_open_signals().values()
               if s.get("strategy_id") == strategy_id and s.get("state", "open") == "open"]
    seen = {s.get("symbol") for s in signals}
    if wanted:
        for r in reversed(state_store.get_alert_history()):
            if r.get("strategy_id") != strategy_id or r.get("symbol") in seen:
                continue
            seen.add(r.get("symbol"))  # latest record per symbol decides
            if r.get("resolution") in wanted:
                signals.append(r)
    return signals


def _sort_key(card: dict):
    return card["signal"].get("entry_time") or ""


def build_strategy_report_data(strategy_id: str, include_stopped: bool = False,
                               include_cancelled: bool = False, include_achieved: bool = False,
                               new_since: datetime | None = None, refresh_minutes: int = 0) -> dict:
    """The whole-strategy report: one card per stock. *new_since* marks a
    signal "recently added" when it was entered after that time (the caller
    passes the previous generation time, so a refresh highlights exactly the
    stocks that matched since)."""
    cards = []
    for signal in strategy_signals(strategy_id, include_stopped, include_cancelled, include_achieved):
        card = build_report_data(strategy_id, signal.get("symbol"), signal=signal)
        entered = _parse_dt(signal.get("entry_time"))
        card["is_new"] = bool(new_since and entered and entered > new_since)
        card["sector_name"] = (signal.get("sector") or "Unclassified")
        cards.append(card)
    cards.sort(key=_sort_key, reverse=True)

    strategies_by_id = {s["id"]: s for s in strategy_store.load_all()}
    pending = sum(1 for s in state_store.get_open_signals().values()
                  if s.get("strategy_id") == strategy_id and s.get("state") == "pending")
    return {
        "mode": "strategy",
        "pending_count": pending,
        "strategy_id": strategy_id,
        "strategy_name": strategies_by_id.get(strategy_id, {}).get("name", cards[0]["strategy_name"] if cards else ""),
        "cards": cards,
        "generated_at": datetime.now(),
        "refresh_minutes": refresh_minutes,
        "options": {"stopped": include_stopped, "cancelled": include_cancelled, "achieved": include_achieved},
    }


def _parse_dt(iso: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None


# ── Rendering ────────────────────────────────────────────────────────────

_SECTOR_PALETTE = ["#2979FF", "#16a34a", "#D97706", "#dc2626", "#8250df", "#0969da", "#bf3989", "#65a30d",
                   "#0891b2", "#9333ea", "#ca8a04", "#475569"]
# Estimated heights (px @96dpi) for flow pagination — see emv_report_data.
_CARD_BASE_PX = 128   # header + KPI strip + card padding + progress block spacing
_LADDER_ROW_PX = 30
_PROGRESS_ROW_PX = 22


def _level_rows(data: dict) -> list:
    """Price-ladder rows for one card: targets, nearby possible resistance/
    support (with source + confluence), last/current, entry, stop loss."""
    rows = []
    for t in data["targets"]:
        if t["value"] is not None:
            rows.append({"label": t["name"], "price": t["value"], "color": "#16a34a",
                         "sub": "ACHIEVED" if t["achieved"] else ("invalid (wrong side of entry)" if not t["valid"] else "")})
    prefix = "R" if data["direction"] == "BUY" else "S"
    zones = data["sr"].get("confluence") or []
    for i, lvl in enumerate(data["sr"]["levels"], start=1):
        sub = lvl["label"]
        for z in zones:
            if lvl["price"] and abs(z["price"] - lvl["price"]) / lvl["price"] < 0.005:
                sub += f' · ★ {z["count"]} factors'
                break
        rows.append({"label": f"{prefix}{i}", "price": lvl["price"], "color": "#2979FF", "sub": sub})
    if data["current_price"] is not None:
        rows.append({"label": "CURRENT", "price": data["current_price"], "color": "#0F172A", "emphasis": True,
                     "sub": "last live price" if (data["signal"].get("last_price") is not None) else "last known"})
    if data["entry_price"] is not None:
        rows.append({"label": "ENTRY", "price": data["entry_price"], "color": "#D97706", "emphasis": True})
    if data["stop_loss"] is not None:
        rows.append({"label": "STOP LOSS", "price": data["stop_loss"], "color": "#dc2626"})
    return rows


def _status_badge(data: dict) -> str:
    kind = {"TARGETS ACHIEVED": "win", "STOPPED OUT": "loss", "TRADE CANCELLED": "cancel"}.get(data["status"], "open")
    return f'<span class="fk-badge {kind}">{templates.esc(data["status"])}</span>'


def _kpi(label: str, value: str, cls: str = "") -> str:
    return f'<div class="fk-kpi {cls}"><div class="l">{templates.esc(label)}</div><div class="v">{templates.esc(value)}</div></div>'


def card_html(data: dict, generated_at: datetime | None = None) -> tuple:
    """One stock's dashboard card -> (html, estimated_height_px)."""
    direction = data["direction"]
    side = "buy" if direction == "BUY" else "sell"
    new_badge = ""
    if data.get("is_new"):
        stamp = f' {generated_at.strftime("%H:%M")}' if generated_at else ""
        new_badge = f'<span class="fk-badge new">★ RECENTLY ADDED{templates.esc(stamp)}</span>'

    band = data["score"].get("band")
    score_txt = f'{data["score"]["score"]:.0f}/{data["score"]["max_score"]:.0f}'
    if band:
        score_txt += f' {band["label"]}'
    mv = data.get("pct_move")
    mv_cls = "" if mv is None else ("pos" if mv >= 0 else "neg")
    first_target = next((t for t in data["targets"] if t["value"] is not None), None)
    kpis = (
        _kpi("Fuku score", score_txt, "score")
        + _kpi("Entry", _fmt_price(data["entry_price"]))
        + _kpi("Current", _fmt_price(data["current_price"]))
        + _kpi(first_target["name"] if first_target else "Target", _fmt_price(first_target["value"]) if first_target else "—")
        + _kpi("Stop loss", _fmt_price(data["stop_loss"]))
        + _kpi("% move", f"{mv:+.2f}%" if mv is not None else "—", mv_cls)
    )

    rows = _level_rows(data)
    ladder = charts.price_ladder(rows, data["current_price"], width=430)

    chips = "".join(
        f'<div class="fk-chip {"ok" if t["satisfied"] else "no"}">{"✓" if t["satisfied"] else "✕"} {templates.esc(t["label"])}</div>'
        for t in data["trigger"]
    ) or '<div class="fk-note">No trigger condition configured.</div>'

    tl = "".join(
        f'<div class="fk-tl-item {e["kind"]}"><span class="t">{templates.esc(e["title"])}</span> '
        f'<span class="d">{templates.esc(e["detail"])}</span></div>'
        for e in data["timeline"]
    )

    progress = ""
    for t in data["targets"]:
        if t["value"] is None:
            continue
        pct = 100 if t["achieved"] else round(t["progress"] * 100)
        note = "✓ achieved" if t["achieved"] else (f"{pct}%" if t["valid"] else "invalid")
        progress += (
            f'<div class="fk-prog"><span class="n">{templates.esc(t["name"])} {_fmt_price(t["value"])}</span>'
            f'<span class="bar">{charts.progress_bar(pct / 100, color="#16a34a" if t["valid"] else "#94a3b8")}</span>'
            f'<span class="p">{note}</span></div>'
        )

    sub = " · ".join(x for x in (
        data.get("sector") or "—", data["strategy_name"], data["alert_mode"].title(),
        f'opened {_fmt_time(data["signal"].get("entry_time"))}', f'age {data["elapsed"]}',
    ) if x)
    html_ = (
        f'<div class="fk-card fk-{side}{" fk-new" if data.get("is_new") else ""}">'
        f'<div class="fk-head"><div><div class="fk-sym">{templates.esc(data["symbol"])}</div>'
        f'<div class="fk-sub">{templates.esc(sub)}</div></div>'
        f'<div class="fk-badges">{new_badge}<span class="fk-badge {side}">{direction}</span>{_status_badge(data)}</div></div>'
        f'<div class="fk-kpis">{kpis}</div>'
        f'<div class="fk-cols"><div class="fk-col-main"><div class="fk-h">Price levels — '
        f'{"possible resistance" if direction == "BUY" else "possible support"}</div>{ladder}</div>'
        f'<div class="fk-col-side"><div class="fk-h">Why this signal triggered</div><div class="fk-chips">{chips}</div>'
        f'<div class="fk-h">Signal timeline</div><div class="fk-tl">{tl}</div></div></div>'
        f'<div class="fk-h" style="margin-top:8px">Target progress</div>{progress or "<div class=fk-note>No targets configured.</div>"}'
        f'</div>'
    )
    n_tl = len(data["timeline"]) + len(data["trigger"])
    height = (_CARD_BASE_PX + max(len(rows) * _LADDER_ROW_PX, n_tl * 20 + 30)
              + max(len([t for t in data["targets"] if t["value"] is not None]), 1) * _PROGRESS_ROW_PX)
    return html_, height


def _status_counts(cards: list) -> dict:
    counts = {"open": 0, "win": 0, "loss": 0, "cancel": 0}
    for c in cards:
        key = {"TARGETS ACHIEVED": "win", "STOPPED OUT": "loss", "TRADE CANCELLED": "cancel"}.get(c["status"], "open")
        counts[key] += 1
    return counts


def _sector_overview(cards: list) -> tuple:
    by_sector: dict = {}
    for c in cards:
        by_sector.setdefault(c["sector_name"], []).append(c)
    ranked = sorted(by_sector.items(), key=lambda kv: (-len(kv[1]), kv[0]))
    segments = [
        {"label": name, "value": len(items), "color": _SECTOR_PALETTE[i % len(_SECTOR_PALETTE)]}
        for i, (name, items) in enumerate(ranked)
    ]
    return ranked, segments


def build_strategy_report_pages(data: dict) -> list:
    cards = data["cards"]
    generated = data["generated_at"]
    refresh = data.get("refresh_minutes") or 0
    subtitle = f'{data["strategy_name"]} — {len(cards)} stock{"s" if len(cards) != 1 else ""}'
    meta = f'Auto-refresh every {refresh} min' if refresh else "Live snapshot"
    header = templates.report_header("Fuku Live Report", subtitle, generated, extra_meta=meta)

    pending = data.get("pending_count") or 0
    pending_note = (
        f'<p class="fk-note">{pending} more stock{"s" if pending != 1 else ""} currently match the trigger but '
        f'ha{"ve" if pending != 1 else "s"} not been entered yet (pending) — not listed below.</p>' if pending else ""
    )
    if not cards:
        return [header + templates.section(
            "No signals",
            '<p style="color:#64748b;font-size:11px;">No active signals for this strategy'
            " (try including stopped-out / cancelled trades).</p>" + pending_note)]

    counts = _status_counts(cards)
    moves = [c["pct_move"] for c in cards if c["pct_move"] is not None]
    avg_move = sum(moves) / len(moves) if moves else None
    new_count = sum(1 for c in cards if c.get("is_new"))
    kpis = (
        templates.kpi_card("Stocks", str(len(cards)))
        + templates.kpi_card("Open", str(counts["open"]))
        + templates.kpi_card("Targets hit", str(counts["win"]), kind="positive" if counts["win"] else "neutral")
        + templates.kpi_card("Stopped out", str(counts["loss"]), kind="negative" if counts["loss"] else "neutral")
        + templates.kpi_card("Avg % move", f"{avg_move:+.2f}%" if avg_move is not None else "—",
                             kind="neutral" if avg_move is None else ("positive" if avg_move >= 0 else "negative"))
        + (templates.kpi_card("Recently added", str(new_count), kind="positive") if new_count else "")
    )

    ranked, segments = _sector_overview(cards)
    donut = charts.donut_chart(segments, center_label=str(len(cards)), center_sublabel="Stocks")
    sector_rows = []
    for name, items in ranked:
        mv = [c["pct_move"] for c in items if c["pct_move"] is not None]
        sector_rows.append([name, str(len(items)), f"{sum(mv) / len(mv):+.2f}%" if mv else "—"])
    sector_html = (
        f'<div class="chart-row"><div>{donut}</div><div>{charts.donut_legend(segments)}</div></div>'
        + templates.data_table(["Sector", "Stocks", "Avg % move"], sector_rows)
    )

    bubbles = []
    for c in cards:
        if c["pct_move"] is None:
            continue
        entered = _parse_dt(c["signal"].get("entry_time"))
        end = _parse_dt(c["signal"].get("resolved_at")) or generated
        age_min = max((end - entered).total_seconds() / 60, 0) if entered else 0
        bubbles.append({
            "label": c["symbol"], "x": age_min / 60, "y": c["pct_move"],
            "size": max(c["score"]["score"], 1) if c["score"].get("score") is not None else 1,
            "color": "#16a34a" if c["pct_move"] >= 0 else "#dc2626",
        })
    bubble_html = charts.bubble_chart(
        bubbles, x_label="Hours since signal", y_label="% move since signal (+ = in favour)",
    ) + '<p class="fk-note">Bubble size = Fuku score; green = moving in the signal\'s favour, red = against.</p>'

    page1 = (
        header + f'<div class="kpi-row">{kpis}</div>' + pending_note
        + templates.section("Sector Distribution", sector_html)
    )
    blocks = [(templates.section("Move Since Signal", bubble_html), 38 + 320 + 20)]

    first_used = 74 + 78 + 330
    def _group(head_html: str, group_cards: list):
        """A group heading is glued to its first card so it can never be
        stranded alone at the bottom of a page."""
        for i, c in enumerate(group_cards):
            html_, h = card_html(c, generated)
            if i == 0:
                html_, h = head_html + html_, h + 34
            blocks.append((html_, h))

    new_cards = [c for c in cards if c.get("is_new")]
    if new_cards:
        _group('<div class="fk-sector-head"><span class="name">★ Recently added</span>'
               f'<span class="cnt">{len(new_cards)} · since last refresh</span></div>', new_cards)
    for name, items in ranked:
        rest = [c for c in items if not c.get("is_new")]
        if rest:
            _group(f'<div class="fk-sector-head"><span class="name">{templates.esc(name)}</span>'
                   f'<span class="cnt">{len(rest)} stock{"s" if len(rest) != 1 else ""}</span></div>', rest)

    blocks.append((
        '<p class="fk-note">Possible resistance/support levels are derived from the synced daily bars '
        '(previous day/week/month highs &amp; lows, Camarilla, pivots, ATR bands) — independent of any '
        'informational metric in the strategy. ★ marks a confluence of several sources near the same price. '
        'Current = last live price seen while the alert was open.</p>', 40))

    return emv_report_data._flow_pages(page1, first_used, blocks, "", [], [], set())


def build_strategy_report_html(data: dict, doc_title: str = "Fuku Live Report") -> str:
    return templates.render_report(build_strategy_report_pages(data), doc_title=doc_title)


def build_report_pages(data: dict) -> list:
    """Single-stock report: the same dashboard card as the strategy report,
    followed by the score breakdown and target/SL metric table (the
    explainability detail a whole-strategy report omits)."""
    if not data.get("found"):
        page = (
            templates.report_header("Fuku Live Report", f'{data["symbol"]} — no signal found', datetime.now())
            + templates.section(
                "No Data",
                '<p style="color:#64748b;font-size:11px;">No open or recently resolved '
                "signal found for this strategy/symbol.</p>",
            )
        )
        return [page]

    now = datetime.now()
    card, _ = card_html(data, now)
    page1 = (
        templates.report_header(
            "Fuku Live Report",
            f'{data["symbol"]} — {data["direction"]} — {data["strategy_name"]} ({data["alert_mode"].title()})',
            now,
        )
        + card
    )

    metrics_rows = []
    for m in data["metrics"].values():
        status_label = "ACHIEVED" if m.get("achieved") else ("—" if m.get("value") is None else "OPEN")
        metrics_rows.append([m.get("name", ""), m.get("role", ""), _fmt_price(m.get("value")), status_label])
    metrics_table = (
        templates.data_table(["Metric", "Role", "Value", "Status"], metrics_rows)
        if metrics_rows else '<p style="color:#64748b;font-size:11px;">No target/stop-loss metrics configured.</p>'
    )
    breakdown_rows = [
        [r["label"], f'{r["points"]:g}', f'{r["weight"]:g}', "✓" if r["satisfied"] else "✕",
         f'{r["contribution"]:g}']
        for r in data["score"].get("rule_results", [])
    ]
    breakdown_table = (
        templates.data_table(["Rule", "Points", "Weight", "Met", "Contribution"], breakdown_rows)
        if breakdown_rows else '<p style="color:#64748b;font-size:11px;">No score rules configured.</p>'
    )
    page2 = (
        templates.section("Target / Stop-Loss Metrics", metrics_table)
        + templates.section(f'Fuku Score Breakdown — {templates.esc(data["score"].get("config_name", ""))}', breakdown_table)
    )
    return [page1, page2]


def build_report_html(data: dict, doc_title: str = "Fuku Live Report") -> str:
    return templates.render_report(build_report_pages(data), doc_title=doc_title)
