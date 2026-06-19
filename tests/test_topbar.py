import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def topbar(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    tm = ThemeManager(qapp)
    return TopBar(tm)

def test_topbar_fixed_height(topbar):
    assert topbar.minimumHeight() == 40
    assert topbar.maximumHeight() == 40

def test_theme_toggled_signal_exists(topbar):
    assert hasattr(topbar, "theme_toggled")
