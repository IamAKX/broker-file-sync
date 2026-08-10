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


def test_system_and_email_default_checked_slack_default_unchecked(screen):
    from PySide6.QtWidgets import QCheckBox
    for row in range(screen._table.rowCount()):
        system_cb = screen._table.cellWidget(row, 2).findChild(QCheckBox)
        slack_cb = screen._table.cellWidget(row, 3).findChild(QCheckBox)
        email_cb = screen._table.cellWidget(row, 4).findChild(QCheckBox)
        assert system_cb.isChecked() is True
        assert slack_cb.isChecked() is False
        assert email_cb.isChecked() is True


def test_system_and_email_channel_cards_enabled_by_default(screen):
    # System and Email are both live channels — their top-level toggles (and
    # status dots) default on, unlike Slack which needs a webhook configured
    # before it's worth turning on.
    assert screen._system_card.is_enabled() is True
    assert screen._email_card.is_enabled() is True
    assert screen._slack_card.is_enabled() is False
    assert "Enabled" in screen._system_status_lbl.text()


def test_email_card_has_configure_button(screen):
    from PySide6.QtWidgets import QToolButton
    assert screen._email_card.findChildren(QToolButton) != []


def test_email_card_prefilled_with_logged_in_user_email(qapp, isolated_store, monkeypatch):
    from api.token_store import token_manager
    monkeypatch.setattr(token_manager, "get_user_email", lambda: "user@example.com")

    from app import AppController
    from screens.notifications import NotificationsScreen
    screen = NotificationsScreen(AppController(qapp))

    assert screen._email_card.get_value("Email Address") == "user@example.com"


def test_test_notification_button_sends_to_configured_email(qapp, isolated_store, monkeypatch):
    from api.token_store import token_manager
    monkeypatch.setattr(token_manager, "get_user_email", lambda: "user@example.com")

    from app import AppController
    from screens.notifications import NotificationsScreen
    screen = NotificationsScreen(AppController(qapp))

    import screens.notifications as notifications_module
    from PySide6.QtCore import QTimer
    from api import notifications_api

    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, cb: scheduled.append(cb)))
    calls = []
    monkeypatch.setattr(notifications_api, "send_test_email", lambda *a: calls.append(a))
    monkeypatch.setattr(notifications_module.QMessageBox, "information", MagicMock())

    screen._email_card._send_btn.click()
    assert len(scheduled) == 1
    scheduled[0]()   # run the deferred send synchronously

    assert calls == [(
        "user@example.com", "Test Notification",
        "This is a test notification from Broker File Sync.",
    )]


def test_test_notification_button_sends_to_reconfigured_email(screen, monkeypatch):
    import screens.notifications as notifications_module
    from PySide6.QtCore import QTimer
    from api import notifications_api

    screen._email_card._values["Email Address"] = "other@example.com"

    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, cb: scheduled.append(cb)))
    calls = []
    monkeypatch.setattr(notifications_api, "send_test_email", lambda *a: calls.append(a))
    monkeypatch.setattr(notifications_module.QMessageBox, "information", MagicMock())

    screen._email_card._send_btn.click()
    scheduled[0]()

    assert calls[0][0] == "other@example.com"


def test_test_notification_button_warns_when_email_address_blank(screen, monkeypatch):
    import screens.notifications as notifications_module

    screen._email_card._values["Email Address"] = ""
    warn = MagicMock()
    monkeypatch.setattr(notifications_module.QMessageBox, "warning", warn)

    screen._email_card._send_btn.click()

    warn.assert_called_once()


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
    screen._on_checkbox_changed(cfg, "slack", True)

    reloaded = trigger_config.load_trigger_configs()
    match = next(c for c in reloaded if c.id == cfg.id)
    assert match.slack_enabled is True


def test_slack_card_prefilled_with_saved_webhook_url(qapp, isolated_store):
    from services import slack_config
    slack_config.save_webhook_url("https://hooks.slack.com/services/T/B/X")

    from app import AppController
    from screens.notifications import NotificationsScreen
    screen = NotificationsScreen(AppController(qapp))

    assert screen._slack_card.get_value("Webhook URL") == "https://hooks.slack.com/services/T/B/X"


