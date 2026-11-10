"""#110 — header right-click > Show top / bottom N by this column (LMV, EMV View by Date popup, HMV)."""
import sys

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _table(values):
    t = QTableWidget(len(values), 2)
    t.setHorizontalHeaderLabels(["Symbol", "DAY TO"])
    for r, (sym, v) in enumerate(values):
        t.setItem(r, 0, QTableWidgetItem(sym))
        t.setItem(r, 1, QTableWidgetItem(v))
    return t


VALUES = [("A", "1.5"), ("B", "9"), ("C", "1,200.5"), ("D", "-3"), ("E", ""), ("F", "n/a"), ("G", "4%")]


def _filter(t, sort_calls=None):
    from components.color_filter import ColorColumnFilter
    return ColorColumnFilter(
        t, lambda c: t.horizontalHeaderItem(c).text(), lambda: None,
        sort_fn=(lambda n, d: sort_calls.append((n, d))) if sort_calls is not None else None)


def test_parse_number():
    from components.color_filter import parse_number
    assert parse_number("1,234.50") == 1234.5 and parse_number("-2.5%") == -2.5
    assert parse_number("") is None and parse_number("n/a") is None and parse_number(None) is None


def test_top_and_bottom_n_rank_numeric_cells_and_skip_non_numbers(qapp):
    t = _table(VALUES)
    calls = []
    f = _filter(t, calls)
    rows = range(t.rowCount())
    assert f.limit_rows(rows) == set(rows) and not f.active          # nothing set -> no limit

    f.set_topn("DAY TO", 3, "top")
    assert f.active and f.limit_rows(rows) == {2, 1, 6}               # 1200.5, 9, 4 (blank / n/a never kept)
    assert calls == [("DAY TO", True)]                                # sorted descending
    assert f.summary() == "top 3 by DAY TO"

    f.set_topn("DAY TO", 2, "bottom")
    assert f.limit_rows(rows) == {3, 0}                               # -3, 1.5
    assert calls[-1] == ("DAY TO", False)                             # sorted ascending

    f.set_topn("DAY TO", 100, "top")                                  # N larger than the rows -> all numeric rows
    assert f.limit_rows(rows) == {0, 1, 2, 3, 6}

    assert f.limit_rows([0, 1, 6]) == {0, 1, 6}                       # ranks only what other filters kept
    f.set_topn("DAY TO", 1, "top")
    assert f.limit_rows([0, 1, 6]) == {1}

    f.clear()
    assert not f.active and f.limit_rows(rows) == set(rows) and f.summary() == ""


def test_header_menu_has_top_bottom_and_clear(qapp):
    t = _table(VALUES)
    f = _filter(t)
    menu = f.build_menu(1)
    labels = [a.text() for a in menu.actions() if a.text()]
    assert "Show top N…" in labels and "Show bottom N…" in labels and "Clear top / bottom N" in labels
    assert not next(a for a in menu.actions() if a.text() == "Clear top / bottom N").isEnabled()
    f.set_topn("DAY TO", 2, "top")
    menu = f.build_menu(1)
    assert next(a for a in menu.actions() if a.text() == "Clear top / bottom N").isEnabled()
    next(a for a in menu.actions() if a.text() == "Clear top / bottom N").trigger()
    assert f.topn() is None


def test_emv_view_by_date_popup_top_n_composes_with_search_sorts_and_resets(qapp):
    from screens.historic_viewer import HistoricDataViewer
    headers = ["Sector", "Symbol", "DAY TO"]
    rows = [["Bank", "HDFC", "5"], ["Bank", "ICICI", "50"], ["IT", "TCS", "20"], ["IT", "INFY", "30"], ["IT", "WIPRO", "1"]]
    v = HistoricDataViewer(headers, rows, "d", frozen_headers=["Sector", "Symbol"])
    visible = lambda: [v._table.item(r, 1).text() for r in range(5) if not v._table.isRowHidden(r)]

    v._color_filter.set_topn("DAY TO", 2, "top")
    assert visible() == ["ICICI", "INFY"]                             # best first (sorted descending)
    assert "top 2 by DAY TO" in v._stock_count_lbl.text() and "Stocks : 2" in v._stock_count_lbl.text()
    assert all(v._freeze._overlay.isRowHidden(r) == v._table.isRowHidden(r) for r in range(5))

    v._color_filter.set_topn("DAY TO", 2, "bottom")
    assert visible() == ["WIPRO", "HDFC"]                             # ascending

    v._color_filter.set_topn("DAY TO", 2, "top")
    v._sector_combo.setCurrentText("IT")                              # sector filter first, THEN rank
    assert visible() == ["INFY", "TCS"]

    v._reset_columns()
    assert len(visible()) == 5 and not v._color_filter.active


