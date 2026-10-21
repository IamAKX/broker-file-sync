import sys
import time
from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def _isolate_inception_bars_db(tmp_path, monkeypatch):
    # Not covered by conftest.py's autouse _isolate_disk_stores (that fixture
    # only redirects the JSON-blob stores) — inception_bars_store is a
    # separate SQLite file, defaulting to the real repo-root inception_bars.db
    # if left unpatched, which is real production data this suite must never
    # touch (see services/inception_bars_store.py's own module docstring).
    from services import inception_bars_store, inception_formula_builder_columns
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "test_bars.db"))
    inception_formula_builder_columns.clear_cache()


@pytest.fixture
def screen(qapp):
    # tests/conftest.py's autouse _isolate_disk_stores fixture redirects
    # config_store to a per-test tmp path.
    from app import AppController
    from screens.reports import ReportsScreen
    screen = ReportsScreen(AppController(qapp))
    screen._async_generation = False   # most tests assert on the result straight away
    return screen


def _seed_bars(symbol: str, start: date, days: int, start_price: float = 100.0):
    from services import inception_bars_store

    rows = []
    d = start
    price = start_price
    count = 0
    while count < days:
        if d.weekday() < 5:
            rows.append({
                "symbol": symbol, "trade_date": d, "open": price, "high": price + 2,
                "low": price - 2, "close": price, "volume": 1000,
            })
            price += 1
            count += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)


def test_reports_screen_creates_on_gallery_page(screen):
    assert screen._stack.currentWidget() is screen._gallery_page


def test_gallery_starts_with_no_saved_reports(screen):
    assert screen._saved_table.rowCount() == 0


def test_new_report_opens_wizard_prefilled(screen):
    from services import report_store

    screen._start_new_report(report_store.REPORT_TYPE_LMV)

    assert screen._stack.currentWidget() is screen._wizard_page
    assert screen._active_report["type"] == report_store.REPORT_TYPE_LMV
    assert screen._name_edit.text() == screen._active_report["name"]


def test_save_and_generate_requires_a_name(screen, monkeypatch):
    from services import report_store

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._name_edit.setText("   ")

    screen._save_and_generate()

    assert report_store.load_all() == []
    assert screen._stack.currentWidget() is screen._wizard_page


def test_save_and_generate_persists_report_and_shows_preview(screen, qapp):
    from services import report_store, strategy_store

    strategy_store.save_strategy(strategy_store.new_strategy("Stage 2 CWTO Buy"))

    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    screen._name_edit.setText("My Weekly LMV Report")
    screen._recipients_edit.setText("a@example.com;b@example.com")

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()
    assert len(saved) == 1
    assert saved[0]["name"] == "My Weekly LMV Report"
    assert saved[0]["subject_config"]["strategy_a_id"] is not None

    from services import report_recipients
    assert report_recipients.load_recipients(saved[0]["id"]) == ["a@example.com", "b@example.com"]

    assert screen._stack.currentWidget() is screen._preview_page
    assert "My Weekly LMV Report" in screen._last_rendered_html
    assert "Page 1 of" in screen._last_rendered_html


def test_save_and_generate_rejects_invalid_recipient(screen, monkeypatch):
    from services import report_store

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._name_edit.setText("Bad recipients")
    screen._recipients_edit.setText("not-an-email")

    screen._save_and_generate()

    assert report_store.load_all() == []


def test_build_placeholder_html_is_the_fallback_for_any_future_unbuilt_type():
    # All 3 current report types (LMV/EMV/Fuku Live) are wired to real data
    # now — _build_placeholder_html is exercised directly here as the
    # fallback _build_report_html still has ready for whatever report type
    # might be added next.
    from screens.reports import _build_placeholder_html

    html = _build_placeholder_html({"type": "some_future_type", "name": "Preview only"})
    assert "coming soon" in html.lower()


def test_generate_and_preview_renders_real_fuku_live_report_with_no_signal_gracefully(screen):
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_FUKU_LIVE, "Fuku preview")
    screen._generate_and_preview(report)

    assert screen._stack.currentWidget() is screen._preview_page
    assert "<!DOCTYPE html>" in screen._last_rendered_html
    assert "no signal found" in screen._last_rendered_html.lower()


def test_generate_and_preview_renders_real_emv_stock_report_with_no_data_gracefully(screen):
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_EMV, "EMV preview")
    screen._generate_and_preview(report)

    assert screen._stack.currentWidget() is screen._preview_page
    assert "<!DOCTYPE html>" in screen._last_rendered_html


def test_delete_report_removes_it_from_gallery(screen, monkeypatch):
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "To delete")
    report_store.save_report(report)
    screen.refresh_gallery()
    assert screen._saved_table.rowCount() == 1

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    screen._delete_report(report)

    assert report_store.load_all() == []
    assert screen._saved_table.rowCount() == 0


