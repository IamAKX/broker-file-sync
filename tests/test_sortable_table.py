"""#98: click-to-sort on the EMV View by Date popup (HistoricDataViewer) and HMV."""
import sys

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _col(table, c):
    return [table.item(r, c).text() for r in range(table.rowCount())]


def _viewer(qapp):
    from screens.historic_viewer import HistoricDataViewer
    headers = ["Sector", "Symbol", "Close", "Note"]
    rows = [
        ["Bank", "HDFC", 9.5, "b"],
        ["Bank", "ICICI", 100.25, None],
        ["IT", "TCS", -3.0, "a"],
        ["IT", "INFY", None, "c"],
        ["Auto", "TVS", 10.0, ""],
    ]
    return HistoricDataViewer(headers, rows, "16-Oct-2026", frozen_headers=["Sector", "Symbol"],
                              cell_highlights={(2, 2): "#ff0000"})


def test_numeric_sort_ascending_then_descending_blanks_last(qapp):
    v = _viewer(qapp)
    v._sorter._on_clicked(2)
    # numeric (not lexical: 9.5 < 10 < 100), blank last
    assert _col(v._table, 2) == ["-3.0000", "9.5000", "10.0000", "100.2500", ""]
    v._sorter._on_clicked(2)
    assert _col(v._table, 2) == ["100.2500", "10.0000", "9.5000", "-3.0000", ""]
    hdr = v._table.horizontalHeader()
    assert hdr.sortIndicatorSection() == 2
    assert hdr.sortIndicatorOrder() == Qt.SortOrder.DescendingOrder


def test_text_sort_and_rows_stay_intact(qapp):
    v = _viewer(qapp)
    v._sorter._on_clicked(1)          # Symbol asc
    assert _col(v._table, 1) == ["HDFC", "ICICI", "INFY", "TCS", "TVS"]
    # whole rows moved together
    r = _col(v._table, 1).index("TCS")
    assert v._table.item(r, 0).text() == "IT" and v._table.item(r, 2).text() == "-3.0000"
    # cell highlight travelled with its cell
    assert v._table.item(r, 2).background().color().name() == "#ff0000"


def test_frozen_overlay_header_sorts_too(qapp):
    v = _viewer(qapp)
    fh = v._freeze.overlay_header()
    assert fh.sectionsClickable()
    fh.sectionClicked.emit(1)
    assert _col(v._table, 1) == ["HDFC", "ICICI", "INFY", "TCS", "TVS"]


def test_sort_reapplies_search_filter(qapp):
    v = _viewer(qapp)
    v._search_box.setText("tc")
    v._sorter._on_clicked(2)
    visible = [r for r in range(v._table.rowCount()) if not v._table.isRowHidden(r)]
    assert len(visible) == 1
    assert v._table.item(visible[0], 1).text() == "TCS"
    assert not v._freeze._overlay.isRowHidden(visible[0])


def test_reapply_keeps_sort_after_repopulate_and_drops_missing_column(qapp):
    from components.sortable_table import HeaderSorter, SortableItem
    from PySide6.QtWidgets import QTableWidget
    t = QTableWidget(2, 2)
    t.setHorizontalHeaderLabels(["A", "B"])
    for r, (a, b) in enumerate([("2", "x"), ("1", "y")]):
        t.setItem(r, 0, SortableItem(a)); t.setItem(r, 1, SortableItem(b))
    s = HeaderSorter(t)
    s._on_clicked(0)
    assert [t.item(r, 0).text() for r in range(2)] == ["1", "2"]
    # repopulate with the original order
    for r, (a, b) in enumerate([("2", "x"), ("1", "y")]):
        t.setItem(r, 0, SortableItem(a)); t.setItem(r, 1, SortableItem(b))
    s.reapply()
    assert [t.item(r, 0).text() for r in range(2)] == ["1", "2"]
    t.setHorizontalHeaderLabels(["Z", "B"])
    s.reapply()
    assert s.column_name is None


def test_hmv_sorts_with_header_click(qapp):
    from screens.inception_hmv import InceptionHmvScreen
    from app import AppController
    scr = InceptionHmvScreen(AppController(qapp))
    scr._headers = ["Sector", "Symbol", "V"]
    scr._data = [["A", "X", 5.0], ["A", "Y", 12.0], ["B", "Z", 1.0]]
    scr._visible_cols = {0, 1, 2}
    scr._fmt_colors = []
    scr._changed_cells = set()
    scr._populate_table()
    scr._sorter._on_clicked(2)
    assert [scr._table.item(r, 2).text() for r in range(3)] == ["1.0000", "5.0000", "12.0000"]
    scr._sorter._on_clicked(2)
    assert [scr._table.item(r, 2).text() for r in range(3)] == ["12.0000", "5.0000", "1.0000"]
