import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    from services import config_store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Open", "High", "Low", "Close"]
    w._data    = [["INFY", "100", "110", "95", "105"], ["TCS", "200", "210", "195", "205"]]
    w._visible_cols = set(range(len(w._headers)))
    w._populate_table(w._data, changed_keys=set())
    return w


def test_scrip_name_column_is_frozen(lmv):
    assert lmv._frozen_logical_col == lmv._headers.index("Scrip Name")
    assert lmv._frozen_table.isHidden() is False


def test_only_scrip_name_visible_in_frozen_table(lmv):
    n = lmv._frozen_table.model().columnCount()
    for c in range(n):
        expected_hidden = c != lmv._frozen_logical_col
        assert lmv._frozen_table.isColumnHidden(c) == expected_hidden


def test_frozen_table_shares_content_via_common_model(lmv):
    col = lmv._frozen_logical_col
    assert lmv._table.item(0, col).text() == "INFY"
    assert lmv._frozen_table.model().index(0, col).data() == "INFY"
    assert lmv._table.item(1, col).text() == "TCS"
    assert lmv._frozen_table.model().index(1, col).data() == "TCS"


def test_scrip_name_pinned_to_visual_index_zero(lmv):
    hdr = lmv._table.horizontalHeader()
    assert hdr.visualIndex(lmv._frozen_logical_col) == 0


def test_dragging_another_column_in_front_snaps_scrip_name_back(lmv):
    hdr = lmv._table.horizontalHeader()
    # Drag "Open" (logical 1) to the far left (visual 0), displacing Scrip Name.
    hdr.moveSection(hdr.visualIndex(1), 0)
    assert hdr.visualIndex(lmv._frozen_logical_col) == 0
    assert hdr.visualIndex(1) == 1


def test_dragging_scrip_name_away_snaps_it_back(lmv):
    hdr = lmv._table.horizontalHeader()
    hdr.moveSection(hdr.visualIndex(lmv._frozen_logical_col), 2)
    assert hdr.visualIndex(lmv._frozen_logical_col) == 0


def test_sector_filter_hides_rows_in_frozen_table_too(lmv):
    lmv._table.setRowHidden(0, False)
    lmv._table.setRowHidden(1, False)
    lmv._sector_combo.addItem("SomeSector")
    lmv._sector_combo.setCurrentText("SomeSector")
    lmv._apply_sector_filter()
    for r in range(lmv._table.rowCount()):
        assert lmv._frozen_table.isRowHidden(r) == lmv._table.isRowHidden(r)


def test_programmatic_pinning_does_not_persist_column_order(lmv, monkeypatch):
    """The automatic left-pin of Scrip Name (see test above) must not be
    saved to disk as if the user had dragged it — that would bake a
    snap-back into the saved order instead of leaving it alone."""
    from services import config_store
    saved = {}
    monkeypatch.setattr(config_store, "save_column_order",
                        lambda ordered: saved.setdefault("ordered", ordered))

    hdr = lmv._table.horizontalHeader()
    hdr.moveSection(hdr.visualIndex(1), 0)   # triggers the automatic snap-back

    assert "ordered" not in saved


def test_real_user_drag_of_non_frozen_columns_still_persists_order(lmv, monkeypatch):
    from services import config_store
    saved = {}
    monkeypatch.setattr(config_store, "save_column_order",
                        lambda ordered: saved.setdefault("ordered", ordered))

    hdr = lmv._table.horizontalHeader()
    # Move "High" (logical 2, currently visual 2) to visual 1 — doesn't
    # touch Scrip Name's position, so this is a genuine user reorder.
    hdr.moveSection(hdr.visualIndex(2), 1)

    assert "ordered" in saved
    assert saved["ordered"][0] == "Scrip Name"