def test_download_pdf_writes_a_real_file(screen, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "Downloadable")
    screen._generate_and_preview(report)

    out_path = str(tmp_path / "downloadable.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out_path, "")))

    shown = {}
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **k: shown.setdefault("called", True)),
    )

    screen._download_pdf()

    deadline = time.time() + 15
    while "called" not in shown and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    import os
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0
    assert screen._download_btn.text() == "Download PDF"
    assert screen._download_btn.isEnabled()


def test_refresh_theme_rebuilds_pages_without_crashing(screen):
    screen.refresh_theme()
    assert screen._stack.currentWidget() is screen._gallery_page


# ── EMV wizard ────────────────────────────────────────────────────────────

def test_emv_wizard_defaults_to_stock_subtype(screen):
    from services import report_store

    screen._start_new_report(report_store.REPORT_TYPE_EMV)

    # isHidden() (the EXPLICIT hidden flag), not isVisible() — this widget
    # tree is never actually shown in a test, so isVisible() is always
    # False regardless of setVisible() calls (it also requires every
    # ancestor up to a shown top-level window).
    assert screen._emv_subtype_combo.currentData() == "stock"
    assert not screen._emv_stock_frame.isHidden()
    assert screen._emv_strategy_frame.isHidden()


def test_emv_wizard_stock_subtype_saves_and_generates(screen, qapp):
    from services import report_store

    _seed_bars("DIVISLAB", date(2026, 1, 1), 30)

    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._name_edit.setText("DIVISLAB Day Top")
    screen._emv_symbol_edit.setText("DIVISLAB")
    idx = screen._emv_field_combo.findData("DT")
    screen._emv_field_combo.setCurrentIndex(idx)
    screen._emv_periods_spin.setValue(10)

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()
    assert len(saved) == 1
    assert saved[0]["subject_config"]["subtype"] == "stock"
    assert saved[0]["subject_config"]["symbol"] == "DIVISLAB"
    assert screen._stack.currentWidget() is screen._preview_page
    assert "DIVISLAB" in screen._last_rendered_html


def test_emv_wizard_stock_subtype_requires_symbol(screen, monkeypatch):
    from services import report_store

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._name_edit.setText("No symbol")
    screen._emv_symbol_edit.setText("")

    screen._save_and_generate()

    assert report_store.load_all() == []


def test_emv_wizard_strategy_subtype_saves_and_generates(screen, qapp, monkeypatch):
    from services import inception_strategy_store, report_store

    _seed_bars("ABB_I", date(2026, 1, 1), 10, start_price=200)
    strategy = {
        "id": "strat-1", "name": "Above 150", "active": True, "category": "Daily",
        "columns": [], "row_filter": [
            {"type": "col", "value": "CLOSE"}, {"type": "op", "value": ">"}, {"type": "num", "value": "150"},
        ],
    }
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [strategy])

    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    idx = screen._emv_subtype_combo.findData("strategy")
    screen._emv_subtype_combo.setCurrentIndex(idx)
    screen._name_edit.setText("Above 150 stocks")

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()
    assert len(saved) == 1
    assert saved[0]["subject_config"]["subtype"] == "strategy"
    assert saved[0]["subject_config"]["strategy_id"] == "strat-1"
    assert screen._stack.currentWidget() is screen._preview_page
    assert "Above 150" in screen._last_rendered_html


def test_emv_wizard_strategy_subtype_requires_a_strategy(screen, monkeypatch):
    from services import inception_strategy_store, report_store

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [])
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    idx = screen._emv_subtype_combo.findData("strategy")
    screen._emv_subtype_combo.setCurrentIndex(idx)
    screen._name_edit.setText("No strategy")

    screen._save_and_generate()

    assert report_store.load_all() == []


# ── Fuku Live wizard ──────────────────────────────────────────────────────

def test_fuku_live_wizard_requires_an_alert_when_none_exist(screen, monkeypatch):
    from services import report_store

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._name_edit.setText("No alerts")

    screen._save_and_generate()

    assert report_store.load_all() == []


def test_fuku_live_wizard_saves_and_generates_for_an_open_signal(screen, qapp):
    from services import report_store
    from services.strategy_alerts import state_store

    state_store.set_open_signal("strat-1::INFY", {
        "state": "open", "strategy_id": "strat-1", "strategy_name": "PWHBUY",
        "symbol": "INFY", "sector": "IT", "direction": "BUY",
        "entry_time": "2026-03-01T09:31:00", "entry_price": 100.0,
        "metrics": {}, "risk_reward": None, "score": None,
        "running_high": 110.0, "running_low": 95.0,
        "repeat_armed": True, "last_repeat_at": None, "exit_price": None,
    }, force_flush=True)

    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._select_data(screen._fuku_scope_combo, "single")
    screen._name_edit.setText("INFY Live Report")

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()
    assert len(saved) == 1
    assert saved[0]["subject_config"] == {"strategy_id": "strat-1", "symbol": "INFY",
                                          "show_why": True,
                                          "indicator_ids": [], "indicator_days": 60}
    assert screen._stack.currentWidget() is screen._preview_page
    assert "INFY" in screen._last_rendered_html
    assert "Fuku Score" in screen._last_rendered_html


