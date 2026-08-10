"""
Persistence for the Slack channel's Incoming Webhook URL, configured via the
Notifications screen's Slack row (its Configure button).

Unlike Email (recipient resolved server-side by broker-sync-api) and unlike
System (nothing to configure at all), Slack is entirely client-direct: this
app POSTs straight to the webhook URL itself (see
services/notifications/channels/slack.py) — there is no backend endpoint in
the middle. That makes the webhook URL the one piece of channel config that
actually has to be persisted (contrast with the Email row's address field,
which only ever controls where its Test Notification button sends, never
real delivery).

Stored via services.config_store (same mechanism as services/trigger_config.py
and services/notification_channels.py), so it's backend-synced for free
through the generic per-user settings endpoint — no different a trust
boundary than everything else already stored there.
"""

from services import config_store

_WEBHOOK_KEY = "slack_webhook_url"


def load_webhook_url() -> str:
    """Return the saved Incoming Webhook URL, or "" if none configured yet."""
    url = config_store.load_json(_WEBHOOK_KEY, "")
    return url if isinstance(url, str) else ""


def save_webhook_url(url: str) -> None:
    config_store.save_json(_WEBHOOK_KEY, (url or "").strip())
