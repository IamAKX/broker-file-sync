"""
Placeholder for the upcoming Telegram channel — no bot/backend exists yet.
Implement send() and register an instance in NotificationService's channel
list (services/notifications/manager.py) once one does.

TriggerConfig.telegram_enabled (services/trigger_config.py) is UI-only until
then — the Notifications screen's Telegram checkboxes don't route anywhere.
"""

from services.notifications.channels.base import NotificationChannel
from services.notifications.payload import NotificationPayload


class TelegramChannel(NotificationChannel):
    CHANNEL_ID = "telegram"

    def send(self, payload: NotificationPayload) -> None:
        raise NotImplementedError("Telegram notifications are not implemented yet")
