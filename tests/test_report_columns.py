import sys

import pytest
from PySide6.QtWidgets import QApplication

from services import report_columns


def test_resolve_columns_keeps_order_and_drops_unknown():
    out = report_columns.resolve_columns(["Yield", "Bogus", "Ticker"], ["Ticker", "Yield"], ["Ticker"])
    assert out == ["Yield", "Ticker"]


def test_resolve_columns_empty_selection_uses_default():
    assert report_columns.resolve_columns([], ["A", "B"], ["B"]) == ["B"]
    assert report_columns.resolve_columns(None, ["A", "B"], ["B"]) == ["B"]


def test_lmv_cell_reads_signal_fields_and_metrics():
    row = {"symbol": "INFY", "direction": "BUY", "entry": 100.0, "exit": 110.0, "yield": 10.0,
           "days_true": "2 Days", "status_label": "Target", "status_kind": "positive",
           "trade": {"sector": "IT", "running_high": 112.0,
                     "metrics": {"m": {"name": "Target 1", "value": 110.0}}}}
    assert report_columns.lmv_cell("Sector", "S", row, str) == "IT"
    assert report_columns.lmv_cell("High", "S", row, str) == "112.00"
    assert report_columns.lmv_cell("Target 1", "S", row, str) == "110.00"
    assert report_columns.lmv_cell("Nope", "S", row, str) == "—"


def test_emv_cell_reads_arbitrary_field_values():
    row = {"symbol": "X", "sector": "IT", "score": {"score": 80, "max_score": 100},
           "values": {"DT": 1234.5, "Flag": "Y"}}
    assert report_columns.emv_cell("DT", row) == "1,234.50"
    assert report_columns.emv_cell("Flag", row) == "Y"
    assert report_columns.emv_cell("Missing", row) == "—"
    assert report_columns.emv_cell("Fuku Score", row) == "80 / 100"


def test_lmv_report_renders_only_selected_columns():
    from services import lmv_report_data

    summary = {"name": "S", "blended_yield": 1.0, "closed_trades": 1, "win_rate": 100.0,
               "resolution_counts": {}, "sharpe": None, "sortino": None, "calmar": None,
               "trades": [{"sector": "IT", "metrics": {}}],
               "rows": [{"symbol": "INFY", "direction": "BUY", "entry": 1.0, "exit": 2.0, "yield": 1.0,
                         "days_true": "1 Day", "status_label": "T", "status_kind": "positive",
                         "trade": {"sector": "IT", "metrics": {}}}]}
    data = {"summary_a": summary, "summary_b": None, "bucket_keys": [], "curve_a": None, "curve_b": None,
            "investment": {"starting": 1, "ending": 1, "profit": 0}, "investment_amount": 1,
            "timeframe": "daily", "date_from": None, "date_to": None}
    html = lmv_report_data.build_report_html(data, columns=["Sector", "Ticker"])

    assert html.index("Sector") < html.index("Ticker")
    assert "Days True" not in html


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_picker_add_remove_and_reorder(qapp):
    from screens.report_column_picker import ColumnPickerWidget

    w = ColumnPickerWidget(["A", "B", "C"], selected=["A"])
    w._avail_list.item(0).setSelected(True)   # B
    w._add()
    assert w.columns() == ["A", "B"]

    w._sel_list.item(1).setSelected(True)
    w._move(-1)
    assert w.columns() == ["B", "A"]

    w._sel_list.clearSelection()
    w._sel_list.item(0).setSelected(True)
    w._remove()
    assert w.columns() == ["A"]
    assert [w._avail_list.item(i).text() for i in range(w._avail_list.count())] == ["B", "C"]


def test_picker_search_filters_available(qapp):
    from screens.report_column_picker import ColumnPickerWidget

    w = ColumnPickerWidget(["Open", "Close", "Volume"])
    w._search.setText("clo")
    assert [w._avail_list.item(i).text() for i in range(w._avail_list.count())] == ["Close"]
