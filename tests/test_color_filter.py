"""#99: Excel-style filter by cell colour on the LMV grid, EMV View by Date and HMV."""
import sys

import pytest
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QApplication, QTableWidget, QTableWidgetItem


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _table(rows):
    t = QTableWidget(len(rows), 2)
    t.setHorizontalHeaderLabels(["Symbol", "Sig"])
    for r, (sym, color) in enumerate(rows):
        t.setItem(r, 0, QTableWidgetItem(sym))
        it = QTableWidgetItem(sym)
        if color:
            it.setBackground(QBrush(QColor(color)))
        t.setItem(r, 1, it)
    return t


def test_component_lists_present_colours_and_filters_rows(qapp):
    from components.color_filter import ColorColumnFilter, NO_FILL
    t = _table([("A", "#16a34a"), ("B", "#dc2626"), ("C", "#16a34a"), ("D", None), ("E", "#16a34a")])
    seen = []
    f = ColorColumnFilter(t, lambda c: t.horizontalHeaderItem(c).text(), on_changed=lambda: seen.append(1))

    assert f.colors_in_column(1) == ["#16a34a", "#dc2626", NO_FILL]        # by frequency, No fill last
    assert f.colors_in_column(0) == [NO_FILL]                               # an unformatted column
    assert not f.active and all(f.row_passes(r) for r in range(5))

    f.set_filter("Sig", "#16a34a")
    assert [f.row_passes(r) for r in range(5)] == [True, False, True, False, True]
    f.set_filter("Sig", NO_FILL)
    assert [r for r in range(5) if f.row_passes(r)] == [3]
    assert f.summary() == "colour filter: Sig"
    f.set_filter("Sig", None)
    assert not f.active and len(seen) == 3
    f.set_filter("Sig", "#dc2626"); f.clear()
    assert not f.active and len(seen) == 5


def test_translucent_tints_and_base_fill_count_as_no_fill(qapp):
    from components.color_filter import ColorColumnFilter, NO_FILL
    t = _table([("A", "#1c2128"), ("B", None), ("C", "#16a34a")])
    t.item(1, 1).setBackground(QBrush(QColor(57, 211, 83, 34)))            # LMV strategy-column tint
    f = ColorColumnFilter(t, lambda c: t.horizontalHeaderItem(c).text(), lambda: None,
                          base_colors={"#1c2128"})
    assert f.colors_in_column(1) == ["#16a34a", NO_FILL]


def test_header_menu_offers_colours_swatches_and_clear(qapp):
    from components.color_filter import ColorColumnFilter
    t = _table([("A", "#16a34a"), ("B", "#dc2626")])
    f = ColorColumnFilter(t, lambda c: t.horizontalHeaderItem(c).text(), lambda: None)
    menu = f.build_menu(1)
    sub = menu._submenu
    labels = [a.text() for a in sub.actions() if a.text()]
    assert "#16A34A" in labels and "#DC2626" in labels and "Clear filter on this column" in labels
    swatch = next(a for a in sub.actions() if a.text() == "#16A34A")
    assert not swatch.icon().isNull()
    assert [a for a in menu.actions() if a.text() == "Clear all colour filters"][0].isEnabled() is False
    next(a for a in sub.actions() if a.text() == "#DC2626").trigger()
    assert f.filters() == {"Sig": "#dc2626"}
    menu2 = f.build_menu(1)
    assert [a for a in menu2.actions() if a.text() == "Clear all colour filters"][0].isEnabled() is True
    assert next(a for a in menu2._submenu.actions() if a.text() == "#DC2626").isChecked()


def test_historic_viewer_colour_filter_combines_with_search_and_resets(qapp):
    from screens.historic_viewer import HistoricDataViewer
    headers = ["Sector", "Symbol", "Sig"]
    rows = [["Bank", "HDFC", "x"], ["Bank", "ICICI", "x"], ["IT", "TCS", "x"], ["IT", "INFY", "x"]]
    v = HistoricDataViewer(headers, rows, "d", frozen_headers=["Sector", "Symbol"],
                           cell_highlights={(0, 2): "#16a34a", (2, 2): "#16a34a", (1, 2): "#dc2626"})
    visible = lambda: [v._table.item(r, 1).text() for r in range(4) if not v._table.isRowHidden(r)]

    v._color_filter.set_filter("Sig", "#16a34a")
    assert visible() == ["HDFC", "TCS"]
    assert "colour filter: Sig" in v._stock_count_lbl.text() and "Stocks : 2" in v._stock_count_lbl.text()
    assert all(v._freeze._overlay.isRowHidden(r) == v._table.isRowHidden(r) for r in range(4))

    v._search_box.setText("tc")                                   # composes with the symbol search
    assert visible() == ["TCS"]
    v._search_box.setText("")
    v._sorter._on_clicked(1)                                      # still applied after a sort
    assert visible() == ["HDFC", "TCS"]

    v._reset_columns()                                            # ↺ Reset clears it
    assert len(visible()) == 4 and not v._color_filter.active


