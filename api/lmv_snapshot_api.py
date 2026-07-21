from datetime import date

from api.client import api_client
from api.endpoints import LMV_SNAPSHOT_DAILY_UPLOAD


def upload_daily(trade_date: date, rows: list[dict]) -> dict:
    return api_client.post(
        LMV_SNAPSHOT_DAILY_UPLOAD,
        json_body={"trade_date": trade_date.isoformat(), "rows": rows},
    )
