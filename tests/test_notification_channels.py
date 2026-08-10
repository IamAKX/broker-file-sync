import os
import sys
from unittest.mock import patch

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication, QSystemTrayIcon


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeTrayIcon(QObject):
    messageClicked = Signal()

    def __init__(self):
        super().__init__()
        self.messages = []

    def showMessage(self, title, message, icon, timeout_ms):
        self.messages.append((title, message, icon, timeout_ms))


class _FakeSound:
    def __init__(self):
        self.play_count = 0

    def play(self):
        self.play_count += 1


# ── SystemChannel ─────────────────────────────────────────────────────────

def test_system_channel_shows_message_and_plays_sound(qapp):
    from services.notifications.channels.system import SystemChannel
    from services.notifications.levels import NotificationLevel
    from services.notifications.payload import NotificationPayload

    tray = _FakeTrayIcon()
    sound = _FakeSound()
    channel = SystemChannel(tray, sound)

    channel.send(NotificationPayload(title="T", message="M", level=NotificationLevel.SUCCESS))

    assert tray.messages == [("T", "M", QSystemTrayIcon.MessageIcon.Information, 10_000)]
    assert sound.play_count == 1


def test_system_channel_maps_failure_to_warning_icon(qapp):
    from services.notifications.channels.system import SystemChannel
    from services.notifications.levels import NotificationLevel
    from services.notifications.payload import NotificationPayload

    tray = _FakeTrayIcon()
    channel = SystemChannel(tray, _FakeSound())

    channel.send(NotificationPayload(title="T", message="M", level=NotificationLevel.FAILURE))

    assert tray.messages[0][2] == QSystemTrayIcon.MessageIcon.Warning


def test_system_channel_plays_sound_for_every_level(qapp):
    from services.notifications.channels.system import SystemChannel
    from services.notifications.levels import NotificationLevel
    from services.notifications.payload import NotificationPayload

    tray = _FakeTrayIcon()
    sound = _FakeSound()
    channel = SystemChannel(tray, sound)

    for level in NotificationLevel:
        channel.send(NotificationPayload(title="T", message="M", level=level))

    assert sound.play_count == len(list(NotificationLevel))


def test_system_channel_runs_action_on_message_clicked(qapp):
    from services.notifications.channels.system import SystemChannel
    from services.notifications.payload import NotificationPayload

    tray = _FakeTrayIcon()
    channel = SystemChannel(tray, _FakeSound())

    calls = []
    channel.send(NotificationPayload(title="T", message="M", action=lambda: calls.append(1)))
    tray.messageClicked.emit()

    assert calls == [1]


def test_system_channel_no_action_on_message_clicked_when_none_pending(qapp):
    from services.notifications.channels.system import SystemChannel
    from services.notifications.payload import NotificationPayload

    tray = _FakeTrayIcon()
    channel = SystemChannel(tray, _FakeSound())
    channel.send(NotificationPayload(title="T", message="M"))   # no action

    tray.messageClicked.emit()   # must not raise


def test_email_channel_sends_title_and_message_via_notifications_api():
    from api import notifications_api
    from services.notifications.channels.email import EmailChannel
    from services.notifications.payload import NotificationPayload

    calls = []
    with patch.object(notifications_api, "send_email", lambda title, message: calls.append((title, message))):
        EmailChannel().send(NotificationPayload(title="T", message="M")).result(timeout=5)

    assert calls == [("T", "M")]


def test_email_channel_swallows_api_error_instead_of_raising():
    from api import notifications_api
    from api.exceptions import ApiError
    from services.notifications.channels.email import EmailChannel
    from services.notifications.payload import NotificationPayload

    def _raise(title, message):
        raise ApiError("boom", "unknown_error", 500)

    with patch.object(notifications_api, "send_email", _raise):
        # must not raise, even once the background send actually runs
        EmailChannel().send(NotificationPayload(title="T", message="M")).result(timeout=5)


def test_email_channel_swallows_network_error_instead_of_raising():
    from api import notifications_api
    from api.exceptions import NetworkError
    from services.notifications.channels.email import EmailChannel
    from services.notifications.payload import NotificationPayload

    def _raise(title, message):
        raise NetworkError("unreachable")

    with patch.object(notifications_api, "send_email", _raise):
        # must not raise, even once the background send actually runs
        EmailChannel().send(NotificationPayload(title="T", message="M")).result(timeout=5)


