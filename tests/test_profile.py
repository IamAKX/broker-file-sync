import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.profile import ProfileScreen
    return ProfileScreen(AppController(qapp))

def test_profile_creates(screen):
    assert screen is not None

def test_has_logout_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Logout" in t or "logout" in t.lower() for t in btns)

def test_has_theme_checkbox(screen):
    from PySide6.QtWidgets import QCheckBox
    checks = screen.findChildren(QCheckBox)
    assert len(checks) >= 1

def test_has_change_password_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Password" in t for t in btns)