def test_hmv_top_n_survives_repopulate(qapp):
    from app import AppController
    from screens.inception_hmv import InceptionHmvScreen
    scr = InceptionHmvScreen(AppController(qapp))
    scr._headers = ["Sector", "Symbol", "V"]
    scr._data = [["A", "X", 5.0], ["A", "Y", 12.0], ["B", "Z", 1.0]]
    scr._visible_cols = {0, 1, 2}
    scr._fmt_colors = [{}, {}, {}]
    scr._changed_cells = set()
    scr._populate_table()
    shown = lambda: [scr._table.item(r, 1).text() for r in range(3) if not scr._table.isRowHidden(r)]
    scr._color_filter.set_topn("V", 2, "top")
    assert shown() == ["Y", "X"]
    scr._populate_table()                                              # e.g. a strategy toggle re-render
    assert shown() == ["Y", "X"]
    scr._color_filter.clear()
    assert len(shown()) == 3


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import config_store
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Sector", "Scrip Name", "Open", "DAY TO"]
    w._data = [["IT", "INFY", "100", "3"], ["IT", "TCS", "200", "9"],
               ["BANK", "HDFC", "300", "1.5"], ["BANK", "SBIN", "50", "7"], ["BANK", "AXIS", "60", "4"]]
    w._visible_cols = set(range(len(w._headers)))
    w._populate_table(w._data, changed_keys=set())
    w._apply_sector_filter()
    return w


def test_lmv_top_bottom_n_sorts_and_composes_with_sector(lmv):
    visible = lambda: [lmv._table.item(r, 1).text() for r in range(lmv._table.rowCount())
                       if not lmv._table.isRowHidden(r)]
    lmv._color_filter.set_topn("DAY TO", 3, "top")
    assert visible() == ["TCS", "SBIN", "AXIS"]                       # highest first
    assert "top 3 by DAY TO" in lmv._stock_count_lbl.text() and "Stocks : 3" in lmv._stock_count_lbl.text()
    assert all(lmv._frozen_table.isRowHidden(r) == lmv._table.isRowHidden(r) for r in range(5))

    lmv._color_filter.set_topn("DAY TO", 2, "bottom")
    assert visible() == ["HDFC", "INFY"]                              # lowest first

    lmv._populate_table(lmv._data, changed_keys=set())                # a later tick re-renders
    lmv._apply_sector_filter()
    assert visible() == ["HDFC", "INFY"]

    lmv._color_filter.set_topn("DAY TO", 2, "top")
    lmv._sector_combo.addItem("BANK")
    lmv._sector_combo.setCurrentText("BANK")                          # sector first, then top 2 of the bank stocks
    assert visible() == ["SBIN", "AXIS"]


def test_lmv_top_n_ranks_only_strategy_filtered_rows_and_reset_clears_it(lmv):
    lt = lambda n: [{"type": "col", "value": "DAY TO"}, {"type": "op", "value": "<"}, {"type": "num", "value": str(n)}]
    lmv._strategies = [{"id": "s1", "name": "Sig", "active": True, "category": "Daily",
                        "row_filter": lt(8), "columns": []}]       # strategy drops TCS (9) -> 4 stocks left
    lmv._populate_table(lmv._data, changed_keys=set())
    lmv._apply_sector_filter()
    shown = lambda: [lmv._table.item(r, 1).text() for r in range(lmv._table.rowCount()) if not lmv._table.isRowHidden(r)]
    assert "TCS" not in shown() and len(shown()) == 4                 # the strategy filter really applied
    lmv._color_filter.set_topn("DAY TO", 2, "top")
    assert shown() == ["SBIN", "AXIS"]                                # top 2 of the 4 that passed, not of all 5

    lmv._reset_view()
    assert not lmv._color_filter.active