def test_email_channel_send_does_not_block_caller():
    """The whole point of dispatching to a background pool: send() must
    return immediately regardless of how slow the underlying network call
    is — this is the fix for the app going "Not Responding" when several
    strategy alerts fired (and so emailed) on the same Live Master View
    tick, each serialized inline on the GUI thread."""
    import time
    from api import notifications_api
    from services.notifications.channels.email import EmailChannel
    from services.notifications.payload import NotificationPayload

    def _slow_send(title, message):
        time.sleep(0.3)

    with patch.object(notifications_api, "send_email", _slow_send):
        start = time.monotonic()
        future = EmailChannel().send(NotificationPayload(title="T", message="M"))
        elapsed = time.monotonic() - start
        assert elapsed < 0.1
        future.result(timeout=5)   # let it finish before the test exits


# ── SlackChannel ─────────────────────────────────────────────────────────

def test_slack_channel_posts_title_and_message_to_configured_webhook():
    from services import slack_config
    from services.notifications.channels import slack as slack_channel_module
    from services.notifications.channels.slack import SlackChannel
    from services.notifications.payload import NotificationPayload

    calls = []

    def _fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        class _Resp:
            def raise_for_status(self):
                pass
        return _Resp()

    with patch.object(slack_config, "load_webhook_url", lambda: "https://hooks.slack.com/services/T/B/X"):
        with patch.object(slack_channel_module.requests, "post", _fake_post):
            SlackChannel().send(NotificationPayload(title="T", message="M")).result(timeout=5)

    assert calls == [("https://hooks.slack.com/services/T/B/X", {"text": "*T*\nM"})]


def test_slack_channel_is_a_noop_when_no_webhook_configured():
    from services import slack_config
    from services.notifications.channels import slack as slack_channel_module
    from services.notifications.channels.slack import SlackChannel
    from services.notifications.payload import NotificationPayload

    calls = []
    with patch.object(slack_config, "load_webhook_url", lambda: ""):
        with patch.object(slack_channel_module.requests, "post", lambda *a, **k: calls.append(1)):
            # must not raise, and must not attempt a network call
            SlackChannel().send(NotificationPayload(title="T", message="M")).result(timeout=5)

    assert calls == []


def test_slack_channel_swallows_request_exception_instead_of_raising():
    from services import slack_config
    from services.notifications.channels import slack as slack_channel_module
    from services.notifications.channels.slack import SlackChannel
    from services.notifications.payload import NotificationPayload

    def _raise(*a, **k):
        raise slack_channel_module.requests.RequestException("boom")

    with patch.object(slack_config, "load_webhook_url", lambda: "https://hooks.slack.com/services/T/B/X"):
        with patch.object(slack_channel_module.requests, "post", _raise):
            # must not raise, even once the background send actually runs
            SlackChannel().send(NotificationPayload(title="T", message="M")).result(timeout=5)


def test_slack_channel_send_does_not_block_caller():
    """Same rationale as EmailChannel's equivalent test — send() must return
    immediately regardless of how slow the webhook call is."""
    import time
    from services import slack_config
    from services.notifications.channels import slack as slack_channel_module
    from services.notifications.channels.slack import SlackChannel
    from services.notifications.payload import NotificationPayload

    def _slow_post(*a, **k):
        time.sleep(0.3)
        class _Resp:
            def raise_for_status(self):
                pass
        return _Resp()

    with patch.object(slack_config, "load_webhook_url", lambda: "https://hooks.slack.com/services/T/B/X"):
        with patch.object(slack_channel_module.requests, "post", _slow_post):
            start = time.monotonic()
            future = SlackChannel().send(NotificationPayload(title="T", message="M"))
            elapsed = time.monotonic() - start
            assert elapsed < 0.1
            future.result(timeout=5)   # let it finish before the test exits


# ── Sound asset ──────────────────────────────────────────────────────────

def test_alert_sound_asset_exists():
    from services.notifications.sound import _ASSET_PATH
    assert os.path.isfile(_ASSET_PATH)


def test_alert_sound_plays_without_raising(qapp):
    from services.notifications.sound import AlertSound
    AlertSound().play()   # smoke test — no audio device required to not raise


# ── NotificationService facade ──────────────────────────────────────────────

