import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def sidebar(qapp):
    from theme import ThemeManager
    from components.sidebar import Sidebar
    tm = ThemeManager(qapp)
    return Sidebar(tm)

def test_sidebar_fixed_width(sidebar):
    assert sidebar.minimumWidth() == 180
    assert sidebar.maximumWidth() == 180

def test_set_active_does_not_raise(sidebar):
    sidebar.set_active("dashboard")
    sidebar.set_active("profile")

def test_navigate_signal_exists(sidebar):
    from PySide6.QtCore import Signal
    assert hasattr(sidebar, "navigate")
