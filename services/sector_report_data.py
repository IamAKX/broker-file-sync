"""
Sector Report (EOD and Live) — issue #66, resources spec "Fuku Sector-Based
EOD & Live Reports": stock-level % changes aggregated per sector, ranked
(strong = top two, weak = bottom two, independently for Daily/Weekly/
Monthly), shown as heatmaps, a grouped bar chart and an audit table, with an
optional user-defined metric and a single-sector stock drill-down.

Calculation rules (spec §3, §14):
- A sector's value is the SUM of its stocks' % changes — never an average.
- A stock with no value for a metric is NOT counted as zero: it is skipped
  and reported ("n stocks, m missing") so a sector total can be audited.
- Heatmaps, rankings, the bar graph and the audit table all read the same
  aggregated dataset (built once in build_sector_report_data), never a
  second calculation.

Data: EOD = the Inception universe snapshot for the (latest synced day on or
before the) chosen date; Live = the rows of the open Live Master View
(AppController.get_lmv_snapshot) — one snapshot per generation, so every
component of one report is consistent with the others.
"""

import math
import re
from datetime import date, datetime, timedelta

from services import emv_report_data, inception_sector
from services.report_engine import charts, templates

TIMEFRAMES = ["Daily", "Weekly", "Monthly"]
_TF_FIELD = {"Daily": "DAY % CHANGE", "Weekly": "WEEK % CHANGE", "Monthly": "MONTH % CHANGE"}
_TF_COLOR = {"Daily": "#2979FF", "Weekly": "#D97706", "Monthly": "#8250df"}
UNCLASSIFIED = "Unclassified"

METRIC_NONE = "none"
METRIC_PAIR = "pair"
METRIC_STRATEGY = "strategy"


def _num(value):
    """float, or None for blank/non-numeric (never 0 — see module docstring)."""
    if value is None or isinstance(value, bool):
        return None
    try:
        out = float(str(value).replace(",", "").replace("%", "").strip())
    except ValueError:
        return None
    return None if math.isnan(out) else out


def _norm(name) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).upper())


# ── Custom metric ────────────────────────────────────────────────────────

def metric_label(metric: dict | None) -> str:
    if not metric or metric.get("kind") in (None, METRIC_NONE):
        return ""
    if metric["kind"] == METRIC_PAIR:
        return f'{metric.get("from", "")} vs {metric.get("to", "")} % Change'
    return f'{metric.get("strategy_name") or "Strategy"}: {metric.get("column", "")}'


# Names the EMV field list and the Live Master View use for the same thing.
_FIELD_ALIASES = {
    "current": ("ltp", "last price", "close"),
    "ltp": ("current", "close"),
    "last price": ("current", "close"),
    "close": ("current", "ltp"),
}


def _field_value(values: dict, name):
    """*name*'s value from a stock's column dict: exact match, then
    case-insensitive ("P.HIGH" from the field list vs LMV's "P.High" — #81:
    the pair silently resolved to nothing and the live report came out
    blank), then the Current/LTP/Close aliases."""
    if name is None:
        return None
    if name in values:
        return values[name]
    lowered = {str(k).lower(): k for k in values}
    key = str(name).strip().lower()
    if key in lowered:
        return values[lowered[key]]
    for alias in _FIELD_ALIASES.get(key, ()):
        if alias in lowered:
            return values[lowered[alias]]
    return None


def _pair_value(values: dict, metric: dict):
    """% change going from field *from* to field *to*: (to - from) / from * 100
    — e.g. "MT vs Close" with MT 2100 and Close 2092 = -0.38% (the spec's
    own example)."""
    a, b = _num(_field_value(values, metric.get("from"))), _num(_field_value(values, metric.get("to")))
    if a is None or b is None or a == 0:
        return None
    return (b - a) / a * 100


