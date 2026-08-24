"""Sector lookup for Inception's futures universe — reuses the same
config_defaults.SECTOR_STOCK_DATA table screens.live_viewer's own Sector
column is built from (LMV's ``_sector_map``/``_inject_sector_rows``), so
both stay in sync with one edit instead of maintaining two copies.

Kept as a standalone module (not imported from screens.live_viewer, whose
sector helpers are private/inline to that file) so screens.inception_hmv and
screens.inception_view_by_date share one implementation instead of
duplicating the same dict-comprehension twice.
"""

from config_defaults import SECTOR_STOCK_DATA

_MAP: dict = {stock.strip().upper(): sector for sector, stock in SECTOR_STOCK_DATA}


def sector_for(symbol: str) -> str:
    """"—" for anything not in the sector table (matches screens.live_viewer's
    own fallback for an unmapped scrip)."""
    return _MAP.get(str(symbol).strip().upper(), "—")


def all_sectors() -> list:
    return sorted(set(_MAP.values()))


def inject_sector_rows(headers: list, data: list) -> tuple:
    """Prepends a "Sector" column to *headers* and every row in *data*.
    Assumes headers[...] contains "Symbol" (both screens.inception_hmv and
    screens.inception_view_by_date build their base headers as ["Symbol"] +
    metric codes) — looked up by name rather than assumed to be index 0, so
    call order relative to other column-prepending steps doesn't matter.
    """
    sym_idx = headers.index("Symbol")
    new_headers = ["Sector"] + list(headers)
    new_data = [[sector_for(row[sym_idx])] + list(row) for row in data]
    return new_headers, new_data
