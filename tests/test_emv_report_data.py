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


# ── Multiple columns plotted against Close, configurable colours (issue #61) ──

def test_normalize_extra_fields_defaults_colours_and_drops_blanks_and_dupes():
    out = emv_report_data.normalize_extra_fields(
        ["WT", {"field": "mt", "color": "#123456"}, {"field": "WT"}, "", None, {"field": "  "}])
    assert out == [{"field": "WT", "color": emv_report_data.EXTRA_FIELD_COLORS[0]},
                   {"field": "mt", "color": "#123456"}]
    assert emv_report_data.normalize_extra_fields(None) == []


def test_stock_report_plots_primary_extras_and_close_with_their_colours():
    _seed("DIVISLAB_I", date(2026, 1, 1), 30)
    data = emv_report_data.build_stock_report_data(
        "DIVISLAB_I", "DT", date(2026, 1, 12), date(2026, 1, 30),
        extra_fields=[{"field": "WT", "color": "#aa00aa"}, "MT", "DT"],       # DT == primary -> not duplicated
        field_color="#ff8800",
    )
    assert [e["field"] for e in data["extras"]] == ["WT", "MT"]
    assert all(len(e["series"]) == len(data["series"]) for e in data["extras"])

    html = "".join(emv_report_data.build_stock_report_pages(data))
    assert "DT, WT, MT vs Close" in html
    for label in (">DT<", ">WT<", ">MT<", ">Close<"):                        # legend names every line
        assert label in html
    assert 'stroke="#ff8800"' in html and 'stroke="#aa00aa"' in html          # user-chosen colours drawn


def test_stock_report_without_extras_is_unchanged_in_title_and_data():
    _seed("DIVISLAB_I", date(2026, 1, 1), 30)
    data = emv_report_data.build_stock_report_data("DIVISLAB_I", "DT", date(2026, 1, 12), date(2026, 1, 30))
    assert data["extras"] == []
    assert "DT vs Close" in "".join(emv_report_data.build_stock_report_pages(data))


# ── Trend-category report (issue #64) ────────────────────────────────────

def _trend_setup(monkeypatch):
    """Two stocks with rising closes (ABB higher than SBIN) and three
    strategies: close>150 (ABB only), close>100 (both), close>10000 (nobody)."""
    from services import inception_strategy_store, trend_categories, config_store

    _seed("ABB_I", date(2026, 1, 1), 40, start_price=200)       # always > 150
    _seed("SBIN_I", date(2026, 1, 1), 40, start_price=100)      # 100 -> 139: only > 100 from day 2
    strategies = [
        {"id": "s150", "name": "Above 150", "active": True, "category": "Daily", "columns": [], "row_filter": _cond_close_above(150)},
        {"id": "s100", "name": "Above 100", "active": True, "category": "Weekly", "columns": [], "row_filter": _cond_close_above(100)},
        {"id": "snever", "name": "Never", "active": True, "category": "Daily", "columns": [], "row_filter": _cond_close_above(10000)},
    ]
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: strategies)
    saved = {}
    monkeypatch.setattr(config_store, "load_json", lambda key, default=None: saved.get(key, default))
    monkeypatch.setattr(config_store, "save_json", lambda key, value: saved.__setitem__(key, value))

    bull = trend_categories.new_category("Bullish", "#16a34a")
    bull["rules"]["Daily"] = ["s150", "snever"]
    bull["rules"]["Weekly"] = ["s100"]
    sideways = trend_categories.new_category("Sideways", "#64748b")
    sideways["rules"]["Daily"] = ["s100"]
    ghost = trend_categories.new_category("Ghost", "#000000")
    ghost["rules"]["Daily"] = ["deleted-strategy"]
    inactive = trend_categories.new_category("Off", "#111111")
    inactive["active"] = False
    inactive["rules"]["Daily"] = ["s100"]
    trend_categories.save_all([bull, sideways, ghost, inactive])
    return strategies


