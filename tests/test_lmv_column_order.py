"""screens.live_viewer._restore_column_order — the LMV-side consumer of
Config Editor's "Main Column Order" tab (services.config_store.
save_column_order/load_column_order). See tests/test_config_editor.py for
the save-side regression coverage (the tab used to persist through
save_tab's list-of-row-tuples shape instead, corrupting this key for every
reader)."""
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


def test_restore_column_order_applies_saved_order(lmv):
    from services.config_store import save_column_order
    save_column_order(["Close", "Open"])

    lmv._restore_column_order()

    hdr = lmv._table.horizontalHeader()
    close_logical = lmv._headers.index("Close")
    open_logical = lmv._headers.index("Open")
    assert hdr.visualIndex(close_logical) == 0
    assert hdr.visualIndex(open_logical) == 1


def test_restore_column_order_skips_names_not_in_current_table(lmv):
    from services.config_store import save_column_order
    save_column_order(["Not A Real Column", "Close"])

    lmv._restore_column_order()   # must not raise

    hdr = lmv._table.horizontalHeader()
    close_logical = lmv._headers.index("Close")
    assert hdr.visualIndex(close_logical) == 0


def test_restore_column_order_ignores_non_string_entries_without_crashing(lmv, monkeypatch):
    """Regression: a non-string entry (e.g. the legacy ["Open"]-shaped
    corruption save_column_order's own docstring describes) used to crash
    this loop outright — dict.get() on an unhashable list key — rather than
    just being skipped like any other unmatched name. Bypasses
    load_column_order's own string-filtering (belt-and-suspenders: this
    guard should hold even if some other path ever writes a bad shape)."""
    import services.config_store as config_store
    monkeypatch.setattr(config_store, "load_column_order", lambda: [["Open"], "Close", ["High"]])

    lmv._restore_column_order()   # must not raise

    hdr = lmv._table.horizontalHeader()
    close_logical = lmv._headers.index("Close")
    assert hdr.visualIndex(close_logical) == 0
