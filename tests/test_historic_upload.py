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
    # Of the 11, pdh/pdl/PClose/PQuantity are retired metrics and must not
    # get a checkbox either, leaving 7.
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
    assert len(screen._checkboxes) == 7
    checkbox_texts = [cb.text() for cb in screen._checkboxes]
    assert "PMHL_High" not in checkbox_texts
    assert "DataTime" not in checkbox_texts
    for excluded in ("pdh", "pdl", "PClose", "PQuantity"):
        assert excluded not in checkbox_texts


def test_view_button_enabled_only_on_available_day(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from datetime import date
    screen = HistoricUploadScreen(AppController(qapp))
    screen._available_days = {1, 2, 3}
    screen._selected_browse_date = date(2026, 7, 2)
    screen._update_browse_buttons_enabled()
    assert screen._view_btn.isEnabled()

    screen._selected_browse_date = date(2026, 7, 25)
    screen._update_browse_buttons_enabled()
    assert not screen._view_btn.isEnabled()


def test_delete_button_enabled_only_on_available_day(qapp):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from datetime import date
    screen = HistoricUploadScreen(AppController(qapp))
    screen._available_days = {1, 2, 3}
    screen._selected_browse_date = date(2026, 7, 2)
    screen._update_browse_buttons_enabled()
    assert screen._delete_day_btn.isEnabled()

    screen._selected_browse_date = date(2026, 7, 25)
    screen._update_browse_buttons_enabled()
    assert not screen._delete_day_btn.isEnabled()


def test_delete_day_confirmed_calls_api_and_refreshes(qapp, monkeypatch):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from datetime import date
    from PySide6.QtWidgets import QMessageBox
    from api import historic_api

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    calls = []
    monkeypatch.setattr(
        historic_api, "delete_day",
        lambda d: calls.append(d) or {"trade_date": d.isoformat(), "values_deleted": 12},
    )
    monkeypatch.setattr(historic_api, "get_availability", lambda date_from, date_to: {"dates": []})

    screen = HistoricUploadScreen(AppController(qapp))
    screen._selected_browse_date = date(2026, 7, 20)
    screen._on_delete_day_clicked()

    assert calls == [date(2026, 7, 20)]
    assert "Deleted 12 value(s)" in screen._browse_status_lbl.text()


def test_delete_day_cancelled_does_not_call_api(qapp, monkeypatch):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from datetime import date
    from PySide6.QtWidgets import QMessageBox
    from api import historic_api

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)
    calls = []
    monkeypatch.setattr(historic_api, "delete_day", lambda d: calls.append(d))

    screen = HistoricUploadScreen(AppController(qapp))
    screen._selected_browse_date = date(2026, 7, 20)
    screen._on_delete_day_clicked()

    assert calls == []


def test_delete_day_closes_matching_open_viewer(qapp, monkeypatch):
    from app import AppController
    from screens.historic_upload import HistoricUploadScreen
    from screens.historic_viewer import HistoricDataViewer
    from datetime import date
    from PySide6.QtWidgets import QMessageBox
    from api import historic_api

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(
        historic_api, "delete_day",
        lambda d: {"trade_date": d.isoformat(), "values_deleted": 1},
    )
    monkeypatch.setattr(historic_api, "get_availability", lambda date_from, date_to: {"dates": []})

    screen = HistoricUploadScreen(AppController(qapp))
    screen._selected_browse_date = date(2026, 7, 20)
    viewer = HistoricDataViewer(["Symbol"], [["AAA"]], "20-Jul-2026")
    viewer.show()
    screen._viewers.append(viewer)

    screen._on_delete_day_clicked()

    assert not viewer.isVisible()


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


def test_historic_viewer_symbol_search_keeps_frozen_overlay_rows_in_sync(qapp):
    """Regression: screens.inception_view_by_date's HistoricDataViewer popup
    freezes Sector/Symbol via components.frozen_table_columns.FrozenColumns
    — a SEPARATE QTableView overlay sharing the same model but NOT the real
    table's row-hidden view state. _on_search used to hide non-matching rows
    on self._table only, leaving the overlay showing every row at its
    original, unfiltered position — so after searching e.g. "bajfinance",
    the one real match's data (compacted to the top of the now-filtered
    real table) visually lined up with whatever symbol the overlay's own
    unfiltered row 0 happened to be (alphabetically first — "360ONE" in the
    reported bug), not its own Sector/Symbol. Every row's hidden state must
    now match between the two views after a search."""
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Sector", "Symbol", "Close"],
        [["FINANCE", "360ONE", "100"], ["FINANCE", "BAJFINANCE", "200"], ["CG", "ABB", "300"]],
        "05-Jul-2026",
        frozen_headers=["Sector", "Symbol"],
    )
    overlay = viewer._freeze._overlay

    viewer._search_box.setText("bajfinance")

    for r in range(viewer._table.rowCount()):
        assert overlay.isRowHidden(r) == viewer._table.isRowHidden(r), f"row {r} out of sync"
    assert viewer._table.isRowHidden(1) is False   # BAJFINANCE — the match
    assert overlay.isRowHidden(1) is False
    assert viewer._table.isRowHidden(0) is True    # 360ONE — filtered out
    assert overlay.isRowHidden(0) is True

    viewer._search_box.setText("")
    for r in range(viewer._table.rowCount()):
        assert overlay.isRowHidden(r) == viewer._table.isRowHidden(r), f"row {r} out of sync"


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


# ── HistoricDataViewer: Sector filter (feature request alongside the search
# fix — mirrors screens.lmv_snapshot_viewer's own sector combo) ────────────

