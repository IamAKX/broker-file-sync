"""
Data layer for the EMV EOD Report (resources/report/EMV_EOD_Report_
Requirements...) — two subtypes:

  Stock-based: historical trend/condition analysis for one stock + one
  field/level (e.g. "DIVISLAB Day Top for 20 days" — services.
  inception_historical_field_series is the primitive this needed that
  didn't exist anywhere before).

  Strategy-based: which stocks currently qualify for a trend-category
  strategy. Reuses services.inception_strategy_store's EXISTING category +
  row_filter mechanism (a saved formula condition) rather than building a
  second, structured AND/OR rule-builder UI alongside the one Strategy
  Builder already has — a "category" is just a named, saved condition.
  Sector distribution of qualifying stocks stands in for the spec's
  broader "sector-based" report requirement (a real, useful breakdown of
  the same classification, not a separate wizard flow) rather than
  building fully independent sector-aggregation UI tonight.

Fuku Score here uses a single-rule config wrapping the strategy's own
row_filter (services.fuku_score) — every returned stock already passed
that filter (apply_strategies drops non-matching rows), so every score is
currently 100/100. This is a deliberately honest placeholder: a real
per-sub-condition scoring breakdown needs the strategy's row_filter
decomposed into individually-weighted rules, which is exactly the
Fuku Live report's "trigger explanation" capability (services.
strategy_engine's condition-explain mode) — worth wiring in as a
follow-on once that exists, not duplicated here.
"""

from datetime import date, datetime

from services import fuku_score, inception_sector, report_columns
from services import inception_historical_field_series as hfs
from services.inception_formula_builder_columns import compute_for_bars
from services.report_engine import charts, templates
from services.strategy_engine import apply_strategies

_CANONICAL_SUFFIX = "_I"


def _display_symbol(symbol: str) -> str:
    return symbol[: -len(_CANONICAL_SUFFIX)] if symbol.endswith(_CANONICAL_SUFFIX) else symbol


def resolve_symbol(user_input: str) -> str:
    """Turns whatever a user typed into the wizard's Stock field (either
    the display symbol, e.g. "DIVISLAB", or the raw roll-series symbol
    stored in inception_bars_store, e.g. "DIVISLAB_I") into the stored
    symbol services.inception_bars_store.bars_for_symbol actually needs —
    tries the exact typed value first (covers a symbol that was never
    suffixed to begin with), falling back to appending _CANONICAL_SUFFIX
    only if that finds nothing."""
    from services import inception_bars_store

    raw = user_input.strip().upper()
    known = set(inception_bars_store.available_symbols())
    if raw in known:
        return raw
    suffixed = raw if raw.endswith(_CANONICAL_SUFFIX) else raw + _CANONICAL_SUFFIX
    return suffixed


def _fmt(value, decimals=2) -> str:
    return f"{value:,.{decimals}f}" if value is not None else "—"


# ── Stock-based report ───────────────────────────────────────────────────

def indicator_sections_for(symbol: str, series: list, instance_ids: list | None) -> list:
    """[(title, svg)] for the saved Indicator Library entries whose ids are
    in *instance_ids*, over the dates in *series* (see services.
    indicator_charts)."""
    if not instance_ids:
        return []
    from services import indicator_charts, indicator_library, inception_bars_store
    chosen = [i for i in indicator_library.load_instances() if i.get("id") in set(instance_ids)]
    bars = inception_bars_store.bars_for_symbol(symbol)
    return indicator_charts.build_indicator_sections(bars, [e["date"] for e in series], chosen)


def build_stock_report_data(symbol: str, field: str, date_from: date, date_to: date,
                             indicator_ids: list | None = None) -> dict:
    series = hfs.historical_field_series(symbol, field, date_from, date_to)
    stats = hfs.condition_stats(series)
    current_value = next((e["value"] for e in reversed(series) if e["value"] is not None), None)
    current_close = series[-1]["close"] if series else None
    return {
        "symbol": symbol, "field": field, "date_from": date_from, "date_to": date_to,
        "sector": inception_sector.sector_for(symbol),
        "series": series, "stats": stats,
        "current_value": current_value, "current_close": current_close,
        "indicator_ids": indicator_ids or [],
        "indicator_sections": indicator_sections_for(symbol, series, indicator_ids),
    }


