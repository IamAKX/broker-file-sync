from datetime import date

from api.client import api_client
from api.endpoints import (
    OPENING_RANGE,
    OPENING_RANGE_AVAILABILITY,
    OPENING_RANGE_DAILY_UPLOAD,
    OPENING_RANGE_SNAPSHOT,
)


def upload_daily(trade_date: date, window_minutes: int, rows: list[dict]) -> dict:
    return api_client.post(
        OPENING_RANGE_DAILY_UPLOAD,
        json_body={
            "trade_date": trade_date.isoformat(),
            "window_minutes": window_minutes,
            "rows": rows,
        },
    )


def get_availability(date_from: date, date_to: date) -> dict:
    return api_client.get(
        OPENING_RANGE_AVAILABILITY,
        params={"from": date_from.isoformat(), "to": date_to.isoformat()},
    )


def get_snapshot(trade_date: date | None) -> dict:
    params = {"date": trade_date.isoformat()} if trade_date is not None else None
    return api_client.get(OPENING_RANGE_SNAPSHOT, params=params)


def delete_day(trade_date: date) -> dict:
    return api_client.delete(f"{OPENING_RANGE}/{trade_date.isoformat()}")
