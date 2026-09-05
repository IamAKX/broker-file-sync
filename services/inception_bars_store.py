"""Local cache of Inception's raw daily bars (OPEN/HIGH/LOW/CLOSE/VOL/
OPENINT per instrument/date) — the first SQLite usage in this app (stdlib
sqlite3, no new dependency). Every other local-persistence pattern here
(services/inception_strategy_store.py, services/config_store.py) is a flat
JSON file mirroring a small server-side object; that doesn't scale to the
several-hundred-thousand-row bar history Group A/B computation needs (see
services.inception_formula_engine), hence a real table instead.

services.inception_sync_service is the only writer (backfill + incremental
delta sync against api.inception_api.get_bars); services.
inception_compute_service is the only reader that matters for correctness —
this module is deliberately a thin, dumb store with no knowledge of Group
A/B at all, just OHLCV rows keyed by (symbol, trade_date).

Not a Qt object and does no threading of its own — services.
inception_sync_service is responsible for calling into this from a QThread
where warranted (initial backfill can be several hundred thousand rows).
"""

import os
import sqlite3
from contextlib import contextmanager
from datetime import date

_DB_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "inception_bars.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS eod_bars (
    symbol TEXT NOT NULL,
    trade_date TEXT NOT NULL,
    open REAL NOT NULL,
    high REAL NOT NULL,
    low REAL NOT NULL,
    close REAL NOT NULL,
    volume INTEGER NOT NULL,
    open_interest INTEGER,
    PRIMARY KEY (symbol, trade_date)
);
CREATE INDEX IF NOT EXISTS ix_eod_bars_date ON eod_bars (trade_date);
"""

# Admin Controls > Inception Sync's own fields (services.
# inception_admin_sync_service in the backend repo; api.inception_api.
# get_bars/services.inception_sync_service on this side) — turnover/
# average-traded-price figures, populated only where that admin sync has
# actually run, null everywhere else. Same "blank rather than crash"
# convention as open_interest above.
LMV_METRIC_COLUMNS = [
    "avg_rate", "patp", "pwatp", "pmatp", "cwatp", "cmatp",
    "day_to", "pdto", "cwto", "pwto",
    # Options-OI/max-pain, Market Profile, and Opening Range — same
    # sync-populated/blank-otherwise convention as the metrics above (see
    # app/services/inception_admin_sync_service.py in the backend repo).
    "call_strike_highest_oi", "call_strike_with_second_highest_oi",
    "put_strike_with_second_highest_oi", "today_put_highest_strike",
    "max_pain", "vah", "poc", "val", "or_high", "or_low",
]


def _ensure_lmv_metric_columns(conn: sqlite3.Connection) -> None:
    """ALTER TABLE ADD COLUMN for each of LMV_METRIC_COLUMNS — CREATE
    TABLE IF NOT EXISTS above is a no-op against an eod_bars.db that
    already existed before this feature shipped, so a real column-
    presence check + ALTER is what actually adds them to an existing
    local install. Cheap (one PRAGMA query) and safe to run on every
    connection — sqlite3 has no "ADD COLUMN IF NOT EXISTS" of its own."""
    existing = {row[1] for row in conn.execute("PRAGMA table_info(eod_bars)")}
    for col in LMV_METRIC_COLUMNS:
        if col not in existing:
            conn.execute(f"ALTER TABLE eod_bars ADD COLUMN {col} REAL")


@contextmanager
def _connect():
    conn = sqlite3.connect(_DB_FILE)
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript(_SCHEMA)
        _ensure_lmv_metric_columns(conn)
        yield conn
        conn.commit()
    finally:
        conn.close()


def clear_local_cache() -> None:
    """Deletes the local bars database entirely — a full re-sync starts from
    scratch after this. Used by File > Clear Cache and by tests; also the
    right recovery path if the local cache is ever suspected corrupt."""
    for suffix in ("", "-wal", "-shm"):
        path = _DB_FILE + suffix
        if os.path.exists(path):
            os.remove(path)


def upsert_bars(rows: list[dict]) -> int:
    """rows: [{"symbol", "trade_date" (date or ISO str), "open", "high",
    "low", "close", "volume", "open_interest", <LMV_METRIC_COLUMNS, each
    optional>}, ...]. Returns the number of rows written. A row missing an
    LMV_METRIC_COLUMNS key (e.g. api.inception_api.get_bars against a
    backend that hasn't run Admin Controls > Inception Sync for that
    instrument/date yet) writes None for it, same as a genuinely-absent
    value — not a KeyError."""
    if not rows:
        return 0
    values = [
        (
            r["symbol"],
            r["trade_date"].isoformat() if isinstance(r["trade_date"], date) else r["trade_date"],
            float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]),
            int(r["volume"]), r.get("open_interest"),
            *[r.get(col) for col in LMV_METRIC_COLUMNS],
        )
        for r in rows
    ]
    columns_sql = ", ".join(LMV_METRIC_COLUMNS)
    placeholders = ", ".join("?" * len(LMV_METRIC_COLUMNS))
    with _connect() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO eod_bars "
            f"(symbol, trade_date, open, high, low, close, volume, open_interest, {columns_sql}) "
            f"VALUES (?, ?, ?, ?, ?, ?, ?, ?, {placeholders})",
            values,
        )
    return len(values)


def last_synced_date() -> date | None:
    """The most recent trade_date across every symbol in the local store, or
    None if nothing's been synced yet. services.inception_sync_service's
    incremental_sync uses this as the starting point for its next delta
    fetch."""
    with _connect() as conn:
        row = conn.execute("SELECT MAX(trade_date) FROM eod_bars").fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def latest_synced_date_on_or_before(as_of: date) -> date | None:
    """The latest trade_date <= as_of across every symbol — every synced
    instrument shares the same trading calendar, so this is a single
    indexed MAX() query rather than per-symbol scanning. Used by
    services.inception_compute_service.hmv to resolve "as of the range's
    last trading day" purely from local data."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT MAX(trade_date) FROM eod_bars WHERE trade_date <= ?", (as_of.isoformat(),)
        ).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def row_count() -> int:
    with _connect() as conn:
        return conn.execute("SELECT COUNT(*) FROM eod_bars").fetchone()[0]


