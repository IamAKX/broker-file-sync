"""The Back-test report (issues #82, #83): one design shared by the LMV and EMV
strategy back-tests, so both show the same things — total / average / compounded
yield, win rate, best and worst trade, drawdown, Sharpe / Sortino / Calmar, a
cumulative-yield curve, a month-by-month table, a ₹ investment simulation and the
full trade ledger — for a whole strategy or for one stock under it.

The caller (services.lmv_report_data, services.emv_backtest_report) turns its own
simulated trades into the neutral shape below; nothing here knows how a trade was
produced. A trade is a dict:

    symbol, sector (or None), direction ("BUY"/"SELL"),
    entry_date, exit_date (date), entry, exit (prices), yield (directional %),
    outcome (short label shown in the ledger), kind ("positive"/"negative"/"neutral"
    — the outcome pill colour), extra ({column name: value} informational columns).

and the *result* is {"kind": "LMV"/"EMV", "name", "symbol" (None = whole strategy),
"date_from", "date_to", "investment_amount", "trades", "open_trades" (still open at
the end of the range, not counted), "notes" [str], "method" (html describing how the
trades were simulated), "extra_columns" [names]}.

Everything here is hypothetical: the investment simulation never claims to be a
statement of actual profit.
"""

from collections import defaultdict
from datetime import datetime

from services import emv_report_data, report_metrics
from services.report_engine import charts, templates

MIN_INVESTMENT = 5000.0
_SECTOR_PALETTE = ["#2979FF", "#16a34a", "#D97706", "#dc2626", "#8250df", "#0969da", "#bf3989", "#65a30d"]


def _pct(value) -> str:
    return f"{value:+.2f}%" if value is not None else "—"


def _num(value, digits=2) -> str:
    return f"{value:,.{digits}f}" if value is not None else "—"


def _kind(value) -> str:
    return "neutral" if value is None else ("positive" if value >= 0 else "negative")


def _date_str(value) -> str:
    return value.strftime("%d-%b-%Y") if value else "—"


def one_at_a_time(ordered: list) -> list:
    """The trades a single investor with ONE pot could actually have taken: go
    through them by entry date and take a trade only once the previous one has
    closed (a trade entering on the day the last one exited is fine). Trades
    overlap heavily in a back-test of a whole strategy, so compounding every one
    of them through a single pot is meaningless — this is the honest version."""
    taken, free_from = [], None
    for t in sorted(ordered, key=lambda t: (t["entry_date"], t["exit_date"], t["symbol"])):
        if free_from is None or t["entry_date"] >= free_from:
            taken.append(t)
            free_from = t["exit_date"]
    return taken


def compute_metrics(trades: list, investment_amount: float) -> dict:
    """Every number the report shows, from the neutral trade list."""
    ordered = sorted((t for t in trades if t.get("yield") is not None),
                     key=lambda t: (t["exit_date"], t["entry_date"], t["symbol"]))
    yields = [t["yield"] for t in ordered]
    n = len(yields)
    wins = [y for y in yields if y > 0]
    losses = [y for y in yields if y < 0]
    curve = report_metrics.cumulative(yields)

    taken = one_at_a_time(ordered)
    compounded, equity, peak, drawdown = 1.0, [1.0], 1.0, 0.0
    for t in sorted(taken, key=lambda t: t["exit_date"]):
        compounded *= 1 + t["yield"] / 100
        equity.append(compounded)
        peak = max(peak, compounded)
        drawdown = max(drawdown, (peak - compounded) / peak * 100)
    holding = [(t["exit_date"] - t["entry_date"]).days for t in ordered]

    amount = max(float(investment_amount or MIN_INVESTMENT), MIN_INVESTMENT)
    profit_per_trade = amount * sum(yields) / 100
    deployed = amount * n
    return {
        "trades": n,
        "total_yield": sum(yields) if yields else None,
        "avg_yield": report_metrics.blended_yield(yields),
        "compounded_pct": (compounded - 1) * 100 if taken else None,
        "one_at_a_time_trades": len(taken),
        "win_rate": report_metrics.win_rate(yields),
        "wins": len(wins), "losses": len(losses),
        "best": max(yields) if yields else None,
        "worst": min(yields) if yields else None,
        "profit_factor": (sum(wins) / abs(sum(losses))) if losses else None,
        "avg_days": (sum(holding) / len(holding)) if holding else None,
        "max_drawdown": drawdown if taken else None,
        "sharpe": report_metrics.sharpe_ratio(yields),
        "sortino": report_metrics.sortino_ratio(yields),
        "calmar": report_metrics.calmar_ratio(yields),
        "ordered": ordered,
        "curve": curve,
        "investment": {
            "amount": amount,
            "per_trade": {
                "deployed": deployed, "profit": profit_per_trade if n else None,
                "return_pct": (profit_per_trade / deployed * 100) if deployed else None,
                "ending": (deployed + profit_per_trade) if n else None,
            },
            "single_pot": {
                "trades": len(taken),
                "ending": amount * compounded if taken else None,
                "profit": amount * compounded - amount if taken else None,
                "return_pct": (compounded - 1) * 100 if taken else None,
            },
        },
    }


