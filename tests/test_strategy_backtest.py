from datetime import date

import pytest

from services import lmv_report_data, strategy_backtest as bt
from services.strategy_alerts.models import new_metric, new_notification_config

STRATEGY = {"id": "s-bt", "name": "BT Strategy", "active": False, "columns": [], "row_filter": []}


def _num(v):
    return {"type": "num", "value": str(v)}


def _col(name):
    return {"type": "col", "value": name}


def _config(direction="BUY", stop=95, target=110, trigger_threshold=0):
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["direction"] = direction
    cfg["trigger_condition"] = [_col("Signal"), {"type": "op", "value": ">"}, _num(trigger_threshold)]
    cfg["metrics"] = [new_metric("Stop Loss", "stop_loss", [_num(stop)]),
                      new_metric("Target 1", "target", [_num(target)])]
    return cfg


def _day(d, rows):
    return {"trade_date": d, "stocks": [
        {"symbol": sym, "display_name": sym,
         "metrics": {"Signal": sig, "Current": cur, "High": hi, "Low": lo}}
        for sym, sig, cur, hi, lo in rows]}


def _run(days, cfg=None, lo="2026-10-05", hi="2026-10-30"):
    return bt.backtest_trades(STRATEGY, cfg or _config(), {"days": days},
                              date.fromisoformat(lo), date.fromisoformat(hi))


def test_enters_at_close_and_resolves_on_target_from_the_next_day():
    trades = _run([
        _day("2026-10-05", [("INFY", 1, 100, 101, 99)]),       # trigger true -> enters at 100
        _day("2026-10-06", [("INFY", 1, 105, 111, 100)]),      # high 111 >= target 110
    ])
    assert len(trades) == 1
    t = trades[0]
    assert t["resolution"] == "all_targets_achieved" and t["entry_price"] == 100
    assert t["exit_price"] == 110 and t["resolved_at"].startswith("2026-10-06")
    assert t["entry_time"].startswith("2026-10-05") and t["backtest"] is True


def test_entry_day_extremes_do_not_resolve_the_trade():
    """Entry is at the close, so the entry day's own High/Low can't hit anything."""
    trades = _run([_day("2026-10-05", [("INFY", 1, 100, 120, 80)])])
    assert trades == []


def test_stop_loss_resolves_and_wins_when_a_day_touches_both():
    stopped = _run([
        _day("2026-10-05", [("INFY", 1, 100, 100, 100)]),
        _day("2026-10-06", [("INFY", 1, 97, 101, 94)]),
    ])
    assert stopped[0]["resolution"] == "stopped_out" and stopped[0]["exit_price"] == 95
    both = _run([
        _day("2026-10-05", [("INFY", 1, 100, 100, 100)]),
        _day("2026-10-06", [("INFY", 1, 100, 115, 90)]),        # touches target AND stop
    ])
    assert both[0]["resolution"] == "stopped_out"


def test_sell_direction_mirrors():
    trades = _run([
        _day("2026-10-05", [("INFY", 1, 100, 100, 100)]),
        _day("2026-10-06", [("INFY", 1, 92, 99, 89)]),
    ], _config("SELL", stop=105, target=90))
    assert trades[0]["resolution"] == "all_targets_achieved" and trades[0]["exit_price"] == 90


def test_wrong_side_levels_are_a_cancelled_trade():
    trades = _run([_day("2026-10-05", [("INFY", 1, 100, 100, 100)])], _config(stop=95, target=90))
    assert [t["resolution"] for t in trades] == ["trade_cancelled"]


def test_no_reentry_while_trigger_stays_true_after_a_resolution_then_rearms():
    days = [
        _day("2026-10-05", [("INFY", 1, 100, 100, 100)]),
        _day("2026-10-06", [("INFY", 1, 105, 112, 100)]),       # resolves (target)
        _day("2026-10-07", [("INFY", 1, 100, 100, 100)]),       # trigger still true -> cooling, no new entry
        _day("2026-10-08", [("INFY", 0, 100, 100, 100)]),       # trigger false -> re-armed
        _day("2026-10-09", [("INFY", 1, 100, 100, 100)]),       # new entry
        _day("2026-10-12", [("INFY", 1, 104, 113, 100)]),       # resolves again
    ]
    trades = _run(days)
    assert [t["resolved_at"][:10] for t in trades] == ["2026-10-06", "2026-10-12"]


def test_entries_only_inside_the_requested_range_and_open_trades_are_left_open():
    days = [
        _day("2026-10-01", [("INFY", 1, 100, 100, 100)]),       # before the range: history only
        _day("2026-10-06", [("INFY", 0, 100, 100, 100)]),
        _day("2026-10-07", [("TCS", 1, 200, 200, 200)]),        # enters, never resolves
    ]
    config = _config(stop=190, target=220)
    assert _run(days, config, lo="2026-10-05") == []


def test_requires_a_trigger_condition():
    with pytest.raises(bt.BacktestUnavailable):
        bt.backtest_trades(STRATEGY, new_notification_config(), {"days": []}, date(2026, 10, 1), date(2026, 10, 2))


