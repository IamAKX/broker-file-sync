"""Tests for services/formula_stats_engine.py — pure logic, no Qt/network,
so exercised directly against fixture range-response data shaped like
api/lmv_snapshot_api.get_range()'s return value."""
from services.formula_stats_engine import (
    AGGREGATES, DEFAULT_AGGREGATES, compute_day_history, compute_stats,
)


def tok_col(name):
    return {"type": "col", "value": name}


def _columns(formula):
    return [{"name": "MyCol", "formula": formula, "fmt_rules": []}]


def _day(trade_date, stocks):
    return {"trade_date": trade_date, "stocks": stocks}


def _stock(symbol, metrics, display_name=None):
    return {"symbol": symbol, "display_name": display_name or symbol, "metrics": metrics}


def test_compute_stats_evaluates_formula_per_day_and_aggregates():
    columns = _columns([tok_col("High")])
    range_response = {
        "days": [
            _day("2026-01-05", [_stock("INFY", {"High": 100.0})]),
            _day("2026-01-06", [_stock("INFY", {"High": 110.0})]),
        ]
    }

    result = compute_stats(columns, range_response)

    col = result["INFY"]["columns"]["MyCol"]
    assert col["daily"] == [("2026-01-05", 100.0), ("2026-01-06", 110.0)]
    assert col["Min"] == 100.0
    assert col["Max"] == 110.0
    assert col["Average"] == 105.0
    assert col["Sum"] == 210.0
    assert col["Count"] == 2


def test_compute_stats_missing_column_is_none_and_excluded_from_aggregates():
    """A day whose row lacks a column the formula references (e.g. Sector/
    OR.High not persisted historically) must not crash the whole computation
    — it records as None in "daily" and Count reflects only the usable days."""
    columns = _columns([tok_col("OR.High")])
    range_response = {
        "days": [
            _day("2026-01-05", [_stock("INFY", {})]),                  # missing OR.High
            _day("2026-01-06", [_stock("INFY", {"OR.High": 50.0})]),
        ]
    }

    result = compute_stats(columns, range_response)

    col = result["INFY"]["columns"]["MyCol"]
    assert col["daily"] == [("2026-01-05", None), ("2026-01-06", 50.0)]
    assert col["Min"] == 50.0
    assert col["Max"] == 50.0
    assert col["Count"] == 1


def test_compute_stats_handles_stock_absent_on_some_days():
    """A stock that only appears in the universe on some of the N days
    (e.g. newly listed) shouldn't affect any other stock's aggregates."""
    columns = _columns([tok_col("High")])
    range_response = {
        "days": [
            _day("2026-01-05", [_stock("INFY", {"High": 100.0})]),
            _day("2026-01-06", [_stock("INFY", {"High": 110.0}), _stock("TCS", {"High": 200.0})]),
        ]
    }

    result = compute_stats(columns, range_response)

    assert len(result["INFY"]["columns"]["MyCol"]["daily"]) == 2
    assert result["TCS"]["columns"]["MyCol"]["daily"] == [("2026-01-06", 200.0)]
    assert result["TCS"]["columns"]["MyCol"]["Count"] == 1


def test_compute_stats_returns_empty_when_no_days():
    columns = _columns([tok_col("High")])
    result = compute_stats(columns, {"days": []})
    assert result == {}


def test_std_dev_and_variance_none_for_single_data_point():
    columns = _columns([tok_col("High")])
    range_response = {"days": [_day("2026-01-05", [_stock("INFY", {"High": 100.0})])]}

    result = compute_stats(columns, range_response)
    col = result["INFY"]["columns"]["MyCol"]
    assert col["Std Dev"] is None
    assert col["Variance"] is None
    assert col["Range"] == 0.0


def test_aggregates_registry_has_expected_keys_in_order():
    assert list(AGGREGATES.keys()) == [
        "Min", "Max", "Average", "Sum", "Count", "Std Dev", "Median", "Variance", "Range",
    ]


def test_default_aggregates_are_min_max_average_count():
    assert DEFAULT_AGGREGATES == ["Min", "Max", "Average", "Count"]


# ── compute_day_history ──────────────────────────────────────────────────────
# Powers services.strategy_engine's _DAYS aggregate functions (AVG_DAYS,
# MIN_DAYS, ...) — resolves [(col_name, days, formula_tokens), ...] requests
# (services.strategy_engine.collect_day_requests's shape) into
# {(col_name, days): {symbol: {agg_name: value}}}.

def test_compute_day_history_returns_per_symbol_aggregates():
    range_response = {
        "days": [
            _day("2026-01-05", [_stock("INFY", {"High": 100.0})]),
            _day("2026-01-06", [_stock("INFY", {"High": 110.0})]),
        ]
    }
    requests = [("High", 20, [tok_col("High")])]
    result = compute_day_history(requests, lambda days: range_response)

    assert result[("High", 20)]["INFY"]["Average"] == 105.0
    assert result[("High", 20)]["INFY"]["Min"] == 100.0
    assert result[("High", 20)]["INFY"]["Max"] == 110.0