def test_trend_category_store_defaults_roundtrip_and_helpers(monkeypatch):
    from services import trend_categories, config_store
    saved = {}
    monkeypatch.setattr(config_store, "load_json", lambda key, default=None: saved.get(key, default))
    monkeypatch.setattr(config_store, "save_json", lambda key, value: saved.__setitem__(key, value))

    defaults = trend_categories.load_all()
    assert [c["name"] for c in defaults][:3] == ["Bullish", "Extremely Bullish", "Bearish"]
    assert len(defaults) == 9 and all(set(c["rules"]) == set(trend_categories.TIMEFRAMES) for c in defaults)

    custom = trend_categories.new_category("Breakout", "#abcdef", "my own")
    custom["rules"]["Monthly"] = ["a", "b"]
    trend_categories.save_all(defaults + [custom])
    reloaded = trend_categories.load_all()
    assert reloaded[-1]["name"] == "Breakout" and reloaded[-1]["order"] == 9
    assert trend_categories.strategies_for(reloaded[-1], "Monthly") == ["a", "b"]
    assert trend_categories.all_strategy_ids([reloaded[-1]], ["Daily"]) == []
    assert trend_categories.all_strategy_ids([reloaded[-1]]) == ["a", "b"]
    reloaded[0]["active"] = False
    trend_categories.save_all(reloaded)
    assert "Bullish" not in [c["name"] for c in trend_categories.active_categories()]


def test_classify_trend_unions_a_categorys_strategies_for_the_timeframe(monkeypatch):
    _trend_setup(monkeypatch)
    result = emv_report_data.classify_trend("bullish", "Daily", date(2026, 2, 20), with_days_true=False)
    assert [r["symbol"] for r in result["rows"]] == ["ABB"]              # s150 passes ABB; "never" adds nobody
    assert result["rows"][0]["categories"] == ["Bullish"]

    weekly = emv_report_data.classify_trend("bullish", "Weekly", date(2026, 2, 20), with_days_true=False)
    assert sorted(r["symbol"] for r in weekly["rows"]) == ["ABB", "SBIN"]       # s100 passes both


def test_classify_trend_all_categories_skips_inactive_and_reports_missing_strategies(monkeypatch):
    _trend_setup(monkeypatch)
    result = emv_report_data.classify_trend(None, "Daily", date(2026, 2, 20), with_days_true=False)
    cats = {r["symbol"]: r["categories"] for r in result["rows"]}
    assert cats["ABB"] == ["Bullish", "Sideways"] and cats["SBIN"] == ["Sideways"]
    assert "Off" not in {c for cs in cats.values() for c in cs}           # inactive category ignored
    assert result["missing"] == ["deleted-strategy"]                      # Ghost's strategy no longer exists


def test_classify_trend_multi_timeframe_labels_each_timeframe_independently(monkeypatch):
    _trend_setup(monkeypatch)
    result = emv_report_data.classify_trend("sideways", "Daily", date(2026, 2, 20), multi_timeframe=True, with_days_true=False)
    sbin = next(r for r in result["rows"] if r["symbol"] == "SBIN")
    assert sbin["tf_labels"]["Daily"] == ["Sideways"]
    assert sbin["tf_labels"]["Weekly"] == ["Bullish"]       # classified differently on Weekly (s100 -> Bullish)
    assert sbin["tf_labels"]["Monthly"] == [] and sbin["tf_labels"]["Quarterly"] == []


def test_trailing_days_true_counts_consecutive_days_ending_at_as_of(monkeypatch):
    strategies = _trend_setup(monkeypatch)
    s130 = {"id": "s130", "name": "Above 130", "active": True, "category": "Daily", "columns": [],
            "row_filter": _cond_close_above(130)}
    as_of = date(2026, 2, 20)
    bars = inception_bars_store.bars_for_symbol("SBIN_I", date_to=as_of)
    expected = 0
    for bar in reversed(bars):            # SBIN rises every day, so >130 holds on the trailing run only
        if bar["close"] > 130:
            expected += 1
        else:
            break
    assert 0 < expected < len(bars)
    assert emv_report_data.trailing_days_true("SBIN", s130, as_of) == expected
    assert emv_report_data.trailing_days_true("ABB", strategies[0], as_of) == emv_report_data.DAYS_TRUE_LOOKBACK   # true throughout -> capped
    assert emv_report_data.trailing_days_true("NOPE", strategies[0], as_of) == 0