def test_open_fuku_live_for_signal_renders_from_the_given_signal(screen):
    signal = {
        "strategy_id": "no-local-copy", "strategy_name": "PWHBUY", "symbol": "INFY",
        "direction": "BUY", "entry_time": "2026-03-01T09:31:00", "entry_price": 100.0,
        "running_high": 110.0, "running_low": 95.0, "metrics": {},
    }
    screen.open_fuku_live_for_signal(signal)

    assert screen._stack.currentWidget() is screen._preview_page
    assert "Fuku Score" in screen._last_rendered_html
    assert "no signal found" not in screen._last_rendered_html


def test_emv_stock_report_plots_selected_indicators_and_saves_their_ids(screen, qapp):
    from PySide6.QtCore import Qt
    from services import indicator_library, report_store

    indicator_library.reload_cache()
    sma = indicator_library.new_instance("SMA", {"period": 5})
    rsi = indicator_library.new_instance("RSI", {"period": 5})
    indicator_library.save_instance(sma)
    indicator_library.save_instance(rsi)
    # The report window is anchored to today, so seed bars ending today.
    _seed_bars("DIVISLAB", date.today() - timedelta(days=70), 40)

    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._name_edit.setText("With indicators")
    screen._emv_symbol_edit.setText("DIVISLAB")
    screen._emv_periods_spin.setValue(10)
    for i in range(screen._emv_indicator_list.count()):
        screen._emv_indicator_list.item(i).setCheckState(Qt.CheckState.Checked)

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()[0]
    assert set(saved["subject_config"]["indicator_ids"]) == {sma["id"], rsi["id"]}
    assert "Price with SMA(5)" in screen._last_rendered_html
    assert "RSI(5) — Relative Strength Index" in screen._last_rendered_html
    indicator_library.reload_cache()


def test_edit_reopens_wizard_with_saved_settings_and_updates_in_place(screen, qapp):
    from services import report_recipients, report_store, strategy_store

    strategy_store.save_strategy(strategy_store.new_strategy("Alpha"))
    strategy_store.save_strategy(strategy_store.new_strategy("Beta"))
    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    screen._name_edit.setText("Original")
    screen._recipients_edit.setText("a@example.com")
    screen._investment_edit.setText("250000")
    screen._save_and_generate()
    qapp.processEvents()
    saved = report_store.load_all()[0]

    screen._edit_active_report()

    assert screen._stack.currentWidget() is screen._wizard_page
    assert screen._name_edit.text() == "Original"
    assert screen._recipients_edit.text() == "a@example.com"
    assert screen._investment_edit.text() == "250000"
    assert screen._strategy_a_combo.currentData() == saved["subject_config"]["strategy_a_id"]

    screen._name_edit.setText("Renamed")
    screen._save_and_generate()
    qapp.processEvents()

    after = report_store.load_all()
    assert len(after) == 1 and after[0]["id"] == saved["id"]
    assert after[0]["name"] == "Renamed"
    assert report_recipients.load_recipients(saved["id"]) == ["a@example.com"]


def test_clicking_an_indicator_row_toggles_it_and_is_saved(screen, qapp):
    from services import indicator_library, report_store

    inst = indicator_library.new_instance("SMA", {"period": 20})
    indicator_library.save_instance(inst)
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    item = screen._emv_indicator_list.item(0)

    screen._emv_indicator_list.itemClicked.emit(item)
    assert screen._selected_indicator_ids() == [inst["id"]]
    screen._emv_indicator_list.itemClicked.emit(item)
    assert screen._selected_indicator_ids() == []


def test_select_all_and_deselect_all_indicators(screen):
    from services import indicator_library, report_store

    for key in ("SMA", "EMA"):
        indicator_library.save_instance(indicator_library.new_instance(key, {}))
    ids = [i["id"] for i in indicator_library.load_instances()]
    assert len(ids) >= 2
    screen._start_new_report(report_store.REPORT_TYPE_EMV)

    screen._set_all_indicators(True)
    assert sorted(screen._selected_indicator_ids()) == sorted(ids)
    screen._set_all_indicators(False)
    assert screen._selected_indicator_ids() == []


def _seed_open(state_store, symbol, entry_time="2026-03-01T09:31:00", sid="strat-1", state="open"):
    state_store.set_open_signal(f"{sid}::{symbol}", {
        "state": state, "strategy_id": sid, "strategy_name": "PWHBUY",
        "symbol": symbol, "sector": "IT", "direction": "BUY",
        "entry_time": entry_time, "entry_price": 100.0, "last_price": 101.0,
        "metrics": {}, "risk_reward": None, "score": None,
        "running_high": 110.0, "running_low": 95.0,
    }, force_flush=True)


