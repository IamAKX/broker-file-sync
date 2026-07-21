"""
Fetches ExternalImport's data table from the "database" source mode —
stored historic uploads run through services.formula_engine — in the exact
same (headers, rows) shape services.file_reader.read_external_import()
returns for the "file" source mode.

Keeping both source modes' output shape identical lets any caller (the
ExternalImport View popup, the Live Master View merge) treat "file" and
"database" interchangeably without knowing which one is active.
"""

from datetime import date, timedelta

from api import historic_api, holidays_api
from services import formula_engine

FORMULA_LOOKBACK_DAYS = 100


def read_external_import_db(target: date = None) -> tuple[list, list]:
    """Return (headers, rows) computed as of ``target`` (default: today).

    Returns ([], []) if no historic data has been uploaded yet. Network/API
    errors propagate to the caller — this function has no UI concerns.
    """
    headers, rows, _ = _fetch(target)
    return headers, rows


def read_external_import_db_with_live_baseline(target: date = None) -> tuple[list, list, dict]:
    """Like read_external_import_db, but also returns the per-symbol live-
    overlay baseline (see formula_engine.compute_live_baseline_for_symbol),
    keyed by the same ``symbol`` string as each row's own first column.

    Used only by the LMV's live source (services.live_merge) to blend this
    with today's live Sharekhan tick — the static ExternalImport "database"
    preview popup uses read_external_import_db instead and never needs it.
    """
    return _fetch(target)


def _fetch(target: date = None) -> tuple[list, list, dict]:
    target = target or date.today()
    date_from = target - timedelta(days=FORMULA_LOOKBACK_DAYS)

    availability = historic_api.get_availability(date_from, target)
    holidays = {
        date.fromisoformat(h["holiday_date"])
        for year in range(date_from.year, target.year + 1)
        for h in holidays_api.list_holidays(year)
    }

    available_dates = sorted(
        date.fromisoformat(d["trade_date"])
        for d in availability.get("dates", []) if d.get("has_data")
    )
    if not available_dates:
        return [], [], {}

    latest_available = available_dates[-1]
    raw_by_date = {}
    display_names = {}
    for d in available_dates:
        snapshot = historic_api.get_snapshot(d)
        stocks = snapshot.get("stocks", [])
        raw_by_date[d] = {s["symbol"]: s.get("metrics", {}) for s in stocks}
        if d == latest_available:
            display_names = {s["symbol"]: s.get("display_name") or "" for s in stocks}

    results, live_baselines = formula_engine.compute_all_with_live_baseline(
        raw_by_date, target, holidays
    )
    if not results:
        return [], [], {}

    headers = ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES
    rows = []
    for symbol in sorted(results.keys()):
        values = results[symbol]
        row = [symbol, display_names.get(symbol, "")]
        for code in formula_engine.FORMULA_CODES:
            v = values.get(code)
            row.append("" if v is None else round(v, 4))
        rows.append(row)
    return headers, rows, live_baselines
