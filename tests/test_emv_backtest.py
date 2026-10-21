"""#83: EMV strategy back-test (entry / exit conditions + direction, no targets or stop-loss)."""
from datetime import date, timedelta

import pytest

from services import emv_backtest as eb
from services import inception_backtest_config as cfg_store
from services import inception_bars_store, inception_compute_service, inception_formula_builder_columns

D0 = date(2026, 1, 5)          # a Monday


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "bars.db"))
    inception_formula_builder_columns.clear_cache()
    inception_compute_service.clear_cache()


def _seed(symbol, closes):
    rows, d, i = [], D0, 0
    while i < len(closes):
        if d.weekday() < 5:
            c = closes[i]
            rows.append({"symbol": symbol, "trade_date": d, "open": c - 0.5, "high": c + 1, "low": c - 1,
                         "close": c, "volume": 1000})
            i += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)
    return [r["trade_date"] for r in rows]


def _col(n):
    return {"type": "col", "value": n}


def _num(v):
    return {"type": "num", "value": str(v)}


def _op(o):
    return {"type": "op", "value": o}


STRATEGY = {"id": "e1", "name": "Breakout", "active": True, "category": "Daily", "columns": [], "row_filter": []}


def _config(entry=105, exit_=103, direction="BUY", metrics=None):
    cfg = cfg_store.new_config()
    cfg["direction"] = direction
    cfg["entry_condition"] = [_col("CLOSE"), _op(">"), _num(entry)] if entry is not None else []
    cfg["exit_condition"] = [_col("CLOSE"), _op("<"), _num(exit_)] if exit_ is not None else []
    cfg["metrics"] = metrics or []
    return cfg


def _run(closes, cfg=None, strategy=None, **kw):
    dates = _seed("ABB_I", closes)
    return eb.run(strategy or STRATEGY, cfg or _config(), dates[0], dates[-1], **kw), dates


def test_enters_on_the_entry_condition_exits_on_the_exit_condition_at_the_close():
    result, dates = _run([100, 104, 106, 108, 107, 102, 101])
    assert len(result["trades"]) == 1
    t = result["trades"][0]
    assert (t["symbol"], t["direction"]) == ("ABB", "BUY")
    assert t["entry_date"] == dates[2] and t["entry"] == 106          # first close above 105
    assert t["exit_date"] == dates[5] and t["exit"] == 102            # first close below 103
    assert t["yield"] == pytest.approx((102 - 106) / 106 * 100)
    assert result["open_trades"] == 0


def test_sell_direction_mirrors_the_yield():
    result, _ = _run([100, 104, 106, 108, 107, 102, 101], _config(direction="SELL"))
    assert result["trades"][0]["yield"] == pytest.approx(-(102 - 106) / 106 * 100)


def test_no_reentry_until_the_entry_condition_has_turned_false_once():
    # above 105 (enter) ... exit on <103 ... still not re-armed while >105? here it dips <105 first
    closes = [100, 106, 107, 102, 106, 107, 102]
    result, dates = _run(closes)
    assert [(t["entry_date"], t["exit_date"]) for t in result["trades"]] == [(dates[1], dates[3]), (dates[4], dates[6])]

    # exit while the entry condition is STILL true (exit rule is independent): must wait for it to go false
    cfg = _config(entry=105, exit_=None)
    cfg["exit_condition"] = [_col("CLOSE"), _op(">"), _num(108)]
    result, dates = _run([100, 106, 109, 110, 111, 104, 106], cfg)
    assert [(t["entry_date"], t["exit_date"]) for t in result["trades"]] == [(dates[1], dates[2])]
    assert result["open_trades"] == 1      # re-armed by the 104 dip, re-entered on the 106 close (still open, not counted)


def test_open_position_at_the_end_is_not_counted_but_reported():
    result, _ = _run([100, 106, 107, 108])
    assert result["trades"] == [] and result["open_trades"] == 1


def test_no_exit_condition_exits_when_the_entry_no_longer_holds():
    result, dates = _run([100, 106, 107, 104, 100], _config(entry=105, exit_=None))
    t = result["trades"][0]
    assert t["entry_date"] == dates[1] and t["exit_date"] == dates[3] and t["exit"] == 104