def test_fuku_strategy_scope_wizard_saves_options_and_starts_refresh_timer(screen, qapp):
    from services import report_store
    from services.strategy_alerts import state_store

    _seed_open(state_store, "INFY")
    _seed_open(state_store, "TCS")
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    assert screen._fuku_scope_combo.currentData() == "strategy"   # new default
    screen._fuku_inc_cancelled.setChecked(True)
    screen._fuku_refresh_spin.setValue(3)
    screen._name_edit.setText("Whole strategy")

    screen._save_and_generate()
    qapp.processEvents()

    cfg = report_store.load_all()[0]["subject_config"]
    assert cfg == {
        "scope": "strategy", "strategy_id": "strat-1", "include_stopped": False,
        "include_cancelled": True, "include_achieved": False, "refresh_minutes": 3,
        "show_why": True, "indicator_ids": [], "indicator_days": 60,
    }
    assert 'fk-sym">INFY<' in screen._last_rendered_html and 'fk-sym">TCS<' in screen._last_rendered_html
    assert screen._refresh_timer.isActive() and screen._refresh_timer.interval() == 3 * 60_000
    screen._leave_preview()
    assert not screen._refresh_timer.isActive()


def test_fuku_auto_refresh_adds_newly_matched_stock_and_flags_it(screen, qapp):
    from datetime import datetime
    from services import report_store
    from services.strategy_alerts import state_store

    _seed_open(state_store, "INFY")
    report = report_store.new_report(report_store.REPORT_TYPE_FUKU_LIVE, "Live")
    report["subject_config"] = {"scope": "strategy", "strategy_id": "strat-1", "refresh_minutes": 5}
    screen._generate_and_preview(report)
    assert 'fk-sym">TCS<' not in screen._last_rendered_html
    first_run = screen._last_generated_at

    _seed_open(state_store, "TCS", entry_time=datetime.now().isoformat())   # matched after first run
    screen._auto_refresh_tick()
    qapp.processEvents()

    assert 'fk-sym">TCS<' in screen._last_rendered_html
    assert "RECENTLY ADDED" in screen._last_rendered_html
    assert screen._last_generated_at > first_run


def test_fuku_auto_refresh_stops_once_preview_is_left(screen):
    from services import report_store
    report = report_store.new_report(report_store.REPORT_TYPE_FUKU_LIVE, "Live")
    report["subject_config"] = {"scope": "strategy", "strategy_id": "strat-1", "refresh_minutes": 5}
    screen._generate_and_preview(report)
    screen._stack.setCurrentWidget(screen._gallery_page)
    screen._auto_refresh_tick()
    assert not screen._refresh_timer.isActive()


# ── Background generation: the window must not hang while a report builds (issue #63) ──

def _wait_for(qapp, predicate, seconds=5):
    import time
    end = time.time() + seconds
    while not predicate() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    return predicate()


def test_generation_runs_off_the_gui_thread_and_shows_progress_then_result(screen, qapp, monkeypatch):
    import threading
    from screens import reports
    from services import report_store

    started, release, thread_names = threading.Event(), threading.Event(), []

    def slow_build(report, new_since=None, lmv_snapshot=None):
        thread_names.append(threading.current_thread().name)
        started.set()
        release.wait(5)
        return "<html><body>DONE REPORT</body></html>"

    monkeypatch.setattr(reports, "_build_report_html", slow_build)
    screen._async_generation = True
    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "Slow")

    screen._generate_and_preview(report)          # returns immediately — GUI thread not blocked
    assert started.wait(2)
    assert screen._stack.currentWidget() is screen._preview_page
    assert "Generating" in screen._preview_title.text()
    assert not screen._download_btn.isEnabled() and not screen._email_btn.isEnabled()
    assert screen._last_rendered_html is None or "DONE REPORT" not in screen._last_rendered_html

    release.set()
    assert _wait_for(qapp, lambda: screen._last_rendered_html and "DONE REPORT" in screen._last_rendered_html)
    assert thread_names == ["report-generation"]
    assert screen._download_btn.isEnabled() and screen._email_btn.isEnabled()
    assert screen._preview_title.text() == "Slow"


def test_failed_background_generation_warns_and_returns_to_gallery(screen, qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from screens import reports
    from services import report_store

    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warnings.append(a[2])))

    def boom(report, new_since=None, lmv_snapshot=None):
        raise RuntimeError("snapshot exploded")

    monkeypatch.setattr(reports, "_build_report_html", boom)
    screen._async_generation = True
    screen._generate_and_preview(report_store.new_report(report_store.REPORT_TYPE_LMV, "Bad"))

    assert _wait_for(qapp, lambda: bool(warnings))
    assert "snapshot exploded" in warnings[0]
    assert screen._stack.currentWidget() is screen._gallery_page
    assert screen._download_btn.isEnabled()


