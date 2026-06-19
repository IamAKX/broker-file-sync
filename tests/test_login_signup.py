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

def test_login_screen_creates(controller):
    from screens.login import LoginScreen
    s = LoginScreen(controller)
    assert s is not None

def test_signup_screen_creates(controller):
    from screens.signup import SignupScreen
    s = SignupScreen(controller)
    assert s is not None

def test_login_has_login_button(controller):
    from screens.login import LoginScreen
    from PySide6.QtWidgets import QPushButton
    s = LoginScreen(controller)
    buttons = s.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    assert any("Login" in t or "login" in t.lower() for t in labels)

def test_signup_has_create_button(controller):
    from screens.signup import SignupScreen
    from PySide6.QtWidgets import QPushButton
    s = SignupScreen(controller)
    buttons = s.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    assert any("Create" in t or "Account" in t for t in labels)
