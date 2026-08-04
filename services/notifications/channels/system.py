"""
Delivers notifications via the OS tray icon, with a loud alert sound
alongside every message (see services/notifications/sound.py).
"""

from PySide6.QtWidgets import QSystemTrayIcon

from services.notifications.channels.base import NotificationChannel
from services.notifications.levels import NotificationLevel
from services.notifications.payload import NotificationPayload
from services.notifications.sound import AlertSound

_ICON_BY_LEVEL = {
    NotificationLevel.INFO: QSystemTrayIcon.MessageIcon.Information,
    NotificationLevel.SUCCESS: QSystemTrayIcon.MessageIcon.Information,
    NotificationLevel.FAILURE: QSystemTrayIcon.MessageIcon.Warning,
}


class SystemChannel(NotificationChannel):
    CHANNEL_ID = "system"

    def __init__(self, tray_icon: QSystemTrayIcon, sound: AlertSound):
        self._tray = tray_icon
        self._sound = sound
        self._pending_action = None
        self._tray.messageClicked.connect(self._on_message_clicked)

    def send(self, payload: NotificationPayload) -> None:
        self._pending_action = payload.action
        self._tray.showMessage(
            payload.title, payload.message,
            _ICON_BY_LEVEL[payload.level], payload.timeout_ms,
        )
        self._sound.play()

    def _on_message_clicked(self):
        if self._pending_action is not None:
            action, self._pending_action = self._pending_action, None
            action()
