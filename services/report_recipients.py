"""
Persistence for a Report's own email recipient list — distinct from
services.email_recipients_config's list (that one is a single, global
"where do Strategy Notifications emails go" setting; a report's recipients
are per-report, e.g. the LMV EOD report might go to a different desk than
the EMV one).

Parsing/validation (";"-separated, de-duplicated, capped) is NOT
reimplemented here — services.email_recipients_config.parse_recipients
already does exactly this and is reused directly, so both features enforce
the same rules and the same cap.

Stored as one dict ({report_id: [emails]}) under a single config_store key,
same backend-synced JSON-blob pattern every other per-user Reports setting
here uses (services.fuku_score, services.report_store).
"""

from services import config_store
from services.email_recipients_config import MAX_RECIPIENTS, parse_recipients  # noqa: F401

_REPORT_RECIPIENTS_KEY = "report_recipients"


def _load_raw() -> dict:
    value = config_store.load_json(_REPORT_RECIPIENTS_KEY, {})
    return value if isinstance(value, dict) else {}


def load_recipients(report_id: str) -> list[str]:
    """Return the saved recipient list for *report_id*, or [] if none
    configured yet."""
    value = _load_raw().get(report_id)
    return [e for e in value if isinstance(e, str)] if isinstance(value, list) else []


def save_recipients(report_id: str, emails: list[str]) -> None:
    data = _load_raw()
    if emails:
        data[report_id] = list(emails)
    else:
        data.pop(report_id, None)
    config_store.save_json(_REPORT_RECIPIENTS_KEY, data)


def delete_recipients(report_id: str) -> None:
    """Drops *report_id*'s entry entirely — used when a saved report config
    itself is deleted (see services.report_store.delete_report), so a
    deleted report's recipient list doesn't linger orphaned."""
    data = _load_raw()
    if report_id in data:
        del data[report_id]
        config_store.save_json(_REPORT_RECIPIENTS_KEY, data)
