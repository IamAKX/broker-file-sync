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

    signal = state_store.get_open_signals()[f"{strategy_id}::INFY"]
    signal["last_price"] = 110.0   # current price drives progress, not the running high
    data = fl.build_report_data(strategy_id, "INFY")
    html = "".join(fl.build_report_pages(data))

    assert "Target 1" in html
    assert "progress-track" in html
    assert "50%" in html   # (110-100)/(120-100)


# ── Strategy-wide report (issue #58) ─────────────────────────────────────

def _resolved(symbol, resolution, strategy_id="s1", entry=100.0, metrics=None):
    rec = _open_signal(strategy_id=strategy_id, symbol=symbol, entry=entry, metrics=metrics)
    rec.update({"id": f"{symbol}-{resolution}", "resolution": resolution,
                "resolved_at": "2026-03-01T11:00:00", "exit_price": 98.0})
    return rec


def test_strategy_signals_only_entered_trades_and_toggles():
    state_store.set_open_signal("s1::INFY", _open_signal(symbol="INFY"), force_flush=True)
    pending = _open_signal(symbol="PEND")
    pending["state"] = "pending"          # trigger true, not entered yet — no price/sector
    state_store.set_open_signal("s1::PEND", pending, force_flush=True)
    state_store.set_open_signal("other::ZZZ", _open_signal(strategy_id="other", symbol="ZZZ"), force_flush=True)
    state_store.append_alert_history(_resolved("SL1", "stopped_out"))
    state_store.append_alert_history(_resolved("CAN1", "trade_cancelled"))
    state_store.append_alert_history(_resolved("WIN1", "all_targets_achieved"))

    def symbols(**kw):
        return sorted(s["symbol"] for s in fl.strategy_signals("s1", **kw))

    assert symbols() == ["INFY"]
    assert symbols(include_stopped=True) == ["INFY", "SL1"]
    assert symbols(include_cancelled=True) == ["CAN1", "INFY"]
    assert symbols(include_stopped=True, include_cancelled=True, include_achieved=True) == \
        ["CAN1", "INFY", "SL1", "WIN1"]


def test_open_symbol_hides_its_older_resolved_record():
    state_store.set_open_signal("s1::INFY", _open_signal(symbol="INFY"), force_flush=True)
    state_store.append_alert_history(_resolved("INFY", "stopped_out"))
    assert [s["symbol"] for s in fl.strategy_signals("s1", include_stopped=True)] == ["INFY"]


def test_current_price_prefers_last_tick_never_running_high():
    sig = _open_signal(entry=100, running_high=150)
    assert fl.current_price_of(sig) == 100          # no live tick known -> entry, NOT the 150 high
    sig["last_price"] = 104.0
    assert fl.current_price_of(sig) == 104.0
    assert fl.pct_move(sig) == pytest.approx(4.0)
    sell = _open_signal(direction="SELL", entry=100)
    sell["last_price"] = 97.0
    assert fl.pct_move(sell) == pytest.approx(3.0)  # falling is in a SELL's favour


def test_targets_flag_wrong_side_of_entry_and_progress():
    metrics = {
        "t1": {"name": "Target 1", "role": "target", "value": 110.0, "achieved": False},
        "t2": {"name": "Target 2", "role": "target", "value": 95.0, "achieved": False},   # below entry for a BUY
        "t3": {"name": "Target 3", "role": "target", "value": 120.0, "achieved": True, "achieved_at": "2026-03-01T10:00:00"},
        "sl": {"name": "SL", "role": "informational", "value": 90.0},
    }
    sig = _open_signal(entry=100, metrics=metrics)
    sig["last_price"] = 105.0
    t = {x["name"]: x for x in fl._targets(sig)}
    assert t["Target 1"]["progress"] == pytest.approx(0.5) and t["Target 1"]["valid"]
    assert not t["Target 2"]["valid"] and t["Target 2"]["progress"] == 0.0
    assert t["Target 3"]["progress"] == 1.0
    assert fl._stop_loss(sig) == 90.0               # informational metric named SL


def test_strategy_report_flags_recently_added_and_groups_by_sector():
    from datetime import datetime
    old, new = _open_signal(symbol="OLD"), _open_signal(symbol="NEWB")
    old["entry_time"] = "2026-03-01T09:00:00"
    new["entry_time"] = "2026-03-01T10:30:00"
    new["sector"] = "AUTO"
    state_store.set_open_signal("s1::OLD", old, force_flush=True)
    state_store.set_open_signal("s1::NEWB", new, force_flush=True)

    data = fl.build_strategy_report_data("s1", new_since=datetime(2026, 3, 1, 10, 0), refresh_minutes=5)
    flags = {c["symbol"]: c["is_new"] for c in data["cards"]}
    assert flags == {"OLD": False, "NEWB": True}
    assert data["cards"][0]["symbol"] == "NEWB"      # newest first

    html = "".join(fl.build_strategy_report_pages(data))
    assert "RECENTLY ADDED" in html and "Recently added" in html
    assert "Sector Distribution" in html and "AUTO" in html and "IT" in html
    assert html.index("NEWB") < html.index("OLD")    # new stock upfront


def test_strategy_report_has_no_page_limit_and_empty_state():
    for i in range(30):
        state_store.set_open_signal(f"s1::S{i}", _open_signal(symbol=f"S{i}"), force_flush=True)
    data = fl.build_strategy_report_data("s1")
    pages = fl.build_strategy_report_pages(data)
    assert len(pages) >= 8
    assert all(f"S{i}" in "".join(pages) for i in range(30))

    empty = fl.build_strategy_report_pages(fl.build_strategy_report_data("nothing-here"))
    assert len(empty) == 1 and "No active signals" in empty[0]


