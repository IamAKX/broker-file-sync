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
        "services.file_reader.read_nifty_invest",
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
        "services.file_reader.read_nifty_invest",
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
        "services.file_reader.read_nifty_invest",
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
        "services.file_reader.read_nifty_invest",
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
        "services.file_reader.read_nifty_invest",
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
    from app import AppController
    from screens.data_import import DataImportScreen
    from screens.historic_viewer import HistoricDataViewer
    from services import formula_engine
    from api import historic_api

    d1, d2 = "2026-06-01", "2026-06-02"
    monkeypatch.setattr(
        historic_api, "get_availability",
        lambda date_from, date_to: {
            "dates": [
                {"trade_date": d1, "has_data": True},
                {"trade_date": d2, "has_data": True},
            ]
        },
    )

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
                        "pdh": base + 1, "pdl": base - 2, "PClose": base,
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
    # "as of" — the target is the latest date WITH data, not necessarily
    # today, and a plain date was previously mistaken for "current" data.
    assert card._formula_viewer.windowTitle() == "External Import — as of 02-Jun-2026"


def test_database_mode_no_data_shows_message(qapp, monkeypatch):
    from app import AppController
    from screens.data_import import DataImportScreen
    from api import historic_api
    from PySide6.QtWidgets import QMessageBox

    monkeypatch.setattr(historic_api, "get_availability", lambda date_from, date_to: {"dates": []})
    shown = []
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: shown.append(a)))

    screen = DataImportScreen(AppController(qapp))
    card = screen._cards["ExternalImport"]
    card._on_source_toggled(True)
    card._on_primary_action()

    assert card._formula_viewer is None
    assert len(shown) == 1
