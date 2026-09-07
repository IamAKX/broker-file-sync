from datetime import date

from api.client import api_client
from api.endpoints import AVAILABILITY, DAILY_UPLOAD, HISTORIC, RANGE, SNAPSHOT


def upload_daily(trade_date: date, rows: list[dict]) -> dict:
    return api_client.post(
        DAILY_UPLOAD,
        json_body={"trade_date": trade_date.isoformat(), "rows": rows},
    )


def get_availability(date_from: date, date_to: date) -> dict:
    return api_client.get(
        AVAILABILITY,
        params={"from": date_from.isoformat(), "to": date_to.isoformat()},
    )


def get_snapshot(trade_date: date | None) -> dict:
    params = {"date": trade_date.isoformat()} if trade_date is not None else None
    return api_client.get(SNAPSHOT, params=params)


_RANGE_TIMEOUT_SECONDS = 60  # see this function's own docstring


def get_range(days: int) -> dict:
    """The `days` most recent trade dates with saved historic-upload data,
    each pivoted the same way as get_snapshot — backs ExternalImport's
    "database" source (services.external_import_source), replacing what
    used to be one get_snapshot() call per date (issue #30: on a cold
    per-LiveDataReader-session cache, that meant up to ~70 individual HTTP
    round trips fired 8 at a time, which starved the backend's small
    worker pool and made unrelated in-flight requests — the live read
    itself, an N-Day strategy's day-history fetch — time out, looking like
    the whole app had frozen on a strategy's first apply). One bulk call
    here instead.

    A longer-than-default timeout, same rationale as api.lmv_snapshot_api.
    get_range: the payload scales with the full stock universe times
    *days*, not the generic 15s default's assumption of a quick CRUD round
    trip.
    """
    return api_client.get(RANGE, params={"days": days}, timeout=_RANGE_TIMEOUT_SECONDS)


def delete_day(trade_date: date) -> dict:
    return api_client.delete(f"{HISTORIC}/{trade_date.isoformat()}")