def test_strategy_report_mentions_pending_stocks():
    p = _open_signal(symbol="PEND")
    p["state"] = "pending"
    state_store.set_open_signal("s1::PEND", p, force_flush=True)
    state_store.set_open_signal("s1::INFY", _open_signal(symbol="INFY"), force_flush=True)
    html = "".join(fl.build_strategy_report_pages(fl.build_strategy_report_data("s1")))
    assert "1 more stock currently match" in html or "not been entered yet" in html
    assert "PEND" not in html.replace("pending", "")


def test_timeline_lists_target_achievement_time_and_outcome():
    metrics = {"t1": {"name": "Target 1", "role": "target", "value": 110.0, "achieved": True,
                      "achieved_at": "2026-03-01T10:48:00"}}
    rec = _resolved("INFY", "all_targets_achieved", metrics=metrics)
    state_store.append_alert_history(rec)
    data = fl.build_report_data("s1", "INFY")
    details = [e["detail"] for e in data["timeline"]]
    assert any("TARGET 1 ACHIEVED" in d for d in details)
    assert details[-1] == "TARGETS ACHIEVED"
    assert any(e["title"].endswith("10:48") for e in data["timeline"])


def _card_data(symbol="INFY", direction="BUY", current=125.0):
    return {
        "symbol": symbol, "direction": direction, "entry_price": 100.0, "current_price": current,
        "stop_loss": 95.0,
        "targets": [{"name": "TARGET 1", "value": 130.0, "valid": True, "achieved": False, "progress": 0.5},
                    {"name": "TARGET 2", "value": 140.0, "valid": True, "achieved": False, "progress": 0.2}],
        "sr": fl.support_resistance_data(symbol, direction, current),
    }


def test_price_chart_is_a_line_chart_of_closes_with_levels_and_a_live_point():
    """#76: the Fuku card carries a price line chart (daily closes + live point)
    with entry / stop loss / targets / resistance drawn on it."""
    _seed_bars("INFY", date(2026, 1, 1), 40, base=100)
    svg = fl.price_chart_svg(_card_data())
    assert svg.startswith("<svg") and ("<path" in svg or "<polyline" in svg)
    for label in ("Close", "Entry", "Stop loss", "TARGET 1"):
        assert label in svg
    assert "live" in svg or "Close" in svg


def test_price_chart_empty_without_synced_history():
    assert fl.price_chart_svg(_card_data("NOPE")) == ""


def test_levels_note_names_resistance_for_buy_and_support_for_sell_or_explains_absence():
    _seed_bars("INFY", date(2026, 1, 1), 40, base=100)
    buy = fl._levels_note(_card_data("INFY", "BUY", current=90.0))
    assert "Possible resistance:" in buy
    sell = fl._levels_note(_card_data("INFY", "SELL", current=500.0))
    assert "Possible support:" in sell
    none = fl._levels_note(_card_data("NOPE", "BUY"))
    assert "No possible resistance levels" in none


def _why_config():
    alerts_config_store.save_config("s1", {
        "enabled": True, "direction": "BUY",
        "trigger_condition": [
            {"type": "col", "value": "Close"}, {"type": "op", "value": ">"}, {"type": "num", "value": "100"},
        ],
    })


def test_show_why_false_drops_the_trigger_section_single_and_strategy():
    """#89: the "Why this signal triggered" block is optional."""
    _why_config()
    state_store.set_open_signal("s1::INFY", _open_signal(), force_flush=True)

    on = fl.build_report_html(fl.build_report_data("s1", "INFY"))
    assert "Why this signal triggered" in on          # default: unchanged

    off = fl.build_report_html(fl.build_report_data("s1", "INFY", show_why=False))
    assert "Why this signal triggered" not in off
    assert "Signal timeline" in off and "Target progress" in off   # rest intact

    strat_off = fl.build_strategy_report_html(fl.build_strategy_report_data("s1", show_why=False))
    assert "Why this signal triggered" not in strat_off
    assert "INFY" in strat_off
    strat_on = fl.build_strategy_report_html(fl.build_strategy_report_data("s1"))
    assert "Why this signal triggered" in strat_on


def test_open_signal_with_some_targets_achieved_is_labelled_partial_in_the_report():
    """#94"""
    sig = _open_signal(symbol="PNB", entry=100.0)
    sig["metrics"] = {
        "t1": {"name": "TARGET 1", "role": "target", "value": 101.0, "achieved": True, "achieved_at": "2026-03-01T10:00:00"},
        "t2": {"name": "TARGET 2", "role": "target", "value": 105.0, "achieved": False, "achieved_at": None},
        "sl": {"name": "SL", "role": "stop_loss", "value": 95.0},
    }
    state_store.set_open_signal("s1::PNB", sig, force_flush=True)
    data = fl.build_report_data("s1", "PNB")
    assert data["status"] == "TARGETS PARTIALLY ACHIEVED 1/2"
    html = fl.build_report_html(data)
    assert "TARGETS PARTIALLY ACHIEVED 1/2" in html and 'fk-badge partial' in html

    strat = fl.build_strategy_report_html(fl.build_strategy_report_data("s1"))
    assert "Partially achieved" in strat                        # KPI card
    plain = _open_signal(symbol="PLAIN")
    state_store.set_open_signal("s1::PLAIN", plain, force_flush=True)
    assert fl.build_report_data("s1", "PLAIN")["status"] == "OPEN"
