"""
Persistence for the global "which notification channels are enabled" toggles
shown in screens/notifications.py (System/Email/Slack). Previously these
toggles were purely cosmetic — nothing persisted them and nothing read them
back (every notification always went to System+Email regardless of what the
UI showed).

They now back strategy-alert delivery (see screens/live_viewer.py's wiring of
services.strategy_alerts.engine and services.notifications.manager.
NotificationService.notify's channels= param) — deliberately scoped to that
one delivery path; services/scheduled_jobs.py's background-job notifications
keep their existing unconditional System+Email behavior unchanged.

Stored via services.config_store (same mechanism as services/trigger_config.py),
so it's backend-synced for free through the generic per-user settings endpoint.
"""

from services import config_store

_CHANNELS_KEY = "notification_channels_enabled"

_DEFAULTS = {"system": True, "email": True, "slack": False}


def load_enabled_channels() -> dict:
    """Return {"system": bool, "email": bool, "slack": bool}. Missing keys
    (e.g. a value saved before a new channel existed) fall back to that
    channel's default rather than reading as disabled."""
    saved = config_store.load_json(_CHANNELS_KEY, {})
    if not isinstance(saved, dict):
        saved = {}
    return {name: bool(saved.get(name, default)) for name, default in _DEFAULTS.items()}


def save_enabled_channels(enabled: dict) -> None:
    config_store.save_json(_CHANNELS_KEY, {name: bool(enabled.get(name, default))
                                            for name, default in _DEFAULTS.items()})


def enabled_channel_ids() -> set[str]:
    """The subset of channel ids currently enabled — the shape
    NotificationService.notify's channels= param expects."""
    return {name for name, on in load_enabled_channels().items() if on}
