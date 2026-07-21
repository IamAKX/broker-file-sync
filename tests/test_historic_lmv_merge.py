import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date

import pytest

from services.formula_engine import FORMULA_CODES


def _stub_readers(monkeypatch, ext_headers=None, ext_rows=None, live_baselines=None):
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_sharekhan",
        lambda path: (["Scrip Name", "Current"], [["ADANIENT", 1800.0], ["ABB", 7500.0]]),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], [["ADANIENT", 111.0]]),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_nifty_invest_multi",
        lambda paths: (["Symbol", "Max Pain"], [["ADANIENT", 1900.0]]),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_market_profile",
        lambda path: (["stock", "VAH", "POC", "VAL"], [["ADANIENT", 10.0, 20.0, 30.0]]),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_external_import_db_with_live_baseline",
        lambda target: (ext_headers or [], ext_rows or [], live_baselines or {}),
    )


def test_read_merged_static_produces_sharekhan_backbone(monkeypatch):
    from services.historic_lmv_merge import read_merged_static

    _stub_readers(monkeypatch)
    script_name_data = [("ADANIENT", "ADANIENT"), ("ABB LTD", "ABB")]
    headers, rows = read_merged_static(
        "sk.xls", "rs.xls", "ni.csv", "mp.csv", script_name_data, target=date(2026, 7, 20),
    )
    assert headers[0] == "Sector"
    assert "Scrip Name" in headers
    assert len(rows) == 2


def test_read_merged_static_injects_sector_from_map(monkeypatch):
    from services.historic_lmv_merge import read_merged_static

    _stub_readers(monkeypatch)
    script_name_data = [("ADANIENT", "ADANIENT"), ("ABB LTD", "ABB")]
    headers, rows = read_merged_static(
        "sk.xls", "rs.xls", "ni.csv", "mp.csv", script_name_data,
        target=date(2026, 7, 20), sector_map={"ADANIENT": "Energy"},
    )
    scrip_idx = headers.index("Scrip Name")
    row_by_scrip = {r[scrip_idx]: r for r in rows}
    assert row_by_scrip["ADANIENT"][0] == "Energy"
    assert row_by_scrip["ABB"][0] == "—"


def test_read_merged_static_includes_external_import_columns(monkeypatch):
    from services.historic_lmv_merge import read_merged_static

    _stub_readers(
        monkeypatch,
        ext_headers=["Symbol", "Display Name", "PATP", "PDTO"],
        ext_rows=[["ADANIENT", "ADANIENT", 1780.0, 12.3]],
    )
    script_name_data = [("ADANIENT", "ADANIENT")]
    headers, rows = read_merged_static(
        "sk.xls", "rs.xls", "ni.csv", "mp.csv", script_name_data, target=date(2026, 7, 20),
    )
    assert "PATP" in headers
    assert "PDTO" in headers
    scrip_idx = headers.index("Scrip Name")
    patp_idx = headers.index("PATP")
    row = next(r for r in rows if r[scrip_idx] == "ADANIENT")
    assert row[patp_idx] == 1780.0


def test_read_merged_static_overlays_day_to_and_week_month_change(monkeypatch):
    """The 4 columns that need *target*'s own row (never saved yet at preview
    time — see the module docstring) must be filled in from the browsed
    Sharekhan file's own values, not left blank."""
    from services.historic_lmv_merge import read_merged_static

    # Full-width Sharekhan row so indices 2/3/4/8/12 (diffpcnt/current/open/
    # avg_rate/qty) are populated, matching _SHAREKHAN_COLS' real layout.
    sk_headers = [
        "Scrip Name", "Lot Size", "% Change", "Current", "Open", "High", "Low",
        "Close", "Avg Rate", "OI Difference Percentage", "P.High", "P.Low",
        "Qty", "P.Quantity", "TurnOver",
    ]
    sk_row = ["ADANIENT", 25, 1.5, 1830.0, 1800.0, 1840.0, 1795.0, 1830.0,
              1820.0, 0.0, 1840.0, 1795.0, 5000.0, 4800.0, 100.0]
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_sharekhan", lambda path: (sk_headers, [sk_row]),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_reliable_software", lambda path: ([], []),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_nifty_invest_multi", lambda paths: ([], []),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_market_profile", lambda path: ([], []),
    )
    monkeypatch.setattr(
        "services.historic_lmv_merge.read_external_import_db_with_live_baseline",
        lambda target: (
            ["Symbol", "Display Name"] + FORMULA_CODES,
            [["ADANIENT", "ADANIENT"] + [None] * len(FORMULA_CODES)],
            {"ADANIENT": {
                "is_first_trading_day_of_week": False,
                "is_first_trading_day_of_month": False,
                "prev_atp_values_week": [1810.0],
                "prev_atp_values_month": [1800.0, 1810.0],
                "prev_qty_values_week": [4000.0],
                "pwc": 1750.0,
                "pmc": 1700.0,
            }},
        ),
    )

    script_name_data = [("ADANIENT", "ADANIENT")]
    headers, rows = read_merged_static(
        "sk.xls", "rs.xls", "ni.csv", "mp.csv", script_name_data, target=date(2026, 7, 21),
    )
    row = dict(zip(headers, rows[0]))
    assert row["DAY TO"] is not None
    assert row["CWTO"] is not None
    assert row["WEEK % CHANGE"] is not None
    assert row["MONTH % CHANGE"] is not None
    assert row["WEEK % CHANGE"] == pytest.approx(round((1830.0 - 1750.0) / 1750.0 * 100, 4))


def test_read_merged_static_no_market_profile_path(monkeypatch):
    from services.historic_lmv_merge import read_merged_static

    _stub_readers(monkeypatch)
    script_name_data = [("ADANIENT", "ADANIENT"), ("ABB LTD", "ABB")]
    headers, rows = read_merged_static(
        "sk.xls", "rs.xls", "ni.csv", None, script_name_data, target=date(2026, 7, 20),
    )
    assert len(rows) == 2
