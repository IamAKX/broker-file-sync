"""Tests for the Market Holidays CRUD screen."""
import sys
import os
from datetime import date
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def _make_screen(qapp, monkeypatch, rows=None):
    from app import AppController
    from api import holidays_api
    from screens.holidays import HolidaysScreen
    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: rows or [])
    return HolidaysScreen(AppController(qapp))


def test_holidays_screen_creates(qapp, monkeypatch):
    screen = _make_screen(qapp, monkeypatch)
    assert screen is not None


def test_load_holidays_populates_table(qapp, monkeypatch):
    rows = [{"id": 1, "holiday_date": "2026-01-26", "name": "Republic Day"}]
    screen = _make_screen(qapp, monkeypatch, rows)
    screen._load_holidays()
    assert screen._table.rowCount() == 1


def test_deferred_initial_load_never_pops_a_blocking_popup_on_error(qapp, monkeypatch):
    # Regression: the initial fetch is scheduled via QTimer.singleShot(0, ...)
    # during construction, so it can fire well after the screen that
    # triggered it is gone (e.g. from a theme-toggle cascade touching every
    # screen, not just the visible one). If a network failure there popped a
    # blocking QMessageBox, an automated/headless run has no user to click
    # it, and the whole test process hangs forever. Construction and
    # refresh_theme() must both fail quietly instead.
    from app import AppController
    from api import holidays_api
    from api.exceptions import NetworkError
    from screens.holidays import HolidaysScreen
    from unittest.mock import MagicMock
    import screens.holidays as holidays_screen_module

    monkeypatch.setattr(
        holidays_api, "list_holidays",
        lambda year: (_ for _ in ()).throw(NetworkError("unreachable")),
    )
    popup = MagicMock()
    monkeypatch.setattr(holidays_screen_module, "show_api_error", popup)

    screen = HolidaysScreen(AppController(qapp))
    screen._load_holidays(show_popup_on_error=False)
    screen.refresh_theme()

    popup.assert_not_called()
    assert "connection" in screen._status_lbl.text().lower()


def test_year_change_still_shows_popup_on_error(qapp, monkeypatch):
    # User-initiated (screen is visible, they just changed the year) — a
    # blocking popup here is fine, unlike the deferred/theme-cascade paths.
    from app import AppController
    from api import holidays_api
    from api.exceptions import NetworkError
    from screens.holidays import HolidaysScreen
    from unittest.mock import MagicMock
    import screens.holidays as holidays_screen_module

    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: [])
    screen = HolidaysScreen(AppController(qapp))

    monkeypatch.setattr(
        holidays_api, "list_holidays",
        lambda year: (_ for _ in ()).throw(NetworkError("unreachable")),
    )
    popup = MagicMock()
    monkeypatch.setattr(holidays_screen_module, "show_api_error", popup)
    screen._year_spin.setValue(screen._year_spin.value() + 1)

    popup.assert_called_once()