# ── Flow pagination ─────────────────────────────────────────────────────
# Each .report-page is a fixed A4 block; content past it would be reflowed by
# the browser onto footer-less overflow pages. So content is packed into pages
# here using height estimates (px at 96dpi, matching templates.py's CSS).
_PAGE_BUDGET_PX = 1000      # 297mm - 2*12mm padding, minus footer clearance
_PAGE1_USED_PX = 74 + 78 + 250 + 24   # header + KPI row + first chart section + its legend row (measured)
_SECTION_OVERHEAD_PX = 22 + 16   # <h2> + bottom margin
_STRATEGY_PAGE1_USED_PX = 74 + 78 + 240   # header + KPI row + donut section
_TABLE_HEAD_PX = 30
_TABLE_ROW_PX = 26


def _section_height(svg_html: str) -> int:
    import re
    m = re.search(r'<svg[^>]*\sheight="(\d+(?:\.\d+)?)"', svg_html)
    return int(float(m.group(1))) + _SECTION_OVERHEAD_PX if m else 120


def _flow_pages(first_page: str, used_px: int, blocks: list, table_title: str,
                headers: list, rows: list, column_html: set, table_empty: bool = False) -> list:
    """Greedy-pack *blocks* ((html, height_px)) then the table's rows (split
    across pages with a "(continued)" title) after *first_page*."""
    pages, cur, used = [], first_page, used_px

    def _new_page():
        nonlocal cur, used
        pages.append(cur)
        cur, used = "", 0

    for html_, h in blocks:
        if used + h > _PAGE_BUDGET_PX and used > 0:
            _new_page()
        cur += html_
        used += h

    if table_empty:
        cur += templates.section(table_title,
            '<p style="color:#64748b;font-size:11px;">No historical data for this symbol/period.</p>')
        pages.append(cur)
        return pages

    i, first_chunk = 0, True
    while i < len(rows):
        room = _PAGE_BUDGET_PX - used - _SECTION_OVERHEAD_PX - _TABLE_HEAD_PX
        if room < 3 * _TABLE_ROW_PX:
            _new_page()
            continue
        n = room // _TABLE_ROW_PX
        chunk = rows[i:i + n]
        title = table_title if first_chunk else f"{table_title} (continued)"
        cur += templates.section(title, templates.data_table(headers, chunk, column_html=column_html))
        used += _SECTION_OVERHEAD_PX + _TABLE_HEAD_PX + len(chunk) * _TABLE_ROW_PX
        i += n
        first_chunk = False
        if i < len(rows):
            _new_page()
    pages.append(cur)
    return pages


def _level_change_basis(field: str, series: list) -> str:
    """Spells out where Level Change comes from: the field's value on the
    first period of the report vs its latest value, as a % of the first."""
    values = [e["value"] for e in series if e["value"] is not None]
    if len(values) < 2:
        return ""
    return f'{field}: {_fmt(values[0])} → {_fmt(values[-1])}'