def test_stale_background_result_is_ignored_after_leaving_preview(screen, qapp, monkeypatch):
    import threading
    from screens import reports
    from services import report_store

    release = threading.Event()

    def slow_build(report, new_since=None, lmv_snapshot=None):
        release.wait(5)
        return "<html>STALE</html>"

    monkeypatch.setattr(reports, "_build_report_html", slow_build)
    screen._async_generation = True
    screen._generate_and_preview(report_store.new_report(report_store.REPORT_TYPE_LMV, "Abandoned"))
    screen._leave_preview()                       # user goes back before it finishes
    release.set()
    for _ in range(40):
        qapp.processEvents()
    assert screen._last_rendered_html is None or "STALE" not in screen._last_rendered_html
    assert screen._stack.currentWidget() is screen._gallery_page


# ── Light / dark report theme (issue #59) ────────────────────────────────

def test_wizard_saves_report_theme_and_dark_is_applied_to_the_generated_html(screen, qapp):
    from services import report_store
    from services.strategy_alerts import state_store

    _seed_open(state_store, "INFY")
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._name_edit.setText("Dark one")
    assert screen._report_theme_combo.currentData() == "light"             # default
    screen._select_data(screen._report_theme_combo, "dark")

    screen._save_and_generate()
    qapp.processEvents()

    assert report_store.load_all()[0]["visuals"]["theme"] == "dark"
    assert "--text-primary: #E2E8F0" in screen._last_rendered_html


def test_light_theme_report_has_no_dark_overrides_and_edit_prefills_theme(screen, qapp):
    from services import report_store
    from services.strategy_alerts import state_store

    _seed_open(state_store, "INFY")
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._name_edit.setText("Light one")
    screen._save_and_generate()
    qapp.processEvents()
    assert "--text-primary: #E2E8F0" not in screen._last_rendered_html

    saved = report_store.load_all()[0]
    saved["visuals"]["theme"] = "dark"
    screen._edit_report(saved)
    assert screen._report_theme_combo.currentData() == "dark"              # prefilled when editing


# ── EMV stock report: stock dropdown + several columns with colours (issue #61) ──

def test_emv_stock_wizard_offers_a_stock_dropdown_with_type_ahead_and_free_text(screen):
    from services import report_store
    _seed_bars("DIVISLAB_I", date(2026, 1, 1), 5)
    _seed_bars("ABB_I", date(2026, 1, 1), 5)
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    combo = screen._emv_symbol_edit
    items = [combo.itemText(i) for i in range(combo.count())]
    assert "DIVISLAB" in items and "ABB" in items and items == sorted(items)
    combo.setText("whatever")                       # still free text, same API as before
    assert combo.text() == "whatever"


def test_emv_stock_wizard_adds_recolours_removes_extra_columns_and_saves_them(screen, qapp):
    from services import report_store
    _seed_bars("DIVISLAB_I", date.today() - timedelta(days=70), 45)     # the report window is relative to today
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._name_edit.setText("Multi")
    screen._emv_symbol_edit.setText("DIVISLAB")
    screen._select_data(screen._emv_field_combo, "DT")

    for code in ("WT", "MT", "DT", "WT"):           # DT == primary and the second WT are ignored
        screen._select_data(screen._emv_extra_combo, code)
        screen._add_extra_field()
    assert [e["field"] for e in screen._emv_extra_fields] == ["WT", "MT"]

    screen._emv_extra_list.setCurrentRow(1)
    screen._emv_extra_fields[1]["color"] = "#112233"      # (what the colour dialog does on accept)
    screen._set_primary_field_color("#ff0000")
    screen._emv_extra_list.setCurrentRow(0)
    screen._remove_extra_field()
    assert [e["field"] for e in screen._emv_extra_fields] == ["MT"]

    screen._select_data(screen._emv_extra_combo, "WT")
    screen._add_extra_field()
    screen._save_and_generate()
    qapp.processEvents()

    cfg = report_store.load_all()[0]["subject_config"]
    assert cfg["field_color"] == "#ff0000"
    assert [e["field"] for e in cfg["extra_fields"]] == ["MT", "WT"]
    assert cfg["extra_fields"][0]["color"] == "#112233"
    assert "DT, MT, WT vs Close" in screen._last_rendered_html and 'stroke="#ff0000"' in screen._last_rendered_html


def test_emv_stock_wizard_edit_prefills_extra_columns_and_colour(screen):
    from services import report_store
    report = report_store.new_report(report_store.REPORT_TYPE_EMV, "Saved")
    report["subject_config"] = {"subtype": "stock", "symbol": "ABB", "field": "DT", "n_periods": 20,
                                "field_color": "#abcdef", "extra_fields": [{"field": "WT", "color": "#654321"}]}
    screen._edit_report(report)
    assert screen._emv_field_color == "#abcdef"
    assert screen._emv_extra_fields == [{"field": "WT", "color": "#654321"}]
    assert screen._emv_extra_list.count() == 1


# ── EMV Trend-category report: wizard + category manager (issue #64) ─────