def test_hmv_colour_filter_hides_rows_and_survives_repopulate(qapp):
    from app import AppController
    from screens.inception_hmv import InceptionHmvScreen
    scr = InceptionHmvScreen(AppController(qapp))
    scr._headers = ["Sector", "Symbol", "V"]
    scr._data = [["A", "X", 5.0], ["A", "Y", 12.0], ["B", "Z", 1.0]]
    scr._visible_cols = {0, 1, 2}
    scr._fmt_colors = [{"V": "#16a34a"}, {}, {"V": "#16a34a"}]
    scr._changed_cells = set()
    scr._populate_table()
    assert scr._color_filter.colors_in_column(2)[0] == "#16a34a"
    scr._color_filter.set_filter("V", "#16a34a")
    shown = lambda: [scr._table.item(r, 1).text() for r in range(3) if not scr._table.isRowHidden(r)]
    assert shown() == ["X", "Z"]
    scr._populate_table()                                          # e.g. a strategy toggle re-render
    assert shown() == ["X", "Z"]
    scr._color_filter.clear()
    assert shown() == ["X", "Y", "Z"]


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import config_store
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Sector", "Scrip Name", "Open", "Close"]
    w._data = [["IT", "INFY", "100", "110"], ["IT", "TCS", "200", "205"],
               ["BANK", "HDFC", "300", "150"], ["BANK", "SBIN", "50", "180"]]
    w._visible_cols = set(range(len(w._headers)))
    return w


def _apply_strategy(w):
    gt = lambda n: [{"type": "col", "value": "Close"}, {"type": "op", "value": ">"}, {"type": "num", "value": str(n)}]
    w._strategies = [{
        "id": "s1", "name": "Sig", "active": True, "category": "Daily", "row_filter": [],
        "columns": [{"name": "Sig", "formula": [{"type": "col", "value": "Close"}], "fmt_rules": [
            {"condition": gt(200), "color": "#16a34a", "target_column": None},
            {"condition": [{"type": "col", "value": "Close"}, {"type": "op", "value": "<"}, {"type": "num", "value": "160"}],
             "color": "#dc2626", "target_column": None}]}],
    }]
    w._populate_table(w._data, changed_keys=set())
    w._apply_sector_filter()


def test_lmv_filters_by_conditional_format_colour_and_composes_with_sector(lmv):
    _apply_strategy(lmv)
    col = lmv._headers.__len__()                     # the strategy column follows the base columns
    visible = lambda: [lmv._table.item(r, 1).text() for r in range(4) if not lmv._table.isRowHidden(r)]
    assert visible() == ["INFY", "TCS", "HDFC", "SBIN"]

    colours = lmv._color_filter.colors_in_column(col)
    assert set(colours[:2]) == {"#16a34a", "#dc2626"}        # fmt colours, not the card background

    lmv._color_filter.set_filter("Sig", "#16a34a")           # Close > 200 -> TCS
    assert visible() == ["TCS"]
    assert "Stocks : 1" in lmv._stock_count_lbl.text() and "colour filter: Sig" in lmv._stock_count_lbl.text()
    assert lmv._frozen_table.isRowHidden(0) and not lmv._frozen_table.isRowHidden(1)   # overlay mirrors it

    lmv._color_filter.set_filter("Sig", "#dc2626")           # Close < 160 -> INFY, HDFC
    assert visible() == ["INFY", "HDFC"]

    lmv._color_filter.clear()
    lmv._sector_combo.addItem("IT")
    lmv._sector_combo.setCurrentText("IT")
    lmv._color_filter.set_filter("Sig", "#dc2626")           # red + sector IT -> INFY only
    assert visible() == ["INFY"]
    lmv._color_filter.set_filter("Sig", "__no_fill__")       # "No fill" + IT -> nobody (both IT rows coloured)
    assert visible() == []


def test_lmv_colour_filter_survives_rerender_ticks_and_ignores_amber_flash(lmv):
    from PySide6.QtGui import QBrush, QColor
    _apply_strategy(lmv)
    lmv._color_filter.set_filter("Sig", "#16a34a")
    col = len(lmv._headers)

    lmv._populate_table(lmv._data, changed_keys=set())       # a later tick re-renders
    lmv._apply_sector_filter()
    assert [lmv._table.item(r, 1).text() for r in range(4) if not lmv._table.isRowHidden(r)] == ["TCS"]

    # amber "changed" flash on TCS's coloured cell must not make it look like a different colour
    item = lmv._table.item(1, col)
    base = item.background()
    lmv._highlights[(1, col)] = (1e12, base, item.foreground())
    item.setBackground(QBrush(QColor("#f59e0b")))
    lmv._apply_sector_filter()
    assert not lmv._table.isRowHidden(1)


def test_lmv_reset_clears_the_colour_filter(lmv):
    _apply_strategy(lmv)
    lmv._color_filter.set_filter("Sig", "#16a34a")
    lmv._reset_view()
    assert not lmv._color_filter.active
    assert all(not lmv._table.isRowHidden(r) for r in range(lmv._table.rowCount()))