def test_compute_day_history_fetches_once_per_distinct_days_value():
    """Two requests sharing the same N should share one range_fetcher call
    (and one compute_stats pass) — not one fetch per request."""
    calls = []

    def fetcher(days):
        calls.append(days)
        return {"days": [_day("2026-01-05", [_stock("INFY", {"High": 100.0, "Low": 90.0})])]}

    requests = [
        ("High", 20, [tok_col("High")]),
        ("Low", 20, [tok_col("Low")]),
        ("High", 5, [tok_col("High")]),
    ]
    result = compute_day_history(requests, fetcher)

    assert sorted(calls) == [5, 20]
    assert result[("High", 20)]["INFY"]["Average"] == 100.0
    assert result[("Low", 20)]["INFY"]["Average"] == 90.0
    assert result[("High", 5)]["INFY"]["Average"] == 100.0


def test_compute_day_history_resolves_custom_formula_source():
    """A request's formula_tokens can be any custom formula (e.g. another
    strategy column's own formula), not just a bare column reference —
    compute_day_history evaluates whatever it's given per day."""
    range_response = {
        "days": [_day("2026-01-05", [_stock("INFY", {"High": 100.0, "Low": 90.0})])]
    }
    formula = [tok_col("High"), {"type": "op", "value": "-"}, tok_col("Low")]
    requests = [("Range", 20, formula)]
    result = compute_day_history(requests, lambda days: range_response)
    assert result[("Range", 20)]["INFY"]["Average"] == 10.0


def test_compute_day_history_empty_requests_returns_empty_dict():
    assert compute_day_history([], lambda days: {"days": []}) == {}


# ── FormulaStatsScreen ───────────────────────────────────────────────────────
# strategy_store.load_all() is already safe to call in tests (see
# tests/conftest.py's autouse fixture — a reachable-server-with-nothing-saved
# stub, local cache starts empty). lmv_snapshot_api.get_range isn't covered
# by that fixture (it's not a store sync function), so each test that
# triggers Compute monkeypatches it directly.

import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)


def test_formula_stats_screen_constructs(controller):
    from screens.formula_stats import FormulaStatsScreen
    screen = FormulaStatsScreen(controller)
    assert screen is not None
    assert screen._strategy_combo.count() == 0   # no strategies saved yet
    assert not screen._panel._compute_btn.isEnabled()


def test_reload_strategies_populates_combo_and_preserves_selection(controller, monkeypatch):
    from screens.formula_stats import FormulaStatsScreen
    from services import strategy_store

    strategies = [
        {"id": "1", "name": "Alpha", "active": True, "category": "Daily", "columns": [], "row_filter": []},
        {"id": "2", "name": "Beta", "active": True, "category": "Daily", "columns": [], "row_filter": []},
    ]
    monkeypatch.setattr(strategy_store, "load_all", lambda: strategies)

    screen = FormulaStatsScreen(controller)
    assert screen._strategy_combo.count() == 2
    assert screen._panel._compute_btn.isEnabled()

    screen._strategy_combo.setCurrentIndex(1)   # select "Beta"
    # Reorder on the "server" — Beta now comes first — selection should
    # follow the strategy's id, not its position.
    monkeypatch.setattr(strategy_store, "load_all", lambda: list(reversed(strategies)))
    screen.reload_strategies()

    assert screen._strategy_combo.currentText() == "Beta"


def test_compute_populates_results_table(controller, monkeypatch):
    from screens.formula_stats import FormulaStatsScreen
    from services import strategy_store
    from api import lmv_snapshot_api

    strategy = {
        "id": "1", "name": "Test", "active": True, "category": "Daily",
        "columns": [{"name": "MyCol", "formula": [{"type": "col", "value": "High"}], "fmt_rules": []}],
        "row_filter": [],
    }
    monkeypatch.setattr(strategy_store, "load_all", lambda: [strategy])
    monkeypatch.setattr(lmv_snapshot_api, "get_range", lambda days: {
        "days": [
            {"trade_date": "2026-01-05", "stocks": [{"symbol": "INFY", "display_name": "INFY", "metrics": {"High": 100.0}}]},
            {"trade_date": "2026-01-06", "stocks": [{"symbol": "INFY", "display_name": "INFY", "metrics": {"High": 110.0}}]},
        ]
    })

    screen = FormulaStatsScreen(controller)
    screen._on_compute()

    assert screen._panel._table.rowCount() == 1
    headers = [screen._panel._table.horizontalHeaderItem(c).text() for c in range(screen._panel._table.columnCount())]
    assert headers == ["Symbol", "Display Name", "MyCol (Min)", "MyCol (Max)", "MyCol (Average)", "MyCol (Count)"]
    row_values = [screen._panel._table.item(0, c).text() for c in range(screen._panel._table.columnCount())]
    assert row_values == ["INFY", "INFY", "100", "110", "105", "2"]

    # The data backing the right-click popup is there for this exact cell.
    col_name, agg = screen._panel._table_columns[0]
    assert (col_name, agg) == ("MyCol", "Min")
    daily = screen._panel._computed["INFY"]["columns"]["MyCol"]["daily"]
    assert daily == [("2026-01-05", 100.0), ("2026-01-06", 110.0)]


def test_compute_with_no_columns_shows_message_instead_of_calling_api(controller, monkeypatch):
    from screens.formula_stats import FormulaStatsScreen
    from services import strategy_store
    from api import lmv_snapshot_api

    strategy = {"id": "1", "name": "Empty", "active": True, "category": "Daily", "columns": [], "row_filter": []}
    monkeypatch.setattr(strategy_store, "load_all", lambda: [strategy])
    called = []
    monkeypatch.setattr(lmv_snapshot_api, "get_range", lambda days: called.append(days))

    screen = FormulaStatsScreen(controller)
    screen._on_compute()

    assert called == []
    assert "no formula columns" in screen._panel._status_lbl.text()
