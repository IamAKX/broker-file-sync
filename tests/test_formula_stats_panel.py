"""Tests for components/formula_stats_panel.py — the FormulaStatsPanel widget
shared by screens/formula_stats.py (Data menu) and Live Master View's
per-cell history popup for a strategy column using an AVG_DAYS/MIN_DAYS/etc.
historic aggregate function (services/strategy_engine.py)."""
import sys

import pytest
from PySide6.QtWidgets import QApplication, QTableWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _day(trade_date, stocks):
    return {"trade_date": trade_date, "stocks": stocks}


def _stock(symbol, metrics):
    return {"symbol": symbol, "display_name": symbol, "metrics": metrics}


def test_panel_constructs_empty(qapp):
    from components.formula_stats_panel import FormulaStatsPanel
    panel = FormulaStatsPanel(None, columns=[])
    assert panel._table.rowCount() == 0


def test_compute_populates_table(qapp, monkeypatch):
    from components.formula_stats_panel import FormulaStatsPanel
    from api import lmv_snapshot_api

    monkeypatch.setattr(lmv_snapshot_api, "get_range", lambda days: {
        "days": [
            _day("2026-01-05", [_stock("INFY", {"High": 100.0})]),
            _day("2026-01-06", [_stock("INFY", {"High": 110.0})]),
        ]
    })
    columns = [{"name": "MyCol", "formula": [{"type": "col", "value": "High"}]}]
    panel = FormulaStatsPanel(None, columns=columns)
    panel.compute()

    assert panel._table.rowCount() == 1
    headers = [panel._table.horizontalHeaderItem(c).text() for c in range(panel._table.columnCount())]
    assert headers == ["Symbol", "Display Name", "MyCol (Min)", "MyCol (Max)", "MyCol (Average)", "MyCol (Count)"]
    assert panel._table.item(0, 0).text() == "INFY"


def test_symbol_filter_restricts_results_to_one_stock(qapp, monkeypatch):
    from components.formula_stats_panel import FormulaStatsPanel
    from api import lmv_snapshot_api

    monkeypatch.setattr(lmv_snapshot_api, "get_range", lambda days: {
        "days": [_day("2026-01-05", [_stock("INFY", {"High": 100.0}), _stock("TCS", {"High": 200.0})])]
    })
    columns = [{"name": "MyCol", "formula": [{"type": "col", "value": "High"}]}]
    panel = FormulaStatsPanel(None, columns=columns, symbol_filter="TCS")
    panel.compute()

    assert panel._table.rowCount() == 1
    assert panel._table.item(0, 0).text() == "TCS"


def test_set_columns_replaces_working_set(qapp):
    from components.formula_stats_panel import FormulaStatsPanel
    panel = FormulaStatsPanel(None, columns=[])
    assert panel._columns == []
    new_cols = [{"name": "X", "formula": []}]
    panel.set_columns(new_cols)
    assert panel._columns == new_cols


def test_compute_with_no_columns_shows_message_without_calling_api(qapp, monkeypatch):
    from components.formula_stats_panel import FormulaStatsPanel
    from api import lmv_snapshot_api

    called = []
    monkeypatch.setattr(lmv_snapshot_api, "get_range", lambda days: called.append(days))
    panel = FormulaStatsPanel(None, columns=[])
    panel.compute()

    assert called == []
    assert "No formula columns" in panel._status_lbl.text()


def test_build_daily_popup_sorts_dates_descending(qapp):
    from components.formula_stats_panel import build_daily_popup
    daily = [("2026-01-05", 100.0), ("2026-01-07", 120.0), ("2026-01-06", 110.0)]
    dlg = build_daily_popup(None, None, "INFY", "MyCol", daily)
    table = dlg.findChild(QTableWidget)
    dates = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert dates == ["2026-01-07", "2026-01-06", "2026-01-05"]
    assert dlg.windowTitle() == "INFY — MyCol"
