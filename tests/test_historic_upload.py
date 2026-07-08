"""Tests for the Historic Upload feature."""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


# ── historic_store ────────────────────────────────────────────────────────────

def test_save_and_fetch_round_trip(tmp_path, monkeypatch):
    from services import historic_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "h.json"))

    store.save_historic_upload("2026-07-05", ["Symbol", "Close"], [["INFY", 1800], ["TCS", 3500]])
    headers, rows = store.fetch_historic_data("2026-07-05")
    assert headers == ["Symbol", "Close"]
    assert rows == [["INFY", 1800], ["TCS", 3500]]


def test_fetch_missing_date_returns_none(tmp_path, monkeypatch):
    from services import historic_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "h.json"))
    assert store.fetch_historic_data("2026-01-01") is None


def test_fetch_available_dates_stub_returns_1_to_20():
    from services import historic_store as store
    days = store.fetch_available_dates(2026, 7)
    assert days == set(range(1, 21))
    # stub ignores year/month
    assert store.fetch_available_dates(1999, 1) == days


# ── file_reader ───────────────────────────────────────────────────────────────

def test_read_historic_upload_csv(tmp_path):
    from services.file_reader import read_historic_upload
    f = tmp_path / "hist.csv"
    f.write_text("Symbol,Close\nINFY,1800\nTCS,3500\n")
    headers, data = read_historic_upload(str(f))
    assert headers == ["Symbol", "Close"]
    assert data[0] == ["INFY", "1800"]


def test_read_historic_upload_xlsx(tmp_path):
    import openpyxl
    from services.file_reader import read_historic_upload
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Symbol", "Close"])
    ws.append(["INFY", 1800])
    path = str(tmp_path / "hist.xlsx")
    wb.save(path)
    headers, data = read_historic_upload(path)
    assert headers == ["Symbol", "Close"]
    assert data[0][0] == "INFY"


# ── HistoricUploadScreen ──────────────────────────────────────────────────────

def test_historic_upload_screen_creates(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    screen = HistoricUploadScreen(AppController(qapp))
    assert screen is not None


def test_edit_menu_has_historic_upload(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    tm = ThemeManager(qapp)
    topbar = TopBar(tm)
    # Locate the Edit menu's actions via the QPushButton with menu
    from PySide6.QtWidgets import QPushButton
    found = False
    for btn in topbar.findChildren(QPushButton):
        menu = btn.menu()
        if menu is not None:
            for action in menu.actions():
                if action.text() == "Historic Upload":
                    found = True
    assert found


def test_save_disabled_until_file_and_date(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    screen = HistoricUploadScreen(AppController(qapp))
    assert not screen._save_btn.isEnabled()


def test_populate_columns_creates_checkboxes(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    screen = HistoricUploadScreen(AppController(qapp))
    screen._headers = ["Symbol", "Close", "Volume"]
    screen._rows = [["INFY", 1800, 100]]
    screen._selected_file = "dummy.csv"
    screen._populate_columns()
    assert len(screen._checkboxes) == 3
    screen._update_save_enabled()
    assert screen._save_btn.isEnabled()

    screen._checkboxes[0].setChecked(False)
    screen._checkboxes[1].setChecked(False)
    screen._checkboxes[2].setChecked(False)
    screen._update_save_enabled()
    assert not screen._save_btn.isEnabled()


def test_save_persists_only_checked_columns(qapp, tmp_path, monkeypatch):
    from services import historic_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "h.json"))

    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from datetime import date
    screen = HistoricUploadScreen(AppController(qapp))
    screen._headers = ["Symbol", "Close", "Volume"]
    screen._rows = [["INFY", 1800, 100], ["TCS", 3500, 200]]
    screen._selected_file = "dummy.csv"
    screen._upload_date = date(2026, 7, 5)
    screen._populate_columns()
    screen._checkboxes[2].setChecked(False)  # drop Volume

    screen._on_save()

    headers, rows = store.fetch_historic_data("2026-07-05")
    assert headers == ["Symbol", "Close"]
    assert rows == [["INFY", 1800], ["TCS", 3500]]


def test_view_button_enabled_only_on_available_day(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from datetime import date
    screen = HistoricUploadScreen(AppController(qapp))
    screen._available_days = {1, 2, 3}
    screen._selected_browse_date = date(2026, 7, 2)
    screen._update_view_btn_enabled()
    assert screen._view_btn.isEnabled()

    screen._selected_browse_date = date(2026, 7, 25)
    screen._update_view_btn_enabled()
    assert not screen._view_btn.isEnabled()


# ── HistoricDataViewer ────────────────────────────────────────────────────────

def test_historic_data_viewer_populates_table(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(["Symbol", "Close"], [["INFY", "1800"], ["TCS", "3500"]], "05-Jul-2026")
    assert viewer._table.rowCount() == 2
    assert viewer._table.columnCount() == 2
    assert viewer._table.item(0, 0).text() == "INFY"
    assert viewer._table.item(1, 1).text() == "3500"
