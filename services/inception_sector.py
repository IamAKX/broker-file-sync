"""Sector lookup for Inception's futures universe — reuses the same
(Sector, Stock) table screens.live_viewer's own Sector column is built from:
Config Editor's persisted "sector_stock" tab override (services.config_store,
screens.config_editor's "Sector Stock" tab) if the user has ever saved one,
else config_defaults.SECTOR_STOCK_DATA — so both stay in sync with one edit
instead of maintaining two copies, and a rename saved in Config Editor (e.g.
LTIM -> LTM to match a vendor feed's own spelling) actually takes effect here
too instead of only looking saved.

Kept as a standalone module (not imported from screens.live_viewer, whose
sector helpers are private/inline to that file) so screens.inception_hmv and
screens.inception_view_by_date share one implementation instead of
duplicating the same dict-comprehension twice.
"""

import re

from config_defaults import SECTOR_STOCK_DATA


def _normalize(symbol: str) -> str:
    """Collapses punctuation differences between LMV's own symbol spelling
    (SECTOR_STOCK_DATA, e.g. "BAJAJ-AUTO", "M&M", "NAM-INDIA") and the
    historical/Inception feed's underscore-only spelling for the same
    instrument (e.g. "BAJAJ_AUTO", "M_M", "NAM_INDIA") down to one
    comparable key, so a sector lookup keyed on one side still matches a
    symbol spelled on the other. Every non-alphanumeric character is
    stripped rather than mapped 1:1 (e.g. "_" -> "-") because a single "_"
    on the historical side can stand in for either a "-" or a "&" on LMV's
    side, and there's no way to tell which without a per-stock alias table
    that would need updating every time a new stock hits this same mismatch
    — verified collision-free across the full SECTOR_STOCK_DATA table (see
    tests.test_inception_sector).
    """
    return re.sub(r"[^A-Z0-9]", "", str(symbol).strip().upper())


_MAP: dict = {_normalize(stock): sector for sector, stock in SECTOR_STOCK_DATA}
# ^ pure config_defaults at import time, deliberately with no network I/O
# this early (the app may not even have a logged-in session yet when this
# module is first imported) — same reasoning as every other screen that
# builds its own sector map lazily inside __init__/a button handler rather
# than at import time. refresh() (called from inject_sector_rows, well after
# startup) is what pulls in Config Editor's persisted override.


def refresh() -> None:
    """Rebuilds the sector lookup from Config Editor's currently-persisted
    "sector_stock" table (services.config_store, screens.config_editor's
    "Sector Stock" tab) if the user has saved one, else config_defaults.
    SECTOR_STOCK_DATA. inject_sector_rows calls this once per batch so a
    rename saved in Config Editor (e.g. LTIM -> LTM to match a vendor feed's
    own spelling) shows up the next time a screen loads, without needing an
    app restart."""
    from services import config_store
    global _MAP
    rows = config_store.load_tab("sector_stock", SECTOR_STOCK_DATA)
    _MAP = {_normalize(stock): sector for sector, stock in rows}


def sector_for(symbol: str) -> str:
    """"—" for anything not in the sector table (matches screens.live_viewer's
    own fallback for an unmapped scrip)."""
    return _MAP.get(_normalize(symbol), "—")


def all_sectors() -> list:
    return sorted(set(_MAP.values()))


def inject_sector_rows(headers: list, data: list) -> tuple:
    """Prepends a "Sector" column to *headers* and every row in *data*.
    Assumes headers[...] contains "Symbol" (both screens.inception_hmv and
    screens.inception_view_by_date build their base headers as ["Symbol"] +
    metric codes) — looked up by name rather than assumed to be index 0, so
    call order relative to other column-prepending steps doesn't matter.
    """
    refresh()
    sym_idx = headers.index("Symbol")
    new_headers = ["Sector"] + list(headers)
    new_data = [[sector_for(row[sym_idx])] + list(row) for row in data]
    return new_headers, new_data