def test_row_filter_is_applied_before_the_trigger():
    strategy = dict(STRATEGY, row_filter=[_col("Current"), {"type": "op", "value": ">"}, _num(150)])
    # INFY (100) is filtered out; TCS (200) passes the filter and enters at 200 with stop 190 / target 230
    trades = bt.backtest_trades(strategy, _config(stop=190, target=230), {"days": [
        _day("2026-10-05", [("INFY", 1, 100, 100, 100), ("TCS", 1, 200, 200, 200)]),
        _day("2026-10-06", [("INFY", 1, 105, 120, 100), ("TCS", 1, 210, 240, 200)]),
    ]}, date(2026, 10, 5), date(2026, 10, 30))
    assert [t["symbol"] for t in trades] == ["TCS"]


def test_n_day_history_functions_resolve_from_the_stored_days():
    """VALUE_DAYS_AGO in the trigger is answered from the stored days (each day
    is its own 'today'), including days before the range."""
    days_ago = {"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": "Current", "days_arg": 0}
    cfg = _config(stop=100, target=106)
    cfg["trigger_condition"] = [_col("Current"), {"type": "op", "value": ">"}, days_ago]   # today's close > the previous stored day's (0 = most recent saved day, as in live)
    days = [
        _day("2026-10-01", [("INFY", 0, 100, 100, 100)]),
        _day("2026-10-02", [("INFY", 0, 99, 99, 99)]),         # fell: no entry
        _day("2026-10-05", [("INFY", 0, 105, 105, 105)]),      # rose from 99: enters at 105
        _day("2026-10-06", [("INFY", 0, 106, 107, 105)]),      # high 107 >= target 106
    ]
    trades = _run(days, cfg, lo="2026-10-01")
    assert len(trades) == 1 and trades[0]["entry_price"] == 105
    assert trades[0]["resolution"] == "all_targets_achieved" and trades[0]["entry_time"].startswith("2026-10-05")


def test_report_uses_backtest_trades_and_labels_the_report(monkeypatch):
    from services import strategy_store
    from services.strategy_alerts import config_store as alerts_config_store

    monkeypatch.setattr(strategy_store, "load_all", lambda: [STRATEGY])
    monkeypatch.setattr(alerts_config_store, "load_config", lambda sid: _config())
    response = {"days": [
        _day("2026-10-05", [("INFY", 1, 100, 100, 100)]),
        _day("2026-10-06", [("INFY", 1, 105, 111, 100)]),
    ]}
    monkeypatch.setattr(bt, "fetch_range", lambda date_from: response)
    data = lmv_report_data.build_report_data(
        "s-bt", None, "daily", date(2026, 10, 5), date(2026, 10, 9), backtest=True)
    summary = data["summary_a"]
    assert summary["closed_trades"] == 1 and summary["backtest"] is True
    assert summary["rows"][0]["yield"] == pytest.approx(10.0)
    html = lmv_report_data.build_report_html(data)
    assert "About this back-test" in html and "simulated" in html and "Back-test" in html


def test_report_notes_why_a_backtest_could_not_run(monkeypatch):
    from services import strategy_store
    from services.strategy_alerts import config_store as alerts_config_store

    monkeypatch.setattr(strategy_store, "load_all", lambda: [STRATEGY])
    monkeypatch.setattr(alerts_config_store, "load_config", lambda sid: None)   # no Notifications config
    monkeypatch.setattr(bt, "fetch_range", lambda date_from: {"days": [_day("2026-10-05", [("INFY", 1, 100, 100, 100)])]})
    data = lmv_report_data.build_report_data("s-bt", None, "daily", date(2026, 10, 5), date(2026, 10, 9), backtest=True)
    assert data["summary_a"]["closed_trades"] == 0
    assert "no Strategy Notifications trigger condition" in lmv_report_data.build_report_html(data)


def test_range_fetch_failure_is_reported_not_raised(monkeypatch):
    from api.exceptions import NetworkError

    def boom(date_from):
        raise NetworkError("offline")
    monkeypatch.setattr(bt, "fetch_range", boom)
    trades, notes = bt.run(STRATEGY, _config(), date(2026, 10, 5), date(2026, 10, 9))
    assert trades == [] and "could not be fetched" in notes[0]


def test_coverage_note_when_stored_data_starts_after_the_range(monkeypatch):
    monkeypatch.setattr(bt, "fetch_range", lambda date_from: {"days": [_day("2026-10-08", [("INFY", 0, 100, 100, 100)])]})
    trades, notes = bt.run(STRATEGY, _config(), date(2026, 10, 1), date(2026, 10, 9))
    assert any("only reaches back to 08-Oct-2026" in n for n in notes)


