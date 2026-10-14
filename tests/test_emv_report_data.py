from datetime import date, timedelta

import pytest

from services import emv_report_data, inception_bars_store, inception_formula_builder_columns


@pytest.fixture(autouse=True)
def _isolate_bars_db(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "test_bars.db"))
    inception_formula_builder_columns.clear_cache()
    from services import inception_compute_service
    inception_compute_service.clear_cache()
    yield


def _seed(symbol: str, start: date, days: int, start_price: float = 100.0):
    rows = []
    d = start
    price = start_price
    count = 0
    while count < days:
        if d.weekday() < 5:
            rows.append({
                "symbol": symbol, "trade_date": d, "open": price, "high": price + 2,
                "low": price - 2, "close": price, "volume": 1000,
            })
            price += 1
            count += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)


# ── Stock-based report ───────────────────────────────────────────────────

def test_build_stock_report_data_has_series_and_stats():
    _seed("DIVISLAB_I", date(2026, 1, 1), 30)
    data = emv_report_data.build_stock_report_data(
        "DIVISLAB_I", "DT", date(2026, 1, 20), date(2026, 1, 30)
    )
    assert data["symbol"] == "DIVISLAB_I"
    assert len(data["series"]) > 0
    assert data["stats"]["current_state"] in ("above", "below", None)


def test_build_stock_report_pages_flows_short_series_onto_one_page():
    _seed("DIVISLAB_I", date(2026, 1, 1), 30)
    data = emv_report_data.build_stock_report_data(
        "DIVISLAB_I", "CLOSE", date(2026, 1, 23), date(2026, 1, 30)
    )
    pages = emv_report_data.build_stock_report_pages(data)
    assert len(pages) == 1
    assert "DIVISLAB_I" in pages[0]


def test_build_stock_report_html_is_a_full_document():
    _seed("DIVISLAB_I", date(2026, 1, 1), 15)
    data = emv_report_data.build_stock_report_data(
        "DIVISLAB_I", "CLOSE", date(2026, 1, 12), date(2026, 1, 16)
    )
    html = emv_report_data.build_stock_report_html(data)
    assert "<!DOCTYPE html>" in html
    assert "Page 1 of 1" in html


def test_build_stock_report_handles_unsynced_symbol_gracefully():
    data = emv_report_data.build_stock_report_data("NOPE", "CLOSE", date(2026, 1, 1), date(2026, 1, 5))
    pages = emv_report_data.build_stock_report_pages(data)
    assert "No historical data" in pages[0] or "No historical data" in pages[1]


def test_resolve_symbol_prefers_exact_match():
    _seed("DIVISLAB", date(2026, 1, 1), 5)
    assert emv_report_data.resolve_symbol("divislab") == "DIVISLAB"


def test_resolve_symbol_falls_back_to_suffixed():
    _seed("DIVISLAB_I", date(2026, 1, 1), 5)
    assert emv_report_data.resolve_symbol("DIVISLAB") == "DIVISLAB_I"


def test_resolve_symbol_unknown_still_returns_suffixed_guess():
    assert emv_report_data.resolve_symbol("NOPE") == "NOPE_I"


# ── Strategy-based report ────────────────────────────────────────────────

def _cond_close_above(threshold):
    # Inception rows key raw OHLCV uppercase ("CLOSE", not LMV's "Close") —
    # see services.inception_columns.RAW_FIELDS / inception_compute_service.
    # _compute_rows_for_days.
    return [
        {"type": "col", "value": "CLOSE"},
        {"type": "op", "value": ">"},
        {"type": "num", "value": str(threshold)},
    ]


def test_universe_snapshot_includes_sector_and_symbol_columns():
    _seed("ABB_I", date(2026, 1, 1), 10, start_price=100)
    headers, rows = emv_report_data.universe_snapshot(date(2026, 1, 12))
    assert "Symbol" in headers
    assert "Sector" in headers
    assert len(rows) == 1
    assert rows[0][headers.index("Symbol")] == "ABB"


