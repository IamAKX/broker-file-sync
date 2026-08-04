"""
Delivers notifications by email via the backend's SMTP-backed endpoint
(broker-sync-api's app/services/email_service.py). The recipient is always
the logged-in user's registered email — the backend resolves it from the
bearer token itself, so this channel never carries an address.

Network/API failures are swallowed rather than raised: this channel runs
inside NotificationService.notify() alongside SystemChannel, and a mail
delivery hiccup (no connectivity, expired session) must not stop the tray
notification other channels still deliver, or crash the caller (often a
background scheduled job already mid-failure-report — see
services/scheduled_jobs.py).
"""

from api import notifications_api
from api.exceptions import ApiError, NetworkError
from services.error_logging import error_logger
from services.notifications.channels.base import NotificationChannel
from services.notifications.payload import NotificationPayload


class EmailChannel(NotificationChannel):
    CHANNEL_ID = "email"

    def send(self, payload: NotificationPayload) -> None:
        try:
            notifications_api.send_email(payload.title, payload.message)
        except (ApiError, NetworkError) as exc:
            error_logger.error("Email notification delivery failed: %s", exc)