def test_trend_report_pages_show_distribution_days_true_and_multi_timeframe_columns(monkeypatch):
    _trend_setup(monkeypatch)
    result = emv_report_data.classify_trend(None, "Daily", date(2026, 2, 20), multi_timeframe=True)
    html = "".join(emv_report_data.build_trend_report_pages(result, show_days_true=True, multi_timeframe=True))
    assert "Category Distribution" in html and "Bullish" in html and "Sideways" in html
    for header in ("Stock", "Sector", "Category", "Days True", "Daily", "Weekly", "Monthly", "Quarterly"):
        assert f"<th>{header}</th>" in html
    assert "30+" in html                                   # ABB has been true for the whole lookback
    assert "skipped" in html                               # the deleted strategy is called out

    plain = "".join(emv_report_data.build_trend_report_pages(result, show_days_true=False, multi_timeframe=False))
    assert "<th>Days True</th>" not in plain and "<th>Weekly</th>" not in plain


def test_trend_report_handles_a_category_with_no_matching_stocks(monkeypatch):
    _trend_setup(monkeypatch)
    from services import trend_categories
    cats = trend_categories.load_all()
    cats.append(trend_categories.new_category("Empty", "#222222"))
    trend_categories.save_all(cats)
    result = emv_report_data.classify_trend("empty", "Monthly", date(2026, 2, 20))
    html = "".join(emv_report_data.build_trend_report_pages(result))
    assert "No stocks currently fall in this category" in html


def test_trailing_days_true_shares_one_history_pass_across_strategies(monkeypatch):
    strategies = _trend_setup(monkeypatch)
    calls = []
    real = emv_report_data._recent_rows

    def counting(display_symbol, as_of_date, lookback, cache):
        if cache is None or display_symbol not in cache:
            calls.append(display_symbol)
        return real(display_symbol, as_of_date, lookback, cache)

    monkeypatch.setattr(emv_report_data, "_recent_rows", counting)
    cache = {}
    as_of = date(2026, 2, 20)
    a = emv_report_data.trailing_days_true("ABB", strategies[0], as_of, cache=cache)
    b = emv_report_data.trailing_days_true("ABB", strategies[1], as_of, cache=cache)
    assert calls == ["ABB"]                       # the second strategy reused the cached rows
    assert a == b == emv_report_data.DAYS_TRUE_LOOKBACK


# ── Right-hand axis for columns of a very different scale (issue #61 follow-up: RSC) ──

def test_pick_axes_puts_far_scale_extras_on_the_right_axis():
    price = [4800.0, 4850.0, 4900.0, 4750.0]
    assert emv_report_data.pick_axes(price, [[99.0, 101.0, 103.0, 100.0], [4700.0, 4800.0, 4900.0, 5000.0],
                                              [None, None], [40000.0, 41000.0]]) == ["right", "left", "left", "right"]
    assert emv_report_data.pick_axes([], [[1.0]]) == ["left"]            # nothing to compare against -> keep left


def test_stock_report_draws_a_right_axis_for_an_rsc_like_extra_series():
    _seed("DIVISLAB_I", date(2026, 1, 1), 30, start_price=4800)
    data = emv_report_data.build_stock_report_data("DIVISLAB_I", "CLOSE", date(2026, 1, 12), date(2026, 1, 30))
    data["extras"] = [{"field": "RSC [RSC]", "color": "#aa00aa",
                       "series": [{"date": e["date"], "value": 100.0 + i * 0.5, "close": e["close"]}
                                  for i, e in enumerate(data["series"])]}]
    html = "".join(emv_report_data.build_stock_report_pages(data))
    assert "RSC [RSC] (right axis)" in html                       # legend says which scale it is on
    # the right-hand tick labels run on RSC's own scale (~100-105), not the price's (~4800)
    assert ">100.0<" in html or ">100.5<" in html or ">101.0<" in html or ">104.5<" in html
