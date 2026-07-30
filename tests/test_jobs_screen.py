import sys
from datetime import date, time as dtime

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    # tests/conftest.py's autouse _isolate_disk_stores fixture redirects
    # config_store (and so trigger_config) to a per-test tmp path.
    from app import AppController
    from screens.jobs import JobsScreen
    return JobsScreen(AppController(qapp))


def test_jobs_screen_creates(screen):
    assert screen is not None


def test_data_menu_has_high_low(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    from PySide6.QtWidgets import QPushButton
    tm = ThemeManager(qapp)
    topbar = TopBar(tm)
    found = False
    for btn in topbar.findChildren(QPushButton):
        menu = btn.menu()
        if menu is not None:
            for action in menu.actions():
                if action.text() == "High/Low":
                    found = True
    assert found


# ── Opening Range Capture tab ────────────────────────────────────────────────

def test_default_capture_time_is_0930(screen):
    assert screen._cfg().time == dtime(9, 30)
    assert screen._time_lbl.text() == "9:30 AM"


def test_default_window_label_is_15_minutes(screen):
    assert "15 minute" in screen._window_lbl.text()


def test_default_last_run_label_is_never(screen):
    assert "never" in screen._last_run_lbl.text().lower()


def test_toggling_enabled_persists(screen):
    from services import trigger_config
    screen._on_enabled_toggled(False)
    configs = trigger_config.load_trigger_configs()
    cfg = next(c for c in configs if c.id == "opening_range_capture")
    assert cfg.system_enabled is False


def test_edit_time_updates_label_and_window_and_persists(qapp, screen, monkeypatch):
    from PySide6.QtWidgets import QDialog
    from services import trigger_config

    monkeypatch.setattr(
        "screens.jobs._TriggerTimeDialog.exec",
        lambda self: QDialog.DialogCode.Accepted,
    )
    monkeypatch.setattr(
        "screens.jobs._TriggerTimeDialog.result_time",
        lambda self: dtime(10, 0),
    )

    screen._on_edit_time()

    assert screen._cfg().time == dtime(10, 0)
    assert screen._time_lbl.text() == "10:00 AM"
    assert "45 minute" in screen._window_lbl.text()
    configs = trigger_config.load_trigger_configs()
    cfg = next(c for c in configs if c.id == "opening_range_capture")
    assert cfg.time == dtime(10, 0)


def test_edit_time_cancelled_leaves_time_unchanged(qapp, screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    monkeypatch.setattr(
        "screens.jobs._TriggerTimeDialog.exec",
        lambda self: QDialog.DialogCode.Rejected,
    )

    screen._on_edit_time()

    assert screen._cfg().time == dtime(9, 30)
    assert screen._time_lbl.text() == "9:30 AM"


def test_run_now_calls_job_with_controller_and_notifier(screen, monkeypatch):
    from services import scheduled_jobs

    calls = []
    monkeypatch.setattr(
        scheduled_jobs, "run_opening_range_capture",
        lambda controller, notifier: calls.append((controller, notifier)),
    )
    # A real NotificationService needs a real tray icon — a plain stand-in
    # is enough since run_opening_range_capture is mocked above and never
    # actually calls .notify() on it.
    fake_notifier = object()
    screen._controller._notifier = fake_notifier

    screen._on_run_now()

    assert calls == [(screen._controller, fake_notifier)]
    assert screen._run_now_btn.isEnabled()
    assert screen._run_now_btn.text() == "Run Now"


def test_run_now_without_notifier_shows_message_and_skips_job(screen, monkeypatch):
    from services import scheduled_jobs
    from PySide6.QtWidgets import QMessageBox

    calls = []
    monkeypatch.setattr(
        scheduled_jobs, "run_opening_range_capture",
        lambda controller, notifier: calls.append(1),
    )
    shown = {}
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: shown.setdefault("shown", True),
    )
    screen._controller._notifier = None

    screen._on_run_now()

    assert shown.get("shown") is True
    assert calls == []


# ── Browse by Date tab ───────────────────────────────────────────────────────

def test_view_button_enabled_only_on_available_day(screen):
    screen._available_days = {1, 2, 3}
    screen._selected_browse_date = date(2026, 7, 2)
    screen._update_browse_buttons_enabled()
    assert screen._view_btn.isEnabled()

    screen._selected_browse_date = date(2026, 7, 25)
    screen._update_browse_buttons_enabled()
    assert not screen._view_btn.isEnabled()


def test_delete_button_enabled_only_on_available_day(screen):
    screen._available_days = {1, 2, 3}
    screen._selected_browse_date = date(2026, 7, 2)
    screen._update_browse_buttons_enabled()
    assert screen._delete_day_btn.isEnabled()

    screen._selected_browse_date = date(2026, 7, 25)
    screen._update_browse_buttons_enabled()
    assert not screen._delete_day_btn.isEnabled()


def test_view_clicked_populates_viewer_from_snapshot(screen, monkeypatch):
    from api import opening_range_api

    monkeypatch.setattr(
        opening_range_api, "get_snapshot",
        lambda d: {
            "trade_date": d.isoformat(),
            "stocks": [
                {"symbol": "INFY", "display_name": "Infosys", "high": 1810.5,
                 "low": 1795.0, "window_minutes": 15},
            ],
        },
    )
    screen._selected_browse_date = date(2026, 7, 20)

    screen._on_view_clicked()

    assert len(screen._viewers) == 1
    viewer = screen._viewers[0]
    assert viewer._headers == ["Symbol", "Display Name", "High", "Low", "Window (min)"]
    viewer.close()


def test_view_clicked_shows_status_when_no_data(screen, monkeypatch):
    from api import opening_range_api

    monkeypatch.setattr(opening_range_api, "get_snapshot", lambda d: {"stocks": []})
    screen._selected_browse_date = date(2026, 7, 20)

    screen._on_view_clicked()

    assert screen._viewers == []
    assert "No opening-range data" in screen._browse_status_lbl.text()


def test_delete_day_confirmed_calls_api_and_refreshes(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from api import opening_range_api

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    calls = []
    monkeypatch.setattr(
        opening_range_api, "delete_day",
        lambda d: calls.append(d) or {"trade_date": d.isoformat(), "values_deleted": 7},
    )
    monkeypatch.setattr(opening_range_api, "get_availability", lambda date_from, date_to: {"dates": []})

    screen._selected_browse_date = date(2026, 7, 20)
    screen._on_delete_day_clicked()

    assert calls == [date(2026, 7, 20)]
    assert "Deleted 7 value(s)" in screen._browse_status_lbl.text()


def test_delete_day_cancelled_does_not_call_api(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from api import opening_range_api

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)
    calls = []
    monkeypatch.setattr(opening_range_api, "delete_day", lambda d: calls.append(d))

    screen._selected_browse_date = date(2026, 7, 20)
    screen._on_delete_day_clicked()

    assert calls == []


def test_delete_day_closes_matching_open_viewer(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from api import opening_range_api
    from screens.historic_viewer import HistoricDataViewer

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        opening_range_api, "delete_day",
        lambda d: {"trade_date": d.isoformat(), "values_deleted": 1},
    )
    monkeypatch.setattr(opening_range_api, "get_availability", lambda date_from, date_to: {"dates": []})

    screen._selected_browse_date = date(2026, 7, 20)
    viewer = HistoricDataViewer(["Symbol"], [["AAA"]], "20-Jul-2026", title="Opening Range — 20-Jul-2026")
    viewer.show()
    screen._viewers.append(viewer)

    screen._on_delete_day_clicked()

    assert not viewer.isVisible()
