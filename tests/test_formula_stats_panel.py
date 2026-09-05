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
    assert panel._worker.wait(5000)
    qapp.processEvents()

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
    assert panel._worker.wait(5000)
    qapp.processEvents()

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


def test_compute_resolves_sibling_column_reference(qapp, monkeypatch):
    """A column's formula referencing another of the SAME strategy's own
    columns (e.g. "Trigger Price" = [Floor_10D] * 1.01, an already-supported
    live-rendering pattern) must resolve correctly here too — compute_stats'
    per-day row_dict is raw historic-snapshot metrics only, with no notion
    of a strategy's own computed columns, so an unexpanded sibling
    reference used to silently evaluate to None on every day."""
    from components.formula_stats_panel import FormulaStatsPanel
    from api import lmv_snapshot_api

    monkeypatch.setattr(lmv_snapshot_api, "get_range", lambda days: {
        "days": [_day("2026-01-05", [_stock("INFY", {"Low": 100.0})])]
    })
    columns = [
        {"name": "Floor_10D", "formula": [{"type": "col", "value": "Low"}]},
        {"name": "Trigger Price", "formula": [
            {"type": "col", "value": "Floor_10D"}, {"type": "op", "value": "*"},
            {"type": "num", "value": "1.01"},
        ]},
    ]
    panel = FormulaStatsPanel(None, columns=columns)
    panel.compute()
    assert panel._worker.wait(5000)
    qapp.processEvents()

    trigger_daily = panel._computed["INFY"]["columns"]["Trigger Price"]["daily"]
    assert trigger_daily == [("2026-01-05", 101.0)]
    # set_columns' working list itself must stay untouched (unexpanded) —
    # only the copy handed to compute_stats is expanded.
    assert panel._columns[1]["formula"] == columns[1]["formula"]


# ── compute() runs off the GUI thread; no blocking modal on failure ────────
# issue #22: compute() used to fetch+compute synchronously, so a slow or
# genuinely-timed-out response froze the whole app ("Not Responding") for
# the entire wait, and ANY failure showed a blocking modal (components.
# error_popup.show_api_error) instead of leaving the panel usable.

def test_compute_runs_asynchronously_not_blocking_caller(qapp, monkeypatch):
    """compute() must return immediately, with the actual fetch/compute
    still in flight on the worker thread — not run it inline before
    returning."""
    import threading
    from components.formula_stats_panel import FormulaStatsPanel
    from api import lmv_snapshot_api

    release = threading.Event()

    def _slow_get_range(days):
        release.wait(timeout=5)
        return {"days": [_day("2026-01-05", [_stock("INFY", {"High": 100.0})])]}

    monkeypatch.setattr(lmv_snapshot_api, "get_range", _slow_get_range)
    columns = [{"name": "MyCol", "formula": [{"type": "col", "value": "High"}]}]
    panel = FormulaStatsPanel(None, columns=columns)

    panel.compute()
    # compute() has returned — the fetch is still blocked on `release` — so
    # if this were synchronous, we could never reach this line at all.
    assert panel._worker.isRunning()
    assert panel._compute_btn.isEnabled() is False

    release.set()
    assert panel._worker.wait(5000)
    qapp.processEvents()
    assert panel._table.rowCount() == 1


def test_compute_failure_shows_status_text_not_a_modal(qapp, monkeypatch):
    from api.exceptions import NetworkError
    from components.formula_stats_panel import FormulaStatsPanel
    from api import lmv_snapshot_api
    from PySide6.QtWidgets import QMessageBox

    def _boom(days):
        raise NetworkError("Could not reach server: Read timed out. (read timeout=15)")

    monkeypatch.setattr(lmv_snapshot_api, "get_range", _boom)
    shown = []
    monkeypatch.setattr(QMessageBox, "exec", lambda self: shown.append(self.windowTitle()) or 0)

    columns = [{"name": "MyCol", "formula": [{"type": "col", "value": "High"}]}]
    panel = FormulaStatsPanel(None, columns=columns)
    panel.compute()
    assert panel._worker.wait(5000)
    qapp.processEvents()

    assert shown == []   # no modal shown at all
    assert "Compute failed" in panel._status_lbl.text()
    assert "Read timed out" in panel._status_lbl.text()
    assert panel._compute_btn.isEnabled() is True
    assert panel._compute_btn.text() == "Compute"


def test_lmv_snapshot_range_uses_a_longer_timeout_than_the_default(monkeypatch):
    """issue #22: the generic 15s api_client default was itself a frequent,
    spurious "Read timed out" on this specific heavy endpoint (payload
    scales with the full stock universe times the day count) even when the
    server was perfectly reachable, just still generating the response."""
    from api.client import api_client
    from api import lmv_snapshot_api

    captured = {}
    monkeypatch.setattr(
        api_client, "get",
        lambda path, params=None, auth=True, timeout=None: captured.update(path=path, timeout=timeout) or {},
    )
    lmv_snapshot_api.get_range(30)
    assert captured["timeout"] is not None
    assert captured["timeout"] > 15


def test_build_daily_popup_sorts_dates_descending(qapp):
    from components.formula_stats_panel import build_daily_popup
    daily = [("2026-01-05", 100.0), ("2026-01-07", 120.0), ("2026-01-06", 110.0)]
    dlg = build_daily_popup(None, None, "INFY", "MyCol", daily)
    table = dlg.findChild(QTableWidget)
    dates = [table.item(r, 0).text() for r in range(table.rowCount())]
    assert dates == ["2026-01-07", "2026-01-06", "2026-01-05"]
    assert dlg.windowTitle() == "INFY — MyCol"