def _strategy_values(strategies: list, metric: dict, headers: list, data: list, symbol_col: str) -> dict:
    """{normalized symbol: value of the strategy's *column*} for EVERY row —
    the strategy's row filter is ignored (a sector report needs the metric
    for the whole universe, not only the stocks that pass)."""
    from services.strategy_engine import apply_strategies

    strategy = next((s for s in strategies if s.get("id") == metric.get("strategy_id")), None)
    if strategy is None or symbol_col not in headers:
        return {}
    new_headers, new_data = apply_strategies(
        [dict(strategy, active=True, row_filter=[])], headers, data, day_history={},
        include_streak_columns=False, symbol_col=symbol_col,
    )
    if metric.get("column") not in new_headers:
        return {}
    sym_idx, col_idx = new_headers.index(symbol_col), new_headers.index(metric["column"])
    return {_norm(row[sym_idx]): _num(row[col_idx]) for row in new_data}


# ── Stock-level rows ─────────────────────────────────────────────────────

def _sector_name(sector) -> str:
    """Stocks the sector table doesn't map arrive as "", None or "—" — all
    of them are the one "Unclassified" group."""
    name = str(sector).strip() if sector is not None else ""
    return name if name and name != "—" else UNCLASSIFIED


def _stock(symbol, sector, daily, weekly, monthly, values, custom=None) -> dict:
    return {"symbol": symbol, "sector": _sector_name(sector), "daily": daily, "weekly": weekly,
            "monthly": monthly, "custom": custom, "values": values}


def eod_stocks(as_of_date: date, metric: dict | None = None) -> dict:
    """Stock rows for the Inception universe on the latest synced trading day
    on or before *as_of_date*: {"as_of", "stocks", "source"}."""
    from services import inception_bars_store, inception_strategy_store

    as_of = inception_bars_store.latest_synced_date_on_or_before(as_of_date) or as_of_date
    headers, data = emv_report_data.universe_snapshot(as_of)
    sym_idx = headers.index("Symbol")
    sector_idx = headers.index("Sector") if "Sector" in headers else None
    strategy_values = {}
    if metric and metric.get("kind") == METRIC_STRATEGY:
        strategy_values = _strategy_values(inception_strategy_store.load_all(), metric, headers, data, "Symbol")
    stocks = []
    for row in data:
        values = dict(zip(headers, row))
        custom = None
        if metric and metric.get("kind") == METRIC_PAIR:
            custom = _pair_value(values, metric)
        elif metric and metric.get("kind") == METRIC_STRATEGY:
            custom = strategy_values.get(_norm(row[sym_idx]))
        stocks.append(_stock(
            row[sym_idx], row[sector_idx] if sector_idx is not None else None,
            _num(values.get(_TF_FIELD["Daily"])), _num(values.get(_TF_FIELD["Weekly"])),
            _num(values.get(_TF_FIELD["Monthly"])), values, custom))
    return {"as_of": as_of, "stocks": stocks, "source": f"EOD {as_of.strftime('%d-%b-%Y')}"}


def _prior_closes(symbol: str, today: date) -> tuple:
    """(previous week's close, previous month's close) from synced bars — the
    bases WEEK % CHANGE / MONTH % CHANGE are measured against."""
    from services import inception_bars_store

    raw = emv_report_data.resolve_symbol(symbol)
    bars = inception_bars_store.bars_for_symbol(raw, today - timedelta(days=70), today)
    week_start = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    pwc = next((b["close"] for b in reversed(bars) if b["trade_date"] < week_start), None)
    pmc = next((b["close"] for b in reversed(bars) if b["trade_date"] < month_start), None)
    return pwc, pmc


