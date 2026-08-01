"""
The background-scheduler jobs. Each takes (controller, notifier) so they
stay easy to unit test / call directly — no dependency on the Scheduler class
itself.
"""

from datetime import date, datetime, time as dtime

from api import historic_api, lmv_snapshot_api, opening_range_api
from api.exceptions import ApiError, NetworkError
from config_defaults import SCRIPT_NAME_DATA
from services import config_store, trading_calendar, trigger_config
from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix
from services.notifications import NotificationLevel

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

# NSE standard market open. The opening-range capture window is always
# "market open to the configured trigger time" — see
# _opening_range_window_minutes — so this is the one fixed end of that
# window; the other end (the trigger time itself) is what the Jobs screen
# lets the user configure.
OPENING_RANGE_TRIGGER_ID = "opening_range_capture"
_MARKET_OPEN_TIME = dtime(9, 15)


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


def _trading_day_gate(notifier, job_title: str) -> bool:
    """Whether `job_title`'s job should proceed today — used by every job that's
    a no-op on non-trading days. Both "today isn't a trading day" and "the
    trading-day check itself failed" get a notification instead of a silent
    return: nothing about why a scheduled job did nothing should happen only
    in the background.
    """
    try:
        is_trading_day = _is_today_trading_day()
    except ApiError as exc:
        if not _is_session_expired(exc):
            notifier.notify(
                f"{job_title} Skipped",
                f"Couldn't check whether today is a trading day — {job_title.lower()} "
                f"was skipped. Error: {exc.detail}",
                level=NotificationLevel.FAILURE,
            )
        return False
    except NetworkError as exc:
        notifier.notify(
            f"{job_title} Skipped",
            f"Couldn't reach the server to check whether today is a trading day — "
            f"{job_title.lower()} was skipped. Error: {exc}",
            level=NotificationLevel.FAILURE,
        )
        return False

    if not is_trading_day:
        notifier.notify(
            f"{job_title} Skipped",
            "Today isn't a trading day — nothing to do.",
            level=NotificationLevel.INFO,
        )
        return False
    return True


def run_lmv_check(controller, notifier) -> None:
    if not _trading_day_gate(notifier, "LMV Check"):
        return

    if controller.get_lmv_snapshot() is None:
        notifier.notify(
            "Load Live Master View",
            "LMV isn't loaded yet — load your broker files before today's historic save.",
            action=lambda: controller.show_and_navigate("data_import"),
            level=NotificationLevel.FAILURE,
        )
    else:
        notifier.notify(
            "Live Master View Loaded",
            "LMV is loaded and ready for today's historic save.",
            level=NotificationLevel.SUCCESS,
        )


def run_historic_save(controller, notifier) -> None:
    if not _trading_day_gate(notifier, "Historic Save"):
        return

    snapshot = controller.get_lmv_snapshot()
    if snapshot is None:
        notifier.notify(
            "Load Live Master View",
            "LMV isn't loaded — load your broker files so today's data can be "
            "saved. Data was not saved today.",
            action=lambda: controller.show_and_navigate("data_import"),
            level=NotificationLevel.FAILURE,
        )
        return

    headers, data = snapshot
    script_name_data = config_store.load_tab("script_name", SCRIPT_NAME_DATA)

    rows_payload = _build_rows_payload(headers, data, script_name_data)
    raw_ok = _upload_with_notify(
        lambda: historic_api.upload_daily(date.today(), rows_payload),
        controller, notifier, "Historic Save Failed",
    )

    # Independent of the raw-metric upload above — a failure in one (e.g. the
    # LMV snapshot's larger payload hitting a transient error) must not skip
    # or roll back the other; each is its own save with its own failure
    # notification.
    snapshot_payload = _build_lmv_snapshot_payload(headers, data, script_name_data)
    snapshot_ok = _upload_with_notify(
        lambda: lmv_snapshot_api.upload_daily(date.today(), snapshot_payload),
        controller, notifier, "LMV Snapshot Save Failed",
    )

    if raw_ok and snapshot_ok:
        notifier.notify(
            "Historic Save Completed",
            f"Today's data was saved successfully for {len(rows_payload)} stocks.",
            level=NotificationLevel.SUCCESS,
        )


def _upload_with_notify(upload, controller, notifier, failure_title: str) -> bool:
    """Returns whether `upload` succeeded — callers use this to decide
    whether an overall "saved successfully" notification is still warranted,
    and a session-expired (401) failure counts as not-ok without notifying
    (see _is_session_expired)."""
    try:
        upload()
        return True
    except ApiError as exc:
        if not _is_session_expired(exc):
            notifier.notify(
                failure_title,
                f"Couldn't save today's data — data was not saved today. Error: {exc.detail}",
                action=lambda: controller.show_and_navigate("historic_upload"),
                level=NotificationLevel.FAILURE,
            )
        return False
    except NetworkError as exc:
        notifier.notify(
            failure_title,
            f"Couldn't reach the server — data was not saved today. Error: {exc}",
            action=lambda: controller.show_and_navigate("historic_upload"),
            level=NotificationLevel.FAILURE,
        )
        return False


# ── Opening-range High/Low capture ───────────────────────────────────────────
#
# Saves each stock's highest High and lowest Low, as shown in the Live Master
# View, for the opening window of the trading day. Unlike a running total this
# job has to compute itself, "High"/"Low" in the LMV are already the day's
# cumulative high/low so far (fed live from the broker, distinct from the
# "P.High"/"P.Low" *previous*-day columns) — so capturing "the high/low of the
# first N minutes" only takes one snapshot, taken N minutes after market open,
# not continuous polling across the window. See screens/jobs.py for where the
# capture time (which implies N) is configured.