def curve_points(ordered: list, curve: list) -> tuple:
    """(x_labels, cumulative values): one point per exit day, or per ISO week
    when the range has more than ~60 exit days (keeps the chart readable)."""
    if not ordered:
        return [], []
    days = sorted({t["exit_date"] for t in ordered})
    weekly = len(days) > 60
    last_by_key: dict = {}
    for trade, value in zip(ordered, curve):
        d = trade["exit_date"]
        key = (d.isocalendar()[0], d.isocalendar()[1]) if weekly else d
        last_by_key[key] = (d, value)
    points = sorted(last_by_key.values(), key=lambda p: p[0])
    labels = [d.strftime("%d-%b") if not weekly else f"wk {d.strftime('%d-%b')}" for d, _ in points]
    return labels, [v for _, v in points]


def monthly_rows(ordered: list) -> list:
    by_month: dict = defaultdict(list)
    for t in ordered:
        by_month[t["exit_date"].strftime("%Y-%m")].append(t["yield"])
    rows = []
    for month in sorted(by_month):
        ys = by_month[month]
        rows.append({
            "month": datetime.strptime(month, "%Y-%m").strftime("%b %Y"),
            "trades": len(ys), "win_rate": sum(1 for y in ys if y > 0) / len(ys) * 100,
            "total": sum(ys), "avg": sum(ys) / len(ys),
        })
    return rows


def stock_leaders(ordered: list, limit: int = 5) -> list:
    """[(symbol, trades, total yield, win rate)] best first."""
    by_symbol: dict = defaultdict(list)
    for t in ordered:
        by_symbol[t["symbol"]].append(t["yield"])
    rows = [(s, len(ys), sum(ys), sum(1 for y in ys if y > 0) / len(ys) * 100) for s, ys in by_symbol.items()]
    rows.sort(key=lambda r: (-r[2], r[0]))
    return rows


def outcome_segments(ordered: list) -> list:
    colours = {"positive": "#16a34a", "negative": "#dc2626", "neutral": "#D97706"}
    counts: dict = {}
    for t in ordered:
        key = (t.get("outcome") or "—", t.get("kind", "neutral"))
        counts[key] = counts.get(key, 0) + 1
    return [{"label": label, "value": v, "color": colours.get(kind, "#64748b")}
            for (label, kind), v in sorted(counts.items(), key=lambda kv: -kv[1])]


def sector_segments(ordered: list) -> list:
    stocks: dict = {}
    for t in ordered:
        stocks.setdefault(t.get("sector") or "Unclassified", set()).add(t["symbol"])
    ranked = sorted(stocks.items(), key=lambda kv: -len(kv[1]))
    return [{"label": s, "value": len(syms), "color": _SECTOR_PALETTE[i % len(_SECTOR_PALETTE)]}
            for i, (s, syms) in enumerate(ranked)]