def live_stocks(headers: list, data: list, metric: dict | None = None, today: date | None = None) -> dict:
    """Stock rows from the open Live Master View's snapshot. Daily = the row's
    "% Change"; Weekly/Monthly = its WEEK/MONTH % CHANGE column when LMV
    computes them, else derived from the live price against the synced
    previous week/month close."""
    from services import strategy_store

    today = today or date.today()
    source_label = "Live " + datetime.now().strftime("%d-%b-%Y %H:%M")
    if not headers:   # the Live Master View isn't open/loaded yet
        return {"as_of": datetime.now(), "stocks": [], "source": source_label}
    col = {h: i for i, h in enumerate(headers)}
    symbol_col = "Scrip Name" if "Scrip Name" in col else (headers[1] if len(headers) > 1 else headers[0])
    price_col = next((c for c in ("Current", "LTP", "Last Price") if c in col), None)
    strategy_values = {}
    if metric and metric.get("kind") == METRIC_STRATEGY:
        strategy_values = _strategy_values(strategy_store.load_all(), metric, headers, data, symbol_col)

    stocks = []
    for row in data:
        values = dict(zip(headers, row))
        symbol = str(values.get(symbol_col, "")).strip()
        if not symbol:
            continue
        sector = values.get("Sector") if "Sector" in col else inception_sector.sector_for(symbol)
        daily = _num(values.get("% Change"))
        weekly, monthly = _num(values.get(_TF_FIELD["Weekly"])), _num(values.get(_TF_FIELD["Monthly"]))
        price = _num(values.get(price_col)) if price_col else None
        if (weekly is None or monthly is None) and price is not None:
            pwc, pmc = _prior_closes(symbol, today)
            if weekly is None and pwc:
                weekly = (price - pwc) / pwc * 100
            if monthly is None and pmc:
                monthly = (price - pmc) / pmc * 100
        custom = None
        if metric and metric.get("kind") == METRIC_PAIR:
            custom = _pair_value(values, metric)
        elif metric and metric.get("kind") == METRIC_STRATEGY:
            custom = strategy_values.get(_norm(symbol))
        stocks.append(_stock(symbol, sector if sector not in (None, "", "—") else None,
                             daily, weekly, monthly, values, custom))
    return {"as_of": datetime.now(), "stocks": stocks, "source": source_label}


# ── Aggregation / ranking ────────────────────────────────────────────────

def aggregate_sectors(stocks: list, key: str) -> list:
    """[{"sector","total","n","missing","stocks"}] — total is the SUM of the
    stocks' *key* values (None when a sector has no value at all); stocks
    without one are counted in "missing", never as zero. Sorted by sector."""
    out: dict = {}
    for s in stocks:
        entry = out.setdefault(s["sector"], {"sector": s["sector"], "total": None, "n": 0, "missing": 0, "stocks": []})
        entry["stocks"].append(s)
        value = s.get(key)
        if value is None:
            entry["missing"] += 1
        else:
            entry["total"] = (entry["total"] or 0.0) + value
            entry["n"] += 1
    return sorted(out.values(), key=lambda e: e["sector"])


def rank_sectors(aggregates: list, top: int = 2) -> dict:
    """{"strong": top-N by total, "weak": bottom-N by total} over the sectors
    that have a value; recomputed per call (so per timeframe and per refresh).
    "Unclassified" (stocks with no sector) is a catch-all, not a sector, so it
    is never ranked — it still appears in the heatmaps and the audit table."""
    valid = sorted((a for a in aggregates if a["total"] is not None and a["sector"] != UNCLASSIFIED),
                   key=lambda a: (-a["total"], a["sector"]))
    return {"strong": valid[:top], "weak": list(reversed(valid[-top:])) if valid else []}