def _trend_env(monkeypatch):
    from services import config_store, inception_strategy_store
    strategies = [
        {"id": "s100", "name": "Above 100", "active": True, "category": "Daily", "columns": [],
         "row_filter": [{"type": "col", "value": "CLOSE"}, {"type": "op", "value": ">"}, {"type": "num", "value": "100"}]},
        {"id": "s999", "name": "Above 999", "active": True, "category": "Weekly", "columns": [],
         "row_filter": [{"type": "col", "value": "CLOSE"}, {"type": "op", "value": ">"}, {"type": "num", "value": "999"}]},
    ]
    saved = {}
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: strategies)
    monkeypatch.setattr(config_store, "load_json", lambda key, default=None: saved.get(key, default))
    monkeypatch.setattr(config_store, "save_json", lambda key, value: saved.__setitem__(key, value))
    return strategies, saved


def test_category_manager_edits_save_rules_colour_and_new_categories(qapp, monkeypatch):
    from screens.trend_category_dialog import TrendCategoryDialog
    from services import trend_categories
    from PySide6.QtCore import Qt

    _, saved = _trend_env(monkeypatch)
    dlg = TrendCategoryDialog()
    assert dlg._category_list.count() == 9                       # spec's default set
    dlg._category_list.setCurrentRow(0)                          # Bullish
    dlg._name_edit.setText("Strong Bullish")
    dlg._desc_edit.setText("monthly breakout")
    dlg._color = "#112233"
    dlg._active_check.setChecked(True)
    monthly = dlg._tf_lists["Monthly"]
    monthly.item(0).setCheckState(Qt.CheckState.Checked)         # Above 100
    monthly.item(1).setCheckState(Qt.CheckState.Checked)         # Above 999

    dlg._add_category()                                          # a 10th, custom category
    assert dlg._category_list.count() == 10 and dlg._name_edit.text() == "New category"
    dlg._name_edit.setText("Breakout")
    dlg._move_category(-1)                                       # becomes 9th
    dlg._save()

    cats = trend_categories.load_all()
    assert cats[0]["name"] == "Strong Bullish" and cats[0]["color"] == "#112233"
    assert cats[0]["rules"]["Monthly"] == ["s100", "s999"] and cats[0]["rules"]["Daily"] == []
    assert [c["name"] for c in cats][-2:] == ["Breakout", "Sideways"]


