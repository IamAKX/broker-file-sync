"""Tests for the External Import feature."""
import csv
import io
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


# ── file_reader ───────────────────────────────────────────────────────────────

def test_read_external_import_csv(tmp_path):
    from services.file_reader import read_external_import
    f = tmp_path / "ext.csv"
    f.write_text("Symbol,MyCol1,MyCol2\nINFY,100,200\nTCS,300,400\n")
    headers, data = read_external_import(str(f))
    assert headers == ["Symbol", "MyCol1", "MyCol2"]
    assert len(data) == 2
    assert data[0] == ["INFY", "100", "200"]


def test_read_external_import_xlsx(tmp_path):
    import openpyxl
    from services.file_reader import read_external_import
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Symbol", "Score"])
    ws.append(["INFY", 42])
    ws.append(["TCS", 99])
    path = str(tmp_path / "ext.xlsx")
    wb.save(path)
    headers, data = read_external_import(path)
    assert headers == ["Symbol", "Score"]
    assert len(data) == 2
    assert data[0][0] == "INFY"
    assert data[0][1] == 42


def test_read_external_import_empty_csv(tmp_path):
    from services.file_reader import read_external_import
    f = tmp_path / "empty.csv"
    f.write_text("")
    headers, data = read_external_import(str(f))
    assert headers == []
    assert data == []


def test_count_rows_external(tmp_path):
    from services.file_reader import count_rows_external
    f = tmp_path / "ext.csv"
    f.write_text("Symbol,Col\nINFY,1\nTCS,2\nHDFCBANK,3\n")
    assert count_rows_external(str(f)) == 3


# ── external_import_source: custom "last N trading days" formulas ──────────────

def _stub_historic_backend(monkeypatch):
    from datetime import date, timedelta
    from api import historic_api, holidays_api

    # Fixed Mon..Fri week (2026-06-01 is a Monday) — deterministic regardless
    # of which real-world weekday the test suite happens to run on.
    dates = [date(2026, 6, 1) + timedelta(days=i) for i in range(5)]
    monkeypatch.setattr(
        historic_api, "get_availability",
        lambda date_from, date_to: {
            "dates": [{"trade_date": d.isoformat(), "has_data": True} for d in dates]
        },
    )
    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: [])

    def fake_snapshot(trade_date):
        i = dates.index(trade_date)
        return {
            "trade_date": trade_date.isoformat(),
            "stocks": [{
                "symbol": "INFY", "display_name": "Infosys",
                "metrics": {
                    "Open": 100 + i, "High": 110 + i, "Low": 90 + i, "Close": 105 + i,
                    "AvgRate": 104 + i, "Quantity": 1000, "DiffPcnt": 1.0,
                },
            }],
        }
    monkeypatch.setattr(historic_api, "get_snapshot", fake_snapshot)
    return dates


def _stub_custom_formulas(monkeypatch, formulas):
    from services import config_store
    monkeypatch.setattr(config_store, "load_json", lambda key, default: formulas)


def test_custom_formula_last_n_trading_days_computed_as_extra_column(monkeypatch):
    from services.external_import_source import read_external_import_db

    dates = _stub_historic_backend(monkeypatch)
    _stub_custom_formulas(monkeypatch, [
        {"id": "1", "code": "MAX3D", "name": "Max High 3D", "description": "", "frequency": "DAILY",
         "tokens": [{"type": "func", "value": "MAX_OF(", "field": "HIGH", "window": "LAST_N_TRADING_DAYS", "n": 3}]},
    ])

    headers, rows = read_external_import_db(target=dates[-1])
    assert "MAX3D" in headers
    row = rows[0]
    # High = 110+i for the last 3 stubbed days (i=2,3,4) -> max is 110+4
    assert row[headers.index("MAX3D")] == 110 + 4


def test_custom_formula_colliding_with_builtin_code_ignored(monkeypatch):
    from services.external_import_source import read_external_import_db
    from services import formula_engine

    dates = _stub_historic_backend(monkeypatch)
    _stub_custom_formulas(monkeypatch, [
        {"id": "1", "code": "CMH", "name": "Shadows a built-in", "description": "", "frequency": "DAILY",
         "tokens": [{"type": "func", "value": "MAX_OF(", "field": "HIGH", "window": "LAST_N_TRADING_DAYS", "n": 3}]},
    ])

    headers, rows = read_external_import_db(target=dates[-1])
    # Exactly one "CMH" column — the trusted built-in, not a duplicate.
    assert headers.count("CMH") == 1
    assert headers == ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES


