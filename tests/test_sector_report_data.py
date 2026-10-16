"""Sector Report (issue #66) — the calculation rules come straight from the
requirement document, including its own worked examples."""
from datetime import date, timedelta

import pytest

from services import emv_report_data, inception_bars_store, inception_formula_builder_columns
from services import sector_report_data as sr


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "bars.db"))
    inception_formula_builder_columns.clear_cache()
    from services import inception_compute_service
    inception_compute_service.clear_cache()


def _tech():
    # the spec's §3.4 table
    return [
        sr._stock("TCS", "Technology", -0.38, -1.20, 2.10, {"MT": 2100, "CLOSE": 2092}),
        sr._stock("INFY", "Technology", -1.15, -2.10, 1.20, {"MT": 1000, "CLOSE": 988.5}),
        sr._stock("WIPRO", "Technology", -0.05, -0.80, 0.90, {"MT": 163.26, "CLOSE": 163.18}),
        sr._stock("TECHM", "Technology", -0.18, -0.60, 1.10, {}),
    ]


def test_sector_totals_are_sums_not_averages_matching_the_spec_example():
    stocks = _tech()
    totals = {tf: sr.aggregate_sectors(stocks, tf.lower())[0]["total"] for tf in sr.TIMEFRAMES}
    assert totals["Daily"] == pytest.approx(-1.76)
    assert totals["Weekly"] == pytest.approx(-4.70)
    assert totals["Monthly"] == pytest.approx(5.30)


def test_missing_values_are_skipped_and_counted_never_treated_as_zero():
    stocks = _tech() + [sr._stock("NEWCO", "Technology", None, None, 0.5, {})]
    agg = sr.aggregate_sectors(stocks, "daily")[0]
    assert agg["total"] == pytest.approx(-1.76) and agg["n"] == 4 and agg["missing"] == 1
    assert sr.aggregate_sectors(stocks, "monthly")[0]["n"] == 5            # NEWCO does have a monthly value
    none_at_all = sr.aggregate_sectors([sr._stock("X", "Alone", None, None, None, {})], "daily")[0]
    assert none_at_all["total"] is None and none_at_all["missing"] == 1     # no value at all -> None, not 0


def test_stocks_without_a_sector_are_grouped_under_unclassified_not_dropped():
    out = sr.aggregate_sectors([sr._stock("ZZZ", None, 1.0, 1.0, 1.0, {})], "daily")
    assert [a["sector"] for a in out] == [sr.UNCLASSIFIED] and out[0]["total"] == 1.0


def test_custom_pair_metric_matches_the_spec_mt_vs_close_example():
    metric = {"kind": "pair", "from": "MT", "to": "CLOSE"}
    values = [sr._pair_value(s["values"], metric) for s in _tech()[:3]]
    assert values[0] == pytest.approx(-0.38, abs=0.005) and values[1] == pytest.approx(-1.15, abs=0.005)
    assert values[2] == pytest.approx(-0.05, abs=0.005)
    assert sum(values) == pytest.approx(-1.58, abs=0.01)                    # "Technology Total -1.58%"
    assert sr._pair_value({"MT": 0, "CLOSE": 5}, metric) is None            # can't divide by zero -> blank
    assert sr._pair_value({"MT": 5}, metric) is None                        # missing field -> blank, not zero
    assert sr.metric_label(metric) == "MT vs CLOSE % Change"


def test_strong_and_weak_are_top_and_bottom_two_per_timeframe_independently():
    def stock(sector, d, w, m):
        return sr._stock(sector.lower() + "1", sector, d, w, m, {})
    stocks = [stock("A", 5, -5, 1), stock("B", 4, -4, 2), stock("C", 1, 3, 3), stock("D", -3, 4, 4), stock("E", -4, 5, 5)]
    ranks = {tf: sr.rank_sectors(sr.aggregate_sectors(stocks, tf.lower())) for tf in sr.TIMEFRAMES}
    names = lambda lst: [a["sector"] for a in lst]
    assert names(ranks["Daily"]["strong"]) == ["A", "B"] and names(ranks["Daily"]["weak"]) == ["E", "D"]
    assert names(ranks["Weekly"]["strong"]) == ["E", "D"] and names(ranks["Weekly"]["weak"]) == ["A", "B"]
    assert names(ranks["Monthly"]["strong"]) == ["E", "D"] and names(ranks["Monthly"]["weak"]) == ["A", "B"]


def test_heat_scale_neutral_near_zero_and_auto_step_spans_the_data():
    assert sr.heat_color(0.0, 1.0) == sr.heat_color(None, 1.0) == sr.heat_color(0.05, 1.0) == "#64748b"
    assert sr.heat_color(-0.5, 1.0) == "#f87171" and sr.heat_color(-10, 1.0) == "#991b1b"
    assert sr.heat_color(0.5, 1.0) == "#34d399" and sr.heat_color(10, 1.0) == "#15803d"
    assert sr.auto_step([8.4, -2]) == 2                                     # 8.4/2 = 4.2 -> largest nice step below it
    assert sr.auto_step([]) == 1.0 and sr.auto_step([0, None]) == 1.0
    assert sr.auto_step([0.3, -0.2]) < 0.5                                  # small moves get a small step