def test_no_entry_condition_uses_the_strategy_row_filter():
    strategy = dict(STRATEGY, row_filter=[_col("CLOSE"), _op(">"), _num(105)])
    result, dates = _run([100, 106, 107, 104, 100], _config(entry=None, exit_=None), strategy)
    assert (result["trades"][0]["entry_date"], result["trades"][0]["exit_date"]) == (dates[1], dates[3])
    assert any("no entry / exit condition" in n for n in result["notes"])       # said plainly in the report


def test_row_filter_gates_the_entry_even_when_the_condition_is_true():
    strategy = dict(STRATEGY, row_filter=[_col("CLOSE"), _op(">"), _num(200)])
    result, _ = _run([100, 106, 107, 104, 100], _config(), strategy)
    assert result["trades"] == [] and result["open_trades"] == 0


def test_informational_metrics_are_evaluated_on_the_entry_day():
    metrics = [cfg_store.new_metric("Range", [_col("HIGH"), _op("-"), _col("LOW")]),
               cfg_store.new_metric("Close x2", [_col("CLOSE"), _op("*"), _num(2)])]
    result, _ = _run([100, 104, 106, 108, 102], _config(metrics=metrics))
    assert result["trades"][0]["extra"] == {"Range": 2.0, "Close x2": 212.0}


def test_strategy_columns_can_be_used_by_the_conditions():
    strategy = dict(STRATEGY, columns=[{"name": "Doubled", "fmt_rules": [],
                                        "formula": [_col("CLOSE"), _op("*"), _num(2)]}])
    cfg = _config()
    cfg["entry_condition"] = [_col("Doubled"), _op(">"), _num(210)]
    cfg["exit_condition"] = [_col("Doubled"), _op("<"), _num(206)]
    result, dates = _run([100, 104, 106, 108, 107, 102], cfg, strategy)
    assert result["trades"][0]["entry_date"] == dates[2] and result["trades"][0]["exit_date"] == dates[5]


def test_lookback_columns_see_the_history_as_of_each_day():
    """"Prev Close" (VALUE_DAYS_AGO) must be the previous bar's close on EVERY back-test day."""
    prev = {"name": "Prev Close", "fmt_rules": [], "formula": [
        {"type": "func", "value": "Max("},
        {"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": "CLOSE", "days_arg": 2},
        {"type": "op", "value": ","},
        {"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": "CLOSE", "days_arg": 2},
        {"type": "paren", "value": ")"}]}
    strategy = dict(STRATEGY, columns=[prev])
    cfg = _config()
    cfg["entry_condition"] = [_col("CLOSE"), _op(">"), _col("Prev Close"), _op("+"), _num(1.5)]   # a jump of >1.5
    cfg["exit_condition"] = [_col("CLOSE"), _op("<"), _col("Prev Close")]                        # a down day
    result, dates = _run([100, 101, 104, 105, 103, 104], cfg, strategy)
    t = result["trades"]
    assert len(t) == 1 and t[0]["entry_date"] == dates[2] and t[0]["entry"] == 104     # 104 > 101 + 1.5
    assert t[0]["exit_date"] == dates[4] and t[0]["exit"] == 103                       # 103 < 105


def test_single_stock_and_date_range_are_respected():
    _seed("ABB_I", [100, 106, 107, 102, 106, 107, 102])
    _seed("TCS_I", [100, 106, 107, 102, 106, 107, 102])
    dates = [D0 + timedelta(days=i) for i in range(0, 9) if (D0 + timedelta(days=i)).weekday() < 5]
    both = eb.run(STRATEGY, _config(), dates[0], dates[-1])
    one = eb.run(STRATEGY, _config(), dates[0], dates[-1], stock="tcs")
    assert {t["symbol"] for t in both["trades"]} == {"ABB", "TCS"} and both["symbols"] == 2
    assert {t["symbol"] for t in one["trades"]} == {"TCS"} and one["symbols"] == 1
    late = eb.run(STRATEGY, _config(), dates[3], dates[-1], stock="tcs")            # starts after the first trade
    assert len(late["trades"]) == 1 and late["trades"][0]["entry_date"] >= dates[3]


