"""
Calculation engine for the ExternalImport "database" source.

Computes the 56 built-in formula codes (see services.formula_tokens.BUILTIN_FORMULAS)
per stock, from the raw daily metrics already stored via the Historic Upload feature
(Open, High, Low, Close, pdh, pdl, PClose, AvgRate, Quantity, DiffPcnt).

Calendar weeks run Monday..Sunday. Expiry week is the Mon..Sun week containing the
last Tuesday of the month (see services.master_generator.last_tuesday_of_month);
rollover week is the remainder of that month after the expiry week ends.

This module is pure/offline — it only operates on data already fetched from the
API (one snapshot per available trade_date, plus the tenant's /holidays list).
It never makes network calls itself; callers fetch raw_by_date and holidays and
pass them in.

Holiday-awareness: "working day" lookups (first/last trading day of a week or
month, previous trading day, last N trading days) are resolved against the real
calendar — weekday minus the holiday set — not against "whichever dates happen
to have data". A holiday is an expected non-trading day and is skipped without
comment; a real trading day with no uploaded data is a genuine gap and the
lookup returns None rather than silently substituting a nearby day's data.
"""

from datetime import date, timedelta

from services.master_generator import last_tuesday_of_month

RAW_OPEN = "Open"
RAW_HIGH = "High"
RAW_LOW = "Low"
RAW_CLOSE = "Close"
RAW_PDH = "pdh"
RAW_PDL = "pdl"
RAW_PCLOSE = "PClose"
RAW_AVGRATE = "AvgRate"
RAW_QUANTITY = "Quantity"
RAW_DIFFPCNT = "DiffPcnt"

FORMULA_CODES = [
    "CMH", "CML", "CWH", "CWL", "EWH", "EWL", "RWH", "RWL", "CWO", "FH", "FL",
    "DT", "DB", "PMH", "PML", "PMC", "PWH", "PWL", "PWC", "WT", "WB", "MT", "MB",
    "CMO", "DR3", "DR4", "DR6", "DS3", "DS4", "DS6", "WR3", "WR4", "WR6",
    "WS3", "WS4", "WS6", "MR3", "MR4", "MR6", "MS3", "MS4", "MS6",
    "PATP", "CWATP", "PWATP", "CMATP", "WEEK % CHANGE", "MONTH % CHANGE", "PMATP",
    "DAY TO", "PDTO", "CWTO", "PWTO", "DAY PIVOT", "WEEK PIVOT", "MONTH PIVOT",
]


class StockHistory:
    """Per-symbol lookup over {trade_date: {metric_name: value}}.

    holidays: set of market-holiday dates for this tenant (from GET /holidays)
    — used to tell an expected non-trading day (weekend/holiday, safely
    skipped) apart from a genuine gap (a real trading day with no uploaded
    data, which is missing, not a reason to search further for a substitute).
    """

    # Safety bound on the day-by-day search helpers below, so a pathological
    # holiday list (or a huge gap in uploads) can't loop unboundedly — in
    # practice a trading day is found within a handful of days.
    _SEARCH_LIMIT_DAYS = 30

    def __init__(self, rows_by_date: dict, holidays: set = frozenset()):
        self._rows = rows_by_date
        self._dates = sorted(rows_by_date.keys())
        self._holidays = holidays

    def get(self, metric: str, d: date):
        if d is None:
            return None
        row = self._rows.get(d)
        if row is None:
            return None
        return _to_float(row.get(metric))

    def is_trading_day(self, d: date) -> bool:
        return d.weekday() < 5 and d not in self._holidays

    def dates_in(self, d_from: date, d_to: date) -> list:
        return [d for d in self._dates if d_from <= d <= d_to]

    def trading_dates_in(self, d_from: date, d_to: date) -> list:
        """Like dates_in, but excludes any date uploaded on a weekend/holiday
        (defends against stray/mistaken data on a non-trading day)."""
        return [d for d in self.dates_in(d_from, d_to) if self.is_trading_day(d)]

    def first_trading_day_on_or_after(self, d: date, limit: date = None):
        """The first calendar trading day >= d, skipping weekends/holidays —
        not the first day with data. A trading day with no uploaded data is a
        gap; callers see that by getting None back from .get() for that day,
        not by this method quietly returning a later day instead."""
        cursor, steps = d, 0
        while steps < self._SEARCH_LIMIT_DAYS:
            if limit is not None and cursor > limit:
                return None
            if self.is_trading_day(cursor):
                return cursor
            cursor += timedelta(days=1)
            steps += 1
        return None

    def last_trading_day_on_or_before(self, d: date, limit: date = None):
        cursor, steps = d, 0
        while steps < self._SEARCH_LIMIT_DAYS:
            if limit is not None and cursor < limit:
                return None
            if self.is_trading_day(cursor):
                return cursor
            cursor -= timedelta(days=1)
            steps += 1
        return None

    def last_n_trading_days_on_or_before(self, d: date, n: int) -> list:
        result, cursor, steps = [], d, 0
        while len(result) < n and steps < self._SEARCH_LIMIT_DAYS:
            if self.is_trading_day(cursor):
                result.append(cursor)
            cursor -= timedelta(days=1)
            steps += 1
        return list(reversed(result))