def test_historic_viewer_sector_combo_hidden_without_sector_column(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(["Symbol", "Close"], [["ABB", "100"]], "05-Jul-2026")
    assert viewer._sector_combo is None


def test_historic_viewer_sector_combo_lists_distinct_values(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Sector", "Symbol", "Close"],
        [["FINANCE", "360ONE", "100"], ["FINANCE", "BAJFINANCE", "200"], ["CG", "ABB", "300"]],
        "05-Jul-2026",
    )
    items = [viewer._sector_combo.itemText(i) for i in range(viewer._sector_combo.count())]
    assert items == ["All", "CG", "FINANCE"]


def test_historic_viewer_sector_filter_hides_non_matching_rows(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Sector", "Symbol", "Close"],
        [["FINANCE", "360ONE", "100"], ["FINANCE", "BAJFINANCE", "200"], ["CG", "ABB", "300"]],
        "05-Jul-2026",
        frozen_headers=["Sector", "Symbol"],
    )
    overlay = viewer._freeze._overlay

    viewer._sector_combo.setCurrentText("CG")

    assert viewer._table.isRowHidden(0) is True
    assert viewer._table.isRowHidden(1) is True
    assert viewer._table.isRowHidden(2) is False
    # Overlay must stay in sync here too, same rationale as the search fix.
    for r in range(3):
        assert overlay.isRowHidden(r) == viewer._table.isRowHidden(r), f"row {r} out of sync"


def test_historic_viewer_sector_and_search_filters_combine(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Sector", "Symbol", "Close"],
        [["FINANCE", "360ONE", "100"], ["FINANCE", "BAJFINANCE", "200"], ["CG", "ABB", "300"]],
        "05-Jul-2026",
    )
    viewer._sector_combo.setCurrentText("FINANCE")
    viewer._search_box.setText("bajfinance")

    assert viewer._table.isRowHidden(0) is True    # right sector, wrong symbol
    assert viewer._table.isRowHidden(1) is False    # matches both
    assert viewer._table.isRowHidden(2) is True    # wrong sector entirely


# ── HistoricDataViewer: Category filter (All/Daily/Weekly/Monthly/Common —
# hides/shows already-applied strategy columns, never re-evaluates them) ───

def test_historic_viewer_category_combo_hidden_without_column_categories(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(["Symbol", "Close"], [["ABB", "100"]], "05-Jul-2026")
    assert viewer._category_combo is None


def test_historic_viewer_category_filter_hides_non_matching_strategy_columns(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "Close", "MyDaily", "MyWeekly"],
        [["ABB", "100", "X", "Y"]],
        "05-Jul-2026",
        column_categories={"MyDaily": "Daily", "MyWeekly": "Weekly"},
    )
    viewer._category_combo.setCurrentText("Daily")

    assert viewer._table.isColumnHidden(0) is False   # base column — never gated
    assert viewer._table.isColumnHidden(1) is False   # base column — never gated
    assert viewer._table.isColumnHidden(2) is False   # Daily — matches
    assert viewer._table.isColumnHidden(3) is True    # Weekly — filtered out

    viewer._category_combo.setCurrentText("All")
    assert viewer._table.isColumnHidden(3) is False


def test_historic_viewer_category_and_column_visibility_filters_combine(qapp):
    """A column hidden via the Columns popup must stay hidden regardless of
    the Category filter, and vice versa — the two combine (AND), neither
    one overrides the other."""
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "MyDaily", "MyWeekly"],
        [["ABB", "X", "Y"]],
        "05-Jul-2026",
        column_categories={"MyDaily": "Daily", "MyWeekly": "Weekly"},
    )
    viewer._apply_col_filter({0, 1})   # user unchecked MyWeekly in Columns
    viewer._category_combo.setCurrentText("Daily")

    assert viewer._table.isColumnHidden(1) is False   # Daily, visible -> shown
    assert viewer._table.isColumnHidden(2) is True    # Weekly AND unchecked -> hidden

    viewer._category_combo.setCurrentText("All")
    assert viewer._table.isColumnHidden(2) is True    # still unchecked via Columns


# ── HistoricDataViewer: Reset ("↺ Reset" button) ─────────────────────────

def test_reset_restores_column_visibility_and_clears_filters_and_search(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Sector", "Symbol", "MyDaily"],
        [["FINANCE", "360ONE", "X"], ["CG", "ABB", "Y"]],
        "05-Jul-2026",
        column_categories={"MyDaily": "Daily"},
    )
    viewer._apply_col_filter({0, 1})            # MyDaily hidden via Columns
    viewer._category_combo.setCurrentText("Weekly")
    viewer._sector_combo.setCurrentText("CG")
    viewer._search_box.setText("abb")

    viewer._reset_columns()

    assert viewer._table.isColumnHidden(2) is False
    assert viewer._category_combo.currentText() == "All"
    assert viewer._sector_combo.currentText() == "All"
    assert viewer._search_box.text() == ""
    assert viewer._table.isRowHidden(0) is False
    assert viewer._table.isRowHidden(1) is False


def test_reset_restores_natural_column_order_after_drag(qapp):
    from screens.historic_viewer import HistoricDataViewer
    viewer = HistoricDataViewer(
        ["Symbol", "Close", "Volume"],
        [["ABB", "100", "5000"]],
        "05-Jul-2026",
    )
    hdr = viewer._table.horizontalHeader()
    hdr.moveSection(0, 2)   # drag "Symbol" to the end

    viewer._reset_columns()

    assert [hdr.visualIndex(i) for i in range(3)] == [0, 1, 2]
