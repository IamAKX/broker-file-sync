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


def test_has_five_tabs(screen):
    from PySide6.QtWidgets import QTabWidget
    tab = screen.findChildren(QTabWidget)[0]
    assert tab.count() == 5


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


# ── reorderable tabs: save_column_order/load_column_order, not save_tab ────
#
# Regression: a reorderable ConfigTabWidget (Main Column Order / Inception
# HMV Column Order) used to persist through save_tab/load_tab — the SAME
# generic list-of-row-tuples path every other (non-reorderable) tab uses —
# which wrote [["OPEN"], ["HIGH"], ...] under the shared "main_column_order"
# key instead of the flat ["OPEN", "HIGH", ...] screens.live_viewer.
# _restore_column_order (the only real consumer) actually reads. Every
# render that tried to apply a saved order crashed outright (dict.get on an
# unhashable list key) — using the tab silently broke LMV's live column
# order the next time it rendered. See services.config_store.
# save_column_order's docstring.

def test_reorderable_tab_saves_via_save_column_order_not_save_tab(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from screens.config_editor import ConfigTabWidget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    tab = ConfigTabWidget(["Column Name"], [("OPEN",), ("HIGH",)], theme,
                          reorderable=True, store_key="main_column_order")
    tab._save()

    # The bug: this used to come back [["OPEN"], ["HIGH"]] — a shape that
    # crashes screens.live_viewer._restore_column_order outright.
    loaded = config_store.load_column_order()
    assert loaded == ["OPEN", "HIGH"]
    assert all(isinstance(name, str) for name in loaded)


def test_reorderable_tab_loads_via_load_column_order(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    config_store.save_column_order(["Close", "Open"], key="main_column_order")

    from screens.config_editor import ConfigTabWidget
    tab = ConfigTabWidget(["Column Name"], [("Default",)], theme,
                          reorderable=True, store_key="main_column_order")
    assert tab.get_data() == [("Close",), ("Open",)]


def test_reorderable_tab_up_down_reorder_then_save_persists_new_order(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from screens.config_editor import ConfigTabWidget
    from PySide6.QtWidgets import QMessageBox, QPushButton
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    tab = ConfigTabWidget(["Column Name"], [("A",), ("B",), ("C",)], theme,
                          reorderable=True, store_key="main_column_order")
    # Move row 0 ("A") down once, via the same up/down buttons
    # _make_order_widget wires (up_btn added first, then dn_btn).
    order_widget = tab._table.cellWidget(0, tab._order_col)
    down_btn = order_widget.findChildren(QPushButton)[1]
    tab._move_row(down_btn, +1)
    tab._save()

    assert config_store.load_column_order(key="main_column_order") == ["B", "A", "C"]


def test_inception_hmv_column_order_tab_uses_its_own_key(theme, tmp_path, monkeypatch):
    """Regression: must be a SEPARATE key from LMV's own "main_column_order"
    — Inception's column universe (services.inception_columns) has nothing
    to do with LMV's, and sharing a key would mean saving one tab's order
    silently overwrites the other's."""
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from screens.config_editor import ConfigTabWidget
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", staticmethod(lambda *a, **k: None))

    lmv_tab = ConfigTabWidget(["Column Name"], [("Scrip Name",)], theme,
                              reorderable=True, store_key=config_store.MAIN_COLUMN_ORDER)
    lmv_tab._save()
    inception_tab = ConfigTabWidget(["Column Name"], [("Symbol",), ("Sector",)], theme,
                                    reorderable=True, store_key=config_store.INCEPTION_HMV_COLUMN_ORDER)
    inception_tab._save()

    assert config_store.load_column_order(key=config_store.MAIN_COLUMN_ORDER) == ["Scrip Name"]
    assert config_store.load_column_order(key=config_store.INCEPTION_HMV_COLUMN_ORDER) == ["Symbol", "Sector"]


def test_config_editor_has_inception_hmv_column_order_tab(screen):
    from PySide6.QtWidgets import QTabWidget
    tab = screen.findChildren(QTabWidget)[0]
    labels = [tab.tabText(i) for i in range(tab.count())]
    assert "Inception HMV Column Order" in labels
