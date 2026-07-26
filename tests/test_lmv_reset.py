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


def _make_dirty(w):
    """Apply the kind of on-screen customization _reset_view should undo."""
    from services import strategy_store as store
    w._strategies = [
        {"id": "1", "name": "S1", "active": True, "category": "Daily", "columns": [], "row_filter": []},
    ]
    store.save_strategy(w._strategies[0])
    w._sector_combo.addItem("Auto")
    w._sector_combo.setCurrentText("Auto")
    w._table.setColumnHidden(2, True)
    w._visible_cols.discard(2)
    hdr = w._table.horizontalHeader()
    hdr.moveSection(hdr.visualIndex(3), 1)
    return hdr


def test_reset_button_exists(lmv):
    assert lmv._reset_btn is not None
    assert not lmv._reset_btn.icon().isNull()


def test_reset_deactivates_and_persists_strategies(lmv):
    from services import strategy_store as store
    _make_dirty(lmv)
    lmv._reset_view()
    assert all(not s["active"] for s in lmv._strategies)
    assert all(not s["active"] for s in store.load_all())


def test_reset_clears_sector_filter(lmv):
    _make_dirty(lmv)
    lmv._reset_view()
    assert lmv._sector_combo.currentText() == "All"


def test_reset_clears_category_filter(lmv):
    lmv._cat_combo.setCurrentText("Daily")
    lmv._reset_view()
    assert lmv._cat_combo.currentText() == "All"


def test_reset_shows_all_columns(lmv):
    _make_dirty(lmv)
    lmv._reset_view()
    for c in range(lmv._table.columnCount()):
        assert not lmv._table.isColumnHidden(c)


def test_reset_restores_natural_column_order(lmv):
    hdr = _make_dirty(lmv)
    assert [hdr.logicalIndex(v) for v in range(hdr.count())] != list(range(hdr.count()))
    lmv._reset_view()
    assert [hdr.logicalIndex(v) for v in range(hdr.count())] == list(range(hdr.count()))


def test_reset_clears_saved_column_order_on_disk(lmv):
    from services.config_store import load_column_order
    hdr = _make_dirty(lmv)
    lmv._reset_view()
    assert load_column_order() == []


def test_reset_reflects_when_combos_are_already_at_default(lmv):
    """Regression: setCurrentText("All") is a no-op (no signal, no
    re-render) when a combo already shows "All" — deactivating a strategy
    must still show up even if neither combo actually changes."""
    from services import strategy_store as store
    lmv._strategies = [
        {"id": "1", "name": "S1", "active": True, "category": "Daily", "columns": [], "row_filter": []},
    ]
    store.save_strategy(lmv._strategies[0])
    assert lmv._sector_combo.currentText() == "All"
    assert lmv._cat_combo.currentText() == "All"

    lmv._reset_view()

    assert all(not s["active"] for s in lmv._strategies)
