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

    assert len(pages) == 2
    assert "ALKEM" in pages[1]
    assert "TARGET HIT" in pages[1]


def test_build_report_pages_handles_no_trades():
    _seed_strategy("s1", "Empty Strategy")
    data = lmv_report_data.build_report_data("s1", None, "daily", date(2026, 3, 5), date(2026, 3, 5))

    pages = lmv_report_data.build_report_pages(data)

    assert "No closed trades" in pages[1]


def test_build_report_html_is_a_full_document():
    _seed_strategy("s1", "Strategy A")
    data = lmv_report_data.build_report_data("s1", None, "daily", None, None)
    html = lmv_report_data.build_report_html(data)
    assert "<!DOCTYPE html>" in html
    assert "Page 1 of 2" in html
    assert "Page 2 of 2" in html


def test_fallback_exit_price_used_when_exit_price_missing():
    _seed_strategy("s1", "Legacy Strategy")
    trade = _trade("s1", "OLD", "BUY", 100, None, "all_targets_achieved", "2026-03-05T10:00:00")
    trade["metrics"] = {
        "m1": {"name": "Target 1", "role": "target", "value": 115.0, "achieved": True, "achieved_at": "2026-03-05T10:00:00"},
    }
    state_store.append_alert_history(trade)

    summary = lmv_report_data.compute_strategy_summary("s1", None, None)
    assert round(summary["rows"][0]["yield"], 2) == 15.0