def build_pages(result: dict) -> list:
    metrics = compute_metrics(result["trades"], result.get("investment_amount") or MIN_INVESTMENT)
    ordered = metrics["ordered"]
    single = bool(result.get("symbol"))
    name = result["name"]
    scope = result["symbol"] if single else "All stocks"
    date_from, date_to = result.get("date_from"), result.get("date_to")
    period = f'{_date_str(date_from)} to {_date_str(date_to)}' if date_from and date_to else ""

    header = templates.report_header(
        f'{result.get("kind", "")} Strategy Back-test Report'.strip(),
        f'{name} — {scope}' + (f' — {period}' if period else ""),
        datetime.now(), extra_meta="SIMULATED — not recorded trades",
    )

    kpis = (
        templates.kpi_card("Trades", str(metrics["trades"]),
                           sublabel=f'{metrics["wins"]} won · {metrics["losses"]} lost')
        + templates.kpi_card("Win Rate", f'{metrics["win_rate"]:.0f}%' if metrics["win_rate"] is not None else "—")
        + templates.kpi_card("Average Yield / Trade", _pct(metrics["avg_yield"]), kind=_kind(metrics["avg_yield"]))
        + templates.kpi_card("Total Yield (sum)", _pct(metrics["total_yield"]), kind=_kind(metrics["total_yield"]))
        + templates.kpi_card("Return, one trade at a time", _pct(metrics["compounded_pct"]),
                             sublabel=f'{metrics["one_at_a_time_trades"]} non-overlapping trades, reinvested',
                             kind=_kind(metrics["compounded_pct"]))
        + templates.kpi_card("Best Trade", _pct(metrics["best"]), kind=_kind(metrics["best"]))
        + templates.kpi_card("Worst Trade", _pct(metrics["worst"]), kind=_kind(metrics["worst"]))
        + templates.kpi_card("Max Drawdown", f'{metrics["max_drawdown"]:.2f}%' if metrics["max_drawdown"] is not None else "—",
                             sublabel="one trade at a time", kind="negative" if metrics["max_drawdown"] else "neutral")
        + templates.kpi_card("Profit Factor", _num(metrics["profit_factor"]),
                             sublabel="gross wins ÷ gross losses")
        + templates.kpi_card("Avg Holding", f'{metrics["avg_days"]:.1f} days' if metrics["avg_days"] is not None else "—")
    )

    if ordered:
        labels, points = curve_points(ordered, metrics["curve"])
        curve_html = charts.line_chart(
            [{"label": f"{name} — {scope}", "points": points, "color": "#2979FF"}],
            x_labels=labels, y_label="Cumulative Yield %", zero_line=True)
    else:
        curve_html = '<p style="color:#64748b;font-size:11px;">No completed trades in this period.</p>'

    page1 = (header + f'<div class="kpi-row">{kpis}</div>'
             + templates.section("Cumulative Yield (trades in the order they closed)", curve_html))
    page1_used = 74 + 78 * 2 + 20 + 260

    blocks = []
    segments = outcome_segments(ordered)
    if segments:
        donut = charts.donut_chart(segments, center_label=str(len(ordered)), center_sublabel="Trades")
        blocks.append((templates.section(
            "How the trades ended", f'<div class="chart-row"><div>{donut}</div>{charts.donut_legend(segments)}</div>'),
            38 + 215))

    months = monthly_rows(ordered)
    if months:
        blocks.append((templates.section("Month by Month", templates.data_table(
            ["Month", "Trades", "Win Rate", "Total Yield", "Avg Yield"],
            [[m["month"], str(m["trades"]), f'{m["win_rate"]:.0f}%', _pct(m["total"]), _pct(m["avg"])] for m in months])),
            38 + 30 + 26 * len(months)))

    ratio_cards = (
        templates.kpi_card("Sharpe Ratio", _num(metrics["sharpe"]), sublabel="per trade")
        + templates.kpi_card("Sortino Ratio", _num(metrics["sortino"]), sublabel="per trade")
        + templates.kpi_card("Calmar Ratio", _num(metrics["calmar"]))
    )
    blocks.append((templates.section("Efficiency Ratios", f'<div class="kpi-row">{ratio_cards}</div>'), 38 + 78))

    inv = metrics["investment"]
    pt, sp = inv["per_trade"], inv["single_pot"]
    inv_html = (
        f'<p style="font-size:11px;font-weight:600;margin:0 0 4px 0;">₹{inv["amount"]:,.0f} in every trade</p>'
        '<div class="kpi-row">'
        + templates.kpi_card("Capital Deployed", f'₹{pt["deployed"]:,.0f}', sublabel=f'{metrics["trades"]} × ₹{inv["amount"]:,.0f}')
        + templates.kpi_card("Profit / Loss", f'₹{pt["profit"]:,.0f}' if pt["profit"] is not None else "—", kind=_kind(pt["profit"]))
        + templates.kpi_card("Return on Capital", _pct(pt["return_pct"]), kind=_kind(pt["return_pct"]))
        + '</div>'
        f'<p style="font-size:11px;font-weight:600;margin:6px 0 4px 0;">₹{inv["amount"]:,.0f} in one pot, one trade at a time '
        f'({sp["trades"]} of {metrics["trades"]} trades — a trade is taken only once the previous one has closed)</p>'
        '<div class="kpi-row">'
        + templates.kpi_card("Starting Investment", f'₹{inv["amount"]:,.0f}')
        + templates.kpi_card("Ending Value", f'₹{sp["ending"]:,.0f}' if sp["ending"] is not None else "—", kind=_kind(sp["profit"]))
        + templates.kpi_card("Return on Investment", _pct(sp["return_pct"]), kind=_kind(sp["return_pct"]))
        + '</div><p style="color:#64748b;font-size:10px;">Hypothetical simulation only — not an actual brokerage/P&amp;L '
          "statement. Trades of a strategy overlap in time, so the first view puts the same amount into each one and the "
          "second follows a single investor who holds one position at a time.</p>"
    )
    blocks.append((templates.section("Investment Simulation", inv_html), 38 + 30 + 78 * 2 + 40))

    if not single:
        sectors = sector_segments(ordered)
        if sectors:
            total = sum(s["value"] for s in sectors)
            blocks.append((templates.section("Sector Distribution", '<div class="chart-row"><div>' + charts.donut_chart(
                sectors, center_label=str(total), center_sublabel="Stocks") + f'</div>{charts.donut_legend(sectors)}</div>'),
                38 + 215))
        leaders = stock_leaders(ordered)
        if len(leaders) > 1:
            top, bottom = leaders[:5], list(reversed(leaders[-5:]))
            rows = lambda items: [[s, str(n), _pct(total), f"{wr:.0f}%"] for s, n, total, wr in items]
            blocks.append((templates.section("Best and Worst Stocks", (
                '<p style="font-size:11px;font-weight:600;margin:0 0 4px 0;">Best</p>'
                + templates.data_table(["Stock", "Trades", "Total Yield", "Win Rate"], rows(top))
                + '<p style="font-size:11px;font-weight:600;margin:8px 0 4px 0;">Worst</p>'
                + templates.data_table(["Stock", "Trades", "Total Yield", "Win Rate"], rows(bottom)))),
                38 + 2 * (30 + 26 * 5) + 40))

    method = result.get("method") or ""
    notes = "".join(f'<p class="fk-note"><b>Note:</b> {templates.esc(n)}.</p>' for n in result.get("notes") or [])
    open_note = (f'<p class="fk-note">{result["open_trades"]} trade(s) were still open at the end of the period and '
                 "are not counted.</p>") if result.get("open_trades") else ""
    blocks.append((templates.section("About this back-test", method + open_note + notes),
                   38 + 120 + 24 * len(result.get("notes") or [])))

    extra_columns = list(result.get("extra_columns") or [])
    headers = ["#", "Stock", "Direction", "Entry Date", "Entry", "Exit Date", "Exit", "Yield", "Days", "Outcome"] + extra_columns
    ledger = []
    for i, t in enumerate(ordered, start=1):
        ledger.append([
            str(i), t["symbol"], t["direction"], _date_str(t["entry_date"]), _num(t["entry"]),
            _date_str(t["exit_date"]), _num(t["exit"]), _pct(t["yield"]),
            str((t["exit_date"] - t["entry_date"]).days),
            templates.status_pill(t.get("outcome") or "—", t.get("kind", "neutral")),
        ] + [_cell(t.get("extra", {}).get(c)) for c in extra_columns])
    return emv_report_data._flow_pages(page1, page1_used, blocks, "Trade Ledger", headers, ledger, {"Outcome"},
                                       table_empty=not ledger)


def _cell(value) -> str:
    if value is None:
        return "—"
    return f"{value:,.2f}" if isinstance(value, float) else str(value)


def build_html(result: dict, doc_title: str = "Back-test Report") -> str:
    return templates.render_report(build_pages(result), doc_title=doc_title)