def test_notification_service_dispatches_to_system_channel(qapp):
    from api import notifications_api
    from services import slack_config
    from services.notifications.manager import NotificationService
    from services.notifications.levels import NotificationLevel

    tray = _FakeTrayIcon()
    # EmailChannel and SlackChannel are also registered (see manager.py) —
    # stub both out so this test doesn't make a real HTTP call.
    with patch.object(notifications_api, "send_email", lambda title, message: None), \
         patch.object(slack_config, "load_webhook_url", lambda: ""):
        service = NotificationService(tray)
        service.notify("T", "M", level=NotificationLevel.SUCCESS)

    assert tray.messages == [("T", "M", QSystemTrayIcon.MessageIcon.Information, 10_000)]


def test_notification_service_dispatches_to_email_channel(qapp):
    from api import notifications_api
    from services import slack_config
    from services.notifications.manager import NotificationService
    from services.notifications.levels import NotificationLevel

    tray = _FakeTrayIcon()
    calls = []
    with patch.object(notifications_api, "send_email", lambda title, message: calls.append((title, message))), \
         patch.object(slack_config, "load_webhook_url", lambda: ""):
        service = NotificationService(tray)
        results = service.notify("T", "M", level=NotificationLevel.SUCCESS)
        # Wait for EmailChannel's background dispatch — still inside the
        # patch, since the background thread runs notifications_api.send_email
        # whenever it happens to get scheduled, not necessarily before the
        # `with` block exits and un-patches it.
        for r in results:
            if r is not None:
                r.result(timeout=5)

    assert calls == [("T", "M")]


def test_notification_service_dispatches_to_slack_channel(qapp):
    from api import notifications_api
    from services import slack_config
    from services.notifications.channels import slack as slack_channel_module
    from services.notifications.manager import NotificationService
    from services.notifications.levels import NotificationLevel

    tray = _FakeTrayIcon()
    calls = []

    def _fake_post(url, json=None, timeout=None):
        calls.append((url, json))
        class _Resp:
            def raise_for_status(self):
                pass
        return _Resp()

    with patch.object(notifications_api, "send_email", lambda title, message: None), \
         patch.object(slack_config, "load_webhook_url", lambda: "https://hooks.slack.com/services/T/B/X"), \
         patch.object(slack_channel_module.requests, "post", _fake_post):
        service = NotificationService(tray)
        results = service.notify("T", "M", level=NotificationLevel.SUCCESS)
        for r in results:
            if r is not None:
                r.result(timeout=5)

    assert calls == [("https://hooks.slack.com/services/T/B/X", {"text": "*T*\nM"})]


def test_notification_service_lazy_import_from_package(qapp):
    # Importing NotificationLevel alone must not require NotificationService's
    # heavier dependency chain (see services/notifications/__init__.py).
    from services.notifications import NotificationService
    assert NotificationService is not None


def test_notification_service_channels_filter_restricts_delivery(qapp):
    from api import notifications_api
    from services.notifications.manager import NotificationService

    tray = _FakeTrayIcon()
    email_calls = []
    with patch.object(notifications_api, "send_email", lambda title, message: email_calls.append(1)):
        service = NotificationService(tray)
        service.notify("T", "M", channels={"system"})

    assert tray.messages  # system delivered
    assert email_calls == []  # email filtered out


def test_notification_service_channels_filter_unknown_id_is_noop(qapp):
    from api import notifications_api
    from services.notifications.manager import NotificationService

    tray = _FakeTrayIcon()
    with patch.object(notifications_api, "send_email", lambda title, message: None):
        service = NotificationService(tray)
        # "sms" matches no registered channel today — must not raise.
        service.notify("T", "M", channels={"sms"})

    assert tray.messages == []


def test_notification_service_none_channels_delivers_to_all(qapp):
    from api import notifications_api
    from services import slack_config
    from services.notifications.manager import NotificationService

    tray = _FakeTrayIcon()
    email_calls = []
    with patch.object(notifications_api, "send_email", lambda title, message: email_calls.append(1)), \
         patch.object(slack_config, "load_webhook_url", lambda: ""):
        service = NotificationService(tray)
        results = service.notify("T", "M")
        # Wait while still inside the patch — see the sibling test above.
        for r in results:
            if r is not None:
                r.result(timeout=5)

    assert tray.messages
    assert email_calls == [1]
