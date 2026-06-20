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
