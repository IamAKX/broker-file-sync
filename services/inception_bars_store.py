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


def first_synced_date() -> date | None:
    """The earliest trade_date across every symbol in the local store (None if
    nothing's synced) — how far back a back-test can see."""
    with _connect() as conn:
        row = conn.execute("SELECT MIN(trade_date) FROM eod_bars").fetchone()
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


def _hidden_renamed(symbols) -> dict:
    """{old_symbol: new_symbol} for every renamed stock (services.
    symbol_renames) whose NEW symbol is also present in *symbols* — the old
    one's bars are folded into the new one's history, so it isn't listed as
    a separate instrument (issue #112)."""
    from services import symbol_renames
    present = set(symbols)
    return {
        old: new for old, new in symbol_renames.inception_rename_map().items()
        if old in present and new in present
    }


def available_symbols() -> list[str]:
    with _connect() as conn:
        rows = conn.execute("SELECT DISTINCT symbol FROM eod_bars ORDER BY symbol").fetchall()
    symbols = [r[0] for r in rows]
    hidden = _hidden_renamed(symbols)
    return [s for s in symbols if s not in hidden]


def bar_summaries(date_to: date | None = None) -> dict[str, tuple]:
    """{symbol: (bar_count, first_date, last_date)} over bars on or before
    *date_to* — one grouped query. Lets a caller that only needs these (e.g.
    a cache fingerprint) skip fetching every instrument's full ~5000-bar
    history."""
    sql = "SELECT symbol, COUNT(*), MIN(trade_date), MAX(trade_date) FROM eod_bars"
    params: list = []
    if date_to is not None:
        sql += " WHERE trade_date <= ?"
        params.append(date_to.isoformat())
    sql += " GROUP BY symbol"
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    out = {r[0]: (r[1], date.fromisoformat(r[2]), date.fromisoformat(r[3])) for r in rows}
    for old, new in _hidden_renamed(out).items():
        o_count, o_first, o_last = out.pop(old)
        n_count, n_first, n_last = out[new]
        # Only the old bars dated before the new symbol's first bar are
        # used (see bars_for_symbol) — an approximation of that count is
        # all a cache fingerprint needs.
        out[new] = (n_count + o_count, min(o_first, n_first), max(o_last, n_last))
    return out


def bars_for_symbol(symbol: str, date_from: date | None = None, date_to: date | None = None) -> list[dict]:
    """Ascending-by-trade_date bars for one symbol — the shape
    services.inception_formula_engine.compute_group_a/compute_group_b
    expect (trade_date as a date object, not a string).

    For a renamed stock (services.symbol_renames) the OLD symbol's bars
    dated before the new symbol's first bar are prepended, so the new name
    carries its whole history (issue #112)."""
    from services import symbol_renames
    own = _bars_for_raw_symbol(symbol, date_from, date_to)
    older = [
        _bars_for_raw_symbol(old, date_from, date_to)
        for old in symbol_renames.inception_old_symbols_for(symbol)
    ]
    older = [b for b in older if b]
    if not older:
        return own
    if date_from is not None:
        # *own* may start later than the new symbol's real first bar (the
        # window cut it) — the old bars only count when they predate that.
        first_new = _first_bar_date(symbol)
        if first_new is not None:
            older = [[b for b in bars if b["trade_date"] < first_new] for bars in older]
    return symbol_renames.merge_bar_histories(own, older)


def _first_bar_date(symbol: str) -> date | None:
    with _connect() as conn:
        row = conn.execute("SELECT MIN(trade_date) FROM eod_bars WHERE symbol = ?", (symbol,)).fetchone()
    return date.fromisoformat(row[0]) if row and row[0] else None


def _bars_for_raw_symbol(symbol: str, date_from: date | None = None, date_to: date | None = None) -> list[dict]:
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
    from services import symbol_renames
    renames = symbol_renames.inception_rename_map()
    present = {r[0] for r in rows}
    out = []
    for r in rows:
        sym = r[0]
        new = renames.get(sym)
        if new is not None:
            if new in present:
                continue
            sym = new
            present.add(new)
        out.append(_date_row_to_bar(sym, r))
    return out


def _date_row_to_bar(symbol: str, r) -> dict:
    return {
        "symbol": symbol, "trade_date": date.fromisoformat(r[1]),
        "open": r[2], "high": r[3], "low": r[4], "close": r[5],
        "volume": r[6], "open_interest": r[7],
        **dict(zip(LMV_METRIC_COLUMNS, r[8:])),
    }


def _row_to_bar(r) -> dict:
    return {
        "trade_date": date.fromisoformat(r[0]),
        "open": r[1], "high": r[2], "low": r[3], "close": r[4],
        "volume": r[5], "open_interest": r[6],
        **dict(zip(LMV_METRIC_COLUMNS, r[7:])),
    }
