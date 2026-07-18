import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)

def test_main_window_creates(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    assert w is not None

def test_navigate_does_not_raise(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    for name in ["dashboard", "data_import", "config_editor", "notifications", "profile", "formula_builder"]:
        w.navigate(name)

def test_theme_toggle_refreshes_formula_builder(controller):
    # Regression: formula_builder must be wired into _on_theme_toggled like
    # every other inline-styled screen, or it shows stale colors after a
    # theme switch since its styles are baked into widgets at build time.
    from app_window import MainWindow
    from unittest.mock import MagicMock
    w = MainWindow(controller)
    fake = MagicMock()
    w._screens["formula_builder"] = fake
    w._on_theme_toggled()
    fake.refresh_theme.assert_called_once()


def test_close_event_closes_child_windows(controller):
    from app_window import MainWindow
    from PySide6.QtGui import QCloseEvent
    from unittest.mock import MagicMock

    w = MainWindow(controller)

    live_viewer = MagicMock()
    w._screens["data_import"]._live_viewer = live_viewer

    historic_viewer_1 = MagicMock()
    historic_viewer_2 = MagicMock()
    w._screens["historic_upload"]._viewers = [historic_viewer_1, historic_viewer_2]

    w.closeEvent(QCloseEvent())

    live_viewer.close.assert_called_once()
    historic_viewer_1.close.assert_called_once()
    historic_viewer_2.close.assert_called_once()