def test_non_computable_custom_formula_produces_no_extra_column(monkeypatch):
    from services.external_import_source import read_external_import_db
    from services import formula_engine

    dates = _stub_historic_backend(monkeypatch)
    _stub_custom_formulas(monkeypatch, [
        {"id": "1", "code": "MYFORMULA", "name": "Still just documentation", "description": "",
         "frequency": "DAILY", "tokens": [{"type": "field", "value": "HIGH"}, {"type": "op", "value": "+"},
                                           {"type": "field", "value": "LOW"}]},
    ])

    headers, rows = read_external_import_db(target=dates[-1])
    assert "MYFORMULA" not in headers
    assert headers == ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES


# ── live_merge ────────────────────────────────────────────────────────────────

def _make_csv(tmp_path, name, rows):
    f = tmp_path / name
    with open(f, "w", newline="") as fh:
        w = csv.writer(fh)
        for r in rows:
            w.writerow(r)
    return str(f)


def test_live_merge_includes_external_columns(tmp_path, monkeypatch):
    from services.live_merge import LiveDataReader

    # Stub out the three broker readers so we don't need real files
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], [["INFY", 1800.0], ["TCS", 3500.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], []),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi",
        lambda path: (["Symbol", "Max Pain"], []),
    )

    # External now mirrors ReliableSoftware: col A ignored, col B is the join
    # key (full name + rolling suffix → symbol via config), col C onward = data.
    ext_file = _make_csv(tmp_path, "ext.csv", [
        ["RowNo", "ScripName", "MyScore"],
        ["1", "Infosys Limited.rolling.12D", "99"],
        ["2", "TCS.rolling.11D", "88"],
    ])
    script_name_data = [("Infosys Limited", "INFY"), ("TCS", "TCS")]

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", script_name_data,
                            external_path=ext_file)
    # Trigger slow-source read manually
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    assert "MyScore" in headers
    assert "ScripName" not in headers   # the key column is not output
    score_idx = headers.index("MyScore")
    rows_by_scrip = {r[0]: r for r in data}
    assert rows_by_scrip["INFY"][score_idx] == "99"
    assert rows_by_scrip["TCS"][score_idx] == "88"


def test_live_merge_without_external_is_unchanged(tmp_path, monkeypatch):
    from services.live_merge import LiveDataReader

    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], [["INFY", 1800.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], []),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi",
        lambda path: (["Symbol", "Max Pain"], []),
    )

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [])
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    assert "MyScore" not in headers
    assert len(data) == 1


def test_live_merge_external_missing_scrip_fills_none(tmp_path, monkeypatch):
    from services.live_merge import LiveDataReader

    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], [["INFY", 1800.0], ["TCS", 3500.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], []),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi",
        lambda path: (["Symbol", "Max Pain"], []),
    )

    # Only INFY in external — TCS should get None
    ext_file = _make_csv(tmp_path, "partial.csv", [
        ["RowNo", "ScripName", "MyScore"],
        ["1", "Infosys Limited.rolling.12D", "99"],
    ])
    script_name_data = [("Infosys Limited", "INFY")]

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", script_name_data,
                            external_path=ext_file)
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    score_idx = headers.index("MyScore")
    rows_by_scrip = {r[0]: r for r in data}
    assert rows_by_scrip["INFY"][score_idx] == "99"
    assert rows_by_scrip["TCS"][score_idx] is None


def test_live_merge_external_matches_any_rolling_duration(tmp_path, monkeypatch):
    # External uses .rolling.10D; config (stripped) maps ABB LTD → ABB.
    from services.live_merge import LiveDataReader
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], [["ABB", 1.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], []),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi",
        lambda path: (["Symbol", "Max Pain"], []),
    )
    ext_file = _make_csv(tmp_path, "roll.csv", [
        ["RowNo", "ScripName", "ExtCol"],
        ["1", "ABB LTD.rolling.10D", "XYZ"],
    ])
    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv",
                            [("ABB LTD", "ABB")], external_path=ext_file)
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)
    assert data[0][headers.index("ExtCol")] == "XYZ"


