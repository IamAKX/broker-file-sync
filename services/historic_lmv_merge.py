"""
One-shot (non-live) merge of the 4 browsable broker files + ExternalImport's
"database" source computed as of an arbitrary past trade date — used by
screens.lmv_upload to preview/save a historical Live Master View.

Delegates the actual join/column-layout logic to
services.live_merge.merge_broker_sources, the same function the live LMV
uses, so a historical LMV built here has byte-identical headers to what the
live LMV would have shown that column set as (same order, same names) — the
only difference is where each source's rows come from (static file reads +
formula_engine computed as-of-target, instead of live polling).

*target* almost always hasn't been saved to the backend yet — that's the
whole point of a preview — so formula_engine has no stored row for it and 8
columns (CWO, CMO, CWATP, CMATP, WEEK % CHANGE, MONTH % CHANGE, DAY TO,
CWTO — see services.live_formula) come back empty from a plain historical
read. The browsed Sharekhan file's own row IS what target's data would be
once saved, so it's blended in via the exact same apply_live_overlay() the
live LMV uses for today's live tick — just with the *browsed file's* values
standing in for "today's tick" instead of a live poll.
"""

from datetime import date

from services.external_import_source import read_external_import_db_with_live_baseline
from services.file_reader import (
    read_market_profile, read_nifty_invest_multi, read_reliable_software, read_sharekhan,
)
from services.formula_engine import CODE_TO_INDEX, _to_float
from services.live_formula import apply_live_overlay
from services.live_merge import merge_broker_sources
from services.master_generator import _build_script_name_lookup, _normalise, _SK_PK_IDX


def read_merged_static(
    sharekhan_path: str,
    reliable_path: str,
    nifty_paths,
    market_profile_path: str,
    script_name_data: list,
    target: date,
    expiry_date: date = None,
    sector_map: dict = None,
) -> tuple[list, list]:
    """Return (headers, rows) for the LMV as of *target* — "Sector" injected
    at column 0, matching screens.live_viewer.LiveViewerWindow._inject_sector.
    """
    sk_headers, sk_rows = read_sharekhan(sharekhan_path)
    rs_headers, rs_rows = read_reliable_software(reliable_path)
    ni_headers, ni_rows = read_nifty_invest_multi(nifty_paths)
    mp_headers, mp_rows = (
        read_market_profile(market_profile_path) if market_profile_path else ([], [])
    )
    ext_headers, ext_rows, live_baselines = read_external_import_db_with_live_baseline(target)

    if expiry_date is not None:
        expiry_str = expiry_date.strftime("%d-%b-%Y").upper()
        for sk_row in sk_rows:
            scrip = _normalise(sk_row[_SK_PK_IDX])
            if scrip.upper().endswith(expiry_str):
                sk_row[_SK_PK_IDX] = scrip[:-len(expiry_str)].strip()

    name_to_symbol = _build_script_name_lookup(script_name_data)

    def _preview_overlay_hook(pk, sk_row, ext_row):
        # ext_row[0] is the row's own "Symbol" column — same string space
        # live_baselines is keyed by (see services.live_merge's identical hook).
        baseline = live_baselines.get(ext_row[0])
        if baseline is None or len(sk_row) <= 12:
            return ext_row
        live = {
            "diffpcnt": _to_float(sk_row[2]),
            "current":  _to_float(sk_row[3]),
            "open":     _to_float(sk_row[4]),
            "avg_rate": _to_float(sk_row[8]),
            "qty":      _to_float(sk_row[12]),
        }
        overlay = apply_live_overlay(baseline, live)
        if not overlay:
            return ext_row
        ext_row = list(ext_row)
        for code, v in overlay.items():
            idx = 2 + CODE_TO_INDEX[code]
            if idx < len(ext_row):
                ext_row[idx] = round(v, 4)
        return ext_row

    headers, rows = merge_broker_sources(
        sk_headers, sk_rows, rs_headers, rs_rows, ni_headers, ni_rows,
        ext_headers, ext_rows, mp_headers, mp_rows, name_to_symbol,
        ext_row_hook=_preview_overlay_hook,
    )
    return _inject_sector(headers, rows, sector_map or {})


def _inject_sector(headers: list, data: list, sector_map: dict) -> tuple:
    scrip_idx = headers.index("Scrip Name") if "Scrip Name" in headers else -1
    new_headers = ["Sector"] + list(headers)
    new_data = []
    for row in data:
        scrip = row[scrip_idx] if 0 <= scrip_idx < len(row) else ""
        sector = sector_map.get(str(scrip).strip().upper(), "—")
        new_data.append([sector] + list(row))
    return new_headers, new_data
