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


# ── Admin Controls gating (only sundarhari10@gmail.com) ──────────────────

def test_admin_controls_hidden_by_default(topbar):
    """No user logged in (token_manager empty, the fixture's own state) ->
    Admin Controls must not be visible."""
    btn = topbar._menu_buttons.get("Admin Controls")
    assert btn is not None
    assert btn.isHidden() is True


def test_admin_controls_shown_for_the_admin_account(topbar, monkeypatch):
    from api.token_store import token_manager
    monkeypatch.setattr(token_manager, "get_user_email", lambda: "sundarhari10@gmail.com")
    topbar.refresh_user()
    assert topbar._menu_buttons["Admin Controls"].isHidden() is False


def test_admin_controls_hidden_for_everyone_else(topbar, monkeypatch):
    from api.token_store import token_manager
    monkeypatch.setattr(token_manager, "get_user_email", lambda: "someone.else@gmail.com")
    topbar.refresh_user()
    assert topbar._menu_buttons["Admin Controls"].isHidden() is True


def test_admin_controls_email_match_is_case_insensitive(topbar, monkeypatch):
    from api.token_store import token_manager
    monkeypatch.setattr(token_manager, "get_user_email", lambda: "SundarHari10@Gmail.com")
    topbar.refresh_user()
    assert topbar._menu_buttons["Admin Controls"].isHidden() is False


def test_admin_controls_hides_again_after_logout_and_different_login(topbar, monkeypatch):
    """Regression guard: MainWindow/TopBar are reused across a logout/
    login cycle within the same process (see app.AppController.
    show_main_window) — a second, non-admin user logging in must not
    keep seeing the admin's own menu."""
    from api.token_store import token_manager
    monkeypatch.setattr(token_manager, "get_user_email", lambda: "sundarhari10@gmail.com")
    topbar.refresh_user()
    assert topbar._menu_buttons["Admin Controls"].isHidden() is False

    monkeypatch.setattr(token_manager, "get_user_email", lambda: "someone.else@gmail.com")
    topbar.refresh_user()
    assert topbar._menu_buttons["Admin Controls"].isHidden() is True


def test_admin_controls_navigates_to_inception_admin_sync(topbar):
    """The menu's own action must target the right screen key."""
    from PySide6.QtGui import QAction
    menu = topbar._menu_buttons["Admin Controls"].menu()
    actions = [a for a in menu.actions() if isinstance(a, QAction) and a.text() == "Inception Sync"]
    assert len(actions) == 1
    captured = []
    topbar.navigate.connect(lambda name: captured.append(name))
    actions[0].trigger()
    assert captured == ["inception_admin_sync"]
