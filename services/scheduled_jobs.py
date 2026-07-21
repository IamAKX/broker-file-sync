"""
The 3 background-scheduler jobs. Each takes (controller, notifier) so they
stay easy to unit test / call directly — no dependency on the Scheduler class
itself.
"""

from datetime import date

from api import historic_api, lmv_snapshot_api
from api.exceptions import ApiError, NetworkError
from config_defaults import SCRIPT_NAME_DATA
from services import config_store, trading_calendar
from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix

# Raw historic-upload metric name -> Sharekhan-shaped LMV column name.
# Fixed mapping, not user-editable (see plan doc) — verified against
# services/master_generator.py's Sharekhan column-order docstring.
#
# pdh/pdl/PClose/PQuantity are deliberately absent here — they're still read
# from the broker file into the Live Master View unchanged (see
# config_defaults.MAIN_COLUMN_NAME_DATA), just never uploaded to the backend.
# services/formula_engine.py derives the same "previous trading day" values
# from our own stored High/Low/Close instead of relying on them.
RAW_TO_SHAREKHAN_COLUMN = {
    "DiffPcnt": "% Change",
    "Open": "Open",
    "High": "High",
    "Low": "Low",
    "Close": "Current",
    "AvgRate": "Avg Rate",
    "Quantity": "Qty",
}

# Columns present in the LMV grid (services.live_merge.LiveDataReader.read_merged,
# see screens/live_viewer.py's self._headers) that are neither an imported broker
# column nor a formula_engine-computed one, so they're excluded from the full LMV
# snapshot upload: "Sector" is a local config lookup (services.config_store's
# sector_stock tab), not sourced from any file or the backend, and "Scrip Name" is
# just the join key already carried as the row's own symbol/display_name — every
# other header is either straight from a broker file or one of
# formula_engine.FORMULA_CODES. Strategy columns never appear here at all: they're
# appended to the *display* copy of headers/data only, inside
# live_viewer.py::_populate_table, never written back into self._headers/self._data.
_LMV_SNAPSHOT_EXCLUDED_HEADERS = {"Sector", "Scrip Name"}


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


def _build_lmv_snapshot_payload(headers: list, data: list, script_name_data: list) -> list:
    """Like _build_rows_payload, but keeps every LMV column instead of just the
    7 raw ones — every imported broker column plus every formula_engine
    computed column, excluding _LMV_SNAPSHOT_EXCLUDED_HEADERS. Feeds the
    separate LmvDailySnapshot archive (see api/lmv_snapshot_api.py), not the
    HistoricalStockValue table used for formula recomputation.
    """
    name_to_symbol = _build_script_name_lookup(script_name_data)
    scrip_idx = headers.index("Scrip Name")
    value_indices = [
        i for i, h in enumerate(headers) if h not in _LMV_SNAPSHOT_EXCLUDED_HEADERS
    ]

    rows = []
    for row in data:
        raw_name = str(row[scrip_idx]) if scrip_idx < len(row) else ""
        display_name = _strip_rolling_suffix(raw_name) or raw_name
        symbol = name_to_symbol.get(display_name.lower()) or display_name

        metrics = {headers[i]: row[i] for i in value_indices if i < len(row)}

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
    _upload_with_notify(
        lambda: historic_api.upload_daily(date.today(), rows_payload),
        controller, notifier, "Historic Save Failed",
    )

    # Independent of the raw-metric upload above — a failure in one (e.g. the
    # LMV snapshot's larger payload hitting a transient error) must not skip
    # or roll back the other; each is its own save with its own failure
    # notification.
    snapshot_payload = _build_lmv_snapshot_payload(headers, data, script_name_data)
    _upload_with_notify(
        lambda: lmv_snapshot_api.upload_daily(date.today(), snapshot_payload),
        controller, notifier, "LMV Snapshot Save Failed",
    )


def _upload_with_notify(upload, controller, notifier, failure_title: str) -> None:
    try:
        upload()
    except ApiError as exc:
        if not _is_session_expired(exc):
            notifier.notify(
                failure_title,
                "Couldn't save today's data — data was not saved today.",
                action=lambda: controller.show_and_navigate("historic_upload"),
            )
    except NetworkError:
        notifier.notify(
            failure_title,
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
