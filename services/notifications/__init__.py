"""
Outbound notification delivery, organized by channel. System (tray) is the
only live channel today; Telegram and Email are staged as not-yet-implemented
placeholders (see channels/telegram.py, channels/email.py) for when their
backends land.

NotificationService is imported lazily (module __getattr__ below) rather
than at package import time: it pulls in channels/system.py -> sound.py ->
PySide6.QtMultimedia, which needs a real audio backend. NotificationLevel
alone (what services/scheduled_jobs.py needs at module scope) must stay
importable without that dependency, including on a CI runner with no audio
device.
"""

from services.notifications.levels import NotificationLevel
from services.notifications.payload import NotificationPayload

__all__ = ["NotificationService", "NotificationLevel", "NotificationPayload"]


def __getattr__(name):
    if name == "NotificationService":
        from services.notifications.manager import NotificationService
        return NotificationService
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
