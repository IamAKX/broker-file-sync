"""
Delivers notifications directly to a Slack Incoming Webhook. Unlike
channels/email.py, there's no broker-sync-api endpoint in the middle — this
POSTs straight to the URL the user pastes into the Notifications screen's
Slack row (see services/slack_config.py). A blank/unconfigured webhook is a
harmless no-op, same as toggling Slack on before setting one up.

Network/API failures are swallowed rather than raised: this channel runs
inside NotificationService.notify() alongside System/Email, and a Slack
delivery hiccup (bad webhook, no connectivity) must not stop the other
channels' delivery or crash the caller (often a background scheduled job
already mid-failure-report — see services/scheduled_jobs.py). See
channels/email.py's docstring for the full reasoning — this mirrors it.

send() dispatches to a small background thread pool instead of calling the
network directly, for the same GUI-thread-blocking reason documented on
EmailChannel: notify() runs on the GUI thread, often in a loop over several
strategy-alert events on one tick.
"""

import concurrent.futures

import requests

from services import slack_config
from services.error_logging import error_logger
from services.notifications.channels.base import NotificationChannel
from services.notifications.payload import NotificationPayload

_TIMEOUT_SECONDS = 10

# One shared, small pool for the app's lifetime — same rationale as
# email.py's _executor.
_executor = concurrent.futures.ThreadPoolExecutor(max_workers=2, thread_name_prefix="slack-notify")


def send_to_webhook(webhook_url: str, title: str, message: str) -> None:
    """Raises requests.RequestException on failure — used directly by the
    Notifications screen's Slack Test Notification button so a bad webhook
    surfaces as a popup immediately, instead of being silently swallowed the
    way a real delivery's failure is (see _send_now below)."""
    text = f"*{title}*\n{message}"
    response = requests.post(webhook_url, json={"text": text}, timeout=_TIMEOUT_SECONDS)
    response.raise_for_status()


class SlackChannel(NotificationChannel):
    CHANNEL_ID = "slack"

    def send(self, payload: NotificationPayload) -> concurrent.futures.Future:
        """Returns the submitted Future — ignored by NotificationService's
        plain `channel.send(payload)` call, but lets tests (and any other
        caller that cares) wait for delivery to actually finish."""
        return _executor.submit(self._send_now, payload.title, payload.message)

    @staticmethod
    def _send_now(title: str, message: str) -> None:
        webhook_url = slack_config.load_webhook_url()
        if not webhook_url:
            return
        try:
            send_to_webhook(webhook_url, title, message)
        except requests.RequestException as exc:
            error_logger.error("Slack notification delivery failed: %s", exc)
        except Exception as exc:   # noqa: BLE001
            # Deliberately broader than requests.RequestException above — see
            # EmailChannel._send_now's docstring for why this exists (nothing
            # downstream calls .result() on the Future in production, so an
            # unanticipated bug here would otherwise vanish with zero trace).
            error_logger.exception("Slack notification delivery failed unexpectedly: %s", exc)
