from abc import ABC, abstractmethod

from services.notifications.payload import NotificationPayload


class NotificationChannel(ABC):
    """One outbound delivery mechanism for a NotificationPayload.

    Implementations: channels/system.py and channels/email.py (live),
    channels/telegram.py (not implemented yet — staged for when its bot
    backend exists)."""

    @abstractmethod
    def send(self, payload: NotificationPayload) -> None:
        ...