def test_classify_strategy_filters_to_qualifying_stocks(monkeypatch):
    from services import inception_strategy_store

    _seed("ABB_I", date(2026, 1, 1), 10, start_price=200)   # ends around 209, qualifies (> 150)
    _seed("TCS_I", date(2026, 1, 1), 10, start_price=50)    # ends around 59, does not qualify

    strategy = {
        "id": "strat-1", "name": "Above 150", "active": True, "category": "Daily",
        "columns": [], "row_filter": _cond_close_above(150),
    }
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [strategy])

    result = emv_report_data.classify_strategy("strat-1", date(2026, 1, 12))

    symbols = {r["symbol"] for r in result["rows"]}
    assert symbols == {"ABB"}
    assert result["rows"][0]["score"]["score"] == 100


def test_classify_strategy_unknown_id_returns_empty(monkeypatch):
    from services import inception_strategy_store
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [])

    result = emv_report_data.classify_strategy("missing", date(2026, 1, 12))
    assert result["rows"] == []


def test_build_strategy_report_pages_renders_sector_distribution(monkeypatch):
    from services import inception_strategy_store

    _seed("ABB_I", date(2026, 1, 1), 10, start_price=200)

    strategy = {
        "id": "strat-1", "name": "Above 150", "active": True, "category": "Daily",
        "columns": [], "row_filter": _cond_close_above(150),
    }
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [strategy])

    classification = emv_report_data.classify_strategy("strat-1", date(2026, 1, 12))
    pages = emv_report_data.build_strategy_report_pages(classification)

    # Content flows (no forced page break): summary, sector table, stock map, stock table.
    joined = "".join(pages)
    assert len(pages) <= 2
    assert "ABB" in joined and "Above 150" in joined
    assert "Stocks Matched by Sector" in joined and "Stock Map" in joined


def test_build_strategy_report_html_handles_no_qualifying_stocks(monkeypatch):
    from services import inception_strategy_store

    _seed("TCS_I", date(2026, 1, 1), 10, start_price=50)

    strategy = {
        "id": "strat-1", "name": "Above 150", "active": True, "category": "Daily",
        "columns": [], "row_filter": _cond_close_above(150),
    }
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [strategy])

    classification = emv_report_data.classify_strategy("strat-1", date(2026, 1, 12))
    html = emv_report_data.build_strategy_report_html(classification)

    assert "No stocks currently qualify" in html
    assert "<!DOCTYPE html>" in html


def test_flow_pages_splits_long_table_with_continued_titles():
    rows = [[f"r{i}", "1", "2", "x"] for i in range(300)]
    pages = emv_report_data._flow_pages("<p>first</p>", 400, [], "Hist", ["A", "B", "C", "D"], rows, set())
    assert len(pages) > 2
    assert "Hist (continued)" in pages[1] and "Hist (continued)" not in pages[0]
    assert sum(p.count("<tr>") for p in pages) == 300 + len(pages)  # rows + one header row per page
    # last page is not a tiny orphan
    assert pages[-1].count("<tr>") - 1 >= 3


def test_flow_pages_moves_block_that_does_not_fit_to_next_page():
    blocks = [("<b>one</b>", 400), ("<b>two</b>", 400), ("<b>three</b>", 400)]
    pages = emv_report_data._flow_pages("", 0, blocks, "T", ["A"], [], set(), table_empty=True)
    assert len(pages) == 2 and "three" in pages[1]


# ── Sector / legend / level-change basis (issue #62) ─────────────────────

def test_stock_report_shows_sector_legend_and_level_change_basis(monkeypatch):
    from services import inception_sector
    monkeypatch.setattr(inception_sector, "sector_for", lambda symbol: "PHARMA")
    _seed("DIVISLAB_I", date(2026, 1, 1), 30)
    data = emv_report_data.build_stock_report_data(
        "DIVISLAB_I", "CLOSE", date(2026, 1, 20), date(2026, 1, 30)
    )
    html = "".join(emv_report_data.build_stock_report_pages(data))

    assert data["sector"] == "PHARMA"
    assert "DIVISLAB_I (PHARMA)" in html                      # sector in the report header
    assert ">CLOSE<" in html and ">Close<" in html            # legend names both plotted lines
    assert "CLOSE value per period" in html                   # caption under the bar chart
    values = [e["value"] for e in data["series"] if e["value"] is not None]
    assert f"CLOSE: {emv_report_data._fmt(values[0])} → {emv_report_data._fmt(values[-1])}" in html


