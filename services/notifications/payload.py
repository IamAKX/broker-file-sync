from dataclasses import dataclass
from typing import Callable, Optional

from services.notifications.levels import NotificationLevel


@dataclass
class NotificationPayload:
    """What a channel needs to deliver one notification — channel-agnostic,
    so System/Email/Slack all consume the same shape."""
    title: str
    message: str
    level: NotificationLevel = NotificationLevel.INFO
    action: Optional[Callable[[], None]] = None
    timeout_ms: int = 10_000
