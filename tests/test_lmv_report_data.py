from datetime import date

from services import lmv_report_data, strategy_store
from services.strategy_alerts import state_store


def _trade(strategy_id, symbol, direction, entry, exit_price, resolution,
           resolved_at, entry_time="2026-03-01T09:30:00"):
    return {
        "id": f"{strategy_id}-{symbol}-{resolved_at}",
        "state": "open",
        "strategy_id": strategy_id,
        "strategy_name": "Strat",
        "symbol": symbol,
        "sector": "IT",
        "direction": direction,
        "entry_time": entry_time,
        "entry_price": entry,
        "exit_price": exit_price,
        "metrics": {},
        "risk_reward": None,
        "score": None,
        "running_high": entry,
        "running_low": entry,
        "resolved_at": resolved_at,
        "resolution": resolution,
    }


def _seed_strategy(strategy_id, name):
    strategy_store.save_strategy({
        "id": strategy_id, "name": name, "active": True,
        "category": "Daily", "columns": [], "row_filter": [],
    })


def test_resolved_trades_excludes_cancelled_and_open():
    state_store.append_alert_history(_trade("s1", "INFY", "BUY", 100, 110, "all_targets_achieved", "2026-03-01T10:00:00"))
    state_store.append_alert_history(_trade("s1", "TCS", "BUY", 100, 90, "trade_cancelled", "2026-03-01T10:05:00"))
    state_store.append_alert_history({**_trade("s1", "WIPRO", "BUY", 100, None, "stopped_out", None)})

    trades = lmv_report_data.resolved_trades_for_strategy("s1")
    symbols = [t["symbol"] for t in trades]
    assert symbols == ["INFY"]


def test_directional_yield_matches_spec_example():
    _seed_strategy("s1", "Stage 2 CWTO Buy")
    state_store.append_alert_history(
        _trade("s1", "ALKEM", "SELL", 5450.00, 5395.50, "all_targets_achieved", "2026-03-01T10:00:00")
    )
    state_store.append_alert_history(
        _trade("s1", "TATASTEEL", "BUY", 150.00, 154.50, "all_targets_achieved", "2026-03-01T11:00:00")
    )
    state_store.append_alert_history(
        _trade("s1", "DELIVERY", "BUY", 420.00, 415.80, "stopped_out", "2026-03-01T12:00:00")
    )

    summary = lmv_report_data.compute_strategy_summary("s1", None, None)

    yields = [round(y, 2) for y in summary["yields"]]
    assert yields == [1.0, 3.0, -1.0]
    assert round(summary["blended_yield"], 2) == 1.0


def test_build_report_data_single_strategy():
    _seed_strategy("s1", "Stage 2 CWTO Buy")
    state_store.append_alert_history(
        _trade("s1", "ALKEM", "BUY", 100, 110, "all_targets_achieved", "2026-03-05T10:00:00", "2026-03-05T09:30:00")
    )

    data = lmv_report_data.build_report_data(
        "s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5),
    )

    assert data["summary_a"]["name"] == "Stage 2 CWTO Buy"
    assert data["summary_b"] is None
    assert data["curve_a"] == [10.0]
    assert data["investment"]["starting"] == lmv_report_data.DEFAULT_INVESTMENT_AMOUNT


def test_build_report_data_comparative():
    _seed_strategy("s1", "Strategy A")
    _seed_strategy("s2", "Strategy B")
    state_store.append_alert_history(
        _trade("s1", "ALKEM", "BUY", 100, 120, "all_targets_achieved", "2026-03-05T10:00:00", "2026-03-05T09:30:00")
    )
    state_store.append_alert_history(
        _trade("s2", "TCS", "BUY", 100, 105, "all_targets_achieved", "2026-03-05T10:00:00", "2026-03-05T09:30:00")
    )

    data = lmv_report_data.build_report_data(
        "s1", "s2", "daily", date(2026, 3, 5), date(2026, 3, 5),
    )

    assert data["summary_b"]["name"] == "Strategy B"
    assert data["curve_a"] == [20.0]
    assert data["curve_b"] == [5.0]


