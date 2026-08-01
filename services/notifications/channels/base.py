from abc import ABC, abstractmethod

from services.notifications.payload import NotificationPayload


class NotificationChannel(ABC):
    """One outbound delivery mechanism for a NotificationPayload.

    Implementations: channels/system.py (live), channels/telegram.py and
    channels/email.py (not implemented yet — staged for when their backends
    exist)."""

    @abstractmethod
    def send(self, payload: NotificationPayload) -> None:
        ...
