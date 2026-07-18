from datetime import date

from api.client import api_client
from api.endpoints import HOLIDAYS


def list_holidays(year: int | None) -> list[dict]:
    params = {"year": year} if year is not None else None
    return api_client.get(HOLIDAYS, params=params)


def create_holiday(holiday_date: date, name: str) -> dict:
    return api_client.post(
        HOLIDAYS,
        json_body={"holiday_date": holiday_date.isoformat(), "name": name},
    )


def update_holiday(holiday_id: int, holiday_date: date, name: str) -> dict:
    return api_client.patch(
        f"{HOLIDAYS}/{holiday_id}",
        json_body={"holiday_date": holiday_date.isoformat(), "name": name},
    )


def delete_holiday(holiday_id: int) -> None:
    api_client.delete(f"{HOLIDAYS}/{holiday_id}")
