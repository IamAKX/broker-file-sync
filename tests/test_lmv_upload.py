import sys
import pytest
from datetime import date
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.lmv_upload import LmvUploadScreen
    return LmvUploadScreen(AppController(qapp))


def test_lmv_upload_screen_creates(screen):
    assert screen is not None


def test_has_four_broker_cards_no_external_import(screen):
    assert set(screen._cards.keys()) == {
        "Sharekhan", "ReliableSoftware", "NiftyInvest", "MarketProfile",
    }


def test_view_button_initially_disabled(screen):
    assert not screen._view_btn.isEnabled()


def test_view_button_enabled_once_all_four_cards_have_files(screen, tmp_path):
    for broker in ("Sharekhan", "ReliableSoftware", "MarketProfile"):
        screen._cards[broker]._selected_file = str(tmp_path / f"{broker}.xls")
    screen._cards["NiftyInvest"]._selected_files = [str(tmp_path / "nifty.csv")]
    screen._update_view_btn()
    assert screen._view_btn.isEnabled()


def test_view_button_stays_disabled_if_one_card_missing(screen, tmp_path):
    for broker in ("Sharekhan", "ReliableSoftware"):
        screen._cards[broker]._selected_file = str(tmp_path / f"{broker}.xls")
    # MarketProfile and NiftyInvest left empty
    screen._update_view_btn()
    assert not screen._view_btn.isEnabled()


def test_selected_date_defaults_to_today(screen):
    assert screen._selected_date == date.today()


def test_cards_compare_date_provider_returns_selected_date(screen):
    screen._selected_date = date(2026, 7, 1)
    for card in screen._cards.values():
        assert card._compare_date_provider() == date(2026, 7, 1)


def test_data_menu_has_lmv_upload(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    from PySide6.QtWidgets import QPushButton
    tm = ThemeManager(qapp)
    topbar = TopBar(tm)
    found = False
    for btn in topbar.findChildren(QPushButton):
        menu = btn.menu()
        if menu is not None:
            for action in menu.actions():
                if action.text() == "LMV Upload":
                    found = True
    assert found


# ── _pivot_snapshot_for_viewer ───────────────────────────────────────────────

def test_pivot_snapshot_for_viewer_builds_headers_and_rows():
    from screens.lmv_upload import _pivot_snapshot_for_viewer

    stocks = [
        {"symbol": "INFY", "display_name": "Infosys Limited",
         "metrics": {"Open": 1790.0, "PATP": 1780.0}},
        {"symbol": "ABB", "display_name": "ABB LTD",
         "metrics": {"Open": 7500.0}},
    ]
    headers, rows = _pivot_snapshot_for_viewer(stocks)
    assert headers == ["Sector", "Scrip Name", "Open", "PATP"]
    row_by_scrip = {r[1]: r for r in rows}
    assert row_by_scrip["Infosys Limited"][2] == 1790.0
    assert row_by_scrip["Infosys Limited"][3] == 1780.0
    assert row_by_scrip["ABB LTD"][3] is None
