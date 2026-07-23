import sys
import pytest
from datetime import date
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


HEADERS = ["Sector", "Scrip Name", "Current", "PATP"]
DATA = [
    ["IT", "INFY", 1800.0, 1780.0],
    ["Energy", "ADANIENT", 3200.0, 3150.0],
]


def test_viewer_populates_table(qapp, monkeypatch):
    from screens.lmv_snapshot_viewer import LmvSnapshotViewer
    from services import strategy_store

    # Isolate from whatever's actually saved in the real strategies.json —
    # an active strategy there would add its own output column and break
    # this test's exact column-count assertion regardless of this test's
    # own synthetic data.
    monkeypatch.setattr(strategy_store, "load_all", lambda: [])

    w = LmvSnapshotViewer(HEADERS, DATA, date(2026, 7, 20), theme=None)
    assert w._table.rowCount() == 2
    assert w._table.columnCount() == 4
    assert w._table.horizontalHeaderItem(1).text() == "Scrip Name"


def test_viewer_save_button_hidden_without_on_save(qapp):
    from screens.lmv_snapshot_viewer import LmvSnapshotViewer
    w = LmvSnapshotViewer(HEADERS, DATA, date(2026, 7, 20), theme=None, on_save=None)
    labels = [b.text() for b in w.findChildren(QPushButton)]
    assert "Save" not in labels


def test_viewer_save_button_shown_with_on_save(qapp):
    from screens.lmv_snapshot_viewer import LmvSnapshotViewer
    called = []
    w = LmvSnapshotViewer(HEADERS, DATA, date(2026, 7, 20), theme=None, on_save=lambda: called.append(True))
    labels = [b.text() for b in w.findChildren(QPushButton)]
    assert "Save" in labels
    save_btn = next(b for b in w.findChildren(QPushButton) if b.text() == "Save")
    save_btn.click()
    assert called == [True]


def test_viewer_sector_filter_hides_non_matching_rows(qapp):
    from screens.lmv_snapshot_viewer import LmvSnapshotViewer
    w = LmvSnapshotViewer(HEADERS, DATA, date(2026, 7, 20), theme=None)
    # The combo is populated from the real config_defaults.SECTOR_STOCK_DATA
    # sector list, unrelated to this test's synthetic row data — add the
    # row-level value directly so the filter's row-vs-combo-text comparison
    # (screens.lmv_snapshot_viewer.LmvSnapshotViewer._apply_sector_filter)
    # can be exercised regardless of what's in the real config.
    w._sector_combo.addItem("IT")
    w._sector_combo.setCurrentText("IT")
    assert w._table.isRowHidden(0) is False
    assert w._table.isRowHidden(1) is True


def test_viewer_title_defaults_to_trade_date(qapp):
    from screens.lmv_snapshot_viewer import LmvSnapshotViewer
    w = LmvSnapshotViewer(HEADERS, DATA, date(2026, 7, 20), theme=None)
    assert "20-Jul-2026" in w.windowTitle()