def available_symbols() -> list[str]:
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT symbol FROM eod_bars ORDER BY symbol").fetchall()
    return [r[0] for r in rows]


def bars_for_symbol(symbol: str, date_from: date | None = None, date_to: date | None = None) -> list[dict]:
    """Ascending-by-trade_date bars for one symbol — the shape
    services.inception_formula_engine.compute_group_a/compute_group_b
    expect (trade_date as a date object, not a string)."""
    metric_cols_sql = ", " + ", ".join(LMV_METRIC_COLUMNS)
    sql = (
        f"SELECT trade_date, open, high, low, close, volume, open_interest{metric_cols_sql} "
        f"FROM eod_bars WHERE symbol = ?"
    )
    params: list = [symbol]
    if date_from is not None:
        sql += " AND trade_date >= ?"
        params.append(date_from.isoformat())
    if date_to is not None:
        sql += " AND trade_date <= ?"
        params.append(date_to.isoformat())
    sql += " ORDER BY trade_date"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_bar(r) for r in rows]


def bars_for_date(trade_date: date) -> list[dict]:
    """Every symbol's bar on one date — {"symbol": ..., "trade_date": ...,
    "open": ..., ...}."""
    metric_cols_sql = ", " + ", ".join(LMV_METRIC_COLUMNS)
    with _connect() as conn:
        rows = conn.execute(
            f"SELECT symbol, trade_date, open, high, low, close, volume, open_interest{metric_cols_sql} "
            "FROM eod_bars WHERE trade_date = ?",
            (trade_date.isoformat(),),
        ).fetchall()
    return [
        {
            "symbol": r[0], "trade_date": date.fromisoformat(r[1]),
            "open": r[2], "high": r[3], "low": r[4], "close": r[5],
            "volume": r[6], "open_interest": r[7],
            **dict(zip(LMV_METRIC_COLUMNS, r[8:])),
        }
        for r in rows
    ]


def _row_to_bar(r) -> dict:
    return {
        "trade_date": date.fromisoformat(r[0]),
        "open": r[1], "high": r[2], "low": r[3], "close": r[4],
        "volume": r[5], "open_interest": r[6],
        **dict(zip(LMV_METRIC_COLUMNS, r[7:])),
    }