def test_slack_config_saved_persists_webhook_url(screen, isolated_store):
    from services import slack_config

    screen._on_slack_config_saved({"Webhook URL": "https://hooks.slack.com/services/T/B/X"})

    assert slack_config.load_webhook_url() == "https://hooks.slack.com/services/T/B/X"


def test_test_notification_button_sends_to_configured_slack_webhook(screen, monkeypatch):
    import screens.notifications as notifications_module
    from PySide6.QtCore import QTimer

    screen._slack_card._values["Webhook URL"] = "https://hooks.slack.com/services/T/B/X"

    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, cb: scheduled.append(cb)))
    calls = []
    monkeypatch.setattr(notifications_module, "send_to_webhook", lambda *a: calls.append(a))
    monkeypatch.setattr(notifications_module.QMessageBox, "information", MagicMock())

    screen._slack_card._send_btn.click()
    assert len(scheduled) == 1
    scheduled[0]()   # run the deferred send synchronously

    assert calls == [(
        "https://hooks.slack.com/services/T/B/X", "Test Notification",
        "This is a test notification from Broker File Sync.",
    )]


def test_test_notification_button_warns_when_slack_webhook_blank(screen, monkeypatch):
    import screens.notifications as notifications_module

    screen._slack_card._values["Webhook URL"] = ""
    warn = MagicMock()
    monkeypatch.setattr(notifications_module.QMessageBox, "warning", warn)

    screen._slack_card._send_btn.click()

    warn.assert_called_once()


def test_send_test_slack_shows_error_popup_on_failure(screen, monkeypatch):
    import screens.notifications as notifications_module
    import requests

    def _raise(*a):
        raise requests.RequestException("unreachable")

    monkeypatch.setattr(notifications_module, "send_to_webhook", _raise)
    popup = MagicMock()
    monkeypatch.setattr(notifications_module, "show_api_error", popup)

    screen._do_send_test_slack("https://hooks.slack.com/services/T/B/X")

    popup.assert_called_once()


# ── Slack Configure dialog (guided walkthrough) ─────────────────────────────

def test_slack_config_dialog_rejects_malformed_webhook_url(qapp, isolated_store):
    from app import AppController
    from screens.notifications import _SlackConfigDialog

    dlg = _SlackConfigDialog({}, AppController(qapp).theme)
    dlg.accept = MagicMock()
    dlg._input.setText("not-a-webhook-url")

    dlg._try_accept()

    # Widget-tree isVisible() only reflects reality once the dialog is
    # actually shown (which .exec() would do, but these tests call
    # _try_accept() directly to avoid opening a real modal) — check the
    # message itself and that accept() was withheld instead.
    assert dlg._error_lbl.text() != ""
    dlg.accept.assert_not_called()


def test_slack_config_dialog_accepts_valid_webhook_url(qapp, isolated_store):
    from app import AppController
    from screens.notifications import _SlackConfigDialog

    dlg = _SlackConfigDialog({}, AppController(qapp).theme)
    dlg.accept = MagicMock()
    dlg._input.setText("https://hooks.slack.com/services/T/B/X")

    dlg._try_accept()

    assert dlg._error_lbl.text() == ""
    dlg.accept.assert_called_once()
    assert dlg.values() == {"Webhook URL": "https://hooks.slack.com/services/T/B/X"}


def test_slack_config_dialog_allows_blank_to_clear_webhook(qapp, isolated_store):
    from app import AppController
    from screens.notifications import _SlackConfigDialog

    dlg = _SlackConfigDialog({"Webhook URL": "https://hooks.slack.com/services/T/B/X"}, AppController(qapp).theme)
    dlg.accept = MagicMock()
    dlg._input.setText("")

    dlg._try_accept()

    assert dlg._error_lbl.text() == ""
    dlg.accept.assert_called_once()


def test_slack_config_dialog_prefilled_from_current_values(qapp, isolated_store):
    from app import AppController
    from screens.notifications import _SlackConfigDialog

    dlg = _SlackConfigDialog({"Webhook URL": "https://hooks.slack.com/services/T/B/X"}, AppController(qapp).theme)

    assert dlg._input.text() == "https://hooks.slack.com/services/T/B/X"


def test_slack_card_uses_slack_config_dialog(screen):
    from screens.notifications import _SlackConfigDialog
    assert screen._slack_card._dialog_factory is _SlackConfigDialog
