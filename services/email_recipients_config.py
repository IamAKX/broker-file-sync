"""
Persistence + parsing for Email notifications' recipient list — "add
capability to add multiple emails separated by ; , cap it to 20 emails".

Stored via services.config_store (same mechanism as services/slack_config.py's
webhook URL), so it's backend-synced for free through the generic per-user
settings endpoint — GET/PUT /settings/notification_email_recipients. The
backend's own app/routers/notifications.py reads this SAME key server-side
when resolving who a real "/notifications/email/send" call actually goes
to (see that repo's app/services/email_service.py::resolve_email_recipients,
which re-validates/caps defensively too — this module's validation is a UX
nicety, not the only enforcement).

Unlike Slack (entirely client-direct, no backend endpoint in the middle) or
the old single "Email Address" field (which only ever controlled where the
Test Notification button sent, never real delivery — see git history), this
list now IS what real delivery uses: the backend falls back to the account's
own registered email only when this is empty/unset.
"""

import re

from services import config_store

_RECIPIENTS_KEY = "notification_email_recipients"
MAX_RECIPIENTS = 20

_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def load_recipients() -> list[str]:
    """Return the saved recipient list, or [] if none configured yet."""
    value = config_store.load_json(_RECIPIENTS_KEY, [])
    return [e for e in value if isinstance(e, str)] if isinstance(value, list) else []


def save_recipients(emails: list[str]) -> None:
    config_store.save_json(_RECIPIENTS_KEY, list(emails))


def parse_recipients(text: str) -> tuple[list[str], str | None]:
    """Split *text* on ";", validate and de-duplicate (case-insensitive)
    each address, and enforce the 20-address cap.

    Returns (recipients, error) — error is None on success, or a message
    naming the first problem found (an unparseable address, or too many)
    for the caller to show and refuse to save, same "validate before
    accept" convention services.notifications._SlackConfigDialog already
    uses for its webhook URL field. Rejects rather than silently truncates/
    drops entries — a silently-dropped recipient is exactly the kind of
    "alert didn't reach who I expected" bug this feature exists to avoid.
    """
    seen: set[str] = set()
    out: list[str] = []
    for raw in text.split(";"):
        email = raw.strip()
        if not email:
            continue
        if not _EMAIL_RE.match(email):
            return [], f'"{email}" doesn\'t look like a valid email address.'
        key = email.lower()
        if key in seen:
            continue
        if len(out) >= MAX_RECIPIENTS:
            return [], f"Enter at most {MAX_RECIPIENTS} email addresses."
        seen.add(key)
        out.append(email)
    return out, None