def test_build_report_pages_renders_without_crashing_and_has_two_pages():
    _seed_strategy("s1", "Strategy A")
    state_store.append_alert_history(
        _trade("s1", "ALKEM", "BUY", 100, 110, "all_targets_achieved", "2026-03-05T10:00:00", "2026-03-05T09:30:00")
    )
    data = lmv_report_data.build_report_data("s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5))

    pages = lmv_report_data.build_report_pages(data)

    assert len(pages) >= 2  # summary page + flowed content
    joined = "".join(pages)
    assert "Sector Distribution" in joined
    assert "ALKEM" in joined
    assert "TARGET HIT" in joined


def test_build_report_pages_handles_no_trades():
    _seed_strategy("s1", "Empty Strategy")
    data = lmv_report_data.build_report_data("s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5))

    pages = lmv_report_data.build_report_pages(data)

    assert "No closed trades" in "".join(pages)


def test_build_report_html_is_a_full_document():
    _seed_strategy("s1", "Strategy A")
    data = lmv_report_data.build_report_data("s1", None, "daily", None, None)
    html = lmv_report_data.build_report_html(data)
    assert "<!DOCTYPE html>" in html
    assert "Page 1 of" in html


def test_fallback_exit_price_used_when_exit_price_missing():
    _seed_strategy("s1", "Legacy Strategy")
    trade = _trade("s1", "OLD", "BUY", 100, None, "all_targets_achieved", "2026-03-05T10:00:00")
    trade["metrics"] = {
        "m1": {"name": "Target 1", "role": "target", "value": 115.0, "achieved": True, "achieved_at": "2026-03-05T10:00:00"},
    }
    state_store.append_alert_history(trade)

    summary = lmv_report_data.compute_strategy_summary("s1", None, None)
    assert round(summary["rows"][0]["yield"], 2) == 15.0


def test_backend_signals_use_status_field_and_paginate(monkeypatch):
    """Issue #56: backend rows carry "status", not "resolution" — they used
    to be dropped wholesale, leaving a Custom-range report blank."""
    from api import strategy_signals_api

    def row(i, status, resolved="2026-09-04T10:00:00"):
        return {"id": f"b{i}", "strategy_id": "s1", "symbol": f"S{i}", "direction": "BUY",
                "status": status, "entry_price": 100.0, "exit_price": 110.0,
                "entry_time": "2026-09-03T10:00:00", "resolved_at": resolved, "metrics": {}}

    pages = {
        1: {"items": [row(1, "all_targets_achieved"), row(2, "open", None)], "total_pages": 2},
        2: {"items": [row(3, "stopped_out"), row(4, "trade_cancelled")], "total_pages": 2},
    }
    monkeypatch.setattr(strategy_signals_api, "list_signals", lambda **kw: pages[kw["page"]])

    out = lmv_report_data._backend_resolved_trades("s1", date(2026, 9, 3), date(2026, 9, 8))
    assert [t["symbol"] for t in out] == ["S1", "S3"]
    assert [t["resolution"] for t in out] == ["all_targets_achieved", "stopped_out"]


def test_cross_compare_defaults_to_alkem_vs_tatasteel():
    _seed_strategy("s1", "Strategy A")
    for sym, ex in (("ALKEM", 110), ("TATASTEEL", 90), ("INFY", 120)):
        state_store.append_alert_history(
            _trade("s1", sym, "BUY", 100, ex, "all_targets_achieved", "2026-03-05T10:00:00")
        )
    data = lmv_report_data.build_report_data("s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5))
    cmp_rows = lmv_report_data.compare_assets(data["summary_a"])["rows"]
    assert [r["name"] for r in cmp_rows] == ["ALKEM", "TATASTEEL"]
    assert "Cross-Compare" in "".join(lmv_report_data.build_report_pages(data))
    assert lmv_report_data.sector_distribution(data["summary_a"])[0]["label"] == "IT"


def test_cross_compare_user_picks_and_sector_mode():
    _seed_strategy("s1", "Strategy A")
    for sym, sector, ex in (("ALKEM", "Pharma", 110), ("TATASTEEL", "Metals", 90), ("INFY", "IT", 105)):
        tr = _trade("s1", sym, "BUY", 100, ex, "all_targets_achieved", "2026-03-05T10:00:00")
        tr["sector"] = sector
        state_store.append_alert_history(tr)
    summary = lmv_report_data.build_report_data(
        "s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5))["summary_a"]
    picked = lmv_report_data.compare_assets(summary, "stock", "infy", "ALKEM")
    assert [r["name"] for r in picked["rows"]] == ["INFY", "ALKEM"]
    sectors = lmv_report_data.compare_assets(summary, "sector", "Metals", "IT")
    assert [r["name"] for r in sectors["rows"]] == ["Metals", "IT"]
    # An untraded pick falls back to the auto choice rather than failing.
    assert len(lmv_report_data.compare_assets(summary, "stock", "NOPE", "ALKEM")["rows"]) == 2


def test_boolean_style_target_metric_is_not_treated_as_exit_price():
    """A target whose value is a 1.0/0.0 condition flag (not a price) used
    to produce a bogus ~-100% yield for pre-exit_price history."""
    _seed_strategy("s1", "Strategy A")
    trade = _trade("s1", "BANKNIFTY", "BUY", 57412.0, None, "all_targets_achieved", "2026-03-05T10:00:00")
    trade["metrics"] = {"m1": {"name": "Target 1", "role": "target", "value": 1.0, "achieved": True}}
    state_store.append_alert_history(trade)

    summary = lmv_report_data.compute_strategy_summary("s1", None, None)
    assert summary["rows"][0]["yield"] is None
    assert summary["blended_yield"] is None


def test_long_trade_table_flows_across_pages():
    _seed_strategy("s1", "Strategy A")
    for i in range(120):
        tr = _trade("s1", f"S{i}", "BUY", 100, 110, "all_targets_achieved", "2026-03-05T10:00:00")
        tr["id"] = f"t{i}"
        state_store.append_alert_history(tr)
    data = lmv_report_data.build_report_data("s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5))
    pages = lmv_report_data.build_report_pages(data)
    assert len(pages) >= 3
    assert "(continued)" in "".join(pages)
    assert sum(p.count("<tr>") for p in pages) >= 120
