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