def build_stock_report_pages(data: dict) -> list:
    series, stats = data["series"], data["stats"]

    kpis = (
        templates.kpi_card(f'Current {data["field"]}', _fmt(data["current_value"]))
        + templates.kpi_card("Current Close", _fmt(data["current_close"]))
        + templates.kpi_card("Current State", (stats["current_state"] or "—").title())
        + templates.kpi_card(
            "Current Streak", f'{stats["current_streak"]} periods' if stats["current_streak"] else "—"
        )
        + templates.kpi_card(
            "Level Change", f'{stats["level_change_pct"]:+.2f}%' if stats["level_change_pct"] is not None else "—",
            sublabel=_level_change_basis(data["field"], series),
            kind="positive" if (stats["level_change_pct"] or 0) >= 0 else "negative",
        )
    )

    if series:
        line = charts.line_chart(
            [
                {"label": data["field"], "points": [e["value"] for e in series], "color": "#2979FF"},
                {"label": "Close", "points": [e["close"] for e in series], "color": "#16a34a", "dashed": True},
            ],
            x_labels=[e["date"].strftime("%d-%b") for e in series], y_label="Value",
        )
        bar = charts.bar_chart(
            [e["date"].strftime("%d-%b") for e in series], [e["value"] for e in series], color="#2979FF",
            # A PDF page can't scroll: let long series squeeze to the page width
            # (thin bars) instead of the chart running off the right edge.
            min_bar_width=1,
        )
    else:
        line = bar = '<p style="color:#64748b;font-size:11px;">No historical data for this symbol/period.</p>'

    page1 = (
        templates.report_header(
            "EMV EOD Report",
            f'{data["symbol"]} ({data.get("sector") or "—"}) — {data["field"]} — {len(series)} periods',
            datetime.now(),
        )
        + f'<div class="kpi-row">{kpis}</div>'
        + templates.section(f'{data["field"]} vs Close', line)
    )

    def _state_pill(entry):
        if entry["value"] is None or entry["close"] is None:
            return "—"
        above = entry["close"] >= entry["value"]
        return templates.status_pill("ABOVE" if above else "BELOW", "positive" if above else "negative")

    rows = [
        [e["date"].strftime("%d-%b-%Y"), _fmt(e["value"]), _fmt(e["close"]), _state_pill(e)]
        for e in reversed(series)
    ]
    blocks = [
        (templates.section(title, svg), _section_height(svg))
        for title, svg in data.get("indicator_sections", [])
    ]
    bar_caption = (
        f'<p style="font-size:10px;color:#64748b;margin:2px 0 0 0;">'
        f'<span style="display:inline-block;width:10px;height:10px;background:#2979FF;border-radius:2px;'
        f'vertical-align:middle;margin-right:4px;"></span>{templates.esc(data["field"])} value per period</p>'
    ) if series else ""
    blocks.append((templates.section(f'Historical {data["field"]} — {len(series)} periods', bar + bar_caption),
                   _section_height(bar) + (22 if bar_caption else 0)))
    return _flow_pages(page1, _PAGE1_USED_PX, blocks, "Historical Values",
                       ["Date", data["field"], "Close", "State"], rows, {"State"}, table_empty=not rows)


def build_stock_report_html(data: dict, doc_title: str = "EMV EOD Report") -> str:
    return templates.render_report(build_stock_report_pages(data), doc_title=doc_title)


# ── Strategy-based (trend-category) report ──────────────────────────────

def universe_snapshot(as_of_date: date) -> tuple:
    """(headers, rows) for every locally-synced instrument with a bar on
    *as_of_date* — DISPLAY symbol (not the raw "_I" roll-series name), raw
    OHLCV + Group A/B values (services.inception_compute_service.snapshot),
    Formula Builder codes (DT/WT/MT/Camarilla, merged in per symbol same as
    screens.inception_view_by_date does), and a Sector column. Does NOT
    build the elaborate VALUE_DAYS_AGO/_DAYS-family day_history those
    screens also construct (see this module's own docstring) — a strategy
    row_filter referencing those functions reads blank here, same "blank
    rather than crash" convention used everywhere else.
    """
    from services import inception_bars_store, inception_compute_service

    snap_rows = inception_compute_service.snapshot(as_of_date)
    for row in snap_rows:
        bars = inception_bars_store.bars_for_symbol(row["symbol"], date_to=as_of_date)
        row["values"].update(compute_for_bars(row["symbol"], bars))

    metric_keys = sorted({k for r in snap_rows for k in r.get("values", {})})
    headers = ["Symbol"] + metric_keys
    data = [
        [_display_symbol(r["symbol"])] + [r.get("values", {}).get(k) for k in metric_keys]
        for r in snap_rows
    ]
    return inception_sector.inject_sector_rows(headers, data)