def test_live_merge_external_column_a_is_ignored(tmp_path, monkeypatch):
    # Column A holds junk; matching must rely on column B only.
    from services.live_merge import LiveDataReader
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], [["INFY", 1.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], []),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi",
        lambda path: (["Symbol", "Max Pain"], []),
    )
    ext_file = _make_csv(tmp_path, "cola.csv", [
        ["GARBAGE", "ScripName", "ExtCol"],
        ["zzz", "Infosys Limited.rolling.12D", "OK"],
    ])
    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv",
                            [("Infosys Limited", "INFY")], external_path=ext_file)
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)
    # Column A header ("GARBAGE") must not be in output; ExtCol is matched.
    assert "GARBAGE" not in headers
    assert data[0][headers.index("ExtCol")] == "OK"


# ── live_merge: database-mode live overlay (CWO/CWATP/.../CWTO) ────────────────

_SK_LIVE_HEADERS = [
    "Scrip Name", "Lot Size", "% Change", "Current", "Open", "High", "Low",
    "Close", "Avg Rate", "OI Difference Percentage", "P.High", "P.Low",
    "Qty", "P.Quantity", "TurnOver",
]


def _stub_sk_and_slow_sources(monkeypatch, sk_row):
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (_SK_LIVE_HEADERS, [list(sk_row)]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], []),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi",
        lambda path: (["Symbol", "Max Pain"], []),
    )


def _ext_db_fixture(live_baselines):
    from services import formula_engine
    codes = formula_engine.FORMULA_CODES
    ext_headers = ["Symbol", "Display Name"] + codes
    # CWO pre-populated with a "stored DB" value, as formula_engine.compute_all
    # would already correctly give it for a non-first day of the week.
    ext_row = ["INFY", "Infosys"] + ["" for _ in codes]
    ext_row[2 + formula_engine.CODE_TO_INDEX["CWO"]] = 95.5
    return ext_headers, [ext_row], live_baselines


def test_live_merge_database_mode_overlays_live_values_on_first_trading_day(monkeypatch):
    from services.live_merge import LiveDataReader
    from services import external_import_source

    sk_row = ["INFY", 1, 2.0, 110.0, 105.0, 111.0, 104.0, 109.0, 108.0, 0.0,
              112.0, 103.0, 1000.0, 900.0, 50000.0]
    _stub_sk_and_slow_sources(monkeypatch, sk_row)

    live_baselines = {
        "INFY": {
            "is_first_trading_day_of_week": True,
            "is_first_trading_day_of_month": False,
            "prev_atp_values_week": [],
            "prev_atp_values_month": [50.0, 51.0],
            "prev_qty_values_week": [],
            "pwc": 100.0,
            "pmc": 200.0,
        }
    }
    ext_headers, ext_rows, baselines = _ext_db_fixture(live_baselines)
    monkeypatch.setattr(
        external_import_source, "read_external_import_db_with_live_baseline",
        lambda: (ext_headers, ext_rows, baselines),
    )

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [("Infosys", "INFY")],
                            external_mode="database")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)
    row = data[0]

    # First trading day of the week -> CWO overridden with today's live Open
    # (overwriting the stale "stored DB" placeholder from the fixture).
    assert row[headers.index("CWO")] == 105.0
    # Not the first trading day of the month -> CMO left alone (still blank).
    assert row[headers.index("CMO")] == ""
    assert row[headers.index("CWATP")] == 108.0        # no prior days -> live Avg Rate alone
    assert row[headers.index("CMATP")] == 69.6667       # avg(50, 51, 108)
    assert row[headers.index("WEEK % CHANGE")] == 10.0  # (110-100)/100*100, vs live Current
    assert row[headers.index("MONTH % CHANGE")] == -45.0
    assert row[headers.index("DAY TO")] == 0.0002
    assert row[headers.index("CWTO")] == 0.0011