def test_level_change_basis_is_blank_without_two_values():
    assert emv_report_data._level_change_basis("DT", []) == ""
    assert emv_report_data._level_change_basis("DT", [{"value": 1.0}]) == ""


# ── EMV strategy report: sector %, sector ordering, bubble map (issue #63) ──

def _fake_classification():
    def row(sym, sector, score=100.0, **vals):
        return {"symbol": sym, "sector": sector, "values": vals, "score": {"score": score, "max_score": 100.0}}
    return {
        "strategy": {"name": "S", "category": "Daily"}, "as_of_date": date(2026, 1, 12),
        "headers": ["Symbol", "Sector"], "sector_totals": {"FINANCE": 20, "IT": 4, "AUTO": 8},
        "rows": [
            row("AAA", "IT", **{"WEEK % CHANGE": 2.0, "% CHG PDC AND OPEN": 0.5}),
            row("BBB", "FINANCE", **{"WEEK % CHANGE": -1.0, "% CHG PDC AND OPEN": 1.5}),
            row("CCC", "FINANCE", **{"WEEK % CHANGE": 3.0, "% CHG PDC AND OPEN": -0.5}),
            row("DDD", "AUTO"),
        ],
    }


def test_sector_breakdown_gives_matched_total_and_percent_most_matched_first():
    out = emv_report_data.sector_breakdown(_fake_classification())
    assert [(d["sector"], d["matched"], d["total"]) for d in out] == [
        ("FINANCE", 2, 20), ("AUTO", 1, 8), ("IT", 1, 4)]
    assert out[0]["pct"] == 10.0 and out[2]["pct"] == 25.0


def test_strategy_report_lists_stocks_grouped_by_largest_sector_first():
    html = "".join(emv_report_data.build_strategy_report_pages(_fake_classification()))
    assert "% matched" in html and "10%" in html and "25%" in html
    body = html[html.rindex("Qualifying Stocks"):]
    assert body.index("BBB") < body.index("DDD") < body.index("AAA")      # FINANCE, AUTO, IT
    assert body.index("CCC") < body.index("DDD")


def test_strategy_bubble_uses_chosen_axes_and_skips_rows_without_values():
    colors = {"IT": "#111111", "FINANCE": "#222222"}
    svg = emv_report_data.strategy_bubble_svg(
        _fake_classification(), "WEEK % CHANGE", "% CHG PDC AND OPEN", colors)
    assert svg.count("<circle") == 3                 # DDD has no metric values -> skipped
    assert "WEEK % CHANGE" in svg and "% CHG PDC AND OPEN" in svg
    html = "".join(emv_report_data.build_strategy_report_pages(
        _fake_classification(), bubble_x="MONTH % CHANGE", bubble_y="DAY % CHANGE"))
    assert "Stock Map — MONTH % CHANGE vs DAY % CHANGE" in html


def test_classify_strategy_uses_latest_synced_day_on_or_before_a_weekend_as_of(monkeypatch):
    from services import inception_strategy_store

    _seed("ABB_I", date(2026, 1, 1), 10, start_price=200)      # trading days only (Mon-Fri)
    strategy = {"id": "s", "name": "Above 150", "active": True, "category": "Daily",
                "columns": [], "row_filter": _cond_close_above(150)}
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [strategy])

    saturday = date(2026, 1, 10)
    assert saturday.weekday() == 5
    classification = emv_report_data.classify_strategy("s", saturday)

    assert [r["symbol"] for r in classification["rows"]] == ["ABB"]      # not an empty universe
    assert classification["as_of_date"] < saturday                       # the real trading day used