def test_live_stocks_read_the_lmv_snapshot_and_derive_weekly_monthly_from_prior_closes(monkeypatch):
    headers = ["Sector", "Scrip Name", "% Change", "Current"]
    data = [["IT", "TCS", "1.5", "110"], ["IT", "INFY", "-0.5", "95"], ["BANK", "HDFC", "x", "50"], ["", "", "", ""]]
    monkeypatch.setattr(sr, "_prior_closes", lambda symbol, today: (100.0, 80.0) if symbol == "TCS" else (None, None))
    out = sr.live_stocks(headers, data)["stocks"]
    by = {s["symbol"]: s for s in out}
    assert set(by) == {"TCS", "INFY", "HDFC"}                               # the blank row is skipped
    assert by["TCS"]["daily"] == 1.5 and by["TCS"]["weekly"] == pytest.approx(10.0) and by["TCS"]["monthly"] == pytest.approx(37.5)
    assert by["INFY"]["weekly"] is None                                     # no prior close -> missing, not zero
    assert by["HDFC"]["daily"] is None                                      # unparseable "% Change" -> missing


def test_live_stocks_prefer_lmv_week_month_columns_and_support_both_custom_metric_kinds(monkeypatch):
    headers = ["Sector", "Scrip Name", "% Change", "Current", "WEEK % CHANGE", "MONTH % CHANGE", "MT", "Close"]
    data = [["IT", "TCS", "1", "110", "2.5", "3.5", "100", "110"]]
    monkeypatch.setattr(sr, "_prior_closes", lambda *a: pytest.fail("columns present — no derivation needed"))
    s = sr.live_stocks(headers, data, {"kind": "pair", "from": "MT", "to": "Close"})["stocks"][0]
    assert (s["weekly"], s["monthly"], s["custom"]) == (2.5, 3.5, pytest.approx(10.0))


def test_eod_stocks_use_the_latest_synced_day_and_the_snapshots_percent_changes():
    rows, d, price = [], date(2026, 1, 5), 100.0
    for _ in range(40):
        if d.weekday() < 5:
            for sym, base in (("ABB_I", 0), ("SBIN_I", 50)):
                rows.append({"symbol": sym, "trade_date": d, "open": price + base, "high": price + base + 2,
                             "low": price + base - 2, "close": price + base, "volume": 1000})
            price += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)
    saturday = date(2026, 2, 28)
    assert saturday.weekday() == 5
    src = sr.eod_stocks(saturday, {"kind": "pair", "from": "OPEN", "to": "CLOSE"})
    assert src["as_of"] < saturday and {s["symbol"] for s in src["stocks"]} == {"ABB", "SBIN"}
    abb = next(s for s in src["stocks"] if s["symbol"] == "ABB")
    assert abb["daily"] is not None and abb["daily"] > 0                    # rising prices
    assert abb["custom"] == pytest.approx(0.0)                              # open == close in the seed data


def _report_data(**kw):
    stocks = _tech() + [sr._stock("HDFC", "Banking", 0.4, 1.0, -2.0, {}), sr._stock("SBIN", "Banking", 0.1, 0.5, -1.0, {}),
                        sr._stock("AUTO1", "Auto", 2.0, 3.0, 4.0, {}), sr._stock("AUTO2", "Auto", 1.0, 1.0, 1.0, {})]
    for s in stocks:
        s["custom"] = sr._pair_value(s["values"], {"kind": "pair", "from": "MT", "to": "CLOSE"})
    source = {"stocks": stocks, "as_of": date(2026, 10, 13), "source": "EOD 13-Oct-2026"}
    return sr.build_sector_report_data(source, "eod", {"kind": "pair", "from": "MT", "to": "CLOSE"}, **kw)


def test_report_pages_hold_heatmaps_rankings_bars_custom_and_audit_from_one_dataset():
    data = _report_data()
    html = "".join(sr.build_sector_report_pages(data))
    for part in ("Sector Heatmap — Daily % Change", "Sector Heatmap — Weekly % Change", "Sector Heatmap — Monthly % Change",
                 "Strongest &amp; Weakest Sectors", "Sector Performance — Daily / Weekly / Monthly",
                 "Custom Metric Heatmap — MT vs CLOSE % Change", "Sector Values Used (audit)",
                 "EOD 13-Oct-2026", "Fuku Lens EOD Sector Report"):
        assert part in html, part
    assert "-1.76%" in html and "-4.70%" in html and "+5.30%" in html       # Technology's spec totals appear
    assert "Daily %</th>" in html and "Monthly %</th>" in html
    assert data["rankings"]["Daily"]["strong"][0]["sector"] == "Auto"       # same dataset as the heatmap order


