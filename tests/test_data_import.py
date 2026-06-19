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

def test_has_import_button(screen):
    from PySide6.QtWidgets import QPushButton
    buttons = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Import" in t for t in buttons)

def test_has_combobox(screen):
    from PySide6.QtWidgets import QComboBox
    combos = screen.findChildren(QComboBox)
    assert len(combos) >= 1