def test_backtest_result_feeds_the_shared_report(monkeypatch):
    from services import backtest_report, inception_strategy_store
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [STRATEGY])
    cfg_store.save_config("e1", _config(metrics=[cfg_store.new_metric("Range", [_col("HIGH"), _op("-"), _col("LOW")])]))
    dates = _seed("ABB_I", [100, 104, 106, 108, 107, 102, 101, 107, 108, 100])
    result = eb.backtest_result("e1", dates[0], dates[-1], 8000.0)
    assert result["kind"] == "EMV" and result["name"] == "Breakout" and result["investment_amount"] == 8000.0
    assert result["extra_columns"] == ["Range"] and len(result["trades"]) == 2
    assert result["trades"][0]["outcome"] == "Exit signal" and result["trades"][0]["kind"] == "negative"
    html = backtest_report.build_html(result)
    assert "EMV Strategy Back-test Report" in html and ">Range<" in html and "simulated" in html
    assert eb.backtest_result("missing", dates[0], dates[-1])["notes"] == ["the strategy was not found"]


def test_config_store_roundtrip_defaults_and_normalisation():
    assert cfg_store.load_config("nope") == cfg_store.new_config() and not cfg_store.has_rules("nope")
    cfg_store.save_config("s9", {"direction": "sell", "entry_condition": [_col("CLOSE")], "exit_condition": [],
                                 "metrics": [{"name": "M", "formula": [_col("HIGH")]}, {"name": ""}]})
    loaded = cfg_store.load_config("s9")
    assert loaded["direction"] == "SELL" and loaded["entry_condition"] and cfg_store.has_rules("s9")
    assert len(loaded["metrics"]) == 1 and loaded["metrics"][0]["id"]               # nameless dropped, id filled
    cfg_store.delete_config("s9")
    assert not cfg_store.has_rules("s9")


# ── Strategy Builder UI ─────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def qapp():
    import sys
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_builder_shows_the_backtest_section_and_saves_the_rules(qapp):
    from screens.inception_strategy_builder import _InceptionStrategyEditor
    strategy = dict(STRATEGY, id="ui-1", columns=[])
    editor = _InceptionStrategyEditor(strategy, ["CLOSE", "OPEN", "HIGH", "LOW"], None)
    assert editor._bt_direction.currentData() == "BUY"
    assert editor._bt_previews["entry_condition"].text() == "(not set)"

    editor._bt["entry_condition"] = [_col("CLOSE"), _op(">"), _num(105)]
    editor._bt["exit_condition"] = [_col("CLOSE"), _op("<"), _num(103)]
    editor._refresh_bt_previews()
    assert "105" in editor._bt_previews["entry_condition"].text()
    editor._bt["metrics"].append(cfg_store.new_metric("Range", [_col("HIGH"), _op("-"), _col("LOW")]))
    editor._refresh_bt_metrics()
    editor._bt_direction.setCurrentIndex(editor._bt_direction.findData("SELL"))

    saved = []
    editor.saved.connect(saved.append)
    editor._save()
    assert saved and saved[0]["id"] == "ui-1"
    stored = cfg_store.load_config("ui-1")
    assert stored["direction"] == "SELL" and stored["entry_condition"] and stored["exit_condition"]
    assert [m["name"] for m in stored["metrics"]] == ["Range"]

    # reopening the strategy restores them; clearing a condition works
    again = _InceptionStrategyEditor(strategy, ["CLOSE"], None)
    assert again._bt_direction.currentData() == "SELL" and len(again._bt["metrics"]) == 1
    again._clear_bt_condition("entry_condition")
    assert again._bt_previews["entry_condition"].text() == "(not set)"
    again._delete_bt_metric(0)
    assert again._bt["metrics"] == []


def test_a_strategy_without_saved_rules_still_saves_cleanly(qapp):
    from screens.inception_strategy_builder import _InceptionStrategyEditor
    editor = _InceptionStrategyEditor(dict(STRATEGY, id="ui-2"), ["CLOSE"], None)
    saved = []
    editor.saved.connect(saved.append)
    editor._save()
    assert saved and cfg_store.load_config("ui-2")["entry_condition"] == []
