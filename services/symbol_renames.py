"""Stock symbol renames (old exchange symbol -> new one), e.g. NSE renaming
ICICIPRULI to ICICILIFE on 23-Oct-2026 (issue #112).

After a rename the history is split under two names everywhere it is stored
by symbol:

* LMV daily snapshots on the backend (``/lmv-snapshot/range``): every day up
  to the rename is saved under the OLD symbol, every day after under the NEW
  one. N-day / day-history formula columns (MAX_DAYS, VALUE_DAYS_AGO, row
  filter streaks, ...) for the new symbol then see only the few days since the
  rename and come back blank.
* Inception EOD bars (``inception_bars.db``): ``ICICIPRULI_I`` holds 2017 ->
  22-Oct, ``ICICILIFE_I`` only the days since. 52WH, ATH, gap areas, etc. for
  the new name are computed from a few weeks of bars.

This module holds the rename list (Config Editor > "Symbol Rename" tab, key
``symbol_rename``; built-in defaults in config_defaults.SYMBOL_RENAME_DATA)
and the helpers that stitch the old history onto the new symbol. Reads are
LOCAL ONLY (config_data.json cache + defaults) — never a network call — so
they're safe on any thread, including inside a render pass or a per-tick
LMV path. The Config Editor refreshes that cache whenever it loads or saves
the tab.
"""

from __future__ import annotations

STORE_KEY = "symbol_rename"

_INCEPTION_SUFFIXES = ("_I", "_II")


def _rows_to_map(rows) -> dict:
    mapping: dict = {}
    for row in rows or []:
        if not isinstance(row, (list, tuple)) or len(row) < 2:
            continue
        old = str(row[0] or "").strip().upper()
        new = str(row[1] or "").strip().upper()
        if old and new and old != new:
            mapping[old] = new
    return mapping


def rename_map() -> dict:
    """{old_symbol: final_new_symbol} — chains (A->B, B->C) are resolved so
    every old name maps straight to the CURRENT symbol. Built-in defaults
    first, user rows (Config Editor) override them."""
    from config_defaults import SYMBOL_RENAME_DATA
    mapping = _rows_to_map(SYMBOL_RENAME_DATA)
    try:
        from services import config_store
        saved = config_store._load_raw().get(STORE_KEY)
    except Exception:
        saved = None
    if isinstance(saved, list):
        # A saved tab is the user's whole list — it replaces the defaults
        # (so deleting a default row really removes it).
        mapping = _rows_to_map(saved)

    resolved: dict = {}
    for old in mapping:
        cur, seen = old, {old}
        while cur in mapping and mapping[cur] not in seen:
            cur = mapping[cur]
            seen.add(cur)
        if cur != old:
            resolved[old] = cur
    return resolved


def old_names_for(new_symbol: str, mapping: dict | None = None) -> list[str]:
    """Every old symbol that was renamed to *new_symbol* (bare, no _I)."""
    mapping = rename_map() if mapping is None else mapping
    target = (new_symbol or "").upper()
    return [old for old, new in mapping.items() if new == target]


# ── Inception bar symbols ("ICICILIFE_I") ─────────────────────────────────

def _split_suffix(symbol: str) -> tuple[str, str]:
    for suffix in sorted(_INCEPTION_SUFFIXES, key=len, reverse=True):
        if symbol.endswith(suffix):
            return symbol[: -len(suffix)], suffix
    return symbol, ""


def inception_rename_map(mapping: dict | None = None) -> dict:
    """{"ICICIPRULI_I": "ICICILIFE_I", "ICICIPRULI_II": "ICICILIFE_II", ...}"""
    mapping = rename_map() if mapping is None else mapping
    out: dict = {}
    for old, new in mapping.items():
        for suffix in _INCEPTION_SUFFIXES:
            out[old + suffix] = new + suffix
        out[old] = new
    return out


def inception_old_symbols_for(symbol: str, mapping: dict | None = None) -> list[str]:
    """Old Inception bar symbols whose history belongs to *symbol*
    ("ICICILIFE_I" -> ["ICICIPRULI_I"])."""
    base, suffix = _split_suffix(symbol or "")
    return [old + suffix for old in old_names_for(base, mapping)]


def merge_bar_histories(current: list[dict], older: list[list[dict]]) -> list[dict]:
    """*current* (the new symbol's bars) plus every older-symbol bar dated
    before the new symbol's first bar, ascending by trade_date. On a date
    both carry, the new symbol's bar wins."""
    if not older:
        return current
    first_new = current[0]["trade_date"] if current else None
    merged = {}
    for bars in older:
        for bar in bars:
            if first_new is None or bar["trade_date"] < first_new:
                merged[bar["trade_date"]] = bar
    for bar in current:
        merged[bar["trade_date"]] = bar
    return [merged[d] for d in sorted(merged)]


# ── LMV snapshot range responses ─────────────────────────────────────────

def apply_to_range_response(response: dict, mapping: dict | None = None) -> dict:
    """Rewrite every day's stocks in an ``/lmv-snapshot/range`` (or
    ``/snapshot``) response so an old symbol's rows are reported under its
    new symbol — the history then lines up with today's live LMV row.
    If a day already has the new symbol, the old row is dropped (the new
    name's own data wins). Mutates and returns *response*."""
    mapping = rename_map() if mapping is None else mapping
    if not mapping or not isinstance(response, dict):
        return response
    days = response.get("days")
    day_list = days if isinstance(days, list) else [response]
    for day in day_list:
        stocks = day.get("stocks") if isinstance(day, dict) else None
        if not isinstance(stocks, list):
            continue
        present = {str(s.get("symbol") or "").upper() for s in stocks}
        kept = []
        for stock in stocks:
            sym = str(stock.get("symbol") or "").upper()
            new = mapping.get(sym)
            if new is None:
                kept.append(stock)
                continue
            if new in present:
                continue
            stock = dict(stock)
            stock["symbol"] = new
            if str(stock.get("display_name") or "").upper() == sym:
                stock["display_name"] = new
            present.add(new)
            kept.append(stock)
        day["stocks"] = kept
    return response
