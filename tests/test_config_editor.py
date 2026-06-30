import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.config_editor import ConfigEditorScreen
    return ConfigEditorScreen(AppController(qapp))


def test_config_editor_creates(screen):
    assert screen is not None


def test_has_tab_widget(screen):
    from PySide6.QtWidgets import QTabWidget
    tabs = screen.findChildren(QTabWidget)
    assert len(tabs) == 1


def test_has_four_tabs(screen):
    from PySide6.QtWidgets import QTabWidget
    tab = screen.findChildren(QTabWidget)[0]
    assert tab.count() == 4


def test_has_add_row_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Add Row" in t for t in btns)


@pytest.fixture
def theme(qapp):
    from app import AppController
    return AppController(qapp).theme


def test_main_column_name_tab_uses_actual_renamed_pairs(theme, tmp_path, monkeypatch):
    # Regression: the "Main Column Name" tab must hold (Actual, Renamed) pairs,
    # not the single-column order data.
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from config_defaults import MAIN_COLUMN_NAME_DATA
    from screens.config_editor import ConfigTabWidget
    tab = ConfigTabWidget(["Actual", "Renamed"], MAIN_COLUMN_NAME_DATA, theme,
                          store_key="main_column_name")
    rows = tab.get_data()
    assert all(len(r) == 2 for r in rows)
    assert ("Scrip Name", "Scrip Name") in rows


def test_config_tab_save_persists(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from screens.config_editor import ConfigTabWidget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    tab = ConfigTabWidget(["Actual", "Renamed"], [("Current", "Current")], theme,
                          store_key="main_column_name")
    # Edit the renamed cell, then save.
    tab._table.item(0, tab._data_start + 1).setText("LTP")
    tab._save()
    assert config_store.get_rename_map() == {"Current": "LTP"}


def test_config_tab_loads_persisted_data(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    config_store.save_tab("main_column_name", [("Open", "Open Price")])
    from screens.config_editor import ConfigTabWidget
    tab = ConfigTabWidget(["Actual", "Renamed"], [("X", "X")], theme,
                          store_key="main_column_name")
    assert tab.get_data() == [("Open", "Open Price")]
