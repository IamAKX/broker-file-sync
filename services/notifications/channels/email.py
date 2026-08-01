"""
Placeholder for the upcoming Email channel — no mail backend exists yet.
Implement send() and register an instance in NotificationService's channel
list (services/notifications/manager.py) once one does.
"""

from services.notifications.channels.base import NotificationChannel
from services.notifications.payload import NotificationPayload


class EmailChannel(NotificationChannel):
    def send(self, payload: NotificationPayload) -> None:
        raise NotImplementedError("Email notifications are not implemented yet")
