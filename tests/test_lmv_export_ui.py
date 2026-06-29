import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from PySide6.QtWidgets import QApplication, QPushButton


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Current", "High"]
    w._data    = [["INFY", "100", "110"], ["TCS", "200", "210"]]
    w._visible_cols = set(range(3))
    w._populate_table(w._data, changed_keys=set())
    return w


def test_export_button_exists(lmv):
    labels = [b.text() for b in lmv.findChildren(QPushButton)]
    assert any("Export" in t for t in labels)


def test_visible_table_data_returns_all_when_unfiltered(lmv):
    headers, rows = lmv._visible_table_data()
    assert headers == ["Scrip Name", "Current", "High"]
    assert rows == [["INFY", "100", "110"], ["TCS", "200", "210"]]


def test_visible_table_data_skips_hidden_columns(lmv):
    lmv._table.setColumnHidden(1, True)   # hide "Current"
    headers, rows = lmv._visible_table_data()
    assert headers == ["Scrip Name", "High"]
    assert rows == [["INFY", "110"], ["TCS", "210"]]


def test_visible_table_data_skips_hidden_rows(lmv):
    lmv._table.setRowHidden(0, True)      # hide INFY
    _, rows = lmv._visible_table_data()
    assert rows == [["TCS", "200", "210"]]


def test_export_applies_rename_map(lmv, tmp_path, monkeypatch):
    openpyxl = pytest.importorskip("openpyxl")
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    config_store.save_tab("main_column_name", [("Current", "LTP")])

    out = tmp_path / "export.xlsx"
    # Drive the export without the interactive file dialog.
    from PySide6.QtWidgets import QFileDialog, QMessageBox
    monkeypatch.setattr(QFileDialog, "getSaveFileName",
                        staticmethod(lambda *a, **k: (str(out), "")))
    monkeypatch.setattr(QMessageBox, "information",
                        staticmethod(lambda *a, **k: None))
    lmv._export()

    ws = openpyxl.load_workbook(str(out)).active
    assert [c.value for c in ws[1]] == ["Scrip Name", "LTP", "High"]
    assert ws.max_row == 3