def test_wizard_offers_the_backtest_source_and_saves_it(monkeypatch):
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from app import AppController
    from screens.reports import ReportsScreen
    from services import report_store, strategy_store

    strategy_store.save_strategy(strategy_store.new_strategy("Alpha"))
    screen = ReportsScreen(AppController(app))
    screen._async_generation = False
    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    assert screen._lmv_source_combo.currentData() == "recorded"
    screen._select_data(screen._lmv_source_combo, "backtest")
    screen._name_edit.setText("BT report")
    captured = {}
    monkeypatch.setattr(lmv_report_data, "build_report_data",
                        lambda *a, **k: captured.update(k) or (_ for _ in ()).throw(RuntimeError("stop")))
    monkeypatch.setattr("PySide6.QtWidgets.QMessageBox.warning", staticmethod(lambda *a, **k: None))
    screen._save_and_generate()
    saved = report_store.load_all()[0]
    assert saved["subject_config"]["source"] == "backtest"
    assert captured.get("backtest") is True


def _hl_day(d, close, high, low, signal=0):
    return {"trade_date": d, "stocks": [{"symbol": "INFY", "display_name": "INFY", "metrics": {
        "Signal": signal, "Current": close, "High": high, "Low": low, "Open": close}}]}


def _atr_strategy():
    """TR2 = High - Low; ATR2 = average of TR2 over the 2 days before today — a
    strategy column averaged over past days of ANOTHER strategy column (like ATR)."""
    return dict(
        STRATEGY,
        columns=[
            {"name": "TR2", "formula": [_col("High"), {"type": "op", "value": "-"}, _col("Low")]},
            {"name": "ATR2", "formula": [{"type": "func", "value": "AVG_DAYS(", "col_arg": "TR2", "days_arg": 2}]},
        ])


def _atr_config():
    cfg = _config(stop=50)
    cfg["metrics"] = [
        new_metric("Stop Loss", "stop_loss", [_num(50)]),
        new_metric("Target 1", "target", [_col("Current"), {"type": "op", "value": "+"}, _col("ATR2")]),
    ]
    return cfg


def test_strategy_column_history_feeds_n_day_averages_in_targets():
    days = [
        _hl_day("2026-10-01", 100, 105, 95),                 # TR2 = 10
        _hl_day("2026-10-02", 100, 110, 90),                 # TR2 = 20
        _hl_day("2026-10-05", 100, 115, 85, signal=1),       # entry; ATR2 = avg(10, 20) = 15
        _hl_day("2026-10-06", 100, 120, 99),                 # high 120 >= target 115
    ]
    trades, stats = bt.backtest(_atr_strategy(), _atr_config(), {"days": days}, date(2026, 10, 1), date(2026, 10, 30))
    assert stats["skipped_no_levels"] == 0 and len(trades) == 1
    target = next(m for m in trades[0]["metrics"].values() if m["name"] == "Target 1")
    assert target["value"] == pytest.approx(115.0)
    assert trades[0]["resolution"] == "all_targets_achieved" and trades[0]["exit_price"] == pytest.approx(115.0)


def test_entry_is_skipped_while_levels_cannot_be_computed_yet():
    days = [_hl_day("2026-10-01", 100, 105, 95, signal=1),   # no prior days -> ATR2 blank -> no target
            _hl_day("2026-10-02", 100, 110, 90, signal=1)]
    trades, stats = bt.backtest(_atr_strategy(), _atr_config(), {"days": days}, date(2026, 10, 1), date(2026, 10, 30))
    assert trades == [] and stats["skipped_no_levels"] >= 1


def test_history_is_the_days_before_today_like_live():
    """'today's close above the highest close of the previous 2 days' can only be
    true if today is NOT part of its own history window."""
    cfg = _config(stop=90, target=130)
    cfg["trigger_condition"] = [_col("Current"), {"type": "op", "value": ">"},
                                {"type": "func", "value": "MAX_DAYS(", "col_arg": "Current", "days_arg": 2}]
    days = [
        _day("2026-10-01", [("INFY", 0, 100, 100, 100)]),
        _day("2026-10-02", [("INFY", 0, 101, 101, 101)]),
        _day("2026-10-05", [("INFY", 0, 105, 105, 105)]),     # 105 > max(100, 101): entry
        _day("2026-10-06", [("INFY", 0, 131, 131, 120)]),     # target 130 hit
    ]
    trades = _run(days, cfg, lo="2026-10-01")
    assert [(t["entry_time"][:10], t["resolution"]) for t in trades] == [("2026-10-05", "all_targets_achieved")]


def test_report_notes_cancelled_and_skipped_entries(monkeypatch):
    monkeypatch.setattr(bt, "fetch_range", lambda date_from: {"days": [
        _day("2026-10-05", [("INFY", 1, 100, 100, 100)]),
        _day("2026-10-06", [("INFY", 0, 100, 100, 100)]),
    ]})
    trades, notes = bt.run(STRATEGY, _config(stop=95, target=90), date(2026, 10, 5), date(2026, 10, 9))
    assert [t["resolution"] for t in trades] == ["trade_cancelled"]
    assert any("cancelled trades" in n for n in notes)
