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
    return ReportsScreen(AppController(qapp))


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
    assert "Page 1 of 2" in screen._last_rendered_html


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
    screen._name_edit.setText("INFY Live Report")

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()
    assert len(saved) == 1
    assert saved[0]["subject_config"] == {"strategy_id": "strat-1", "symbol": "INFY"}
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