def test_live_merge_database_mode_leaves_cwo_alone_mid_week(monkeypatch):
    from services.live_merge import LiveDataReader
    from services import external_import_source

    sk_row = ["INFY", 1, 2.0, 110.0, 105.0, 111.0, 104.0, 109.0, 108.0, 0.0,
              112.0, 103.0, 1000.0, 900.0, 50000.0]
    _stub_sk_and_slow_sources(monkeypatch, sk_row)

    live_baselines = {
        "INFY": {
            "is_first_trading_day_of_week": False,
            "is_first_trading_day_of_month": False,
            "prev_atp_values_week": [100.0, 102.0],
            "prev_atp_values_month": [100.0, 102.0],
            "prev_qty_values_week": [500.0],
            "pwc": 100.0,
            "pmc": 200.0,
        }
    }
    ext_headers, ext_rows, baselines = _ext_db_fixture(live_baselines)
    monkeypatch.setattr(
        external_import_source, "read_external_import_db_with_live_baseline",
        lambda: (ext_headers, ext_rows, baselines),
    )

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [("Infosys", "INFY")],
                            external_mode="database")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)
    row = data[0]

    # Mid-week -> CWO keeps the pre-existing "stored DB" value untouched...
    assert row[headers.index("CWO")] == 95.5
    # ...while CWATP still blends the elapsed days with today's live tick.
    assert row[headers.index("CWATP")] == 103.3333  # avg(100, 102, 108)


def test_live_merge_database_mode_symbol_missing_from_baseline_falls_back_cleanly(monkeypatch):
    from services.live_merge import LiveDataReader
    from services import external_import_source

    sk_row = ["INFY", 1, 2.0, 110.0, 105.0, 111.0, 104.0, 109.0, 108.0, 0.0,
              112.0, 103.0, 1000.0, 900.0, 50000.0]
    _stub_sk_and_slow_sources(monkeypatch, sk_row)

    # A brand-new listing: matched via Sharekhan/ExternalImport join, but no
    # entry in the live-baseline cache at all (zero stored history yet).
    ext_headers, ext_rows, baselines = _ext_db_fixture(live_baselines={})
    monkeypatch.setattr(
        external_import_source, "read_external_import_db_with_live_baseline",
        lambda: (ext_headers, ext_rows, baselines),
    )

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [("Infosys", "INFY")],
                            external_mode="database")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)
    row = data[0]

    # No crash, and the untouched fixture value passes straight through.
    assert row[headers.index("CWO")] == 95.5
    assert row[headers.index("CWATP")] == ""


def test_live_merge_file_mode_never_applies_live_overlay(tmp_path, monkeypatch):
    from services.live_merge import LiveDataReader
    from services import live_formula

    calls = []
    monkeypatch.setattr(
        live_formula, "apply_live_overlay",
        lambda baseline, live: calls.append(1) or {},
    )

    sk_row = ["INFY", 1, 2.0, 110.0, 105.0, 111.0, 104.0, 109.0, 108.0, 0.0,
              112.0, 103.0, 1000.0, 900.0, 50000.0]
    _stub_sk_and_slow_sources(monkeypatch, sk_row)

    ext_file = _make_csv(tmp_path, "ext.csv", [
        ["RowNo", "ScripName", "MyScore"],
        ["1", "Infosys.rolling.12D", "99"],
    ])
    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [("Infosys", "INFY")],
                            external_path=ext_file, external_mode="file")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    assert data[0][headers.index("MyScore")] == "99"
    assert calls == []


# ── data_import UI ────────────────────────────────────────────────────────────

def test_external_import_card_present(qapp):
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    assert "ExternalImport" in screen._cards


def test_watcher_btn_enabled_with_all_five(qapp):
    """Watcher must be enabled only when all five files are imported."""
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    for broker in ["Sharekhan", "ReliableSoftware", "NiftyInvest",
                   "ExternalImport", "MarketProfile"]:
        screen._imported_brokers.add(broker)
    screen._update_watcher_btn()
    assert screen._watcher_btn.isEnabled()


def test_watcher_btn_disabled_without_market_profile(qapp):
    """Watcher must NOT be enabled when MarketProfile is missing."""
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    for broker in ["Sharekhan", "ReliableSoftware", "NiftyInvest", "ExternalImport"]:
        screen._imported_brokers.add(broker)
    screen._update_watcher_btn()
    assert not screen._watcher_btn.isEnabled()


def test_watcher_btn_disabled_without_external(qapp):
    """Watcher must NOT be enabled when ExternalImport is missing."""
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    for broker in ["Sharekhan", "ReliableSoftware", "NiftyInvest"]:
        screen._imported_brokers.add(broker)
    screen._update_watcher_btn()
    assert not screen._watcher_btn.isEnabled()


def test_external_import_accepts_csv_and_xlsx(qapp):
    from screens.data_import import BROKERS
    ext = next(b for b in BROKERS if b[0] == "ExternalImport")
    assert ".csv" in ext[3]
    assert ".xlsx" in ext[3]


