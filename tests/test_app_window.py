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
    for name in ["dashboard", "data_import", "config_editor", "notifications", "profile"]:
        w.navigate(name)
