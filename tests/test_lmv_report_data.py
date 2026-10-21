from datetime import date, datetime, timedelta

import pytest

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


# ── #94: open trades that achieved some, not all, targets ───────────────────

def _partial_signal(symbol="PNBHOUSING", strategy_id="s-part", achieved=2, total=4, last_price=1215.0,
                    entry=1190.3, state="open", direction="BUY"):
    metrics = {}
    for i in range(total):
        metrics[f"t{i}"] = {"name": f"TARGET {i + 1}", "role": "target", "value": entry + 6 * (i + 1),
                            "achieved": i < achieved, "achieved_at": "2026-10-13T11:59:00" if i < achieved else None}
    metrics["sl"] = {"name": "SL", "role": "stop_loss", "value": 1139.74}
    return {
        "id": f"id-{symbol}", "state": state, "strategy_id": strategy_id, "strategy_name": "TOPBOTTOM CALLOI STRONG BUY",
        "symbol": symbol, "sector": "FINANCE", "direction": direction,
        "entry_time": "2026-10-12T09:35:00", "entry_price": entry, "metrics": metrics,
        "running_high": 1220.7, "running_low": 1163.0, "last_price": last_price,
        "last_tick_time": datetime.now().isoformat(),
    }


def test_partial_targets_helper_only_flags_open_signals_with_some_targets_done():
    from services.strategy_alerts.models import is_partially_achieved, target_progress
    assert target_progress(_partial_signal(achieved=2, total=4)) == (2, 4)
    assert is_partially_achieved(_partial_signal(achieved=2, total=4))
    assert not is_partially_achieved(_partial_signal(achieved=0, total=4))        # nothing yet = plain Open
    assert not is_partially_achieved(_partial_signal(achieved=4, total=4))        # all hit
    assert not is_partially_achieved(dict(_partial_signal(), resolution="stopped_out"))
    assert not is_partially_achieved(_partial_signal(state="pending"))
    assert not is_partially_achieved({"state": "open", "metrics": {}})            # no targets configured


def test_lmv_report_includes_open_partial_trades_with_their_mark_to_market_return():
    from services.strategy_alerts import state_store
    state_store.set_open_signal("s-part::PNBHOUSING", _partial_signal(), force_flush=True)
    state_store.set_open_signal("s-part::FINNIFTY", _partial_signal("FINNIFTY", achieved=1, total=3, entry=1000.0,
                                                                   last_price=1010.0), force_flush=True)
    state_store.set_open_signal("s-part::NOTHING", _partial_signal("NOTHING", achieved=0), force_flush=True)   # plain open: not listed
    state_store.set_open_signal("other::X", _partial_signal("X", strategy_id="other"), force_flush=True)

    today = date.today()
    summary = lmv_report_data.compute_strategy_summary("s-part", today, today)

    assert {r["symbol"] for r in summary["rows"]} == {"PNBHOUSING", "FINNIFTY"}
    assert summary["closed_trades"] == 0 and summary["partial_trades"] == 2
    by_symbol = {r["symbol"]: r for r in summary["rows"]}
    assert by_symbol["PNBHOUSING"]["status_label"] == "PARTIAL 2/4"
    # profit booked at the achieved targets + the remainder marked at the last price
    pnb = ((1196.3 - 1190.3) / 1190.3 * 100 + (1202.3 - 1190.3) / 1190.3 * 100
           + 2 * (1215.0 - 1190.3) / 1190.3 * 100) / 4
    assert by_symbol["PNBHOUSING"]["yield"] == pytest.approx(pnb)
    assert by_symbol["FINNIFTY"]["yield"] == pytest.approx((0.6 + 2 * 1.0) / 3)
    assert summary["blended_yield"] == pytest.approx((pnb + (0.6 + 2 * 1.0) / 3) / 2)


def test_partial_trades_are_not_pulled_into_a_past_range_or_a_backtest():
    from services.strategy_alerts import state_store
    state_store.set_open_signal("s-part::PNBHOUSING", _partial_signal(), force_flush=True)
    past = date.today() - timedelta(days=30)
    assert lmv_report_data.compute_strategy_summary("s-part", past, past + timedelta(days=3))["rows"] == []   # not true back then
    assert lmv_report_data.partial_open_trades("s-part", date.today() + timedelta(days=1))                    # a range covering today: yes


def test_report_shows_partial_kpi_donut_segment_and_status_in_the_table():
    from services.strategy_alerts import state_store
    state_store.set_open_signal("s-part::PNBHOUSING", _partial_signal(), force_flush=True)
    today = date.today()
    data = lmv_report_data.build_report_data("s-part", None, "daily", today, today)
    html = lmv_report_data.build_report_html(data)
    assert "Partially Achieved (open)" in html and "Partial Targets" in html and "PARTIAL 2/4" in html
    assert "PNBHOUSING" in html


def test_scale_out_yield_books_achieved_targets_and_the_rest_at_exit():
    trade = _partial_signal(achieved=2, total=4, entry=100.0)        # targets 106, 112, 118, 124
    y, hit, total = lmv_report_data.scale_out_yield(trade, 100.0, 95.0, "BUY")
    assert (hit, total) == (2, 4)
    assert y == pytest.approx((6 + 12 + 2 * -5) / 4)                  # two quarters at +6/+12, two at the 95 stop
    # SELL mirrors it (targets below entry)
    sell = _partial_signal(achieved=1, total=2, entry=100.0, direction="SELL")
    for m in sell["metrics"].values():
        if m["role"] == "target":
            m["value"] = 100 - (m["value"] - 100)
    y, *_ = lmv_report_data.scale_out_yield(sell, 100.0, 104.0, "SELL")
    assert y == pytest.approx((6 + -4) / 2)
    # nothing to book / all done / a target that is not a price -> plain yield is used
    assert lmv_report_data.scale_out_yield(_partial_signal(achieved=0), 100.0, 95.0, "BUY")[0] is None
    assert lmv_report_data.scale_out_yield(_partial_signal(achieved=4, total=4), 100.0, 95.0, "BUY")[0] is None
    boolean = _partial_signal(achieved=1, total=2, entry=100.0)
    for m in boolean["metrics"].values():
        if m["role"] == "target":
            m["value"] = 1.0
    assert lmv_report_data.scale_out_yield(boolean, 100.0, 95.0, "BUY")[0] is None


def test_stopped_out_trade_that_hit_targets_first_keeps_the_profit_it_booked():
    """#94: stopped out after 2 of 4 targets used to count only entry->stop."""
    trade = _partial_signal(symbol="PNBHOUSING", strategy_id="s-stop", achieved=2, total=4, entry=1000.0)
    trade.update(state="open", resolution="stopped_out", resolved_at=datetime.now().isoformat(), exit_price=990.0)
    trade["metrics"]["t0"]["value"], trade["metrics"]["t1"]["value"] = 1010.0, 1020.0
    state_store.append_alert_history(trade)
    today = date.today()

    summary = lmv_report_data.compute_strategy_summary("s-stop", today, today)

    row = summary["rows"][0]
    assert row["booked_targets"] == (2, 4)
    assert row["yield"] == pytest.approx((1.0 + 2.0 + 2 * -1.0) / 4)          # +0.25%, not the plain -1.0%
    assert row["status_label"] == "STOP LOSS (2/4 targets)" and row["status_kind"] == "positive"
    assert summary["closed_trades"] == 1 and summary["partial_trades"] == 0
    html = lmv_report_data.build_report_html(lmv_report_data.build_report_data("s-stop", None, "daily", today, today))
    assert "Partially achieved targets" in html and "STOP LOSS (2/4 targets)" in html
