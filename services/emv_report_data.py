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

from services import fuku_score, inception_sector
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

def build_stock_report_data(symbol: str, field: str, date_from: date, date_to: date) -> dict:
    series = hfs.historical_field_series(symbol, field, date_from, date_to)
    stats = hfs.condition_stats(series)
    current_value = next((e["value"] for e in reversed(series) if e["value"] is not None), None)
    current_close = series[-1]["close"] if series else None
    return {
        "symbol": symbol, "field": field, "date_from": date_from, "date_to": date_to,
        "series": series, "stats": stats,
        "current_value": current_value, "current_close": current_close,
    }


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
        )
    else:
        line = bar = '<p style="color:#64748b;font-size:11px;">No historical data for this symbol/period.</p>'

    page1 = (
        templates.report_header(
            "EMV EOD Report",
            f'{data["symbol"]} — {data["field"]} — {len(series)} periods',
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
    table = templates.data_table(["Date", data["field"], "Close", "State"], rows, column_html={"State"}) \
        if rows else '<p style="color:#64748b;font-size:11px;">No historical data for this symbol/period.</p>'

    page2 = (
        templates.section(f'Historical {data["field"]} — {len(series)} periods', bar)
        + templates.section("Historical Values", table)
    )

    return [page1, page2]


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
    from services import inception_formula_variable_store, inception_strategy_store

    strategy = next(
        (s for s in inception_strategy_store.load_all() if s.get("id") == strategy_id), None
    )
    if strategy is None:
        return {"strategy": {"name": "Unknown Strategy", "id": strategy_id},
                "as_of_date": as_of_date, "headers": [], "rows": []}

    headers, data = universe_snapshot(as_of_date)
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

    return {"strategy": strategy, "as_of_date": as_of_date, "headers": new_headers, "rows": rows}


_SECTOR_PALETTE = ["#2979FF", "#16a34a", "#D97706", "#dc2626", "#8250df", "#0969da", "#bf3989", "#65a30d"]


def build_strategy_report_pages(classification: dict) -> list:
    strategy, rows = classification["strategy"], classification["rows"]

    sector_counts: dict = {}
    for r in rows:
        sector_counts[r["sector"]] = sector_counts.get(r["sector"], 0) + 1
    ranked = sorted(sector_counts.items(), key=lambda kv: -kv[1])
    segments = [
        {"label": sector, "value": count, "color": _SECTOR_PALETTE[i % len(_SECTOR_PALETTE)]}
        for i, (sector, count) in enumerate(ranked)
    ]
    donut = charts.donut_chart(segments, center_label=str(len(rows)), center_sublabel="Qualifying")
    legend = charts.donut_legend(segments)

    kpis = (
        templates.kpi_card("Qualifying Stocks", str(len(rows)))
        + templates.kpi_card("As Of", classification["as_of_date"].strftime("%d-%b-%Y"))
        + templates.kpi_card("Category", strategy.get("category", "—"))
    )

    page1 = (
        templates.report_header(
            "EMV EOD Report",
            f'{strategy.get("name", "")} — {classification["as_of_date"].strftime("%d-%b-%Y")}',
            datetime.now(),
        )
        + f'<div class="kpi-row">{kpis}</div>'
        + templates.section("Sector Distribution", f'<div class="chart-row"><div>{donut}</div>{legend}</div>')
    )

    if rows:
        table_rows = [
            [r["symbol"], r["sector"], f'{r["score"]["score"]:.0f} / {r["score"]["max_score"]:.0f}']
            for r in rows
        ]
        table = templates.data_table(["Stock", "Sector", "Fuku Score"], table_rows)
    else:
        table = '<p style="color:#64748b;font-size:11px;">No stocks currently qualify for this strategy.</p>'

    page2 = templates.section(f'Qualifying Stocks — {strategy.get("name", "")}', table)

    return [page1, page2]


def build_strategy_report_html(classification: dict, doc_title: str = "EMV EOD Report") -> str:
    return templates.render_report(build_strategy_report_pages(classification), doc_title=doc_title)