def classify_strategy(strategy_id: str, as_of_date: date) -> dict:
    """Qualifying stocks (rows passing the strategy's row_filter — see
    services.strategy_engine.apply_strategies, which drops the rest) plus
    each stock's Fuku Score (see this module's own docstring for why every
    score is currently 100/100)."""
    from services import inception_bars_store, inception_formula_variable_store, inception_strategy_store

    # A weekend/holiday (or a day not synced yet) has no bars of its own —
    # use the latest synced trading day on or before it rather than an empty
    # universe; the report header shows the date actually used.
    as_of_date = inception_bars_store.latest_synced_date_on_or_before(as_of_date) or as_of_date

    strategy = next(
        (s for s in inception_strategy_store.load_all() if s.get("id") == strategy_id), None
    )
    if strategy is None:
        return {"strategy": {"name": "Unknown Strategy", "id": strategy_id},
                "as_of_date": as_of_date, "headers": [], "rows": []}

    headers, data = universe_snapshot(as_of_date)
    universe_sector_idx = headers.index("Sector") if "Sector" in headers else None
    sector_totals: dict = {}
    if universe_sector_idx is not None:
        for universe_row in data:
            name = universe_row[universe_sector_idx]
            sector_totals[name] = sector_totals.get(name, 0) + 1
    new_headers, new_data = apply_strategies(
        [strategy], headers, data, day_history={}, include_streak_columns=False,
        symbol_col="Symbol", variable_store=inception_formula_variable_store,
    )

    score_config = fuku_score.new_config(f'{strategy.get("name", "")} Score', max_score=100)
    score_config["rules"] = [
        fuku_score.new_rule(strategy.get("name", "Rule"), strategy.get("row_filter", []), points=100),
    ]
    score_config = fuku_score.config_for_strategy(strategy_id) or score_config

    symbol_idx = new_headers.index("Symbol")
    sector_idx = new_headers.index("Sector") if "Sector" in new_headers else None
    rows = []
    for row in new_data:
        row_dict = dict(zip(new_headers, row))
        score_result = fuku_score.compute_score(score_config, row_dict, [row_dict])
        rows.append({
            "symbol": row[symbol_idx],
            "sector": row[sector_idx] if sector_idx is not None else "—",
            "values": row_dict,
            "score": score_result,
        })

    return {"strategy": strategy, "as_of_date": as_of_date, "headers": new_headers, "rows": rows,
            "sector_totals": sector_totals}


_SECTOR_PALETTE = ["#2979FF", "#16a34a", "#D97706", "#dc2626", "#8250df", "#0891b2", "#bf3989", "#65a30d",
                   "#7c2d12", "#475569", "#ca8a04", "#0f766e", "#be123c", "#4f46e5", "#a16207", "#334155"]


BUBBLE_METRICS = ["% CHG PDC AND OPEN", "WEEK % CHANGE", "MONTH % CHANGE", "DAY % CHANGE"]
BUBBLE_DEFAULT_X, BUBBLE_DEFAULT_Y = "WEEK % CHANGE", "% CHG PDC AND OPEN"


def sector_breakdown(classification: dict) -> list:
    """[{"sector","matched","total","pct"}] — how many stocks of each sector
    matched the strategy and what share of that sector's stocks that is
    (total = every synced stock in the sector), most-matched first."""
    totals = classification.get("sector_totals") or {}
    counts: dict = {}
    for r in classification["rows"]:
        counts[r["sector"]] = counts.get(r["sector"], 0) + 1
    out = []
    for sector, matched in counts.items():
        total = totals.get(sector) or 0
        out.append({"sector": sector, "matched": matched, "total": total,
                    "pct": (matched / total * 100) if total else None})
    out.sort(key=lambda d: (-d["matched"], d["sector"]))
    return out


def _bubble_value(row: dict, metric: str):
    try:
        return float(row["values"].get(metric))
    except (TypeError, ValueError):
        return None


