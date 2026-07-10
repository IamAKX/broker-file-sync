from datetime import date

from api.client import api_client
from api.endpoints import AVAILABILITY, DAILY_UPLOAD, SNAPSHOT


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