def test_selected_sector_adds_stock_heatmaps_for_each_timeframe_and_the_custom_metric():
    html = "".join(sr.build_sector_report_pages(_report_data(selected_sector="Technology")))
    for tf in ("Daily", "Weekly", "Monthly"):
        assert f"Technology — Stock Heatmap ({tf} % Change)" in html
    assert "Technology — Stock Heatmap (MT vs CLOSE % Change)" in html
    assert "TCS" in html and "WIPRO" in html
    missing = "".join(sr.build_sector_report_pages(_report_data(selected_sector="Nope")))
    assert "No stocks found for this sector" in missing


def test_primary_timeframe_orders_the_heatmaps_and_live_header_and_empty_state():
    html = "".join(sr.build_sector_report_pages(_report_data(primary_timeframe="Monthly")))
    assert html.index("Heatmap — Monthly") < html.index("Heatmap — Daily") < html.index("Heatmap — Weekly")
    live = _report_data(refresh_minutes=5)
    live["mode"] = "live"
    live_html = "".join(sr.build_sector_report_pages(live))
    assert "Fuku Lens Live Sector Report" in live_html and "Auto-refresh every 5 min" in live_html
    empty = sr.build_sector_report_data({"stocks": [], "as_of": date(2026, 1, 1), "source": "Live"}, "live")
    assert "open the Live Master View first" in "".join(sr.build_sector_report_pages(empty))


def test_grouped_bar_chart_draws_three_bars_per_sector_with_legend_and_skips_missing():
    svg = sr.grouped_sector_bars(_report_data()["sectors"])
    assert svg.count("<rect") == 3 * 3                                      # 3 sectors x (Daily, Weekly, Monthly)
    for label in ("Daily %", "Weekly %", "Monthly %", "Technology"):
        assert label in svg
    from services.report_engine import charts
    gap = charts.grouped_bar_chart(["A"], [{"label": "x", "color": "#111", "values": [None]}])
    assert "No data" in gap
    one_missing = charts.grouped_bar_chart(["A", "B"], [{"label": "x", "color": "#111", "values": [1.0, None]}])
    assert one_missing.count("<rect") == 1                                  # a missing value draws no bar (not a zero bar)


def test_live_stocks_with_no_live_view_open_gives_an_empty_snapshot_not_a_crash():
    out = sr.live_stocks([], [])
    assert out["stocks"] == [] and out["source"].startswith("Live ")


def test_unmapped_stocks_become_one_unclassified_group_that_is_never_ranked():
    stocks = [sr._stock("A1", "Alpha", 3.0, 3.0, 3.0, {}), sr._stock("B1", "Beta", 1.0, 1.0, 1.0, {}),
              sr._stock("C1", "Gamma", -2.0, -2.0, -2.0, {}),
              sr._stock("X1", "—", 50.0, 50.0, 50.0, {}), sr._stock("X2", "", -90.0, -90.0, -90.0, {}),
              sr._stock("X3", None, 1.0, 1.0, 1.0, {})]
    aggs = sr.aggregate_sectors(stocks, "daily")
    assert {a["sector"] for a in aggs} == {"Alpha", "Beta", "Gamma", sr.UNCLASSIFIED}
    unclassified = next(a for a in aggs if a["sector"] == sr.UNCLASSIFIED)
    assert unclassified["n"] == 3 and unclassified["total"] == pytest.approx(-39.0)
    rank = sr.rank_sectors(aggs)
    assert [a["sector"] for a in rank["strong"]] == ["Alpha", "Beta"]        # Unclassified's -39 is not "weak"
    assert [a["sector"] for a in rank["weak"]] == ["Gamma", "Beta"]


def test_heat_legend_labels_match_the_actual_colour_bins():
    step = 2.0
    legend = sr.heat_legend(step)
    for label in ("≤ -4", "-4 to -2", "-2 to 0", "0 to +2", "+2 to +4", "≥ +4"):
        assert label in legend
    # the bins those labels promise
    assert sr.heat_color(-4.0, step) == sr.heat_color(-9.0, step) == "#991b1b"       # <= -2s
    assert sr.heat_color(-3.0, step) == "#dc2626"                                    # -2s..-s
    assert sr.heat_color(-1.0, step) == "#f87171"                                    # -s..0
    assert sr.heat_color(1.0, step) == "#34d399" and sr.heat_color(3.0, step) == "#16a34a"
    assert sr.heat_color(4.0, step) == "#15803d"
    top = 94.09
    assert sr.heat_color(top, sr.auto_step([top, -50.1])) == "#15803d"               # the largest value gets the darkest colour


def test_stock_heatmap_items_are_descending_with_missing_last():
    """#75: a single sector's stock heatmap was alphabetical, not strongest-first."""
    stocks = [
        {"symbol": "AAA", "daily": 1.0}, {"symbol": "BBB", "daily": None},
        {"symbol": "CCC", "daily": 3.5}, {"symbol": "DDD", "daily": -2.0}, {"symbol": "EEE", "daily": 3.5},
    ]
    items = sr._stock_items(stocks, "daily")
    assert [i["name"] for i in items] == ["CCC", "EEE", "AAA", "DDD", "BBB"]
