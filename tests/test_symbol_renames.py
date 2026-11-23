"""Issue #112: a renamed stock (ICICIPRULI -> ICICILIFE) keeps its history —
LMV day-history snapshots and Inception bars saved under the old symbol are
joined onto the new one."""

from datetime import date, timedelta

import pytest

from services import config_store, inception_bars_store, symbol_renames


def _bar(symbol, d, close):
    return {
        "symbol": symbol, "trade_date": d, "open": close, "high": close + 1,
        "low": close - 1, "close": close, "volume": 100, "open_interest": 10,
    }


@pytest.fixture
def bars_db(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "bars.db"))
    start = date(2026, 10, 1)
    rows = []
    for i in range(10):                      # old symbol: 1st..10th Oct
        rows.append(_bar("ICICIPRULI_I", start + timedelta(days=i), 600 + i))
    for i in range(10, 15):                  # new symbol: 11th..15th Oct
        rows.append(_bar("ICICILIFE_I", start + timedelta(days=i), 600 + i))
    rows.append(_bar("ABB_I", start, 5000))
    inception_bars_store.upsert_bars(
        [{**r, "trade_date": r["trade_date"].isoformat()} for r in rows])
    return start


def test_default_rename_is_icicipruli_to_icicilife():
    assert symbol_renames.rename_map() == {"ICICIPRULI": "ICICILIFE"}


def test_saved_tab_replaces_defaults_and_chains_resolve():
    data = config_store._load_raw()
    data[symbol_renames.STORE_KEY] = [["A", "B"], ["b", "c"], ["", "X"], ["SAME", "SAME"]]
    config_store._save_raw(data)
    assert symbol_renames.rename_map() == {"A": "C", "B": "C"}


def test_available_symbols_hides_old_symbol(bars_db):
    assert inception_bars_store.available_symbols() == ["ABB_I", "ICICILIFE_I"]


def test_bars_for_new_symbol_include_old_history(bars_db):
    bars = inception_bars_store.bars_for_symbol("ICICILIFE_I")
    assert len(bars) == 15
    assert bars[0]["trade_date"] == bars_db
    assert [b["close"] for b in bars] == [600 + i for i in range(15)]


def test_bars_for_new_symbol_window_before_rename(bars_db):
    bars = inception_bars_store.bars_for_symbol(
        "ICICILIFE_I", bars_db + timedelta(days=2), bars_db + timedelta(days=4))
    assert [b["close"] for b in bars] == [602, 603, 604]


def test_bar_summaries_and_bars_for_date_use_new_symbol(bars_db):
    summaries = inception_bars_store.bar_summaries()
    assert "ICICIPRULI_I" not in summaries
    assert summaries["ICICILIFE_I"][0] == 15
    assert summaries["ICICILIFE_I"][1] == bars_db
    day = inception_bars_store.bars_for_date(bars_db + timedelta(days=3))
    assert [b["symbol"] for b in day] == ["ICICILIFE_I"]


def test_no_rename_when_new_symbol_absent(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "bars.db"))
    inception_bars_store.upsert_bars([{**_bar("ICICIPRULI_I", date(2026, 1, 1), 1), "trade_date": "2026-01-01"}])
    assert inception_bars_store.available_symbols() == ["ICICIPRULI_I"]
    assert len(inception_bars_store.bars_for_symbol("ICICIPRULI_I")) == 1


def test_range_response_reports_old_days_under_new_symbol():
    response = {"days": [
        {"trade_date": "2026-10-22", "stocks": [
            {"symbol": "ICICIPRULI", "display_name": "ICICIPRULI", "metrics": {"LTP": 1}},
            {"symbol": "ABB", "display_name": "ABB", "metrics": {"LTP": 2}},
        ]},
        {"trade_date": "2026-10-23", "stocks": [
            {"symbol": "ICICIPRULI", "display_name": "ICICIPRULI", "metrics": {"LTP": 3}},
            {"symbol": "ICICILIFE", "display_name": "ICICILIFE", "metrics": {"LTP": 4}},
        ]},
    ]}
    out = symbol_renames.apply_to_range_response(response)
    day1, day2 = out["days"]
    assert [(s["symbol"], s["display_name"]) for s in day1["stocks"]] == [
        ("ICICILIFE", "ICICILIFE"), ("ABB", "ABB")]
    # The new symbol's own row wins on a day that has both.
    assert [(s["symbol"], s["metrics"]["LTP"]) for s in day2["stocks"]] == [("ICICILIFE", 4)]


def test_get_range_applies_renames(monkeypatch):
    from api import lmv_snapshot_api
    monkeypatch.setattr(lmv_snapshot_api.api_client, "get", lambda *a, **k: {"days": [
        {"trade_date": "2026-10-22", "stocks": [{"symbol": "ICICIPRULI", "metrics": {}}]}]})
    assert lmv_snapshot_api.get_range(5)["days"][0]["stocks"][0]["symbol"] == "ICICILIFE"
