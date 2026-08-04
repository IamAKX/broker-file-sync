"""Tests for LiveViewerWindow's strategy-column click-through to a last-N-days
history popup (_on_cell_clicked / _open_formula_history) — only strategy
columns whose formula references a _DAYS historic aggregate function
(AVG_DAYS, MIN_DAYS, ...) are clickable this way; any other strategy column,
or a native sheet column, is a no-op click."""
import sys

import pytest
from PySide6.QtWidgets import QApplication, QDialog, QTableWidgetItem, QWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp):
    from screens.live_viewer import LiveViewerWindow
    return LiveViewerWindow("", "", "", [])


def _days_formula(col="High", days=20):
    return [{"type": "func", "value": "AVG_DAYS(", "col_arg": col, "days_arg": days}]


def test_on_cell_clicked_ignores_native_columns(lmv, monkeypatch):
    lmv._headers = ["Scrip Name", "LTP"]
    lmv._base_col_count = 2
    lmv._strat_col_defs = [{"name": "AvgHigh20", "formula": _days_formula()}]
    called = []
    monkeypatch.setattr(lmv, "_open_formula_history", lambda *a: called.append(a))

    lmv._on_cell_clicked(0, 1)   # LTP — a native column, not a strategy one

    assert called == []


def test_on_cell_clicked_ignores_non_day_strategy_columns(lmv, monkeypatch):
    """A strategy column with an ordinary formula (no _DAYS function) has
    nothing to drill into — clicking it is a no-op."""
    lmv._headers = ["Scrip Name", "LTP"]
    lmv._base_col_count = 2
    lmv._strat_col_defs = [{"name": "Plain", "formula": [{"type": "col", "value": "LTP"}]}]
    lmv._table.setColumnCount(3)
    lmv._table.setRowCount(1)
    lmv._table.setItem(0, 0, QTableWidgetItem("INFY"))
    called = []
    monkeypatch.setattr(lmv, "_open_formula_history", lambda *a: called.append(a))

    lmv._on_cell_clicked(0, 2)

    assert called == []


def test_on_cell_clicked_opens_history_for_days_column(lmv, monkeypatch):
    lmv._headers = ["Scrip Name", "LTP"]
    lmv._base_col_count = 2
    col_def = {"name": "AvgHigh20", "formula": _days_formula("High", 20)}
    lmv._strat_col_defs = [col_def]
    lmv._table.setColumnCount(3)
    lmv._table.setRowCount(1)
    lmv._table.setItem(0, 0, QTableWidgetItem("INFY"))

    called = []
    monkeypatch.setattr(lmv, "_open_formula_history",
                        lambda sym, src, days, name: called.append((sym, src, days, name)))

    lmv._on_cell_clicked(0, 2)   # column 2 = base_col_count(2) + strat idx 0

    assert called == [("INFY", "High", 20, "AvgHigh20")]


def test_on_cell_clicked_noop_without_scrip_name_column(lmv, monkeypatch):
    lmv._headers = ["LTP"]   # no "Scrip Name" — nothing to key the popup by
    lmv._base_col_count = 1
    lmv._strat_col_defs = [{"name": "AvgHigh20", "formula": _days_formula()}]
    called = []
    monkeypatch.setattr(lmv, "_open_formula_history", lambda *a: called.append(a))

    lmv._on_cell_clicked(0, 1)

    assert called == []


def test_resolve_day_source_formula_prefers_own_strategy_column(lmv):
    """AVG_DAYS([MyComputedCol], 20) should drill into MyComputedCol's own
    (arbitrary) formula, not a literal raw column named "MyComputedCol"."""
    formula = [{"type": "col", "value": "High"}, {"type": "op", "value": "-"},
              {"type": "col", "value": "Low"}]
    lmv._strategies = [{
        "id": "s1", "active": True, "category": "Daily",
        "columns": [{"name": "MyComputedCol", "formula": formula, "fmt_rules": []}],
    }]

    resolved = lmv._resolve_day_source_formula("MyComputedCol")

    assert resolved == formula


def test_resolve_day_source_formula_falls_back_to_raw_column(lmv):
    lmv._strategies = []
    resolved = lmv._resolve_day_source_formula("High")
    assert resolved == [{"type": "col", "value": "High"}]


def test_open_formula_history_computes_single_symbol_panel_scoped_to_days(lmv, monkeypatch):
    captured = {}

    class _FakePanel(QWidget):
        def __init__(self, theme, columns, symbol_filter=None, initial_days=20, parent=None):
            super().__init__(parent)
            captured["columns"] = columns
            captured["symbol_filter"] = symbol_filter
            captured["initial_days"] = initial_days

        def compute(self):
            captured["computed"] = True

    monkeypatch.setattr("components.formula_stats_panel.FormulaStatsPanel", _FakePanel)
    monkeypatch.setattr(QDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    lmv._strategies = []   # "High" resolves to a raw column reference

    lmv._open_formula_history("INFY", "High", 20, "AvgHigh20")

    assert captured["columns"] == [{"name": "High", "formula": [{"type": "col", "value": "High"}]}]
    assert captured["symbol_filter"] == "INFY"
    assert captured["initial_days"] == 20
    assert captured["computed"] is True
