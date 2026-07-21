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


def test_check_for_update_requested_signal_fires(topbar):
    fired = []
    topbar.check_for_update_requested.connect(lambda: fired.append(1))
    topbar.check_for_update_requested.emit()
    assert fired == [1]


def test_about_shows_version_without_crashing(topbar, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from version import APP_VERSION
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.text()) or QMessageBox.StandardButton.Ok)
    topbar._show_about()
    assert shown and APP_VERSION in shown[0]
