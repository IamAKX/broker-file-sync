"""
Fetches ReliableSoftware, NiftyInvest, and MarketProfile's data columns from
the *last trading day's* already-saved LMV snapshot — the "database" source
mode for these three brokers on the Data Import screen (see
screens.data_import's single File/DB toggle, shared with ExternalImport).

Unlike ExternalImport's database mode (services.external_import_source,
formula_engine-computed as of today), these three don't run through any
formula — they're literally last trading day's already-merged LMV columns,
read back out of the same LmvDailySnapshot archive
services.scheduled_jobs.run_historic_save writes to every trading day.
"Last trading day" (services.trading_calendar.previous_trading_day) is used
rather than "latest day with data" — an intentionally-skipped trading day
should surface as missing data, not silently fall further back.

Output shape matches each broker's file-mode reader
(services.file_reader.read_reliable_software / read_nifty_invest_multi /
read_market_profile) exactly — column 0 is that broker's own join key,
verified against the real export layouts in resources/. ReliableSoftware's
file-mode join key is a full company name that services.master_generator
resolves through the Script Name config table before matching; here it's
already the resolved symbol, so services.live_merge.merge_broker_sources
falls back to matching it directly when that resolution comes up empty (see
its rs_lookup fallback) — NiftyInvest/MarketProfile's own file columns are
already symbols either way, so no such fallback is needed for them.
"""

from datetime import date

from api import lmv_snapshot_api
from services import trading_calendar

RELIABLE_HEADERS = [
    "ScripName", "callstrikehighestoi", "Callstrikewithsecondhighestoi",
    "PutStrikeWithsecondHighestOI", "TodayPutHighestStrike",
]
NIFTY_HEADERS = ["Symbol", "Max Pain"]
MARKET_PROFILE_HEADERS = ["stock", "VAH", "POC", "VAL"]


def last_trading_day(ref_date: date = None) -> date:
    """Most recent weekday that isn't a configured market holiday, strictly
    before ref_date (default: today) — same rule
    services.scheduled_jobs.run_availability_check uses for "yesterday"."""
    ref_date = ref_date or date.today()
    holidays = trading_calendar.get_holiday_set(ref_date.year - 1, ref_date.year)
    return trading_calendar.previous_trading_day(ref_date, holidays) or ref_date


def _fetch_snapshot_stocks(trade_date: date, snapshot_cache: dict | None = None) -> list:
    if snapshot_cache is not None and trade_date in snapshot_cache:
        return snapshot_cache[trade_date]
    stocks = lmv_snapshot_api.get_snapshot(trade_date).get("stocks", [])
    if snapshot_cache is not None:
        snapshot_cache[trade_date] = stocks
    return stocks


def read_reliable_software_db(trade_date: date, snapshot_cache: dict | None = None) -> tuple[list, list]:
    stocks = _fetch_snapshot_stocks(trade_date, snapshot_cache)
    rows = [
        [s["symbol"],
         s.get("metrics", {}).get("callstrikehighestoi"),
         s.get("metrics", {}).get("Callstrikewithsecondhighestoi"),
         s.get("metrics", {}).get("PutStrikeWithsecondHighestOI"),
         s.get("metrics", {}).get("TodayPutHighestStrike")]
        for s in stocks
    ]
    return RELIABLE_HEADERS, rows


def read_nifty_invest_db(trade_date: date, snapshot_cache: dict | None = None) -> tuple[list, list]:
    stocks = _fetch_snapshot_stocks(trade_date, snapshot_cache)
    rows = [[s["symbol"], s.get("metrics", {}).get("Max Pain")] for s in stocks]
    return NIFTY_HEADERS, rows


def read_market_profile_db(trade_date: date, snapshot_cache: dict | None = None) -> tuple[list, list]:
    stocks = _fetch_snapshot_stocks(trade_date, snapshot_cache)
    rows = [
        [s["symbol"],
         s.get("metrics", {}).get("VAH"),
         s.get("metrics", {}).get("POC"),
         s.get("metrics", {}).get("VAL")]
        for s in stocks
    ]
    return MARKET_PROFILE_HEADERS, rows
