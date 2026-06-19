import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.notifications import NotificationsScreen
    return NotificationsScreen(AppController(qapp))

def test_notifications_creates(screen):
    assert screen is not None

def test_has_mark_all_read_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("read" in t.lower() or "Read" in t for t in btns)
