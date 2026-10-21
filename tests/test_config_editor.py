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


def test_config_editor_has_inception_column_order_tab(screen):
    """Tab renamed from "Inception HMV Column Order" now that screens.
    inception_view_by_date reads the same saved list too (services.
    config_store.INCEPTION_HMV_COLUMN_ORDER — key name kept as-is so an
    already-saved order isn't orphaned; see that constant's own docstring)."""
    from PySide6.QtWidgets import QTabWidget
    tab = screen.findChildren(QTabWidget)[0]
    labels = [tab.tabText(i) for i in range(tab.count())]
    assert "Inception Column Order" in labels


# ── Unordered known columns are auto-listed (issue #67) ──────────────────

def test_reorderable_tab_appends_known_columns_missing_from_saved_order(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    config_store.save_column_order(["Close", "Open"], key="main_column_order")

    from screens.config_editor import ConfigTabWidget
    tab = ConfigTabWidget(["Column Name"], [("Default",)], theme, reorderable=True,
                          store_key="main_column_order",
                          extra_names=lambda: ["Open", "RSC", "My Strategy Col", "RSC", ""])
    # saved order untouched and first; only genuinely new names appended, once each, blanks skipped
    assert tab.get_data() == [("Close",), ("Open",), ("RSC",), ("My Strategy Col",)]


def test_reorderable_tab_extra_names_also_extend_the_default_list(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from screens.config_editor import ConfigTabWidget
    tab = ConfigTabWidget(["Column Name"], [("A",)], theme, reorderable=True,
                          store_key="main_column_order", extra_names=["B"])
    assert tab.get_data() == [("A",), ("B",)]


def test_extra_names_failure_never_breaks_the_tab(theme, tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    from screens.config_editor import ConfigTabWidget

    def boom():
        raise RuntimeError("backend down")
    tab = ConfigTabWidget(["Column Name"], [("A",)], theme, reorderable=True,
                          store_key="main_column_order", extra_names=boom)
    assert tab.get_data() == [("A",)]


def test_column_name_sources_cover_formula_strategy_and_inception_columns(monkeypatch):
    from screens import config_editor
    from services import formula_tokens, strategy_store, inception_columns
    monkeypatch.setattr(formula_tokens, "all_field_codes", lambda: ["RSC", "PDTO"])
    monkeypatch.setattr(strategy_store, "load_all", lambda: [{"columns": [{"name": "Floor_10D"}, {"name": "Trigger"}]}])
    lmv = config_editor._all_lmv_column_names()
    assert {"RSC", "PDTO", "Floor_10D", "Trigger"} <= set(lmv)
    inception = config_editor._all_inception_column_names()
    assert inception[:2] == ["Sector", "Symbol"] and "52WH" in inception and len(inception) > 100


def test_main_column_order_lists_row_filter_streak_columns_of_every_strategy(monkeypatch):
    """#85: "<strategy> — Days True" / "— Since" show in LMV but were missing here."""
    from screens import config_editor
    from services import formula_tokens, strategy_store
    from services.strategy_engine import apply_strategies
    monkeypatch.setattr(formula_tokens, "all_field_codes", lambda: [])
    filtered = {"id": "a", "name": "TOPBOTTOM CALLOI STRONG BUY NEAR PHIGH", "active": True,
                "columns": [{"name": "Col", "formula": [{"type": "col", "value": "X"}], "fmt_rules": []}],
                "row_filter": [{"type": "col", "value": "X"}, {"type": "op", "value": ">"}, {"type": "num", "value": "1"}]}
    unfiltered = {"id": "b", "name": "Plain", "active": True, "columns": [{"name": "Other"}], "row_filter": []}
    monkeypatch.setattr(strategy_store, "load_all", lambda: [filtered, unfiltered])

    names = config_editor._all_lmv_column_names()

    assert "TOPBOTTOM CALLOI STRONG BUY NEAR PHIGH — Days True" in names
    assert "TOPBOTTOM CALLOI STRONG BUY NEAR PHIGH — Since" in names
    assert not any(n.startswith("Plain —") for n in names)       # no filter -> no streak columns
    # ...and these are exactly the names the LMV grid uses
    headers, _ = apply_strategies([filtered], ["X"], [[5]], day_history={})
    assert headers[-2:] == ["TOPBOTTOM CALLOI STRONG BUY NEAR PHIGH — Days True",
                            "TOPBOTTOM CALLOI STRONG BUY NEAR PHIGH — Since"]
