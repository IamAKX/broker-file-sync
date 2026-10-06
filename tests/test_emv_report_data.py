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
        "DIVISLAB_I", "CLOSE", date(2026, 1, 20), date(2026, 1, 30)
    )
    pages = emv_report_data.build_stock_report_pages(data)
    assert len(pages) == 1
    assert "DIVISLAB_I" in pages[0]


def test_build_stock_report_html_is_a_full_document():
    _seed("DIVISLAB_I", date(2026, 1, 1), 15)
    data = emv_report_data.build_stock_report_data(
        "DIVISLAB_I", "CLOSE", date(2026, 1, 5), date(2026, 1, 15)
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

    # Small result: everything now flows onto one page (no forced page break).
    assert len(pages) == 1
    assert "ABB" in pages[0]
    assert "Above 150" in pages[0]


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
