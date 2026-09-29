from datetime import date, timedelta

import pytest

from services import fuku_live_report_data as fl
from services import inception_bars_store, inception_formula_builder_columns, strategy_store
from services.strategy_alerts import config_store as alerts_config_store
from services.strategy_alerts import state_store


@pytest.fixture(autouse=True)
def _isolate_bars_db(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "test_bars.db"))
    inception_formula_builder_columns.clear_cache()


def _open_signal(strategy_id="s1", symbol="INFY", direction="BUY", entry=100.0,
                  running_high=110.0, running_low=95.0, metrics=None):
    return {
        "state": "open", "strategy_id": strategy_id, "strategy_name": "PWHBUY",
        "symbol": symbol, "sector": "IT", "direction": direction,
        "entry_time": "2026-03-01T09:31:00", "entry_price": entry,
        "metrics": metrics or {}, "risk_reward": None, "score": None,
        "running_high": running_high, "running_low": running_low,
        "repeat_armed": True, "last_repeat_at": None, "exit_price": None,
    }


def _seed_bars(symbol: str, start: date, days: int, base=100.0):
    rows = []
    d = start
    price = base
    count = 0
    while count < days:
        if d.weekday() < 5:
            rows.append({
                "symbol": symbol, "trade_date": d, "open": price, "high": price + 3,
                "low": price - 3, "close": price, "volume": 1000,
            })
            price += 1
            count += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)


def test_list_available_signals_includes_open_signal():
    state_store.set_open_signal("s1::INFY", _open_signal(), force_flush=True)
    available = fl.list_available_signals()
    assert any(s["symbol"] == "INFY" and s["state"] == "open" for s in available)


def test_get_signal_prefers_open_over_resolved():
    state_store.set_open_signal("s1::INFY", _open_signal(entry=100), force_flush=True)
    state_store.append_alert_history({**_open_signal(entry=90), "resolved_at": "2026-02-01T10:00:00", "resolution": "stopped_out"})

    signal = fl.get_signal("s1", "INFY")
    assert signal["entry_price"] == 100
    assert signal["state"] == "open"


def test_get_signal_falls_back_to_resolved_history():
    state_store.append_alert_history({
        **_open_signal(entry=90), "resolved_at": "2026-02-01T10:00:00", "resolution": "stopped_out",
    })
    signal = fl.get_signal("s1", "INFY")
    assert signal["resolution"] == "stopped_out"


def test_get_signal_none_when_nothing_found():
    assert fl.get_signal("nope", "NOPE") is None


def test_trigger_explanation_uses_strategy_config():
    alerts_config_store.save_config("s1", {
        "enabled": True, "direction": "BUY",
        "trigger_condition": [
            {"type": "col", "value": "Close"}, {"type": "op", "value": ">"}, {"type": "num", "value": "100"},
            {"type": "op", "value": " and "},
            {"type": "col", "value": "Volume"}, {"type": "op", "value": ">"}, {"type": "num", "value": "1000"},
        ],
        "debounce_minutes": 2, "score": None, "risk_reward": None, "metrics": [],
        "repeat_enabled": False, "repeat_condition": [], "repeat_min_gap_minutes": 5,
        "alert_mode": "positional",
    })

    explanation = fl.trigger_explanation("s1")

    assert len(explanation) == 2
    assert all(e["satisfied"] for e in explanation)
    assert "[Close]" in explanation[0]["label"]


def test_trigger_explanation_empty_when_no_config():
    assert fl.trigger_explanation("unknown") == []


def test_compute_score_is_full_marks():
    result = fl.compute_score()
    assert result["score"] == 100
    assert result["max_score"] == 100


def test_support_resistance_data_returns_levels_for_synced_symbol():
    _seed_bars("INFY", date(2026, 1, 1), 30, base=100)
    data = fl.support_resistance_data("INFY", "BUY", current_price=125)
    assert data["sources"]
    assert isinstance(data["levels"], list)


def test_support_resistance_data_empty_for_unsynced_symbol():
    data = fl.support_resistance_data("NOPE", "BUY", current_price=100)
    assert data["sources"] == {}
    assert data["levels"] == []


def test_build_report_data_not_found():
    data = fl.build_report_data("nope", "NOPE")
    assert data["found"] is False


def test_build_report_data_open_signal():
    strategy_store.save_strategy(strategy_store.new_strategy("PWHBUY"))
    all_strats = strategy_store.load_all()
    strategy_id = all_strats[0]["id"]

    state_store.set_open_signal(f"{strategy_id}::INFY", _open_signal(strategy_id=strategy_id), force_flush=True)
    alerts_config_store.save_config(strategy_id, {
        "enabled": True, "direction": "BUY", "trigger_condition": [],
        "debounce_minutes": 2, "score": None, "risk_reward": None, "metrics": [],
        "repeat_enabled": False, "repeat_condition": [], "repeat_min_gap_minutes": 5,
        "alert_mode": "intraday",
    })

    data = fl.build_report_data(strategy_id, "INFY")

    assert data["found"] is True
    assert data["status"] == "OPEN"
    assert data["alert_mode"] == "intraday"
    assert data["entry_price"] == 100.0


def test_build_report_pages_not_found_renders_gracefully():
    data = fl.build_report_data("nope", "NOPE")
    pages = fl.build_report_pages(data)
    assert len(pages) == 1
    assert "no signal found" in pages[0].lower() or "No Data" in pages[0]


def test_build_report_html_full_document_for_open_signal():
    strategy_store.save_strategy(strategy_store.new_strategy("PWHBUY"))
    strategy_id = strategy_store.load_all()[0]["id"]
    state_store.set_open_signal(f"{strategy_id}::INFY", _open_signal(strategy_id=strategy_id), force_flush=True)

    data = fl.build_report_data(strategy_id, "INFY")
    html = fl.build_report_html(data)

    assert "<!DOCTYPE html>" in html
    assert "INFY" in html
    assert "Fuku Score" in html


def test_build_report_pages_shows_target_progress():
    strategy_store.save_strategy(strategy_store.new_strategy("PWHBUY"))
    strategy_id = strategy_store.load_all()[0]["id"]
    metrics = {
        "m1": {"name": "Target 1", "role": "target", "value": 120.0, "achieved": False, "achieved_at": None},
    }
    state_store.set_open_signal(
        f"{strategy_id}::INFY",
        _open_signal(strategy_id=strategy_id, entry=100, running_high=110, metrics=metrics),
        force_flush=True,
    )

    data = fl.build_report_data(strategy_id, "INFY")
    pages = fl.build_report_pages(data)

    assert "Target 1" in pages[1]
    assert "progress-track" in pages[1]