def _opening_range_window_minutes() -> int:
    """Minutes between market open and the configured capture trigger time —
    e.g. the default 09:30 capture time is a 15-minute window. Floored at 1
    so a misconfigured time at/before market open still produces a valid
    (if degenerate) window instead of a rejected upload."""
    configs = trigger_config.load_trigger_configs()
    capture_time = next(
        (c.time for c in configs if c.id == OPENING_RANGE_TRIGGER_ID), dtime(9, 30)
    )
    today = date.today()
    delta = datetime.combine(today, capture_time) - datetime.combine(today, _MARKET_OPEN_TIME)
    return max(1, int(delta.total_seconds() // 60))


def _build_opening_range_payload(headers: list, data: list, script_name_data: list) -> list:
    """One row per stock with a usable High/Low — symbol resolution matches
    _build_rows_payload (same script-name lookup / rolling-suffix strip) so
    the "symbol" identifier lines up with every other upload for the same
    stock.

    A row with a missing/non-numeric High or Low, or High < Low (a stale or
    bad tick), is silently dropped rather than failing the whole batch — the
    backend also rejects an upload containing any High < Low row, so this
    client-side filter is what keeps one bad stock from blocking every other
    stock's save.
    """
    if "Scrip Name" not in headers or "High" not in headers or "Low" not in headers:
        return []
    name_to_symbol = _build_script_name_lookup(script_name_data)
    scrip_idx = headers.index("Scrip Name")
    high_idx = headers.index("High")
    low_idx = headers.index("Low")

    rows = []
    for row in data:
        raw_name = str(row[scrip_idx]) if scrip_idx < len(row) else ""
        display_name = _strip_rolling_suffix(raw_name) or raw_name
        symbol = name_to_symbol.get(display_name.lower()) or display_name

        try:
            high = float(row[high_idx])
            low = float(row[low_idx])
        except (TypeError, ValueError, IndexError):
            continue
        if high < low:
            continue

        rows.append({"symbol": symbol, "display_name": display_name or None, "high": high, "low": low})
    return rows


def run_opening_range_capture(controller, notifier) -> None:
    if not _trading_day_gate(notifier, "Opening Range Capture"):
        return

    snapshot = controller.get_lmv_snapshot()
    if snapshot is None:
        notifier.notify(
            "Load Live Master View",
            "LMV isn't loaded — load your broker files so today's High/Low "
            "can be captured. High/Low was not saved today.",
            action=lambda: controller.show_and_navigate("data_import"),
            level=NotificationLevel.FAILURE,
        )
        return

    headers, data = snapshot
    script_name_data = config_store.load_tab("script_name", SCRIPT_NAME_DATA)
    rows_payload = _build_opening_range_payload(headers, data, script_name_data)

    if not rows_payload:
        notifier.notify(
            "Opening Range Capture Skipped",
            "No usable High/Low values were found in the Live Master View — "
            "High/Low was not saved today.",
            action=lambda: controller.show_and_navigate("data_import"),
            level=NotificationLevel.FAILURE,
        )
        return

    window_minutes = _opening_range_window_minutes()
    try:
        opening_range_api.upload_daily(date.today(), window_minutes, rows_payload)
    except ApiError as exc:
        if not _is_session_expired(exc):
            notifier.notify(
                "Opening Range Save Failed",
                f"Couldn't save today's High/Low — data was not saved today. Error: {exc.detail}",
                action=lambda: controller.show_and_navigate("data_import"),
                level=NotificationLevel.FAILURE,
            )
        return
    except NetworkError as exc:
        notifier.notify(
            "Opening Range Save Failed",
            f"Couldn't reach the server — High/Low was not saved today. Error: {exc}",
            action=lambda: controller.show_and_navigate("data_import"),
            level=NotificationLevel.FAILURE,
        )
        return

    notifier.notify(
        "Opening Range Saved",
        f"High and Low saved for {len(rows_payload)} stocks.",
        level=NotificationLevel.SUCCESS,
    )


def run_availability_check(controller, notifier) -> None:
    today = date.today()
    try:
        holidays = trading_calendar.get_holiday_set(today.year - 1, today.year)
        prev_day = trading_calendar.previous_trading_day(today, holidays)
        if prev_day is None:
            notifier.notify(
                "Historic Availability Check Skipped",
                "No previous trading day was found to check.",
                level=NotificationLevel.INFO,
            )
            return
        availability = historic_api.get_availability(prev_day, prev_day)
    except ApiError as exc:
        if not _is_session_expired(exc):
            notifier.notify(
                "Historic Availability Check Failed",
                f"Couldn't check whether yesterday's historic data was saved. Error: {exc.detail}",
                level=NotificationLevel.FAILURE,
            )
        return
    except NetworkError as exc:
        notifier.notify(
            "Historic Availability Check Failed",
            f"Couldn't reach the server to check whether yesterday's historic data was "
            f"saved. Error: {exc}",
            level=NotificationLevel.FAILURE,
        )
        return

    has_data = any(
        d.get("has_data") for d in availability.get("dates", [])
        if d.get("trade_date") == prev_day.isoformat()
    )
    if has_data:
        notifier.notify(
            "Historic Data Available",
            f"Historic data on file for {prev_day.strftime('%d-%b-%Y')}.",
            level=NotificationLevel.SUCCESS,
        )
    else:
        notifier.notify(
            "Missing Historic Data",
            f"No historic data on file for {prev_day.strftime('%d-%b-%Y')}.",
            action=lambda: controller.show_and_navigate("historic_upload"),
            level=NotificationLevel.FAILURE,
        )
