"""
Facade the rest of the app calls into — services/scheduled_jobs.py and
screens/notifications.py's "Test Notification" button both go through
.notify() without knowing which channels are live. System and Email are both
live; Telegram joins _channels once its backend exists (see
channels/telegram.py).
"""

from PySide6.QtWidgets import QSystemTrayIcon

from services.notifications.channels.email import EmailChannel
from services.notifications.channels.system import SystemChannel
from services.notifications.levels import NotificationLevel
from services.notifications.payload import NotificationPayload
from services.notifications.sound import AlertSound


class NotificationService:
    def __init__(self, tray_icon: QSystemTrayIcon):
        sound = AlertSound()
        self._channels = [SystemChannel(tray_icon, sound), EmailChannel()]

    def notify(self, title: str, message: str, action=None,
               level: NotificationLevel = NotificationLevel.INFO,
               timeout_ms: int = 10_000) -> None:
        payload = NotificationPayload(
            title=title, message=message, action=action,
            level=level, timeout_ms=timeout_ms,
        )
        for channel in self._channels:
            channel.send(payload)