def test_category_manager_rejects_duplicate_names(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from screens.trend_category_dialog import TrendCategoryDialog
    from services import trend_categories

    _, saved = _trend_env(monkeypatch)
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    dlg = TrendCategoryDialog()
    dlg._category_list.setCurrentRow(1)
    dlg._name_edit.setText("bullish")                            # clashes with the first (case-insensitive)
    dlg._save()
    assert warned and "different name" in warned[0]
    assert trend_categories._KEY not in saved                    # nothing was saved


def test_emv_trend_wizard_saves_config_generates_report_and_prefills_on_edit(screen, qapp, monkeypatch):
    from services import report_store, trend_categories
    strategies, saved = _trend_env(monkeypatch)
    _seed_bars("ABB_I", date.today() - timedelta(days=70), 45, start_price=200)
    cats = trend_categories.load_all()
    cats[0]["rules"]["Daily"] = ["s100"]
    trend_categories.save_all(cats)

    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._select_data(screen._emv_subtype_combo, "trend")
    assert not screen._emv_trend_frame.isHidden() and screen._emv_stock_frame.isHidden() and screen._emv_strategy_frame.isHidden()
    assert screen._emv_trend_category.itemText(0) == "All categories"
    assert [screen._emv_trend_timeframe.itemText(i) for i in range(4)] == ["Daily", "Weekly", "Monthly", "Quarterly"]
    screen._select_data(screen._emv_trend_category, "bullish")
    screen._select_data(screen._emv_trend_timeframe, "Daily")
    screen._emv_trend_multi.setChecked(True)
    screen._name_edit.setText("Trend")
    screen._save_and_generate()
    qapp.processEvents()

    report = report_store.load_all()[0]
    assert report["subject_config"]["subtype"] == "trend"
    assert report["subject_config"]["category_id"] == "bullish" and report["subject_config"]["multi_timeframe"] is True
    html = screen._last_rendered_html
    assert "Trend — Bullish — Daily" in html and "ABB" in html
    assert "<th>Weekly</th>" in html and "<th>Days True</th>" in html

    screen._edit_report(report)
    assert screen._emv_subtype_combo.currentData() == "trend"
    assert screen._emv_trend_category.currentData() == "bullish" and screen._emv_trend_multi.isChecked()


def test_category_manager_delete_and_reorder_never_overwrite_other_categories(qapp, monkeypatch):
    from screens.trend_category_dialog import TrendCategoryDialog
    from services import trend_categories

    _trend_env(monkeypatch)
    dlg = TrendCategoryDialog()
    before = [c["name"] for c in dlg._cats]
    dlg._category_list.setCurrentRow(2)
    dlg._delete_category()                                       # remove "Bearish"
    assert [c["name"] for c in dlg._cats] == before[:2] + before[3:]
    dlg._category_list.setCurrentRow(0)
    dlg._move_category(1)                                        # swap first two
    assert [c["name"] for c in dlg._cats][:2] == [before[1], before[0]]
    dlg._save()
    assert [c["name"] for c in trend_categories.load_all()] == [before[1], before[0]] + before[3:]


# ── Sector Report wizard (issue #66) ─────────────────────────────────────

def _lmv_rows():
    headers = ["Sector", "Scrip Name", "% Change", "Current", "WEEK % CHANGE", "MONTH % CHANGE", "MT", "Close"]
    data = [["IT", "TCS", "1.0", "100", "2.0", "3.0", "98", "100"], ["IT", "INFY", "-0.5", "90", "1.0", "1.5", "91", "90"],
            ["BANK", "HDFC", "0.2", "50", "-1.0", "-2.0", "50", "50"]]
    return headers, data


def test_sector_report_gallery_entry_and_live_wizard_generates_from_the_lmv_snapshot(screen, qapp, monkeypatch):
    from services import report_store

    assert report_store.REPORT_TYPE_SECTOR in report_store.REPORT_TYPES
    monkeypatch.setattr(screen._controller, "get_lmv_snapshot", lambda: _lmv_rows(), raising=False)
    screen._start_new_report(report_store.REPORT_TYPE_SECTOR)
    screen._select_data(screen._sector_mode_combo, "live")
    assert screen._sector_live_frame.isHidden() is False and screen._sector_eod_frame.isHidden() is True
    screen._sector_refresh_spin.setValue(2)
    screen._select_data(screen._sector_timeframe_combo, "Weekly")
    screen._select_data(screen._sector_metric_combo, "pair")
    screen._sector_pair_from.setCurrentText("MT")
    screen._sector_pair_to.setCurrentText("Close")
    screen._name_edit.setText("Live sectors")
    screen._save_and_generate()
    qapp.processEvents()

    cfg = report_store.load_all()[0]["subject_config"]
    assert cfg["mode"] == "live" and cfg["refresh_minutes"] == 2 and cfg["primary_timeframe"] == "Weekly"
    assert cfg["metric"] == {"kind": "pair", "from": "MT", "to": "Close"} and cfg["sector"] is None
    html = screen._last_rendered_html
    assert "Fuku Lens Live Sector Report" in html and "MT vs Close % Change" in html
    assert "IT" in html and "BANK" in html
    assert "+0.50%" in html                                                 # IT daily = 1.0 + (-0.5)
    assert "+3.00%" in html                                                 # IT weekly = 2.0 + 1.0 (a SUM, not an average)
    assert html.index("Heatmap — Weekly") < html.index("Heatmap — Daily")   # chosen default timeframe first
    assert screen._refresh_timer.isActive() and screen._refresh_timer.interval() == 2 * 60_000


def test_live_sector_report_refreshes_from_a_fresh_snapshot_each_tick(screen, qapp, monkeypatch):
    from services import report_store

    state = {"rows": _lmv_rows()}
    monkeypatch.setattr(screen._controller, "get_lmv_snapshot", lambda: state["rows"], raising=False)
    report = report_store.new_report(report_store.REPORT_TYPE_SECTOR, "Live")
    report["subject_config"] = {"mode": "live", "refresh_minutes": 5}
    screen._generate_and_preview(report)
    assert "+3.00%" in screen._last_rendered_html and "Auto-refresh every 5 min" in screen._last_rendered_html

    headers, data = _lmv_rows()
    data[0][4] = "10.0"                                                     # TCS weekly jumps 2.0 -> 10.0
    state["rows"] = (headers, data)
    screen._auto_refresh_tick()
    qapp.processEvents()
    assert "+11.00%" in screen._last_rendered_html                          # IT weekly is now 10.0 + 1.0
    screen._leave_preview()
    assert not screen._refresh_timer.isActive()


def test_live_sector_report_without_the_live_view_says_so_instead_of_failing(screen):
    from services import report_store
    screen._controller.get_lmv_snapshot = lambda: None
    report = report_store.new_report(report_store.REPORT_TYPE_SECTOR, "Live")
    report["subject_config"] = {"mode": "live"}
    screen._generate_and_preview(report)
    assert "open the Live Master View first" in screen._last_rendered_html


def test_eod_sector_wizard_saves_options_generates_and_prefills(screen, qapp):
    from services import report_store
    _seed_bars("ABB_I", date.today() - timedelta(days=70), 45, start_price=200)
    screen._start_new_report(report_store.REPORT_TYPE_SECTOR)
    assert screen._sector_mode_combo.currentData() == "eod" and screen._sector_eod_frame.isHidden() is False
    assert screen._sector_view_combo.itemText(0) == "All sectors"
    screen._select_data(screen._sector_metric_combo, "pair")
    screen._sector_pair_from.setCurrentText("OPEN")
    screen._sector_pair_to.setCurrentText("CLOSE")
    screen._sector_step_spin.setValue(1.5)
    screen._name_edit.setText("EOD sectors")
    screen._save_and_generate()
    qapp.processEvents()

    report = report_store.load_all()[0]
    assert report["subject_config"]["mode"] == "eod" and report["subject_config"]["heat_step"] == 1.5
    assert "Fuku Lens EOD Sector Report" in screen._last_rendered_html and "OPEN vs CLOSE % Change" in screen._last_rendered_html
    assert not screen._refresh_timer.isActive()                             # EOD reports never auto-refresh

    screen._edit_report(report)
    assert screen._sector_metric_combo.currentData() == "pair" and screen._sector_pair_from.currentText() == "OPEN"
    assert screen._sector_step_spin.value() == 1.5


def test_sector_wizard_rejects_identical_pair_fields(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from services import report_store
    warned = []
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: warned.append(a[2])))
    screen._start_new_report(report_store.REPORT_TYPE_SECTOR)
    screen._select_data(screen._sector_metric_combo, "pair")
    screen._sector_pair_from.setCurrentText("CLOSE")
    screen._sector_pair_to.setCurrentText("close")
    screen._name_edit.setText("x")
    screen._save_and_generate()
    assert warned and "two different fields" in warned[0] and report_store.load_all() == []


