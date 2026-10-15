"""Indicators plotted in the LMV EOD and Fuku Live reports (issue #71)."""
from datetime import date, datetime, timedelta

import pytest

from services import (
    fuku_live_report_data as fl, indicator_charts, indicator_library, inception_bars_store,
    inception_formula_builder_columns, lmv_report_data, strategy_store,
)
from services.strategy_alerts import config_store as alerts_config_store
from services.strategy_alerts import state_store


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "bars.db"))
    inception_formula_builder_columns.clear_cache()


@pytest.fixture
def instances(monkeypatch):
    sma = indicator_library.new_instance("SMA", {"period": 5})
    rsi = indicator_library.new_instance("RSI", {"period": 14})
    monkeypatch.setattr(indicator_library, "load_instances", lambda: [sma, rsi])
    monkeypatch.setattr(indicator_library, "peek_instances", lambda: [sma, rsi])
    return sma, rsi


def _seed(symbol, days=90, base=100.0):
    rows, d, price, count = [], date.today() - timedelta(days=days * 2), base, 0
    while count < days:
        if d.weekday() < 5:
            rows.append({"symbol": symbol, "trade_date": d, "open": price, "high": price + 2,
                         "low": price - 2, "close": price + (3 if count % 3 == 0 else 0), "volume": 1000})
            price += 1
            count += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)


def _svg_h(svg):
    import re
    return int(float(re.search(r'<svg[^>]*\sheight="(\d+(?:\.\d+)?)"', svg).group(1)))


# ── shared helper ────────────────────────────────────────────────────────

def test_sections_for_symbol_builds_overlay_and_subpanel_charts_over_the_last_n_days(instances):
    sma, rsi = instances
    _seed("HAL_I")
    sections = indicator_charts.sections_for_symbol("HAL", date.today(), 40, [sma["id"], rsi["id"]])
    titles = [t for t, _ in sections]
    assert titles[0].startswith("Price with SMA(5)") and any("RSI(14)" in t for t in titles)
    price_svg = sections[0][1]
    assert price_svg.count('r="2.5"') >= 40                      # ~40 plotted points per line (Close + SMA)
    compact = indicator_charts.sections_for_symbol("HAL", date.today(), 40, [sma["id"], rsi["id"]], compact=True)
    assert _svg_h(compact[0][1]) < _svg_h(price_svg)             # compact = smaller charts for a card


def test_sections_for_symbol_returns_nothing_when_nothing_to_plot(instances):
    sma, _ = instances
    assert indicator_charts.sections_for_symbol("HAL", date.today(), 40, []) == []
    assert indicator_charts.sections_for_symbol("HAL", date.today(), 40, None) == []
    assert indicator_charts.sections_for_symbol("HAL", date.today(), 40, ["deleted-id"]) == []
    assert indicator_charts.sections_for_symbol("NOPE", date.today(), 40, [sma["id"]]) == []   # no synced bars


# ── Fuku Live ────────────────────────────────────────────────────────────

def _open_signal(symbol="HAL", strategy_id="s1"):
    return {"state": "open", "strategy_id": strategy_id, "strategy_name": "PWHBUY", "symbol": symbol, "sector": "CG",
            "direction": "BUY", "entry_time": "2026-03-01T09:31:00", "entry_price": 100.0, "last_price": 101.0,
            "metrics": {}, "risk_reward": None, "score": None, "running_high": 110.0, "running_low": 95.0}


def test_single_stock_fuku_report_lays_indicator_charts_out_full_size_after_the_card(instances):
    sma, rsi = instances
    _seed("HAL_I")
    state_store.set_open_signal("s1::HAL", _open_signal(), force_flush=True)
    data = fl.build_report_data("s1", "HAL", indicator_ids=[sma["id"], rsi["id"]], indicator_days=50)
    assert [t.split(" ")[0] for t, _ in data["indicator_sections"]][0] == "Price"
    pages = fl.build_report_pages(data)
    html = "".join(pages)
    assert "Indicator — Price with SMA(5)" in html and "Indicator — RSI(14)" in html
    assert 'class="fk-h" style="margin-top:10px">Indicators' not in pages[0]      # not embedded in the card
    plain = fl.build_report_pages(fl.build_report_data("s1", "HAL"))
    assert len(plain) == 2 and "Indicator —" not in "".join(plain)


def test_strategy_fuku_report_embeds_compact_indicator_charts_in_each_card_and_grows_the_card(instances):
    sma, rsi = instances
    _seed("HAL_I")
    _seed("ABB_I", base=200)
    for sym in ("HAL", "ABB"):
        state_store.set_open_signal(f"s1::{sym}", _open_signal(sym), force_flush=True)
    plain = fl.build_strategy_report_data("s1")
    withind = fl.build_strategy_report_data("s1", indicator_ids=[sma["id"], rsi["id"]], indicator_days=40)
    assert all(c["indicator_sections"] for c in withind["cards"]) and not any(c["indicator_sections"] for c in plain["cards"])
    html = "".join(fl.build_strategy_report_pages(withind))
    assert html.count('Indicators</div>') >= 2 and "Price with SMA(5)" in html and "RSI(14)" in html
    card_plain, h_plain = fl.card_html(plain["cards"][0])
    card_ind, h_ind = fl.card_html(withind["cards"][0])
    assert h_ind > h_plain + 200 and "Indicators" in card_ind          # the page-flow height estimate accounts for the charts