def _to_float(v):
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _max(hist, metric, dates):
    vals = [v for v in (hist.get(metric, d) for d in dates) if v is not None]
    return max(vals) if vals else None


def _min(hist, metric, dates):
    vals = [v for v in (hist.get(metric, d) for d in dates) if v is not None]
    return min(vals) if vals else None


def _avg(hist, metric, dates):
    vals = [v for v in (hist.get(metric, d) for d in dates) if v is not None]
    return sum(vals) / len(vals) if vals else None


def _sum(hist, metric, dates):
    vals = [v for v in (hist.get(metric, d) for d in dates) if v is not None]
    return sum(vals) if vals else None


# ── Calendar bucket helpers (weeks run Monday..Sunday) ──────────────────────

def _week_start(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _week_end(d: date) -> date:
    return _week_start(d) + timedelta(days=6)


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _month_end(d: date) -> date:
    if d.month == 12:
        return date(d.year, 12, 31)
    return date(d.year, d.month + 1, 1) - timedelta(days=1)


def _prev_week_bounds(d: date):
    start = _week_start(d) - timedelta(days=7)
    return start, start + timedelta(days=6)


def _prev_month_bounds(d: date):
    last_of_prev = _month_start(d) - timedelta(days=1)
    return _month_start(last_of_prev), last_of_prev


def _nth_previous_week_bounds(d: date, n: int):
    """n=1 is the week immediately before d's week, n=2 the one before that, etc."""
    start = _week_start(d) - timedelta(days=7 * n)
    return start, start + timedelta(days=6)


def _nth_previous_month_bounds(d: date, n: int):
    month_start = _month_start(d)
    total = (month_start.year * 12 + (month_start.month - 1)) - n
    y, m = divmod(total, 12)
    start = date(y, m + 1, 1)
    return start, _month_end(start)


def _expiry_week_bounds_for_month(ref_date: date):
    tuesday = last_tuesday_of_month(ref_date)
    return _week_start(tuesday), _week_end(tuesday)


def _expiry_week_window(target: date):
    """The most recently FULLY COMPLETED expiry week, relative to target.

    EWH/EWL hold last month's expiry-week value for the entire month —
    including throughout this month's own expiry week while it's still in
    progress — and only switch over once this month's expiry week has fully
    ended (the Monday after it). Never returns a to-date/in-progress window.
    Walks back a month at a time so the rare case where an expiry week spills
    a few days into the next calendar month is handled correctly too.
    """
    ref = target
    while True:
        start, end = _expiry_week_bounds_for_month(ref)
        if end < target:
            return start, end
        ref = _month_start(ref) - timedelta(days=1)


def _rollover_window(target: date):
    """The calendar week immediately after the currently-held expiry week
    (see _expiry_week_window) — i.e. rollover week = expiry week + 1 week.
    Capped to target, so it's empty before that week begins and a to-date
    partial window while it's in progress (unlike expiry week, which holds
    until fully complete).
    """
    _, expiry_end = _expiry_week_window(target)
    roll_start = expiry_end + timedelta(days=1)
    roll_end = roll_start + timedelta(days=6)
    return roll_start, min(roll_end, target)


def _compute_cwto(hist: StockHistory, asof: date):
    """CURRENT WEEK TURNOVER as of a given date (reused for both CWTO and PWTO)."""
    if asof is None:
        return None
    week_start = _week_start(asof)
    dts = hist.trading_dates_in(week_start, asof)
    qty_sum = _sum(hist, RAW_QUANTITY, dts)
    cwatp = _avg(hist, RAW_AVGRATE, dts)
    close_v = hist.get(RAW_CLOSE, asof)
    pw_start, pw_end = _prev_week_bounds(asof)
    last_pw_day = hist.last_trading_day_on_or_before(pw_end, limit=pw_start)
    pwc_v = hist.get(RAW_CLOSE, last_pw_day) if last_pw_day else None
    if close_v is None or not pwc_v:
        return None
    week_pct = (close_v - pwc_v) / pwc_v * 100
    if qty_sum is None or cwatp is None:
        return None
    return (qty_sum * cwatp) / 10_000_000 * (abs(week_pct) / 100)


def _compute_day_to(hist: StockHistory, d: date):
    qty = hist.get(RAW_QUANTITY, d)
    avgrate = hist.get(RAW_AVGRATE, d)
    diffpcnt = hist.get(RAW_DIFFPCNT, d)
    if qty is None or avgrate is None or diffpcnt is None:
        return None
    return (qty * avgrate) / 10_000_000 * (abs(diffpcnt) / 100)


def compute_for_symbol(hist: StockHistory, target: date) -> dict:
    out = {}

    open_t = hist.get(RAW_OPEN, target)
    pdh_t = hist.get(RAW_PDH, target)
    pdl_t = hist.get(RAW_PDL, target)
    pclose_t = hist.get(RAW_PCLOSE, target)
    close_t = hist.get(RAW_CLOSE, target)

    month_start, week_start = _month_start(target), _week_start(target)
    mtd_dates = hist.trading_dates_in(month_start, target)
    wtd_dates = hist.trading_dates_in(week_start, target)

    out["CMH"] = _max(hist, RAW_HIGH, mtd_dates)
    out["CML"] = _min(hist, RAW_LOW, mtd_dates)
    out["CWH"] = _max(hist, RAW_HIGH, wtd_dates)
    out["CWL"] = _min(hist, RAW_LOW, wtd_dates)

    cwo_day = hist.first_trading_day_on_or_after(week_start, limit=target)
    out["CWO"] = hist.get(RAW_OPEN, cwo_day) if cwo_day else None
    cmo_day = hist.first_trading_day_on_or_after(month_start, limit=target)
    out["CMO"] = hist.get(RAW_OPEN, cmo_day) if cmo_day else None

    ew_start, ew_end = _expiry_week_window(target)
    ew_dates = hist.trading_dates_in(ew_start, ew_end)
    out["EWH"] = _max(hist, RAW_HIGH, ew_dates)
    out["EWL"] = _min(hist, RAW_LOW, ew_dates)

    rw_start, rw_end = _rollover_window(target)
    rw_dates = hist.trading_dates_in(rw_start, rw_end)
    out["RWH"] = _max(hist, RAW_HIGH, rw_dates)
    out["RWL"] = _min(hist, RAW_LOW, rw_dates)

    pw_start, pw_end = _prev_week_bounds(target)
    pw_dates = hist.trading_dates_in(pw_start, pw_end)
    last_pw_day = hist.last_trading_day_on_or_before(pw_end, limit=pw_start)
    out["FH"] = hist.get(RAW_HIGH, last_pw_day) if last_pw_day else None
    out["FL"] = hist.get(RAW_LOW, last_pw_day) if last_pw_day else None
    out["PWH"] = _max(hist, RAW_HIGH, pw_dates)
    out["PWL"] = _min(hist, RAW_LOW, pw_dates)
    out["PWC"] = hist.get(RAW_CLOSE, last_pw_day) if last_pw_day else None

    last5 = hist.last_n_trading_days_on_or_before(target, 5)
    out["DT"] = _max(hist, RAW_PCLOSE, last5)
    out["DB"] = _min(hist, RAW_PCLOSE, last5)

    pm_start, pm_end = _prev_month_bounds(target)
    pm_dates = hist.trading_dates_in(pm_start, pm_end)
    last_pm_day = hist.last_trading_day_on_or_before(pm_end, limit=pm_start)
    out["PMH"] = _max(hist, RAW_HIGH, pm_dates)
    out["PML"] = _min(hist, RAW_LOW, pm_dates)
    out["PMC"] = hist.get(RAW_CLOSE, last_pm_day) if last_pm_day else None

    week_closes = []
    for n in (1, 2, 3):
        wb_start, wb_end = _nth_previous_week_bounds(target, n)
        d = hist.last_trading_day_on_or_before(wb_end, limit=wb_start)
        if d is not None:
            week_closes.append(hist.get(RAW_CLOSE, d))
    week_closes = [c for c in week_closes if c is not None]
    out["WT"] = max(week_closes) if week_closes else None
    out["WB"] = min(week_closes) if week_closes else None

    month_closes = []
    for n in (1, 2):
        mb_start, mb_end = _nth_previous_month_bounds(target, n)
        d = hist.last_trading_day_on_or_before(mb_end, limit=mb_start)
        if d is not None:
            month_closes.append(hist.get(RAW_CLOSE, d))
    month_closes = [c for c in month_closes if c is not None]
    out["MT"] = max(month_closes) if month_closes else None
    out["MB"] = min(month_closes) if month_closes else None

    # Daily camarilla pivots — pure algebra on today's own pdh/pdl/pclose
    if pdh_t is not None and pdl_t is not None and pclose_t is not None:
        rng = pdh_t - pdl_t
        out["DR3"] = pclose_t + rng * 1.1 / 4
        out["DR4"] = pclose_t + rng * 1.1 / 2
        out["DR6"] = (pdh_t / pdl_t) * pclose_t if pdl_t else None
        out["DS3"] = pclose_t - rng * 1.1 / 4
        out["DS4"] = pclose_t - rng * 1.1 / 2
        out["DS6"] = pclose_t - (out["DR6"] - pclose_t) if out["DR6"] is not None else None
    else:
        for code in ("DR3", "DR4", "DR6", "DS3", "DS4", "DS6"):
            out[code] = None

    pwh, pwl, pwc = out["PWH"], out["PWL"], out["PWC"]
    if pwh is not None and pwl is not None and pwc is not None:
        rng = pwh - pwl
        out["WR3"] = pwc + rng * 1.1 / 4
        out["WR4"] = pwc + rng * 1.1 / 2
        out["WR6"] = (pwh / pwl) * pwc if pwl else None
        out["WS3"] = pwc - rng * 1.1 / 4
        out["WS4"] = pwc - rng * 1.1 / 2
        out["WS6"] = pwc - (out["WR6"] - pwc) if out["WR6"] is not None else None
    else:
        for code in ("WR3", "WR4", "WR6", "WS3", "WS4", "WS6"):
            out[code] = None

    pmh, pml, pmc = out["PMH"], out["PML"], out["PMC"]
    if pmh is not None and pml is not None and pmc is not None:
        rng = pmh - pml
        out["MR3"] = pmc + rng * 1.1 / 4
        out["MR4"] = pmc + rng * 1.1 / 2
        out["MR6"] = (pmh / pml) * pmc if pml else None
        out["MS3"] = pmc - rng * 1.1 / 4
        out["MS4"] = pmc - rng * 1.1 / 2
        out["MS6"] = pmc - (out["MR6"] - pmc) if out["MR6"] is not None else None
    else:
        for code in ("MR3", "MR4", "MR6", "MS3", "MS4", "MS6"):
            out[code] = None

    prev_day = hist.last_trading_day_on_or_before(target - timedelta(days=1))
    out["PATP"] = hist.get(RAW_AVGRATE, prev_day) if prev_day else None
    out["CWATP"] = _avg(hist, RAW_AVGRATE, wtd_dates)
    out["PWATP"] = _avg(hist, RAW_AVGRATE, pw_dates)
    out["CMATP"] = _avg(hist, RAW_AVGRATE, mtd_dates)
    out["PMATP"] = _avg(hist, RAW_AVGRATE, pm_dates)

    out["WEEK % CHANGE"] = (
        (close_t - pwc) / pwc * 100 if close_t is not None and pwc else None
    )
    out["MONTH % CHANGE"] = (
        (close_t - pmc) / pmc * 100 if close_t is not None and pmc else None
    )

    out["DAY TO"] = _compute_day_to(hist, target)
    out["PDTO"] = _compute_day_to(hist, prev_day) if prev_day else None
    out["CWTO"] = _compute_cwto(hist, target)
    out["PWTO"] = _compute_cwto(hist, last_pw_day) if last_pw_day else None

    out["DAY PIVOT"] = (
        (pdh_t + pdl_t + pclose_t) / 3
        if pdh_t is not None and pdl_t is not None and pclose_t is not None
        else None
    )
    out["WEEK PIVOT"] = (pwh + pwl + pwc) / 3 if pwh is not None and pwl is not None and pwc is not None else None
    out["MONTH PIVOT"] = (pmh + pml + pmc) / 3 if pmh is not None and pml is not None and pmc is not None else None

    return out


def compute_all(raw_by_date: dict, target: date, holidays: set = frozenset()) -> dict:
    """raw_by_date: {trade_date: {symbol: {metric_name: value}}} for whatever
    dates were fetched (already filtered to dates confirmed available).
    holidays: set of market-holiday dates for this tenant (GET /holidays) —
    see StockHistory for how this disambiguates a holiday from a data gap.

    target is always "today" (the real calendar date), not the latest date
    with data — CWH/CMH/etc. must mean the actual current week/month, even
    on days before that day's own upload has landed. The stock universe is
    therefore taken from the most recent date present in raw_by_date rather
    than from target's own (possibly nonexistent) snapshot; formulas that
    need target's own row (DR3, DAY TO, ...) correctly come back None when
    today has no upload yet, while window-based formulas still compute from
    whatever history exists relative to today.
    """
    if not raw_by_date:
        return {}
    latest_date = max(raw_by_date.keys())
    target_symbols = raw_by_date.get(latest_date, {})
    by_symbol: dict = {sym: {} for sym in target_symbols}
    for d, symbols in raw_by_date.items():
        for sym, metrics in symbols.items():
            if sym in by_symbol:
                by_symbol[sym][d] = metrics

    results = {}
    for sym, rows_by_date in by_symbol.items():
        hist = StockHistory(rows_by_date, holidays)
        results[sym] = compute_for_symbol(hist, target)
    return results
