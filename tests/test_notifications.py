import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    return config_store


@pytest.fixture
def screen(qapp, isolated_store):
    from app import AppController
    from screens.notifications import NotificationsScreen
    return NotificationsScreen(AppController(qapp))


def test_notifications_creates(screen):
    assert screen is not None


def test_has_test_notification_button_per_channel(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert btns.count("Test Notification") == 3


def test_has_two_action_buttons(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert len([t for t in btns if t.strip()]) >= 2


def test_system_test_notification_fires_real_notifier_call(screen):
    calls = []

    class FakeNotifier:
        def notify(self, title, message, action=None):
            calls.append((title, message, action))

    screen._controller._notifier = FakeNotifier()
    screen._system_card._send_btn.click()

    assert len(calls) == 1
    title, message, action = calls[0]
    assert title and message
    assert callable(action)


def test_system_row_has_no_configure_button(screen):
    from PySide6.QtWidgets import QToolButton
    assert screen._system_card.findChildren(QToolButton) == []


def test_trigger_table_has_four_rows(screen):
    assert screen._table.rowCount() == 4


def test_system_and_email_default_checked_telegram_default_unchecked(screen):
    from PySide6.QtWidgets import QCheckBox
    for row in range(screen._table.rowCount()):
        system_cb = screen._table.cellWidget(row, 2).findChild(QCheckBox)
        telegram_cb = screen._table.cellWidget(row, 3).findChild(QCheckBox)
        email_cb = screen._table.cellWidget(row, 4).findChild(QCheckBox)
        assert system_cb.isChecked() is True
        assert telegram_cb.isChecked() is False
        assert email_cb.isChecked() is True


def test_system_and_email_channel_cards_enabled_by_default(screen):
    # System and Email are both live channels — their top-level toggles (and
    # status dots) default on, unlike Telegram which has no backend yet.
    assert screen._system_card.is_enabled() is True
    assert screen._email_card.is_enabled() is True
    assert screen._telegram_card.is_enabled() is False
    assert "Enabled" in screen._system_status_lbl.text()


def test_test_email_dialog_prefilled_with_logged_in_user_email(screen, monkeypatch):
    import screens.notifications as notifications_module
    from api.token_store import token_manager

    monkeypatch.setattr(token_manager, "get_user_email", lambda: "user@example.com")

    captured = {}

    class FakeDialog:
        def __init__(self, title, fields, values, theme, parent=None):
            captured["values"] = values

        def exec(self):
            return notifications_module.QDialog.DialogCode.Rejected

    monkeypatch.setattr(notifications_module, "_ChannelConfigDialog", FakeDialog)
    screen._email_card._send_btn.click()

    assert captured["values"] == {"Email Address": "user@example.com"}


def test_send_test_email_calls_api_with_typed_address(screen, monkeypatch):
    import screens.notifications as notifications_module
    from api import notifications_api

    calls = []
    monkeypatch.setattr(notifications_api, "send_test_email", lambda *a: calls.append(a))
    # The success path pops a real QMessageBox.information — stub it out so
    # the test doesn't block on a modal with no user to dismiss it.
    monkeypatch.setattr(notifications_module.QMessageBox, "information", MagicMock())

    screen._do_send_test_email("someone@example.com")

    assert calls == [(
        "someone@example.com", "Test Notification",
        "This is a test notification from Broker File Sync.",
    )]


def test_send_test_email_shows_error_popup_on_failure(screen, monkeypatch):
    import screens.notifications as notifications_module
    from api import notifications_api
    from api.exceptions import NetworkError

    def _raise(*a):
        raise NetworkError("unreachable")

    monkeypatch.setattr(notifications_api, "send_test_email", _raise)
    popup = MagicMock()
    monkeypatch.setattr(notifications_module, "show_api_error", popup)

    screen._do_send_test_email("someone@example.com")

    popup.assert_called_once()


def test_edited_time_persists(screen, isolated_store):
    from datetime import time as dtime
    from services import trigger_config

    cfg = screen._configs[0]
    cfg.time = dtime(9, 30)
    screen._save_configs()

    reloaded = trigger_config.load_trigger_configs()
    match = next(c for c in reloaded if c.id == cfg.id)
    assert match.time == dtime(9, 30)


def test_checkbox_toggle_persists(screen, isolated_store):
    from services import trigger_config

    cfg = screen._configs[0]
    screen._on_checkbox_changed(cfg, "telegram", True)

    reloaded = trigger_config.load_trigger_configs()
    match = next(c for c in reloaded if c.id == cfg.id)
    assert match.telegram_enabled is True