def build_sector_report_data(source: dict, mode: str, metric: dict | None = None,
                             selected_sector: str | None = None, primary_timeframe: str = "Daily",
                             heat_step: float | None = None, refresh_minutes: int = 0) -> dict:
    """Aggregates *source* (eod_stocks()/live_stocks() output) once; every
    heatmap, ranking, chart and table reads these same dicts."""
    stocks = source["stocks"]
    sectors = {tf: aggregate_sectors(stocks, tf.lower()) for tf in TIMEFRAMES}
    has_custom = bool(metric and metric.get("kind") in (METRIC_PAIR, METRIC_STRATEGY))
    custom_sectors = aggregate_sectors(stocks, "custom") if has_custom else []
    return {
        "mode": mode, "source": source["source"], "as_of": source["as_of"], "stocks": stocks,
        "sectors": sectors, "rankings": {tf: rank_sectors(sectors[tf]) for tf in TIMEFRAMES},
        "metric": metric if has_custom else None, "metric_label": metric_label(metric) if has_custom else "",
        "custom_sectors": custom_sectors,
        "custom_ranking": rank_sectors(custom_sectors) if has_custom else None,
        "selected_sector": selected_sector or None,
        "primary_timeframe": primary_timeframe if primary_timeframe in TIMEFRAMES else "Daily",
        "heat_step": heat_step, "refresh_minutes": refresh_minutes,
    }


# ── Heatmap rendering ────────────────────────────────────────────────────

_HEAT_COLORS = ["#991b1b", "#dc2626", "#f87171", "#64748b", "#34d399", "#16a34a", "#15803d"]


def auto_step(values: list) -> float:
    """A "nice" colour step so the scale spans the data: the largest of
    1/2/5 x 10^n that is <= max |value| / 2 (never below 0.01) — rounded DOWN
    so the biggest value reaches the darkest colour (which starts at 2 steps)."""
    biggest = max((abs(v) for v in values if v is not None), default=0)
    if biggest <= 0:
        return 1.0
    raw = max(biggest / 2, 0.01)
    magnitude = 10 ** math.floor(math.log10(raw))
    best = magnitude
    for mult in (1, 2, 5):
        if mult * magnitude <= raw:
            best = mult * magnitude
    return best