def strategy_bubble_svg(classification: dict, x_metric: str, y_metric: str, colors: dict) -> str:
    """Bubble map of the qualifying stocks: x/y = the two chosen % change
    metrics, bubble size = Fuku score, colour = sector."""
    points = []
    for r in classification["rows"]:
        x, y = _bubble_value(r, x_metric), _bubble_value(r, y_metric)
        if x is None or y is None:
            continue
        points.append({"label": r["symbol"], "x": x, "y": y,
                       "size": (r.get("score") or {}).get("score") or 1, "color": colors.get(r["sector"], "#64748b")})
    return charts.bubble_chart(points, x_label=x_metric, y_label=y_metric, y_is_percent=False)


def build_strategy_report_pages(classification: dict, columns: list | None = None,
                                bubble_x: str | None = None, bubble_y: str | None = None) -> list:
    strategy, rows = classification["strategy"], classification["rows"]

    breakdown = sector_breakdown(classification)
    segments = [
        {"label": d["sector"], "value": d["matched"], "color": _SECTOR_PALETTE[i % len(_SECTOR_PALETTE)]}
        for i, d in enumerate(breakdown)
    ]
    sector_colors = {s["label"]: s["color"] for s in segments}
    donut = charts.donut_chart(segments, center_label=str(len(rows)), center_sublabel="Qualifying")
    legend = charts.donut_legend(segments)

    kpis = (
        templates.kpi_card("Qualifying Stocks", str(len(rows)))
        + templates.kpi_card("As Of", classification["as_of_date"].strftime("%d-%b-%Y"))
        + templates.kpi_card("Category", strategy.get("category", "—"))
    )

    sector_table = templates.data_table(
        ["Sector", "Matched", "In sector", "% matched"],
        [[d["sector"], str(d["matched"]), str(d["total"]) if d["total"] else "—",
          f'{d["pct"]:.0f}%' if d["pct"] is not None else "—"] for d in breakdown],
    ) if breakdown else ""

    page1 = (
        templates.report_header(
            "EMV EOD Report",
            f'{strategy.get("name", "")} — {classification["as_of_date"].strftime("%d-%b-%Y")}',
            datetime.now(),
        )
        + f'<div class="kpi-row">{kpis}</div>'
        + templates.section("Sector Distribution", f'<div class="chart-row"><div>{donut}</div>{legend}</div>')
    )

    title = f'Qualifying Stocks — {strategy.get("name", "")}'
    if not rows:
        return [page1 + templates.section(
            title, '<p style="color:#64748b;font-size:11px;">No stocks currently qualify for this strategy.</p>')]

    x_metric, y_metric = bubble_x or BUBBLE_DEFAULT_X, bubble_y or BUBBLE_DEFAULT_Y
    bubble = strategy_bubble_svg(classification, x_metric, y_metric, sector_colors)
    blocks = [
        (templates.section("Stocks Matched by Sector", sector_table),
         _SECTION_OVERHEAD_PX + _TABLE_HEAD_PX + len(breakdown) * _TABLE_ROW_PX),
        (templates.section(f"Stock Map — {x_metric} vs {y_metric}", bubble + (
            '<p style="font-size:9px;color:#64748b;margin:2px 0 0 0;">Bubble size = Fuku score; colour = sector.</p>')),
         _section_height(bubble) + 16),
    ]

    available = report_columns.emv_catalog(list(classification.get("headers", [])))
    cols = report_columns.resolve_columns(columns, available, report_columns.EMV_DEFAULT_COLUMNS)
    # Stocks grouped by sector, the sector with the most matches first.
    order = {d["sector"]: i for i, d in enumerate(breakdown)}
    ordered = sorted(rows, key=lambda r: (order.get(r["sector"], len(order)), str(r["symbol"])))
    table_rows = [[report_columns.emv_cell(c, r) for c in cols] for r in ordered]
    return _flow_pages(page1, _STRATEGY_PAGE1_USED_PX, blocks, title, cols, table_rows, set())


def build_strategy_report_html(classification: dict, doc_title: str = "EMV EOD Report",
                                columns: list | None = None, bubble_x: str | None = None,
                                bubble_y: str | None = None) -> str:
    return templates.render_report(
        build_strategy_report_pages(classification, columns, bubble_x, bubble_y), doc_title=doc_title)
