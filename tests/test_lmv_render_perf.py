"""screens.live_viewer._populate_table's full-rebuild path — the "LMV gets
slow when I apply a strategy" performance fix.

Profiling a realistic 220-row x 85-column rebuild found two real, avoidable
costs (not architectural, both fixed here):
  1. resizeColumnsToContents() re-measures EVERY column's text width on
     every render whose header set changed at all — including the ~80 base
     sheet columns, which never actually changed — costing as much as
     populating every cell in the table combined. Fixed: only newly-seen
     column NAMES get resized (self._sized_col_names, a persistent set),
     via resizeColumnToContents() per column instead of the blanket call.
  2. _apply_cell_style() built a fresh QBrush(norm_bg)/QBrush(norm_txt) for
     every single cell, every render — reused now (norm_bg_brush/
     norm_txt_brush, built once per render pass).

These tests guard the resize-scoping behavior specifically (the QBrush
reuse has no externally-observable behavior difference to assert beyond
"styling still works", already covered by tests/test_lmv_frozen_column.py
and friends continuing to pass).
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    from services import config_store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config.json"))
    monkeypatch.setattr(config_store, "load_column_order", lambda key=config_store.MAIN_COLUMN_ORDER: [])
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Open", "High", "Low", "Close"]
    w._data    = [["INFY", "100", "110", "95", "105"], ["TCS", "200", "210", "195", "205"]]
    w._visible_cols = set(range(len(w._headers)))
    w._populate_table(w._data, changed_keys=set())
    return w


def _spy_resize(monkeypatch):
    resized = []
    monkeypatch.setattr(QTableWidget, "resizeColumnToContents",
                        lambda self, col: resized.append(col))
    monkeypatch.setattr(QTableWidget, "resizeColumnsToContents",
                        lambda self: resized.append("ALL"))
    return resized


def test_new_strategy_column_gets_resized_once(lmv, monkeypatch):
    resized = _spy_resize(monkeypatch)
    headers = lmv._headers + ["MyStrategy"]
    data = [row + [1.0] for row in lmv._data]
    lmv._populate_table(data, changed_keys=set(), precomputed_disp=(headers, data))
    assert "MyStrategy" in lmv._sized_col_names
    assert len(resized) >= 1   # the new column (and any other first-seen names) got measured


def test_reapplying_same_strategy_does_not_reresize_anything(lmv, monkeypatch):
    """Toggle a strategy on, off, then on again — the third render (same
    column name reappearing) must not re-measure ANY column, base or
    strategy — this is exactly the "applying a strategy is slow" scenario."""
    headers_on = lmv._headers + ["MyStrategy"]
    data_on = [row + [1.0] for row in lmv._data]
    lmv._populate_table(data_on, changed_keys=set(), precomputed_disp=(headers_on, data_on))   # on (first time — resizes)
    lmv._populate_table(lmv._data, changed_keys=set())                                          # off
    lmv._populate_table(data_on, changed_keys=set(), precomputed_disp=(headers_on, data_on))    # on again

    resized = _spy_resize(monkeypatch)
    lmv._populate_table(lmv._data, changed_keys=set())                                          # off again
    lmv._populate_table(data_on, changed_keys=set(), precomputed_disp=(headers_on, data_on))    # on again — should resize nothing
    assert resized == []


def test_a_second_distinct_strategy_column_only_resizes_itself(lmv, monkeypatch):
    headers1 = lmv._headers + ["StratA"]
    data1 = [row + [1.0] for row in lmv._data]
    lmv._populate_table(data1, changed_keys=set(), precomputed_disp=(headers1, data1))

    resized = _spy_resize(monkeypatch)
    headers2 = lmv._headers + ["StratA", "StratB"]
    data2 = [row + [2.0] for row in data1]
    lmv._populate_table(data2, changed_keys=set(), precomputed_disp=(headers2, data2))
    assert resized == [headers2.index("StratB")]   # only the genuinely new column


def test_sized_col_names_seeded_from_initial_load(lmv):
    assert set(lmv._headers) <= lmv._sized_col_names
