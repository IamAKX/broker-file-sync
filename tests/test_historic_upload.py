"""Tests for the Historic Upload feature."""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


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
    # A=DataTime, B=ScripName (structural, excluded), C-E fall in the C-M metric range
    screen._headers = ["DataTime", "ScripName", "DiffPcnt", "Open", "High"]
    screen._rows = [[46204, "INFY", -0.03, 1800, 1810]]
    screen._selected_file = "dummy.csv"
    screen._structural_cols = {0, 1}
    screen._populate_columns()
    assert len(screen._checkboxes) == 3
    screen._update_save_enabled()
    assert screen._save_btn.isEnabled()

    screen._checkboxes[0].setChecked(False)
    screen._checkboxes[1].setChecked(False)
    screen._checkboxes[2].setChecked(False)
    screen._update_save_enabled()
    assert not screen._save_btn.isEnabled()


def test_populate_columns_excludes_outside_c_to_m_range(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    screen = HistoricUploadScreen(AppController(qapp))
    # 14 headers: A/B structural, C-M (indices 2-12) are the 11 eligible metric
    # columns, N (index 13) is beyond the range and must not get a checkbox.
    screen._headers = [
        "DataTime", "ScripName",
        "DiffPcnt", "Open", "High", "Low", "Close", "pdh", "pdl",
        "PClose", "AvgRate", "Quantity", "PQuantity",
        "PMHL_High",
    ]
    screen._rows = [[46204, "INFY"] + [0] * 11 + [999]]
    screen._selected_file = "dummy.csv"
    screen._structural_cols = {0, 1}
    screen._populate_columns()
    assert len(screen._checkboxes) == 11
    assert "PMHL_High" not in [cb.text() for cb in screen._checkboxes]
    assert "DataTime" not in [cb.text() for cb in screen._checkboxes]


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


def test_historic_data_viewer_default_title_uses_date_str(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(["Symbol"], [["INFY"]], "05-Jul-2026")
    assert viewer.windowTitle() == "Historic Data — 05-Jul-2026"


def test_historic_data_viewer_custom_title_overrides_default(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(["Symbol"], [["INFY"]], "05-Jul-2026", title="Custom Title")
    assert viewer.windowTitle() == "Custom Title"


def test_historic_viewer_symbol_search_filters_rows(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "Display Name", "Close"],
        [["ABB", "ABB LTD", "6832.5"], ["INFY", "INFOSYS LTD", "1800"]],
        "05-Jul-2026",
    )
    viewer._search_box.setText("abb")
    assert viewer._table.isRowHidden(0) is False
    assert viewer._table.isRowHidden(1) is True

    viewer._search_box.setText("")
    assert viewer._table.isRowHidden(0) is False
    assert viewer._table.isRowHidden(1) is False


def test_historic_viewer_column_filter_hides_column(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "Display Name", "Close"],
        [["ABB", "ABB LTD", "6832.5"]],
        "05-Jul-2026",
    )
    viewer._apply_col_filter({0, 2})
    assert viewer._table.isColumnHidden(1) is True
    assert viewer._table.isColumnHidden(0) is False
    assert viewer._table.isColumnHidden(2) is False


def test_historic_viewer_symbol_column_always_visible(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "Display Name", "Close"],
        [["ABB", "ABB LTD", "6832.5"]],
        "05-Jul-2026",
    )
    viewer._apply_col_filter({2})
    assert viewer._table.isColumnHidden(0) is False


def test_historic_viewer_header_sections_movable(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "Display Name", "Close"],
        [["ABB", "ABB LTD", "6832.5"]],
        "05-Jul-2026",
    )
    assert viewer._table.horizontalHeader().sectionsMovable() is True
