import os
import sys

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


# ── Telegram / Email placeholders ───────────────────────────────────────────

def test_telegram_channel_not_implemented():
    from services.notifications.channels.telegram import TelegramChannel
    from services.notifications.payload import NotificationPayload

    with pytest.raises(NotImplementedError):
        TelegramChannel().send(NotificationPayload(title="T", message="M"))


def test_email_channel_not_implemented():
    from services.notifications.channels.email import EmailChannel
    from services.notifications.payload import NotificationPayload

    with pytest.raises(NotImplementedError):
        EmailChannel().send(NotificationPayload(title="T", message="M"))


# ── Sound asset ──────────────────────────────────────────────────────────

def test_alert_sound_asset_exists():
    from services.notifications.sound import _ASSET_PATH
    assert os.path.isfile(_ASSET_PATH)


def test_alert_sound_plays_without_raising(qapp):
    from services.notifications.sound import AlertSound
    AlertSound().play()   # smoke test — no audio device required to not raise


# ── NotificationService facade ──────────────────────────────────────────────

def test_notification_service_dispatches_to_system_channel(qapp):
    from services.notifications.manager import NotificationService
    from services.notifications.levels import NotificationLevel

    tray = _FakeTrayIcon()
    service = NotificationService(tray)
    service.notify("T", "M", level=NotificationLevel.SUCCESS)

    assert tray.messages == [("T", "M", QSystemTrayIcon.MessageIcon.Information, 10_000)]


def test_notification_service_lazy_import_from_package(qapp):
    # Importing NotificationLevel alone must not require NotificationService's
    # heavier dependency chain (see services/notifications/__init__.py).
    from services.notifications import NotificationService
    assert NotificationService is not None