def test_lmv_wizard_date_pickers_only_apply_to_custom_range(screen):
    """#78/#79: From/To were editable but silently ignored for Daily/Weekly/...
    (a 06-Oct..15-Oct range reported just 'today'). They now show the range a
    preset really uses and unlock only for Custom Range."""
    from services import report_metrics, report_store

    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    screen._select_data(screen._timeframe_combo, report_metrics.TIMEFRAME_WEEKLY)
    lo, hi = report_metrics.resolve_preset_range(report_metrics.TIMEFRAME_WEEKLY)
    assert not screen._from_date.isEnabled() and not screen._to_date.isEnabled()
    assert screen._from_date.date().toPython() == lo and screen._to_date.date().toPython() == hi

    screen._select_data(screen._timeframe_combo, report_metrics.TIMEFRAME_CUSTOM)
    assert screen._from_date.isEnabled() and screen._to_date.isEnabled()


def test_wizard_card_is_scrollable_so_fields_keep_their_height(screen):
    from PySide6.QtWidgets import QScrollArea
    from services import report_store

    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    scrolls = screen._wizard_page.findChildren(QScrollArea)
    assert any(s.widget() is not None and s.widget().objectName() == "brokerPanel" and s.widgetResizable()
               for s in scrolls)


def test_fuku_wizard_strategy_dropdown_lists_every_strategy_and_is_searchable(screen):
    """#72: only strategies with a local alert were offered (often none), so
    nothing could be selected."""
    from services import report_store, strategy_store

    strategy_store.save_strategy(strategy_store.new_strategy("Alpha Strategy"))
    strategy_store.save_strategy(strategy_store.new_strategy("Beta Strategy"))
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    names = [screen._fuku_strategy_combo.itemText(i) for i in range(screen._fuku_strategy_combo.count())]
    assert "Alpha Strategy" in names and "Beta Strategy" in names
    assert screen._fuku_strategy_combo.isEditable()
    assert screen._fuku_strategy_combo.completer() is not None
    assert screen._fuku_signal_combo.isEditable()


def test_fuku_wizard_show_why_unchecked_hides_section_and_round_trips(screen, qapp):
    """#89: the checkbox is saved with the report and removes the section."""
    from services import report_store
    from services.strategy_alerts import state_store
    from services.strategy_alerts import config_store as alerts_config_store

    alerts_config_store.save_config("strat-1", {
        "enabled": True, "direction": "BUY",
        "trigger_condition": [{"type": "col", "value": "Close"}, {"type": "op", "value": ">"},
                              {"type": "num", "value": "1"}],
    })
    _seed_open(state_store, "INFY")
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    assert screen._fuku_show_why.isChecked()
    screen._fuku_show_why.setChecked(False)
    screen._name_edit.setText("No why")
    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()[0]
    assert saved["subject_config"]["show_why"] is False
    assert "Why this signal triggered" not in screen._last_rendered_html
    assert 'fk-sym">INFY<' in screen._last_rendered_html

    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._prefill_fields(saved)
    assert screen._fuku_show_why.isChecked() is False


def test_emv_wizard_compare_close_checkbox_is_saved_and_applied(screen, qapp):
    """#84: unticking "Compare against Close" drops Close from the generated report."""
    from services import report_store

    _seed_bars("DIVISLAB", date(2026, 1, 1), 30)
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    assert screen._emv_compare_close.isChecked()                       # default: unchanged
    screen._name_edit.setText("No close")
    screen._emv_symbol_edit.setText("DIVISLAB")
    screen._emv_field_combo.setCurrentIndex(screen._emv_field_combo.findData("DT"))
    screen._emv_periods_spin.setValue(10)
    screen._emv_compare_close.setChecked(False)

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()[0]
    assert saved["subject_config"]["compare_close"] is False
    assert "Close vs" not in screen._last_rendered_html
    assert "Current Close" not in screen._last_rendered_html

    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._prefill_fields(saved)
    assert screen._emv_compare_close.isChecked() is False
