"""
Facade the rest of the app calls into — services/scheduled_jobs.py and
screens/notifications.py's "Test Notification" button both go through
.notify() without knowing which channels are live. System, Email, and Slack
are all live.
"""

from PySide6.QtWidgets import QSystemTrayIcon

from services.notifications.channels.email import EmailChannel
from services.notifications.channels.slack import SlackChannel
from services.notifications.channels.system import SystemChannel
from services.notifications.levels import NotificationLevel
from services.notifications.payload import NotificationPayload
from services.notifications.sound import AlertSound


class NotificationService:
    def __init__(self, tray_icon: QSystemTrayIcon):
        sound = AlertSound()
        self._channels = [SystemChannel(tray_icon, sound), EmailChannel(), SlackChannel()]

    def notify(self, title: str, message: str, action=None,
               level: NotificationLevel = NotificationLevel.INFO,
               timeout_ms: int = 10_000,
               channels: set[str] | None = None) -> list:
        """``channels``, when given, restricts delivery to the channel ids in
        that set (see each channel's CHANNEL_ID, e.g. "system"/"email"/"slack")
        — used by strategy-alert delivery to respect the user's global
        System/Email/Slack toggles (services/notification_channels.py).
        ``None`` (the default) delivers to every registered channel,
        preserving existing callers' behavior (e.g. services/scheduled_jobs.py's
        background-job notifications, which aren't gated by those toggles).
        Requesting a channel id with no matching registered channel is a
        harmless no-op.

        Returns each dispatched channel's own send() result (e.g.
        EmailChannel's concurrent.futures.Future for its background-dispatched
        network call) — every existing caller ignores this, it's there for a
        caller (tests, mainly) that wants to wait for delivery to actually
        finish rather than just assume it did the instant notify() returns.
        """
        payload = NotificationPayload(
            title=title, message=message, action=action,
            level=level, timeout_ms=timeout_ms,
        )
        results = []
        for channel in self._channels:
            if channels is not None and getattr(channel, "CHANNEL_ID", None) not in channels:
                continue
            results.append(channel.send(payload))
        return results
