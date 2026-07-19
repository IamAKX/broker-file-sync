"""
The 3 background-scheduler jobs. Each takes (controller, notifier) so they
stay easy to unit test / call directly — no dependency on the Scheduler class
itself.
"""

from datetime import date

from api import historic_api
from api.exceptions import ApiError, NetworkError
from config_defaults import SCRIPT_NAME_DATA
from services import config_store, trading_calendar
from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix

# Raw historic-upload metric name -> Sharekhan-shaped LMV column name.
# Fixed mapping, not user-editable (see plan doc) — verified against
# services/master_generator.py's Sharekhan column-order docstring.
RAW_TO_SHAREKHAN_COLUMN = {
    "DiffPcnt": "% Change",
    "Open": "Open",
    "High": "High",
    "Low": "Low",
    "Close": "Current",
    "pdh": "P.High",
    "pdl": "P.Low",
    "PClose": "Close",
    "AvgRate": "Avg Rate",
    "Quantity": "Qty",
    "PQuantity": "P.Quantity",
}


def _is_session_expired(exc: ApiError) -> bool:
    # A 401 here means the login screen has already (or is about to be)
    # surfaced by api_client's session-expired callback — a second "data
    # wasn't saved" notification on top of that would just be noise.
    return exc.status_code == 401


def _build_rows_payload(headers: list, data: list, script_name_data: list) -> list:
    name_to_symbol = _build_script_name_lookup(script_name_data)
    scrip_idx = headers.index("Scrip Name")
    col_idx = {sk_col: headers.index(sk_col)
               for sk_col in RAW_TO_SHAREKHAN_COLUMN.values() if sk_col in headers}

    rows = []
    for row in data:
        raw_name = str(row[scrip_idx]) if scrip_idx < len(row) else ""
        display_name = _strip_rolling_suffix(raw_name) or raw_name
        symbol = name_to_symbol.get(display_name.lower()) or display_name

        metrics = {}
        for raw_metric_name, sk_col in RAW_TO_SHAREKHAN_COLUMN.items():
            idx = col_idx.get(sk_col)
            if idx is not None and idx < len(row):
                metrics[raw_metric_name] = row[idx]

        rows.append({"symbol": symbol, "display_name": display_name or None, "metrics": metrics})
    return rows


def _is_today_trading_day() -> bool:
    today = date.today()
    holidays = trading_calendar.get_holiday_set(today.year, today.year)
    return trading_calendar.is_trading_day(today, holidays)


def run_lmv_check(controller, notifier) -> None:
    try:
        if not _is_today_trading_day():
            return
    except (ApiError, NetworkError):
        return   # transient — re-checked on the next 30s poll

    if controller.get_lmv_snapshot() is None:
        notifier.notify(
            "Load Live Master View",
            "LMV isn't loaded yet — load your broker files before today's historic save.",
            action=lambda: controller.show_and_navigate("data_import"),
        )


def run_historic_save(controller, notifier) -> None:
    try:
        if not _is_today_trading_day():
            return
    except (ApiError, NetworkError):
        return   # transient — re-checked on the next 30s poll

    snapshot = controller.get_lmv_snapshot()
    if snapshot is None:
        notifier.notify(
            "Historic Save Skipped",
            "Live Master View isn't loaded — data was not saved today.",
            action=lambda: controller.show_and_navigate("historic_upload"),
        )
        return

    headers, data = snapshot
    script_name_data = config_store.load_tab("script_name", SCRIPT_NAME_DATA)
    rows_payload = _build_rows_payload(headers, data, script_name_data)

    try:
        historic_api.upload_daily(date.today(), rows_payload)
    except ApiError as exc:
        if not _is_session_expired(exc):
            notifier.notify(
                "Historic Save Failed",
                "Couldn't save today's data — data was not saved today.",
                action=lambda: controller.show_and_navigate("historic_upload"),
            )
    except NetworkError:
        notifier.notify(
            "Historic Save Failed",
            "Couldn't reach the server — data was not saved today.",
            action=lambda: controller.show_and_navigate("historic_upload"),
        )


def run_availability_check(controller, notifier) -> None:
    today = date.today()
    try:
        holidays = trading_calendar.get_holiday_set(today.year - 1, today.year)
        prev_day = trading_calendar.previous_trading_day(today, holidays)
        if prev_day is None:
            return
        availability = historic_api.get_availability(prev_day, prev_day)
    except (ApiError, NetworkError):
        return   # transient — re-checked on the next 30s poll before day rolls over

    has_data = any(
        d.get("has_data") for d in availability.get("dates", [])
        if d.get("trade_date") == prev_day.isoformat()
    )
    if not has_data:
        notifier.notify(
            "Missing Historic Data",
            f"No historic data on file for {prev_day.strftime('%d-%b-%Y')}.",
            action=lambda: controller.show_and_navigate("historic_upload"),
        )
