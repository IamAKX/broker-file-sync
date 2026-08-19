import sys
from datetime import date

import pytest
from PySide6.QtWidgets import QApplication

from api import inception_api
from api.client import api_client


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)


# ── api/inception_api.py: wrapper -> api_client call shape ──────────────────

def test_get_availability_hits_expected_path_and_params(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_availability(date(2026, 1, 1), date(2026, 1, 31))
    assert captured["path"] == "/inception/availability"
    assert captured["params"] == {"from": "2026-01-01", "to": "2026-01-31"}


def test_get_snapshot_hits_expected_path(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_snapshot(date(2026, 3, 5))
    assert captured["path"] == "/inception/snapshot"
    assert captured["params"] == {"date": "2026-03-05"}


def test_get_hmv_omits_metrics_param_when_not_given(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_hmv("year", "2025")
    assert captured["params"] == {"period_type": "year", "period": "2025"}


def test_get_hmv_includes_metrics_param_when_given(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_hmv("quarter", "2025-Q2", metrics=["CLOSE", "52WH"])
    assert captured["params"]["metrics"] == ["CLOSE", "52WH"]


def test_upsert_strategy_hits_expected_path_and_body(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "put", lambda path, json_body=None: captured.update(path=path, body=json_body) or {})
    inception_api.upsert_strategy("s1", "My Strategy", True, "Daily", [{"name": "c1"}], [])
    assert captured["path"] == "/inception/strategies/s1"
    assert captured["body"]["name"] == "My Strategy"
    assert captured["body"]["columns"] == [{"name": "c1"}]


def test_compile_check_hits_expected_path(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "post", lambda path, json_body=None: captured.update(path=path, body=json_body) or {})
    inception_api.compile_check([{"type": "num", "value": "1"}])
    assert captured["path"] == "/inception/compile-check"
    assert captured["body"] == {"formula": [{"type": "num", "value": "1"}]}


# ── FormulaBuilder: new params default to prior behavior ────────────────────

def test_formula_builder_defaults_preserve_lmv_label_and_aggregates(qapp, controller):
    from screens.strategy_builder import FormulaBuilder

    fb = FormulaBuilder([], ["Open", "Close"], theme=controller.theme, mode="value")
    assert fb._field_label == "LMV Columns"
    assert fb._show_aggregates is True


def test_formula_builder_inception_overrides(qapp, controller):
    from screens.strategy_builder import FormulaBuilder

    fb = FormulaBuilder(
        [], ["OPEN", "52WH"], theme=controller.theme, mode="value",
        field_label="Inception Fields", show_aggregates=False,
    )
    assert fb._field_label == "Inception Fields"
    assert fb._show_aggregates is False
    assert fb.get_tokens() == []


# ── topbar menu ──────────────────────────────────────────────────────────────

def test_topbar_has_inception_menu_before_help(qapp, controller):
    from components.topbar import TopBar

    bar = TopBar(controller.theme)
    buttons = [w for w in bar.children() if w.__class__.__name__ == "QPushButton"]
    labels = [b.text() for b in buttons if b.menu() is not None]
    assert "Inception" in labels
    assert labels.index("Inception") < labels.index("Help")

    inception_btn = next(b for b in buttons if b.text() == "Inception")
    actions = [a.text() for a in inception_btn.menu().actions()]
    assert actions == ["View by Date", "Strategy Builder", "HMV"]


# ── screens construct and behave ─────────────────────────────────────────────

def test_view_by_date_screen_constructs(qapp, controller):
    from screens.inception_view_by_date import InceptionViewByDateScreen

    screen = InceptionViewByDateScreen(controller)
    assert screen is not None
    screen.refresh_theme()


def test_hmv_screen_period_string_for_each_type(qapp, controller):
    from screens.inception_hmv import InceptionHmvScreen

    screen = InceptionHmvScreen(controller)
    screen._year_spin.setValue(2025)

    screen._period_type_combo.setCurrentIndex(0)  # Calendar Year
    assert screen._current_period() == ("year", "2025")

    screen._period_type_combo.setCurrentIndex(1)  # Quarter
    screen._sub_period_combo.setCurrentIndex(1)   # Q2
    assert screen._current_period() == ("quarter", "2025-Q2")

    screen._period_type_combo.setCurrentIndex(2)  # Half Year
    screen._sub_period_combo.setCurrentIndex(1)   # H2
    assert screen._current_period() == ("half_year", "2025-H2")

    screen._period_type_combo.setCurrentIndex(3)  # Financial Year
    assert screen._current_period() == ("financial_year", "2025")


def test_strategy_builder_screen_constructs_with_empty_data(qapp, controller, monkeypatch):
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen

    monkeypatch.setattr(inception_api, "list_columns", lambda: {"columns": []})
    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()
    assert screen._strategies == []
    assert screen._list.count() == 0


def test_strategy_builder_new_strategy_then_add_column(qapp, controller, monkeypatch):
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen

    monkeypatch.setattr(inception_api, "list_columns", lambda: {"columns": [{"code": "OPEN"}]})
    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()
    screen._on_new()
    assert screen._current["name"] == "New Strategy"
    assert screen._columns_list.count() == 0

    from PySide6.QtWidgets import QListWidgetItem
    from PySide6.QtCore import Qt
    item = QListWidgetItem("Adjusted = [OPEN] + 1")
    item.setData(Qt.ItemDataRole.UserRole, {"name": "Adjusted", "formula": []})
    screen._columns_list.addItem(item)
    assert "Adjusted" in screen._current_field_universe()