def heat_color(value, step: float) -> str:
    """Seven-colour diverging scale (s = *step*): <= -2s, -2s..-s, -s..0,
    neutral, 0..s, s..2s, >= 2s. A value within s/10 of zero (or missing) is
    neutral."""
    if value is None or abs(value) <= step / 10:
        return _HEAT_COLORS[3]
    magnitude = min(int(abs(value) // step), 2)         # 0, 1, 2
    return _HEAT_COLORS[2 - magnitude] if value < 0 else _HEAT_COLORS[4 + magnitude]


def _fmt(value, signed: bool = True) -> str:
    if value is None:
        return "—"
    return f"{value:+.2f}%" if signed else f"{value:.2f}%"


def heat_legend(step: float) -> str:
    labels = [f"≤ -{2 * step:g}", f"-{2 * step:g} to -{step:g}", f"-{step:g} to 0", "≈ 0",
              f"0 to +{step:g}", f"+{step:g} to +{2 * step:g}", f"≥ +{2 * step:g}"]
    cells = "".join(
        f'<span style="background:{c};color:#fff;font-size:9px;font-weight:700;padding:2px 8px;">{templates.esc(l)}</span>'
        for c, l in zip(_HEAT_COLORS, labels)
    )
    return f'<div style="display:flex;gap:1px;margin:2px 0 6px 0;">{cells}</div>'


def heatmap_html(items: list, step: float | None = None, columns: int = 6) -> tuple:
    """(html, estimated_height_px) — a tile per item {"name","value","sub"}:
    the name, the % change prominently, an optional sub-line (stock count),
    coloured on the scale (*step* auto-derived when None) with its legend."""
    values = [i["value"] for i in items]
    step = step or auto_step(values)
    tiles = []
    for item in items:
        sub = f'<div style="font-size:8px;opacity:.85;">{templates.esc(item["sub"])}</div>' if item.get("sub") else ""
        tiles.append(
            f'<div title="{templates.esc(item["name"])}: {templates.esc(_fmt(item["value"]))}" '
            f'style="background:{heat_color(item["value"], step)};color:#fff;border-radius:4px;padding:6px 4px;'
            f'text-align:center;min-height:52px;display:flex;flex-direction:column;justify-content:center;'
            f'width:calc({100 / columns:.4f}% - 4px);box-sizing:border-box;">'
            f'<div style="font-size:9px;font-weight:700;line-height:1.15;overflow-wrap:anywhere;">{templates.esc(item["name"])}</div>'
            f'<div style="font-size:13px;font-weight:800;">{templates.esc(_fmt(item["value"]))}</div>{sub}</div>'
        )
    rows = math.ceil(len(items) / columns) if items else 0
    body = f'<div style="display:flex;flex-wrap:wrap;gap:4px;">{"".join(tiles)}</div>' if tiles else \
        '<p style="color:#64748b;font-size:11px;">No data.</p>'
    return heat_legend(step) + body, 24 + rows * 58 + 16


def grouped_sector_bars(sectors_by_tf: dict) -> str:
    """The Daily/Weekly/Monthly bar graph (spec §6) from the same aggregates
    as the heatmaps: sector names down the left, three bars each."""
    names = sorted({a["sector"] for tf in TIMEFRAMES for a in sectors_by_tf[tf]})
    series = []
    for tf in TIMEFRAMES:
        by_sector = {a["sector"]: a["total"] for a in sectors_by_tf[tf]}
        series.append({"label": f"{tf} %", "color": _TF_COLOR[tf], "values": [by_sector.get(n) for n in names]})
    return charts.grouped_bar_chart(names, series)


def _rank_table(rankings: dict) -> str:
    rows = []
    for tf in TIMEFRAMES:
        strong, weak = rankings[tf]["strong"], rankings[tf]["weak"]
        rows.append([
            tf,
            "<br>".join(f'{templates.esc(a["sector"])} <b style="color:#15803d">{templates.esc(_fmt(a["total"]))}</b>' for a in strong) or "—",
            "<br>".join(f'{templates.esc(a["sector"])} <b style="color:#B91C1C">{templates.esc(_fmt(a["total"]))}</b>' for a in weak) or "—",
        ])
    return templates.data_table(["Timeframe", "Strong sectors (top 2)", "Weak sectors (bottom 2)"], rows,
                                column_html={"Strong sectors (top 2)", "Weak sectors (bottom 2)"})


def _audit_table(data: dict) -> str:
    by_tf = {tf: {a["sector"]: a for a in data["sectors"][tf]} for tf in TIMEFRAMES}
    custom = {a["sector"]: a for a in data["custom_sectors"]}
    headers = ["Sector", "Stocks", "Daily %", "Weekly %", "Monthly %"] + ([data["metric_label"]] if custom else [])
    rows = []
    for sector in sorted(by_tf["Daily"]):
        total = len(by_tf["Daily"][sector]["stocks"])
        miss = {tf: by_tf[tf][sector]["missing"] for tf in TIMEFRAMES}
        row = [sector, str(total)]
        for tf in TIMEFRAMES:
            cell = _fmt(by_tf[tf][sector]["total"])
            row.append(cell + (f' ({miss[tf]} missing)' if miss[tf] else ""))
        if custom:
            c = custom.get(sector)
            row.append(_fmt(c["total"]) + (f' ({c["missing"]} missing)' if c and c["missing"] else "") if c else "—")
        rows.append(row)
    return templates.data_table(headers, rows)


def _stock_items(stocks: list, key: str) -> list:
    """Strongest first (a missing value last), ties by symbol — the same
    descending order as the sector heatmaps (#75)."""
    ordered = sorted(stocks, key=lambda s: (s.get(key) is None, -(s.get(key) or 0), s["symbol"]))
    return [{"name": s["symbol"], "value": s.get(key)} for s in ordered]


def build_sector_report_pages(data: dict) -> list:
    from services.emv_report_data import _flow_pages

    tfs = [data["primary_timeframe"]] + [t for t in TIMEFRAMES if t != data["primary_timeframe"]]
    mode_label = "Live" if data["mode"] == "live" else "EOD"
    scope = f' — {data["selected_sector"]}' if data["selected_sector"] else ""
    meta = f'Auto-refresh every {data["refresh_minutes"]} min' if data.get("refresh_minutes") else data["source"]
    n_sectors = len(data["sectors"]["Daily"])
    kpis = (
        templates.kpi_card("Sectors", str(n_sectors)) + templates.kpi_card("Stocks", str(len(data["stocks"])))
        + templates.kpi_card("Source", data["source"])
        + (templates.kpi_card("Custom metric", data["metric_label"]) if data["metric_label"] else "")
    )
    header = templates.report_header(f"Fuku {mode_label} Sector Report", f"Sector % change (sum of stocks){scope}",
                                     datetime.now(), extra_meta=meta)
    page1 = header + f'<div class="kpi-row">{kpis}</div>'
    if not data["stocks"]:
        return [page1 + templates.section("No data", '<p style="color:#64748b;font-size:11px;">No stock data available'
                                          + (" — open the Live Master View first." if data["mode"] == "live" else ".") + "</p>")]

    blocks = []
    for tf in tfs:
        items = [{"name": a["sector"], "value": a["total"], "sub": f'{a["n"]} stocks'} for a in data["sectors"][tf]]
        items.sort(key=lambda i: (i["value"] is None, -(i["value"] or 0)))
        html_, h = heatmap_html(items, data["heat_step"])
        blocks.append((templates.section(f"Sector Heatmap — {tf} % Change", html_,
                                         subtitle="Sector value = sum of its stocks' % change"), h + 40))
    blocks.append((templates.section("Strongest & Weakest Sectors", _rank_table(data["rankings"])), 40 + 30 + 3 * 50))
    bars = grouped_sector_bars(data["sectors"])
    blocks.append((templates.section("Sector Performance — Daily / Weekly / Monthly", bars), emv_report_data._section_height(bars)))

    if data["custom_sectors"]:
        items = [{"name": a["sector"], "value": a["total"], "sub": f'{a["n"]} stocks'} for a in data["custom_sectors"]]
        items.sort(key=lambda i: (i["value"] is None, -(i["value"] or 0)))
        html_, h = heatmap_html(items, data["heat_step"])
        rk = data["custom_ranking"]
        note = ('<p class="fk-note">Strong: ' + ", ".join(f'{templates.esc(a["sector"])} {_fmt(a["total"])}' for a in rk["strong"])
                + " · Weak: " + ", ".join(f'{templates.esc(a["sector"])} {_fmt(a["total"])}' for a in rk["weak"]) + "</p>")
        blocks.append((templates.section(f'Custom Metric Heatmap — {data["metric_label"]}', html_ + note), h + 70))

    if data["selected_sector"]:
        sector_stocks = next((a["stocks"] for a in data["sectors"]["Daily"] if a["sector"] == data["selected_sector"]), [])
        if not sector_stocks:
            blocks.append((templates.section(f'{data["selected_sector"]} — stocks',
                           '<p style="color:#64748b;font-size:11px;">No stocks found for this sector.</p>'), 70))
        for tf in tfs:
            html_, h = heatmap_html(_stock_items(sector_stocks, tf.lower()), None, columns=8)
            blocks.append((templates.section(f'{data["selected_sector"]} — Stock Heatmap ({tf} % Change)', html_), h + 40))
        if data["metric_label"] and sector_stocks:
            html_, h = heatmap_html(_stock_items(sector_stocks, "custom"), None, columns=8)
            blocks.append((templates.section(
                f'{data["selected_sector"]} — Stock Heatmap ({data["metric_label"]})', html_), h + 40))

    audit = _audit_table(data)
    blocks.append((templates.section("Sector Values Used (audit)", audit,
                                     subtitle="Stocks with no value are left out of a sector's total, not counted as zero"),
                   40 + 30 + 26 * n_sectors))
    return _flow_pages(page1, 74 + 78, blocks, "", [], [], set())


def build_sector_report_html(data: dict, doc_title: str = "Sector Report") -> str:
    return templates.render_report(build_sector_report_pages(data), doc_title=doc_title)
