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

def test_full_navigation_cycle(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    for screen in ["dashboard", "data_import", "config_editor", "notifications", "profile", "formula_builder"]:
        w.navigate(screen)

def test_theme_toggle_does_not_crash(controller, monkeypatch):
    # See tests/test_theme.py's isolated_store fixture for why this is
    # mocked: toggle() -> apply() -> QApplication.setStyleSheet() restyles
    # every widget still alive in the whole process, which made this test
    # take 87s deep into a full `pytest tests/` run (thousands of widgets
    # accumulated from ~1500 preceding tests, none of it exercised by this
    # test's own "does not crash" assertion).
    monkeypatch.setattr(QApplication, "setStyleSheet", lambda self, *a, **k: None)
    controller.theme.toggle()
    controller.theme.toggle()

def test_login_to_main_flow(controller):
    from screens.login import LoginScreen
    login = LoginScreen(controller)
    assert login is not None

def test_signup_to_main_flow(controller):
    from screens.signup import SignupScreen
    signup = SignupScreen(controller)
    assert signup is not None
