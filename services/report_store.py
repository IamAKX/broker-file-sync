"""
Persistence for saved report configurations (the output of the Reports
wizard) — what the LMV/EMV/Fuku Live spec docs call a "reusable view" /
"personal default view": pick a report type, walk the wizard once, save it,
regenerate later without repeating the picks.

Same JSON-blob-under-one-config_store-key pattern as services.fuku_score
and services.email_recipients_config — a user's saved reports are a small,
low-cardinality list, so this doesn't need strategies.json's dedicated
backend CRUD endpoint (services.strategy_store) to get backend sync; config_
store.save_json/load_json already gives it that for free.

A report record:
  {
    "id": str (uuid),
    "type": "lmv" | "emv" | "fuku_live",
    "name": str,
    "subject_config": {...},   # report-type-specific: strategy id(s)/stock/
                                # sector/category selection — shape owned by
                                # each report type's own wizard, opaque here
    "columns": [...],          # selected + ordered column/field names
    "timeframe": {...},        # {"mode": "daily"|"weekly"|...|"custom",
                                #  "from": iso date|None, "to": iso date|None}
    "sections": {...},         # {section_key: bool} — which optional report
                                # sections are enabled (ratios, investment
                                # sim, target-achievement donut, ...)
    "visuals": {...},          # report-type-specific chart/plot-field config
    "created_at": iso str,
    "updated_at": iso str,
  }

Every field beyond id/type/name/created_at/updated_at is intentionally
opaque to this module — it's owned and interpreted entirely by the report
type's own wizard/data-layer code, this module just stores and retrieves it
whole.
"""

import uuid
from datetime import datetime, timezone

from services import config_store

REPORT_TYPE_LMV = "lmv"
REPORT_TYPE_EMV = "emv"
REPORT_TYPE_FUKU_LIVE = "fuku_live"
REPORT_TYPES = (REPORT_TYPE_LMV, REPORT_TYPE_EMV, REPORT_TYPE_FUKU_LIVE)

_REPORTS_KEY = "saved_reports"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_report(report_type: str, name: str) -> dict:
    if report_type not in REPORT_TYPES:
        raise ValueError(f"Unknown report type: {report_type!r}")
    now = _now_iso()
    return {
        "id": str(uuid.uuid4()),
        "type": report_type,
        "name": name,
        "subject_config": {},
        "columns": [],
        "timeframe": {"mode": "daily", "from": None, "to": None},
        "sections": {},
        "visuals": {},
        "created_at": now,
        "updated_at": now,
    }


def load_all() -> list:
    return list(config_store.load_json(_REPORTS_KEY, []))


def load_by_type(report_type: str) -> list:
    return [r for r in load_all() if r.get("type") == report_type]


def get_report(report_id: str) -> dict | None:
    for r in load_all():
        if r.get("id") == report_id:
            return r
    return None


def save_report(report: dict) -> None:
    """Upserts by id, stamping updated_at on every save."""
    report["updated_at"] = _now_iso()
    reports = load_all()
    for i, r in enumerate(reports):
        if r.get("id") == report.get("id"):
            reports[i] = report
            config_store.save_json(_REPORTS_KEY, reports)
            return
    reports.append(report)
    config_store.save_json(_REPORTS_KEY, reports)


def delete_report(report_id: str) -> None:
    from services import report_recipients

    config_store.save_json(
        _REPORTS_KEY, [r for r in load_all() if r.get("id") != report_id]
    )
    report_recipients.delete_recipients(report_id)
