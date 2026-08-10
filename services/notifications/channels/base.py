from abc import ABC, abstractmethod

from services.notifications.payload import NotificationPayload


class NotificationChannel(ABC):
    """One outbound delivery mechanism for a NotificationPayload.

    Implementations: channels/system.py, channels/email.py, and
    channels/slack.py (all live).

    Must never block the caller on network I/O — NotificationService.notify()
    (and this) runs on the GUI thread, often in a loop over several events at
    once (see screens/live_viewer.py's _run_strategy_alert_checks). A channel
    whose delivery is a real network call (channels/email.py) dispatches it
    to a background thread/pool instead of awaiting it inline, optionally
    returning a Future so a caller that wants to (tests, mainly) can wait for
    it — ordinary callers ignore the return value."""

    @abstractmethod
    def send(self, payload: NotificationPayload) -> object | None:
        ...
