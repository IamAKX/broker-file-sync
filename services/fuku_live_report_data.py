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

from services import fuku_score, strategy_store, support_resistance
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


def compute_score() -> dict:
    """Default single-rule Fuku Score — 100/100, since a signal existing
    at all means its trigger condition fired (same principled-default
    pattern as services.emv_report_data.classify_strategy: every returned
    result already passed the one rule that gates it). A real per-sub-
    condition weighted breakdown needs a scoring-rule config UI this
    codebase doesn't have yet."""
    # condition=[{"type": "num", "value": "1"}] — a literal truthy 1, not
    # [] (empty tokens compile to no expression at all, which evaluates to
    # None -> False, not "always true" — see services.strategy_engine.
    # evaluate/_build_compiled).
    score_config = fuku_score.new_config("Fuku Score", max_score=100)
    score_config["rules"] = [
        fuku_score.new_rule("Trigger Condition", [{"type": "num", "value": "1"}], points=100)
    ]
    return fuku_score.compute_score(score_config, {}, [{}])


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


def _elapsed_label(entry_time_iso: str | None, end_iso: str | None = None) -> str:
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


def build_report_data(strategy_id: str, symbol: str) -> dict:
    strategies_by_id = {s["id"]: s for s in strategy_store.load_all()}
    signal = get_signal(strategy_id, symbol)
    if signal is None:
        return {"found": False, "strategy_id": strategy_id, "symbol": symbol}

    config = alerts_config_store.load_config(strategy_id) or {}
    direction = signal.get("direction", "BUY")
    entry_price = signal.get("entry_price")
    current_price = signal.get("running_high") if direction == "BUY" else signal.get("running_low")
    if current_price is None:
        current_price = entry_price

    status = _STATUS_LABELS.get(signal.get("resolution"), signal.get("resolution") or "OPEN")

    return {
        "found": True,
        "signal": signal,
        "strategy_name": strategies_by_id.get(strategy_id, {}).get("name", signal.get("strategy_name", "")),
        "alert_mode": config.get("alert_mode", "positional"),
        "direction": direction,
        "symbol": symbol,
        "sector": signal.get("sector"),
        "entry_price": entry_price,
        "current_price": current_price,
        "status": status,
        "score": compute_score(),
        "trigger": trigger_explanation(strategy_id),
        "sr": support_resistance_data(symbol, direction, current_price),
        "elapsed": _elapsed_label(signal.get("entry_time"), signal.get("resolved_at")),
        "metrics": signal.get("metrics", {}),
    }


def build_report_pages(data: dict) -> list:
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

    status_kind = (
        "positive" if data["status"] == "TARGETS ACHIEVED"
        else "negative" if data["status"] == "STOPPED OUT"
        else "neutral"
    )
    kpis = (
        templates.kpi_card("Fuku Score", f'{data["score"]["score"]:.0f} / {data["score"]["max_score"]:.0f}')
        + templates.kpi_card("Status", data["status"], kind=status_kind)
        + templates.kpi_card("Entry", _fmt_price(data["entry_price"]))
        + templates.kpi_card("Current", _fmt_price(data["current_price"]))
        + templates.kpi_card("Elapsed", data["elapsed"])
    )

    trigger_html = "".join(
        f'<div>{"✓" if t["satisfied"] else "✕"} {templates.esc(t["label"])}</div>' for t in data["trigger"]
    ) or '<p style="color:#64748b;font-size:11px;">No trigger condition configured.</p>'

    levels = data["sr"]["levels"]
    levels_rows = [
        [l["label"], _fmt_price(l["price"]), f'{l["distance_pct"]:+.2f}%' if l["distance_pct"] is not None else "—"]
        for l in levels
    ]
    levels_table = (
        templates.data_table(["Level", "Price", "Distance"], levels_rows) if levels_rows
        else '<p style="color:#64748b;font-size:11px;">No historical data available for support/resistance levels.</p>'
    )

    confluence_html = "".join(
        f'<div>{z["count"]} factors near {_fmt_price(z["price"])} ({templates.esc(", ".join(z["labels"]))})</div>'
        for z in data["sr"]["confluence"]
    )

    metrics_rows = []
    for m in data["metrics"].values():
        progress_html = ""
        if m.get("role") == "target" and data["entry_price"] and m.get("value") is not None:
            span = abs(m["value"] - data["entry_price"])
            done = abs((data["current_price"] or data["entry_price"]) - data["entry_price"])
            frac = min(1.0, done / span) if span else 0.0
            progress_html = charts.progress_bar(frac, color="#16a34a")
        status_label = "ACHIEVED" if m.get("achieved") else ("—" if m.get("value") is None else "OPEN")
        metrics_rows.append(
            [m.get("name", ""), m.get("role", ""), _fmt_price(m.get("value")), status_label, progress_html]
        )
    metrics_table = (
        templates.data_table(["Metric", "Role", "Value", "Status", "Progress"], metrics_rows, column_html={"Progress"})
        if metrics_rows else '<p style="color:#64748b;font-size:11px;">No target/stop-loss metrics configured.</p>'
    )

    page1 = (
        templates.report_header(
            "Fuku Live Report",
            f'{data["symbol"]} — {data["direction"]} — {data["strategy_name"]} ({data["alert_mode"].title()})',
            datetime.now(),
        )
        + f'<div class="kpi-row">{kpis}</div>'
        + templates.section("Why This Signal Triggered", trigger_html)
        + templates.section(
            "Possible " + ("Resistance" if data["direction"] == "BUY" else "Support"),
            levels_table + confluence_html,
        )
    )
    page2 = templates.section("Target / Stop-Loss Progress", metrics_table)

    return [page1, page2]


def build_report_html(data: dict, doc_title: str = "Fuku Live Report") -> str:
    return templates.render_report(build_report_pages(data), doc_title=doc_title)
