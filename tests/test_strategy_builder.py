import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.strategy_builder import StrategyBuilderScreen
    return StrategyBuilderScreen(AppController(qapp))


def test_strategy_builder_creates(screen):
    assert screen is not None


def test_has_new_strategy_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("New Strategy" in t for t in btns)


def test_set_lmv_headers(screen):
    headers = ["Scrip Name", "LTP", "CLOSE", "OPEN"]
    screen.set_lmv_headers(headers)
    assert screen._lmv_headers == headers


def test_get_active_strategies_returns_list(screen):
    result = screen.get_active_strategies()
    assert isinstance(result, list)


def test_new_strategy_has_category():
    from services.strategy_store import new_strategy
    s = new_strategy("Test")
    assert s["category"] == "Daily"


def test_load_all_backfills_category(tmp_path, monkeypatch):
    import json
    from services import strategy_store as store
    legacy = [{"id": "abc", "name": "Old", "active": True, "columns": []}]
    store_file = tmp_path / "strategies.json"
    store_file.write_text(json.dumps(legacy))
    monkeypatch.setattr(store, "_STORE_FILE", str(store_file))
    result = store.load_all()
    assert result[0]["category"] == "Daily"
