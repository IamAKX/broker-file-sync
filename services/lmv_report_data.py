"""
Data layer for the LMV EOD Report (resources/report/LMV_Based_Strategy_EOD_
Report_Requirements_v5.docx) — pulls resolved strategy-alert trades
(services.strategy_alerts.state_store's local alert_history is the source
of truth for "what actually happened"; api.strategy_signals_api.list_signals
is a best-effort supplement for a Custom range going back further than
local history's ~500-record retention), computes directional/blended yield
(services.report_metrics), and builds the report_engine HTML pages the
Reports screen previews/exports.

A "trade_cancelled" resolution is excluded everywhere here — see services.
strategy_alerts.models: that trade never actually executed (issue #32), so
it contributes no yield and isn't part of win/loss counts.
"""

from datetime import date, datetime, timedelta

from services import report_metrics, strategy_store
from services.report_engine import charts, templates
from services.strategy_alerts import state_store

DEFAULT_INVESTMENT_AMOUNT = 5000.0

_RESOLUTION_LABELS = {
    "all_targets_achieved": ("TARGET HIT", "positive"),
    "stopped_out": ("STOP LOSS", "negative"),
    "intraday_closed": ("CLOSED", "neutral"),
}


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _resolved_dt(trade: dict) -> datetime:
    try:
        return datetime.fromisoformat(trade["resolved_at"])
    except Exception:
        return datetime.min


def _fallback_exit_price(trade: dict) -> float | None:
    """Older history (recorded before exit_price capture shipped) has no
    exit_price — approximate with the target/SL threshold value that
    actually resolved the trade rather than showing a blank yield."""
    metrics = trade.get("metrics") or {}
    resolution = trade.get("resolution")
    if resolution == "all_targets_achieved":
        for m in metrics.values():
            if m.get("role") == "target" and m.get("achieved") and m.get("value") is not None:
                return m["value"]
    if resolution == "stopped_out":
        for m in metrics.values():
            if m.get("role") in ("stop_loss", "trailing_exit") and m.get("value") is not None:
                return m["value"]
    return None


def _exit_price(trade: dict) -> float | None:
    price = trade.get("exit_price")
    return price if price is not None else _fallback_exit_price(trade)


