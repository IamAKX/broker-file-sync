import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.config_editor import ConfigEditorScreen
    return ConfigEditorScreen(AppController(qapp))


def test_config_editor_creates(screen):
    assert screen is not None


def test_has_tab_widget(screen):
    from PySide6.QtWidgets import QTabWidget
    tabs = screen.findChildren(QTabWidget)
    assert len(tabs) == 1


def test_has_two_tabs(screen):
    from PySide6.QtWidgets import QTabWidget
    tab = screen.findChildren(QTabWidget)[0]
    assert tab.count() == 2


def test_has_save_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Save" in t for t in btns)