def test_a_stock_without_history_just_shows_no_indicator_charts(instances):
    sma, _ = instances
    state_store.set_open_signal("s1::NOBARS", _open_signal("NOBARS"), force_flush=True)
    data = fl.build_strategy_report_data("s1", indicator_ids=[sma["id"]])
    assert data["cards"][0]["indicator_sections"] == []
    assert "NOBARS" in "".join(fl.build_strategy_report_pages(data))


# ── LMV EOD ──────────────────────────────────────────────────────────────

def _trade(strategy_id, symbol, i):
    return {"id": f"{symbol}-{i}", "state": "open", "strategy_id": strategy_id, "strategy_name": "S", "symbol": symbol,
            "sector": "IT", "direction": "BUY", "entry_time": "2026-03-01T09:30:00", "entry_price": 100.0,
            "exit_price": 105.0, "metrics": {}, "risk_reward": None, "score": None, "running_high": 100, "running_low": 100,
            "resolved_at": f"2026-03-0{2 + i % 5}T10:00:00", "resolution": "all_targets_achieved"}


def _lmv_setup(monkeypatch):
    monkeypatch.setattr(strategy_store, "load_all", lambda: [{"id": "s1", "name": "Strat"}])
    for sym, n in (("HAL", 4), ("ABB", 3), ("TCS", 2), ("INFY", 1)):
        for i in range(n):
            state_store.append_alert_history(_trade("s1", sym, i))


def test_lmv_report_plots_indicators_for_chosen_stocks_or_the_most_traded_by_default(instances, monkeypatch):
    sma, rsi = instances
    _lmv_setup(monkeypatch)
    for sym in ("HAL_I", "ABB_I", "TCS_I", "INFY_I"):
        _seed(sym)
    kw = dict(date_from=date(2026, 3, 1), date_to=date.today())
    explicit = lmv_report_data.build_report_data("s1", None, "daily", indicator_ids=[sma["id"], rsi["id"]],
                                                 indicator_symbols=["tcs"], indicator_days=30, **kw)
    assert [s for s, _ in explicit["indicator_charts"]] == ["tcs"]
    default = lmv_report_data.build_report_data("s1", None, "daily", indicator_ids=[sma["id"]], **kw)
    assert [s for s, _ in default["indicator_charts"]] == ["HAL", "ABB", "TCS", "INFY"]      # most traded first
    none = lmv_report_data.build_report_data("s1", None, "daily", **kw)
    assert none["indicator_charts"] == []
    html = "".join(lmv_report_data.build_report_pages(explicit))
    assert "Price with SMA(5) — tcs" in html and "RSI(14)" in html and "— tcs" in html
    assert "Directional Stock Performance" in html                                     # the trade table still follows


def test_lmv_report_skips_indicator_stocks_with_no_history_and_never_fails(instances, monkeypatch):
    sma, _ = instances
    _lmv_setup(monkeypatch)
    _seed("HAL_I")
    data = lmv_report_data.build_report_data("s1", None, "daily", date(2026, 3, 1), date.today(),
                                             indicator_ids=[sma["id"]], indicator_symbols=["NOPE", "HAL"])
    assert [s for s, _ in data["indicator_charts"]] == ["HAL"]


# ── wizards ──────────────────────────────────────────────────────────────

@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.reports import ReportsScreen
    s = ReportsScreen(AppController(qapp))
    s._async_generation = False
    return s


@pytest.fixture
def qapp():
    import sys
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_lmv_wizard_saves_indicator_choices_generates_charts_and_prefills(screen, qapp, instances, monkeypatch):
    from services import report_store
    sma, rsi = instances
    _lmv_setup(monkeypatch)
    _seed("TCS_I")
    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    picker = screen._report_indicator_picker
    assert picker.count() == 2 and picker.selected_ids() == []
    screen._name_edit.setText("LMV + indicators")
    picker.set_selected([sma["id"]])
    screen._report_indicator_days.setValue(30)
    screen._report_indicator_symbols.setText("TCS, , HAL")
    screen._select_data(screen._timeframe_combo, "custom")
    screen._save_and_generate()
    qapp.processEvents()

    cfg = report_store.load_all()[0]["subject_config"]
    assert cfg["indicator_ids"] == [sma["id"]] and cfg["indicator_days"] == 30 and cfg["indicator_symbols"] == ["TCS", "HAL"]
    assert "Price with SMA(5) — TCS" in screen._last_rendered_html

    screen._edit_report(report_store.load_all()[0])
    assert screen._report_indicator_picker.selected_ids() == [sma["id"]]
    assert screen._report_indicator_symbols.text() == "TCS, HAL" and screen._report_indicator_days.value() == 30


def test_fuku_wizard_saves_indicator_choices_for_both_scopes(screen, qapp, instances):
    from services import report_store
    sma, _ = instances
    _seed("HAL_I")
    state_store.set_open_signal("s1::HAL", _open_signal(), force_flush=True)
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    assert screen._report_indicator_symbols is None                     # stocks are the report's own, no symbol box
    screen._report_indicator_picker.set_selected([sma["id"]])
    screen._name_edit.setText("Whole strategy")
    screen._save_and_generate()
    qapp.processEvents()
    cfg = report_store.load_all()[0]["subject_config"]
    assert cfg["scope"] == "strategy" and cfg["indicator_ids"] == [sma["id"]]
    assert "Price with SMA(5)" in screen._last_rendered_html

    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._select_data(screen._fuku_scope_combo, "single")
    screen._report_indicator_picker.set_selected([sma["id"]])
    screen._name_edit.setText("One stock")
    screen._save_and_generate()
    qapp.processEvents()
    assert "Indicator — Price with SMA(5)" in screen._last_rendered_html
