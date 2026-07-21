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
from services import config_store, formula_engine, formula_tokens

FORMULA_LOOKBACK_DAYS = 100


def _load_custom_defs() -> dict:
    """{code: tokens} for user-defined formulas (screens.formula_builder)
    that are actually computable (see
    formula_engine.is_computable_custom_formula) and don't collide with a
    built-in code — built-ins always go through the trusted, tested
    per-code path in formula_engine.py, never this one. First occurrence
    wins on duplicate codes.
    """
    formulas = config_store.load_json(formula_tokens.STORE_KEY, [])
    custom_defs = {}
    for f in formulas:
        code = (f.get("code") or "").strip()
        if not code or code in formula_engine.FORMULA_CODES or code in custom_defs:
            continue
        tokens = f.get("tokens") or []
        if formula_engine.is_computable_custom_formula(tokens):
            custom_defs[code] = tokens
    return custom_defs


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

    custom_defs = _load_custom_defs()
    results, live_baselines, custom_results = formula_engine.compute_all_with_live_baseline(
        raw_by_date, target, holidays, custom_defs
    )
    if not results:
        return [], [], {}

    headers = ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES + list(custom_defs.keys())
    rows = []
    for symbol in sorted(results.keys()):
        values = results[symbol]
        row = [symbol, display_names.get(symbol, "")]
        for code in formula_engine.FORMULA_CODES:
            v = values.get(code)
            row.append("" if v is None else round(v, 4))
        custom_values = custom_results.get(symbol, {})
        for code in custom_defs:
            v = custom_values.get(code)
            row.append("" if v is None else round(v, 4))
        rows.append(row)
    return headers, rows, live_baselines
