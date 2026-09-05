from datetime import date

from api.client import api_client
from api.endpoints import (
    LMV_SNAPSHOT,
    LMV_SNAPSHOT_AVAILABILITY,
    LMV_SNAPSHOT_DAILY_UPLOAD,
    LMV_SNAPSHOT_RANGE,
    LMV_SNAPSHOT_SNAPSHOT,
)


def upload_daily(trade_date: date, rows: list[dict]) -> dict:
    return api_client.post(
        LMV_SNAPSHOT_DAILY_UPLOAD,
        json_body={"trade_date": trade_date.isoformat(), "rows": rows},
    )


def get_availability(date_from: date, date_to: date) -> dict:
    return api_client.get(
        LMV_SNAPSHOT_AVAILABILITY,
        params={"from": date_from.isoformat(), "to": date_to.isoformat()},
    )


def get_snapshot(trade_date: date | None) -> dict:
    params = {"date": trade_date.isoformat()} if trade_date is not None else None
    return api_client.get(LMV_SNAPSHOT_SNAPSHOT, params=params)


def delete_day(trade_date: date) -> dict:
    return api_client.delete(f"{LMV_SNAPSHOT}/{trade_date.isoformat()}")


_RANGE_TIMEOUT_SECONDS = 60  # see this function's own docstring


def get_range(days: int) -> dict:
    """The `days` most recent trade dates with saved snapshot data, each
    pivoted the same way as get_snapshot — backs the Formula Stats feature's
    per-day recomputation (see services/formula_stats_engine.py), and
    Live Master View's "N-Day Data" refresh (services.formula_stats_engine.
    compute_day_history, via screens/live_viewer.py).

    A longer-than-default timeout: unlike most calls this app makes, this
    one's payload scales with the full stock universe times *days* (a
    single-day pivot across ~78 metrics/stock, times up to 90 days —
    services.formula_stats_engine's own _MAX_SNAPSHOT_RANGE_DAYS) — the
    generic 15s default was a frequent, spurious "Read timed out" on this
    specific endpoint even when the server was perfectly reachable, just
    still generating the response (issue #22: "the columns for this
    strategy ends up empty" — components.formula_stats_panel.compute()
    aborts and shows nothing on ANY exception here, timeout or not).
    """
    return api_client.get(LMV_SNAPSHOT_RANGE, params={"days": days}, timeout=_RANGE_TIMEOUT_SECONDS)