# ── live_viewer accepts external_path ────────────────────────────────────────

def test_live_viewer_accepts_external_path(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [], external_path=str(tmp_path / "ext.csv"))
    assert lmv._external_path is not None


# ── ExternalImport file/database source toggle ─────────────────────────────────

def test_external_import_card_has_source_toggle(qapp):
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    card = screen._cards["ExternalImport"]
    assert card._show_source_toggle is True
    assert card._source_mode == "file"
    assert card._browse_btn.text() == "Browse"


def test_other_cards_have_no_source_toggle(qapp):
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    for broker in ["Sharekhan", "ReliableSoftware", "NiftyInvest", "MarketProfile"]:
        card = screen._cards[broker]
        assert card._show_source_toggle is False
        assert not hasattr(card, "_source_toggle")


def test_toggling_to_database_renames_browse_button_to_view(qapp):
    from app import AppController
    from screens.data_import import DataImportScreen
    screen = DataImportScreen(AppController(qapp))
    card = screen._cards["ExternalImport"]
    card._on_source_toggled(True)
    assert card._source_mode == "database"
    assert card._browse_btn.text() == "View"

    card._on_source_toggled(False)
    assert card._source_mode == "file"
    assert card._browse_btn.text() == "Browse"


def test_database_mode_calculates_and_shows_table(qapp, monkeypatch):
    from datetime import date, timedelta
    from app import AppController
    from screens.data_import import DataImportScreen
    from screens.historic_viewer import HistoricDataViewer
    from services import formula_engine
    from api import historic_api, holidays_api

    # target is always real "today" now — the fixture's latest date must BE
    # today, or today-dependent formulas (DAY TO, camarilla, ...) come back
    # blank since there's no row for target at all.
    today = date.today()
    d1, d2 = (today - timedelta(days=1)).isoformat(), today.isoformat()
    monkeypatch.setattr(
        historic_api, "get_availability",
        lambda date_from, date_to: {
            "dates": [
                {"trade_date": d1, "has_data": True},
                {"trade_date": d2, "has_data": True},
            ]
        },
    )
    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: [])

    def fake_snapshot(trade_date):
        day = trade_date.isoformat()
        base = 10 if day == d1 else 11
        return {
            "trade_date": day,
            "stocks": [
                {
                    "symbol": "INFY",
                    "display_name": "Infosys",
                    "metrics": {
                        "Open": base, "High": base + 2, "Low": base - 1, "Close": base + 1,
                        "AvgRate": base + 0.5, "Quantity": 1000, "DiffPcnt": 1.0,
                    },
                }
            ],
        }

    monkeypatch.setattr(historic_api, "get_snapshot", fake_snapshot)

    screen = DataImportScreen(AppController(qapp))
    card = screen._cards["ExternalImport"]
    card._on_source_toggled(True)
    card._on_primary_action()

    assert isinstance(card._formula_viewer, HistoricDataViewer)
    assert card._formula_viewer._headers == ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES
    assert card._formula_viewer._table.rowCount() == 1
    assert card._formula_viewer._table.item(0, 0).text() == "INFY"
    # DAY TO must be non-blank — (Quantity*AvgRate)/1e7 * abs(DiffPcnt)/100 is fully known
    day_to_col = card._formula_viewer._headers.index("DAY TO")
    assert card._formula_viewer._table.item(0, day_to_col).text() != ""
    # Browse button restored to "View" after the (synchronous) load completes
    assert card._browse_btn.text() == "View"
    assert card._browse_btn.isEnabled()
    # Title must say ExternalImport and clearly mark the reference date as
    # "as of" today (the calculation is always anchored to today, not the
    # latest date with data).
    assert card._formula_viewer.windowTitle() == f"External Import — as of {today.strftime('%d-%b-%Y')}"


def test_database_mode_no_data_shows_message(qapp, monkeypatch):
    from app import AppController
    from screens.data_import import DataImportScreen
    from api import historic_api, holidays_api
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(historic_api, "get_availability", lambda date_from, date_to: {"dates": []})
    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: [])
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a)))

    screen = DataImportScreen(AppController(qapp))
    card = screen._cards["ExternalImport"]
    card._on_source_toggled(True)
    card._on_primary_action()

    assert card._formula_viewer is None
    assert len(shown) == 1