def _days_true_label(trade: dict) -> str:
    try:
        entry = datetime.fromisoformat(trade["entry_time"])
        resolved = _resolved_dt(trade)
    except Exception:
        return "—"
    delta = resolved - entry
    if delta < timedelta(hours=24):
        hours = max(delta.seconds // 3600, 0)
        return f"{hours} Hr" if hours != 1 else "1 Hr"
    days = delta.days
    return f"{days} Day" if days == 1 else f"{days} Days"


def _local_resolved_trades(strategy_id: str) -> list:
    seen_ids = set()
    trades = []
    for r in state_store.get_alert_history():
        if r.get("strategy_id") != strategy_id:
            continue
        if r.get("resolution") in (None, "trade_cancelled"):
            continue
        if not r.get("resolved_at"):
            continue
        rid = r.get("id")
        if rid:
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
        trades.append(r)
    return trades


def _backend_resolved_trades(strategy_id: str, date_from: date, date_to: date) -> list:
    """Best-effort supplement from the backend's durable signal history
    (api.strategy_signals_api), for a Custom range reaching further back
    than local alert_history's ~500-record retention. Deliberately NOT
    called for every report generation (see fetch_extra_history's own
    caller in build_report_data) — a network round trip on every report
    open/refresh would make the feature feel unreliable/slow the moment
    the backend is slow or unreachable; it's only worth the round trip when
    the user explicitly asked for a range local history might not cover."""
    try:
        from api import strategy_signals_api
        from api.exceptions import ApiError, NetworkError

        response = strategy_signals_api.list_signals(
            strategy_id=strategy_id,
            start_time=datetime.combine(date_from, datetime.min.time()).isoformat(),
            end_time=datetime.combine(date_to, datetime.max.time()).isoformat(),
            page_size=100,
        )
    except (ApiError, NetworkError):
        return []
    return [
        r for r in response.get("items", [])
        if r.get("resolution") not in (None, "trade_cancelled") and r.get("resolved_at")
    ]


def resolved_trades_for_strategy(strategy_id: str, date_from: date | None = None,
                                  date_to: date | None = None,
                                  include_backend: bool = False) -> list:
    """Resolved (non-cancelled) trades for *strategy_id*, newest last, from
    local alert_history — plus a best-effort backend supplement when
    *include_backend* is True (build_report_data sets this only for a
    Custom-range request, see _backend_resolved_trades)."""
    trades = _local_resolved_trades(strategy_id)

    if include_backend and date_from is not None:
        seen_ids = {t.get("id") for t in trades if t.get("id")}
        for r in _backend_resolved_trades(strategy_id, date_from, date_to or date_from):
            rid = r.get("id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            trades.append(r)

    if date_from is not None:
        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to or date_from, datetime.max.time())
        trades = [t for t in trades if lo <= _resolved_dt(t) <= hi]

    trades.sort(key=_resolved_dt)
    return trades


def compute_strategy_summary(strategy_id: str, date_from: date | None, date_to: date | None,
                              include_backend: bool = False) -> dict:
    trades = resolved_trades_for_strategy(strategy_id, date_from, date_to, include_backend=include_backend)

    rows = []
    yields = []
    resolution_counts: dict = {}
    for t in trades:
        entry = t.get("entry_price")
        exit_p = _exit_price(t)
        direction = t.get("direction", "BUY")
        y = report_metrics.directional_yield(entry, exit_p, direction)
        yields.append(y)
        resolution_counts[t.get("resolution")] = resolution_counts.get(t.get("resolution"), 0) + 1
        label, kind = _RESOLUTION_LABELS.get(t.get("resolution"), (t.get("resolution", ""), "neutral"))
        # A positional "intraday_closed" isn't inherently a win or loss —
        # recolor it by its own yield sign rather than a fixed neutral tag.
        if t.get("resolution") == "intraday_closed" and y is not None:
            kind = "positive" if y >= 0 else "negative"
        rows.append({
            "date": _resolved_dt(t),
            "symbol": t.get("symbol", ""),
            "direction": direction,
            "entry": entry,
            "exit": exit_p,
            "yield": y,
            "status_label": label,
            "status_kind": kind,
            "days_true": _days_true_label(t),
        })

    return {
        "strategy_id": strategy_id,
        "trades": trades,
        "rows": rows,
        "yields": yields,
        "blended_yield": report_metrics.blended_yield(yields),
        "win_rate": report_metrics.win_rate(yields),
        "closed_trades": len(trades),
        "resolution_counts": resolution_counts,
        "sharpe": report_metrics.sharpe_ratio(yields),
        "sortino": report_metrics.sortino_ratio(yields),
        "calmar": report_metrics.calmar_ratio(yields),
    }


def build_report_data(strategy_a_id: str, strategy_b_id: str | None,
                       timeframe: str, date_from: date | None, date_to: date | None,
                       investment_amount: float = DEFAULT_INVESTMENT_AMOUNT,
                       include_backend: bool = False) -> dict:
    """*timeframe* is the CURVE'S bucketing granularity (daily/weekly/
    monthly/quarterly — how the comparative performance curve groups
    trades), independent of *date_from*/*date_to* (the lookback window
    itself, already resolved by the caller e.g. via report_metrics.
    resolve_preset_range). *include_backend* opts into the backend
    supplement fetch (see _backend_resolved_trades) — callers should only
    set this True for a Custom range reaching further back than local
    alert_history's ~500-record retention; it's False by default so a
    normal Daily/Weekly/Monthly/Quarterly report generates fast and works
    fully offline."""
    strategies_by_id = {s["id"]: s for s in strategy_store.load_all()}
    summary_a = compute_strategy_summary(strategy_a_id, date_from, date_to, include_backend)
    summary_a["name"] = strategies_by_id.get(strategy_a_id, {}).get("name", "Strategy A")

    summary_b = None
    if strategy_b_id:
        summary_b = compute_strategy_summary(strategy_b_id, date_from, date_to, include_backend)
        summary_b["name"] = strategies_by_id.get(strategy_b_id, {}).get("name", "Strategy B")

    curve_a = curve_b = None
    if date_from and date_to:
        bucket_keys = report_metrics.bucket_range(date_from, date_to, timeframe)
        items_a = [{"date": r["date"], "yield": r["yield"]} for r in summary_a["rows"]]
        series_a = report_metrics.bucketed_series(items_a, "date", "yield", bucket_keys, timeframe)
        curve_a = report_metrics.cumulative(series_a)
        if summary_b:
            items_b = [{"date": r["date"], "yield": r["yield"]} for r in summary_b["rows"]]
            series_b = report_metrics.bucketed_series(items_b, "date", "yield", bucket_keys, timeframe)
            curve_b = report_metrics.cumulative(series_b)
    else:
        bucket_keys = []

    investment = report_metrics.investment_simulation(investment_amount, summary_a["blended_yield"])

    return {
        "summary_a": summary_a,
        "summary_b": summary_b,
        "bucket_keys": bucket_keys,
        "curve_a": curve_a,
        "curve_b": curve_b,
        "investment": investment,
        "investment_amount": investment_amount,
        "timeframe": timeframe,
        "date_from": date_from,
        "date_to": date_to,
    }


def _fmt_pct(value) -> str:
    return f"{value:+.2f}%" if value is not None else "—"


def _fmt_price(value) -> str:
    return f"{value:,.2f}" if value is not None else "—"


def _fmt_ratio(value) -> str:
    return f"{value:.2f}" if value is not None else "—"


def build_report_pages(data: dict) -> list:
    """Builds the report's physical pages (see services.report_engine.
    templates' docstring for why pagination is decided here, in Python, not
    left to the browser). Page 1: header/KPIs/target-achievement donut/
    comparative curve. Page 2: directional stock table, efficiency ratios,
    investment simulation — split further if the trade table is long."""
    summary_a, summary_b = data["summary_a"], data["summary_b"]
    comparing = summary_b is not None

    kpis = (
        templates.kpi_card(
            f'Blended Yield — {summary_a["name"]}', _fmt_pct(summary_a["blended_yield"]),
            kind="positive" if (summary_a["blended_yield"] or 0) >= 0 else "negative",
        )
        + templates.kpi_card("Closed Trades", str(summary_a["closed_trades"]))
        + templates.kpi_card("Win Rate", f'{summary_a["win_rate"]:.0f}%' if summary_a["win_rate"] is not None else "—")
    )
    if comparing:
        kpis += templates.kpi_card(
            f'Blended Yield — {summary_b["name"]}', _fmt_pct(summary_b["blended_yield"]),
            kind="positive" if (summary_b["blended_yield"] or 0) >= 0 else "negative",
        )

    def _donut_for(summary):
        counts = summary["resolution_counts"]
        segments = [
            {"label": "Target Hit", "value": counts.get("all_targets_achieved", 0), "color": "#16a34a"},
            {"label": "Stop Loss", "value": counts.get("stopped_out", 0), "color": "#dc2626"},
            {"label": "Closed", "value": counts.get("intraday_closed", 0), "color": "#D97706"},
        ]
        headline = f'{summary["win_rate"]:.0f}%' if summary["win_rate"] is not None else "—"
        return charts.donut_chart(segments, center_label=headline, center_sublabel="Win Rate"), segments

    donut_a_svg, donut_a_segments = _donut_for(summary_a)
    achievement_html = f'<div class="chart-row"><div>{donut_a_svg}</div>{charts.donut_legend(donut_a_segments)}</div>'
    if comparing:
        donut_b_svg, donut_b_segments = _donut_for(summary_b)
        achievement_html += (
            f'<div class="chart-row"><div>{donut_b_svg}</div>{charts.donut_legend(donut_b_segments)}</div>'
        )

    curve_html = '<p style="color:#64748b;font-size:11px;">Select a date range to see the performance curve.</p>'
    if data.get("bucket_keys"):
        series = [{"label": summary_a["name"], "points": data["curve_a"], "color": "#2979FF"}]
        if comparing:
            series.append({"label": summary_b["name"], "points": data["curve_b"], "color": "#D97706", "dashed": True})
        curve_html = charts.line_chart(series, x_labels=data["bucket_keys"], y_label="Cumulative Yield %", zero_line=True)

    page1 = (
        templates.report_header(
            "LMV Based Strategy EOD Report",
            f'{summary_a["name"]}' + (f' vs {summary_b["name"]}' if comparing else ""),
            datetime.now(),
        )
        + f'<div class="kpi-row">{kpis}</div>'
        + templates.section("Target Achievement", achievement_html)
        + templates.section("Comparative Performance Curve" if comparing else "Performance Curve", curve_html)
    )

    def _table_rows(summary):
        return [
            [
                summary["name"], r["symbol"], r["direction"], _fmt_price(r["entry"]),
                _fmt_price(r["exit"]), _fmt_pct(r["yield"]), r["days_true"],
                templates.status_pill(r["status_label"], r["status_kind"]),
            ]
            for r in summary["rows"]
        ]

    all_rows = _table_rows(summary_a) + (_table_rows(summary_b) if comparing else [])
    table_html = templates.data_table(
        ["Strategy", "Ticker", "Direction", "Entry", "Exit", "Yield", "Days True", "Status"],
        all_rows, column_html={"Status"},
    ) if all_rows else '<p style="color:#64748b;font-size:11px;">No closed trades in the selected period.</p>'

    ratio_cards = (
        templates.kpi_card("Sharpe Ratio", _fmt_ratio(summary_a["sharpe"]))
        + templates.kpi_card("Sortino Ratio", _fmt_ratio(summary_a["sortino"]))
        + templates.kpi_card("Calmar Ratio", _fmt_ratio(summary_a["calmar"]))
    )

    inv = data["investment"]
    inv_html = (
        f'<div class="kpi-row">'
        + templates.kpi_card("Starting Investment", f'₹{inv["starting"]:,.0f}')
        + templates.kpi_card(
            "Ending Value", f'₹{inv["ending"]:,.0f}' if inv["ending"] is not None else "—",
            kind="positive" if (inv["profit"] or 0) >= 0 else "negative",
        )
        + templates.kpi_card(
            "Profit / Loss", f'₹{inv["profit"]:,.0f}' if inv["profit"] is not None else "—",
            kind="positive" if (inv["profit"] or 0) >= 0 else "negative",
        )
        + '</div><p style="color:#64748b;font-size:10px;">Hypothetical simulation only — not an actual brokerage/P&amp;L statement.</p>'
    )

    page2 = (
        templates.section("Directional Stock Performance", table_html)
        + templates.section("Efficiency Ratios", f'<div class="kpi-row">{ratio_cards}</div>')
        + templates.section(f'₹{data["investment_amount"]:,.0f} Investment Simulation', inv_html)
    )

    return [page1, page2]


def build_report_html(data: dict, doc_title: str = "LMV EOD Report") -> str:
    return templates.render_report(build_report_pages(data), doc_title=doc_title)
