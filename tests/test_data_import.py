import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.data_import import DataImportScreen
    return DataImportScreen(AppController(qapp))


def test_data_import_creates(screen):
    assert screen is not None


def test_has_watcher_button(screen):
    from PySide6.QtWidgets import QPushButton
    buttons = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Watcher" in t for t in buttons)


def test_has_five_broker_cards(screen):
    assert len(screen._cards) == 5
    # Each card exposes a Browse button and a remove button.
    from PySide6.QtWidgets import QPushButton
    for card in screen._cards.values():
        labels = [b.text() for b in card.findChildren(QPushButton)]
        assert "Browse" in labels


def test_watcher_button_initially_disabled(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b for b in screen.findChildren(QPushButton) if "Watcher" in b.text()]
    assert btns and not btns[0].isEnabled()
