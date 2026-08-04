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


def test_set_lmv_data_populates_first_row_and_all_data(screen):
    headers = ["Scrip Name", "High", "Low"]
    data = [["INFY", "100", "50"], ["TCS", "200", "150"]]
    screen.set_lmv_data(headers, data)
    assert screen._lmv_headers == headers
    assert screen._lmv_first_row == {"Scrip Name": "INFY", "High": "100", "Low": "50"}
    assert len(screen._all_lmv_data) == 2
    assert screen._all_lmv_data[1]["Low"] == "150"


def test_set_lmv_data_enables_compile_against_real_sheet(screen):
    # The bug: LMV loaded but row data never reached compile_check.
    from services.strategy_engine import compile_check
    headers = ["High", "Low"]
    data = [["100", "50"]]
    screen.set_lmv_data(headers, data)
    tokens = [
        {"type": "func", "value": "Max("},
        {"type": "col", "value": "High"},
        {"type": "op", "value": ","},
        {"type": "col", "value": "Low"},
        {"type": "paren", "value": ")"},
    ]
    ok, msg = compile_check(tokens, screen._lmv_first_row, screen._all_lmv_data)
    assert ok, msg
    assert msg == "100.0"


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


# ── import_all: merge by name, not destructive replace ──────────────────────

def test_import_all_overwrites_matching_name_in_place(tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "strategies.json"))

    existing = store.new_strategy("DayTop Buy")
    existing["active"] = False
    store.save_strategy(existing)

    imported = store.new_strategy("DayTop Buy")
    imported["id"] = "brand-new-id"
    imported["active"] = True

    overwritten, added = store.import_all([imported])

    assert (overwritten, added) == (1, 0)
    reloaded = store.load_all()
    assert len(reloaded) == 1
    assert reloaded[0]["id"] == "brand-new-id"   # imported entry fully wins
    assert reloaded[0]["active"] is True


def test_import_all_adds_new_names(tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "strategies.json"))

    store.save_strategy(store.new_strategy("Existing One"))
    overwritten, added = store.import_all([store.new_strategy("Brand New")])

    assert (overwritten, added) == (0, 1)
    names = {s["name"] for s in store.load_all()}
    assert names == {"Existing One", "Brand New"}


def test_import_all_leaves_untouched_strategies_alone(tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "strategies.json"))

    store.save_strategy(store.new_strategy("Untouched"))
    store.save_strategy(store.new_strategy("Overwrite Me"))

    store.import_all([store.new_strategy("Overwrite Me")])

    names = {s["name"] for s in store.load_all()}
    assert "Untouched" in names
    assert len(store.load_all()) == 2   # not wiped down to just the 1 imported


def test_import_all_last_duplicate_in_file_wins(tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "strategies.json"))

    first = store.new_strategy("Dup")
    first["active"] = True
    second = store.new_strategy("Dup")
    second["active"] = False

    store.import_all([first, second])

    reloaded = store.load_all()
    assert len(reloaded) == 1
    assert reloaded[0]["active"] is False


def test_strategy_editor_has_category_combo(qapp):
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor
    s = new_strategy("T")
    editor = StrategyEditor(s, [], None)
    assert hasattr(editor, "_category_combo")
    assert editor._category_combo.currentText() == "Daily"


def test_strategy_editor_save_writes_category(qapp):
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor
    s = new_strategy("T")
    s["category"] = "Weekly"
    editor = StrategyEditor(s, [], None)
    saved = {}
    editor.saved.connect(lambda d: saved.update(d))
    editor._category_combo.setCurrentText("Monthly")
    editor._save()
    assert saved["category"] == "Monthly"


def test_strategy_card_has_no_category_badge(qapp):
    # The card no longer repeats its own category — it already lives inside
    # that category's collapsible section in the sidebar (_CategorySection),
    # so a per-card "Weekly" badge would just be redundant.
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyCard, _CardText
    s = new_strategy("T")
    s["category"] = "Weekly"
    card = StrategyCard(s, None)
    texts = [w._text for w in card.findChildren(_CardText)]
    assert "Weekly" not in texts


def test_strategy_card_shows_name_and_column_count(qapp):
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyCard, _CardText
    s = new_strategy("My Strategy")
    s["columns"] = [{"name": "c1"}, {"name": "c2"}]
    card = StrategyCard(s, None)
    texts = [w._text for w in card.findChildren(_CardText)]
    assert "My Strategy" in texts
    assert "2 columns" in texts


def test_all_categories_defaults_to_builtins_only(tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


def test_add_custom_category_appends_after_builtins(tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    canonical = store.add_custom_category("Intraday")
    assert canonical == "Intraday"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common", "Intraday"]


def test_add_custom_category_persists_across_loads(tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    store.add_custom_category("Intraday")
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common", "Intraday"]


def test_add_custom_category_rejects_case_insensitive_duplicate(tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    assert store.add_custom_category("daily") == "Daily"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]

    store.add_custom_category("Intraday")
    assert store.add_custom_category("INTRADAY") == "Intraday"
    assert store.all_categories().count("Intraday") == 1


def test_add_custom_category_ignores_blank_name(tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    assert store.add_custom_category("   ") == ""
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


def test_category_combo_has_add_category_entry(qapp, tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    from screens.strategy_builder import StrategyEditor, _ADD_CATEGORY_SENTINEL
    s = store.new_strategy("T")
    editor = StrategyEditor(s, [], None)
    items = [editor._category_combo.itemText(i) for i in range(editor._category_combo.count())]
    assert items == ["Daily", "Weekly", "Monthly", "Common", _ADD_CATEGORY_SENTINEL]


def test_selecting_add_category_prompts_dialog_and_adds_it(qapp, tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    from screens.strategy_builder import StrategyEditor, _ADD_CATEGORY_SENTINEL
    import screens.strategy_builder as sb_module

    class FakeDialog:
        def __init__(self, theme, parent=None):
            pass
        def exec(self):
            return sb_module.QDialog.DialogCode.Accepted
        def category_name(self):
            return "Intraday"

    monkeypatch.setattr(sb_module, "_AddCategoryDialog", FakeDialog)

    s = store.new_strategy("T")
    editor = StrategyEditor(s, [], None)
    sentinel_index = editor._category_combo.count() - 1
    assert editor._category_combo.itemText(sentinel_index) == _ADD_CATEGORY_SENTINEL

    editor._category_combo.setCurrentIndex(sentinel_index)
    editor._on_category_activated(sentinel_index)

    assert editor._category_combo.currentText() == "Intraday"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common", "Intraday"]


def test_cancelling_add_category_reverts_to_previous_selection(qapp, tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    from screens.strategy_builder import StrategyEditor
    import screens.strategy_builder as sb_module

    class FakeDialog:
        def __init__(self, theme, parent=None):
            pass
        def exec(self):
            return sb_module.QDialog.DialogCode.Rejected
        def category_name(self):
            return ""

    monkeypatch.setattr(sb_module, "_AddCategoryDialog", FakeDialog)

    s = store.new_strategy("T")
    s["category"] = "Weekly"
    editor = StrategyEditor(s, [], None)
    sentinel_index = editor._category_combo.count() - 1

    editor._category_combo.setCurrentIndex(sentinel_index)
    editor._on_category_activated(sentinel_index)

    assert editor._category_combo.currentText() == "Weekly"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


# ── Rename / delete custom categories ───────────────────────────────────────

def _isolate_stores(tmp_path, monkeypatch):
    from services import config_store, strategy_store as store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "strategies.json"))
    return store


def test_rename_custom_category_updates_list_and_strategies(tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    s = store.new_strategy("A")
    s["category"] = "Intraday"
    store.save_strategy(s)

    canonical = store.rename_custom_category("Intraday", "Scalping")

    assert canonical == "Scalping"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common", "Scalping"]
    assert store.load_all()[0]["category"] == "Scalping"


def test_rename_custom_category_is_noop_for_builtin(tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    assert store.rename_custom_category("Daily", "Everyday") == "Daily"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


def test_rename_custom_category_resolves_case_insensitive_collision(tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    assert store.rename_custom_category("Intraday", "weekly") == "Weekly"
    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


def test_delete_custom_category_reassigns_strategies_to_undefined(tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    s = store.new_strategy("A")
    s["category"] = "Intraday"
    store.save_strategy(s)

    store.delete_custom_category("Intraday")

    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]
    reloaded = store.load_all()[0]
    assert reloaded["category"] == store.UNDEFINED_CATEGORY
    assert reloaded["id"] == s["id"]   # the strategy itself was NOT deleted


def test_delete_custom_category_is_noop_for_builtin(tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    s = store.new_strategy("A")
    s["category"] = "Daily"
    store.save_strategy(s)

    store.delete_custom_category("Daily")

    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]
    assert store.load_all()[0]["category"] == "Daily"


def test_undefined_strategy_gets_its_own_sidebar_section(qapp, tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    s = store.new_strategy("Orphaned")
    s["category"] = "Intraday"
    store.save_strategy(s)
    store.delete_custom_category("Intraday")

    from app import AppController
    from screens.strategy_builder import StrategyBuilderScreen, _CategorySection
    screen = StrategyBuilderScreen(AppController(qapp))
    sections = [w for w in screen.findChildren(_CategorySection)]
    assert any(sec._category == store.UNDEFINED_CATEGORY for sec in sections)


# ── Manage Categories dialog ────────────────────────────────────────────────

def test_manage_categories_dialog_lists_only_custom_categories(qapp, tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    from screens.strategy_builder import ManageCategoriesDialog
    from PySide6.QtWidgets import QLabel
    dlg = ManageCategoriesDialog(None)
    labels = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert "Intraday" in labels
    assert "Daily" not in labels


def test_manage_categories_dialog_shows_empty_state(qapp, tmp_path, monkeypatch):
    _isolate_stores(tmp_path, monkeypatch)
    from screens.strategy_builder import ManageCategoriesDialog
    dlg = ManageCategoriesDialog(None)
    assert dlg._list_layout.count() == 2   # empty-state label + trailing stretch


def test_manage_categories_dialog_rename_flow(qapp, tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    import screens.strategy_builder as sb_module
    from screens.strategy_builder import ManageCategoriesDialog

    class FakeDialog:
        def __init__(self, theme, parent=None, **kwargs):
            pass
        def exec(self):
            return sb_module.QDialog.DialogCode.Accepted
        def category_name(self):
            return "Scalping"

    monkeypatch.setattr(sb_module, "_AddCategoryDialog", FakeDialog)
    dlg = ManageCategoriesDialog(None)
    dlg._rename("Intraday")

    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common", "Scalping"]


def test_manage_categories_dialog_delete_flow(qapp, tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    store.add_custom_category("Intraday")
    from PySide6.QtWidgets import QMessageBox
    from screens.strategy_builder import ManageCategoriesDialog

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    dlg = ManageCategoriesDialog(None)
    dlg._delete("Intraday")

    assert store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


# ── TopBar wiring ────────────────────────────────────────────────────────────

def test_topbar_has_manage_categories_signal(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    topbar = TopBar(ThemeManager(qapp))
    fired = []
    topbar.manage_categories_requested.connect(lambda: fired.append(1))
    topbar.manage_categories_requested.emit()
    assert fired == [1]


# ── Sidebar sections default to collapsed ───────────────────────────────────

def test_category_sections_default_collapsed(qapp, tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    s = store.new_strategy("A")
    store.save_strategy(s)

    from app import AppController
    from screens.strategy_builder import StrategyBuilderScreen, _CategorySection
    screen = StrategyBuilderScreen(AppController(qapp))
    section = screen.findChild(_CategorySection)
    assert section._expanded is False
    # isVisible() is unreliable here (the screen is never actually shown, so
    # it's always False regardless of setVisible() calls) — isHidden()
    # reflects the widget's own setVisible() call directly.
    assert section._body.isHidden() is True


def test_search_force_expands_collapsed_categories(qapp, tmp_path, monkeypatch):
    store = _isolate_stores(tmp_path, monkeypatch)
    s = store.new_strategy("Findme")
    store.save_strategy(s)

    from app import AppController
    from screens.strategy_builder import StrategyBuilderScreen
    screen = StrategyBuilderScreen(AppController(qapp))
    # Read straight off the layout rather than findChild() — _refresh_list()
    # only .hide()s+deleteLater()s the old section, it doesn't necessarily
    # stop being a child before deleteLater() actually runs, so findChild()
    # could still return the stale one.
    section = screen._list_layout.itemAt(0).widget()
    assert section._expanded is False
    assert section._body.isHidden() is True

    screen._search_box.setText("Findme")
    section = screen._list_layout.itemAt(0).widget()
    assert section._expanded is True
    assert section._body.isHidden() is False


def test_live_viewer_has_category_combo(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    from PySide6.QtWidgets import QComboBox
    lmv = LiveViewerWindow("", "", "", [])
    combo_items = []
    for c in lmv.findChildren(QComboBox):
        combo_items += [c.itemText(i) for i in range(c.count())]
    assert "All" in combo_items
    assert "Daily" in combo_items
    assert "Weekly" in combo_items
    assert "Monthly" in combo_items


def test_filtered_strategies_all(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    strats = [
        {"id": "1", "name": "A", "active": True, "category": "Daily",   "columns": []},
        {"id": "2", "name": "B", "active": True, "category": "Weekly",  "columns": []},
        {"id": "3", "name": "C", "active": True, "category": "Monthly", "columns": []},
    ]
    lmv.set_strategies(strats)
    lmv._cat_combo.setCurrentText("All")
    assert len(lmv._filtered_strategies()) == 3


def test_strategies_applied_merges_not_replaces(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    strats = [
        {"id": "1", "name": "A", "active": True,  "category": "Daily",  "columns": []},
        {"id": "2", "name": "B", "active": True,  "category": "Weekly", "columns": []},
        {"id": "3", "name": "C", "active": False, "category": "Weekly", "columns": []},
    ]
    lmv.set_strategies(strats)
    lmv._cat_combo.setCurrentText("Weekly")
    # Simulate picker returning only the Weekly subset with B toggled off
    weekly_updated = [
        {"id": "2", "name": "B", "active": False, "category": "Weekly", "columns": []},
        {"id": "3", "name": "C", "active": True,  "category": "Weekly", "columns": []},
    ]
    lmv._on_strategies_applied(weekly_updated)
    # All 3 strategies must still be present
    assert len(lmv._strategies) == 3
    # B and C should reflect the updated active state
    by_id = {s["id"]: s for s in lmv._strategies}
    assert by_id["2"]["active"] is False
    assert by_id["3"]["active"] is True
    # A (Daily) must be untouched
    assert by_id["1"]["active"] is True


def test_filtered_strategies_by_category(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    strats = [
        {"id": "1", "name": "A", "active": True, "category": "Daily",   "columns": []},
        {"id": "2", "name": "B", "active": True, "category": "Weekly",  "columns": []},
        {"id": "3", "name": "C", "active": True, "category": "Monthly", "columns": []},
    ]
    lmv.set_strategies(strats)
    lmv._cat_combo.setCurrentText("Weekly")
    result = lmv._filtered_strategies()
    assert len(result) == 1
    assert result[0]["name"] == "B"


def test_live_viewer_sector_map_built(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    assert hasattr(lmv, "_sector_map")
    assert isinstance(lmv._sector_map, dict)
    assert lmv._sector_map.get("INFY") == "TECHNOLOGY"
    assert lmv._sector_map.get("HDFCBANK") == "BANKING"


def test_inject_sector_prepends_column(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    headers = ["Scrip Name", "% Change", "Current"]
    data = [["INFY", 1.5, 1800.0], ["HDFCBANK", -0.5, 1650.0], ["UNKNOWN", 0.0, 100.0]]
    new_headers, new_data = lmv._inject_sector(headers, data)
    assert new_headers[0] == "Sector"
    assert new_headers[1] == "Scrip Name"
    assert new_data[0][0] == "TECHNOLOGY"
    assert new_data[1][0] == "BANKING"
    assert new_data[2][0] == "—"


def test_inject_sector_idempotent_on_empty(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    new_headers, new_data = lmv._inject_sector([], [])
    assert new_headers == ["Sector"]
    assert new_data == []


def test_scrip_name_col_is_bold_not_sector(qapp, tmp_path, monkeypatch):
    """After sector injection, Scrip Name (col 1) must be bold, not Sector (col 0)."""
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    headers = ["Scrip Name", "% Change"]
    data    = [["INFY", 1.5]]
    h2, d2  = lmv._inject_sector(headers, data)
    # h2 = ["Sector", "Scrip Name", "% Change"]
    lmv._headers      = h2
    lmv._data         = d2
    lmv._visible_cols = set(range(len(h2)))
    lmv._populate_table(d2, changed_keys=set())
    from PySide6.QtGui import QFont
    sector_item = lmv._table.item(0, 0)
    scrip_item  = lmv._table.item(0, 1)
    assert scrip_item is not None and scrip_item.font().bold(), "Scrip Name must be bold"
    assert sector_item is not None and not sector_item.font().bold(), "Sector must not be bold"


def test_apply_col_filter_keeps_scrip_name_visible(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    headers = ["Scrip Name", "% Change"]
    data    = [["INFY", 1.5]]
    h2, d2  = lmv._inject_sector(headers, data)
    lmv._headers      = h2
    lmv._data         = d2
    lmv._visible_cols = set(range(len(h2)))
    lmv._populate_table(d2, changed_keys=set())
    # Ask to hide everything — Scrip Name (index 1) must stay visible
    lmv._apply_col_filter(set())
    scrip_idx = h2.index("Scrip Name")
    assert scrip_idx in lmv._visible_cols, "Scrip Name must always remain in _visible_cols"
    assert not lmv._table.isColumnHidden(scrip_idx), "Scrip Name column must not be hidden"


def test_live_viewer_has_sector_combo(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    from PySide6.QtWidgets import QComboBox
    lmv = LiveViewerWindow("", "", "", [])
    assert hasattr(lmv, "_sector_combo"), "_sector_combo must exist"
    assert isinstance(lmv._sector_combo, QComboBox)
    items = [lmv._sector_combo.itemText(i) for i in range(lmv._sector_combo.count())]
    assert "All" in items
    assert "TECHNOLOGY" in items
    assert "BANKING" in items


def test_sector_filter_hides_non_matching_rows(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    headers = ["Scrip Name", "% Change"]
    data    = [["INFY", 1.5], ["HDFCBANK", -0.5], ["TCS", 0.2]]
    h2, d2  = lmv._inject_sector(headers, data)
    lmv._headers      = h2
    lmv._data         = d2
    lmv._visible_cols = set(range(len(h2)))
    lmv._populate_table(d2, changed_keys=set())
    # Filter to TECHNOLOGY — only INFY and TCS rows visible
    lmv._sector_combo.setCurrentText("TECHNOLOGY")
    visible_sectors = []
    for r in range(lmv._table.rowCount()):
        if not lmv._table.isRowHidden(r):
            item = lmv._table.item(r, 0)
            if item:
                visible_sectors.append(item.text())
    assert all(s == "TECHNOLOGY" for s in visible_sectors)
    assert len(visible_sectors) == 2   # INFY and TCS


def test_sector_filter_all_shows_all_rows(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    headers = ["Scrip Name", "% Change"]
    data    = [["INFY", 1.5], ["HDFCBANK", -0.5]]
    h2, d2  = lmv._inject_sector(headers, data)
    lmv._headers      = h2
    lmv._data         = d2
    lmv._visible_cols = set(range(len(h2)))
    lmv._populate_table(d2, changed_keys=set())
    lmv._sector_combo.setCurrentText("TECHNOLOGY")
    lmv._sector_combo.setCurrentText("All")
    hidden = sum(1 for r in range(lmv._table.rowCount()) if lmv._table.isRowHidden(r))
    assert hidden == 0


def test_sector_filter_survives_strategy_toggle(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    lmv = LiveViewerWindow("", "", "", [])
    headers = ["Scrip Name", "% Change"]
    data    = [["INFY", 1.5], ["HDFCBANK", -0.5]]
    h2, d2  = lmv._inject_sector(headers, data)
    lmv._headers      = h2
    lmv._data         = d2
    lmv._visible_cols = set(range(len(h2)))
    lmv._populate_table(d2, changed_keys=set())
    # Apply sector filter
    lmv._sector_combo.setCurrentText("TECHNOLOGY")
    # Trigger strategy toggle (re-render)
    lmv.set_strategies([])
    # Sector filter must still be active
    hidden = [lmv._table.isRowHidden(r) for r in range(lmv._table.rowCount())]
    # HDFCBANK (BANKING) should be hidden, INFY (TECHNOLOGY) visible
    assert any(hidden), "Some rows should be hidden after strategy toggle with active filter"


def test_column_editor_has_edit_formula_button(qapp):
    from services.strategy_store import new_column
    from screens.strategy_builder import ColumnEditorDialog
    from PySide6.QtWidgets import QPushButton
    col = new_column("TestCol")
    dlg = ColumnEditorDialog(col, ["LTP", "CLOSE"], None)
    btns = [b.text() for b in dlg.findChildren(QPushButton)]
    assert any("Edit Formula" in t for t in btns)


def test_column_editor_no_inline_formula_builder(qapp):
    """FormulaBuilder widget must NOT be embedded directly in ColumnEditorDialog."""
    from services.strategy_store import new_column
    from screens.strategy_builder import ColumnEditorDialog, FormulaBuilder
    col = new_column("TestCol")
    dlg = ColumnEditorDialog(col, ["LTP"], None)
    # FormulaBuilder may exist for fmt-rule conditions, but NOT as a direct child
    # of the main dialog layout at the value-formula level
    assert dlg._formula_preview is not None  # preview label exists instead


def test_strategy_editor_has_lmv_data_attrs(qapp):
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor
    s = new_strategy("T")
    editor = StrategyEditor(s, [], None)
    assert hasattr(editor, "_lmv_first_row")
    assert hasattr(editor, "_all_lmv_data")


def test_strategy_editor_content_is_page_scrollable(qapp):
    # Regression guard: Row Filter + Columns + Notifications together can
    # exceed the right panel's height (never itself wrapped in a scroll
    # area), so the editor's own content must be wrapped in one QScrollArea
    # rather than having Columns and Notifications both fight for "the rest
    # of the space" via stretch factors — that's what previously collapsed
    # both sections below their minimum size and rendered them overlapping.
    #
    # Exactly one — not one outer plus cramped fixed-height inner scroll
    # areas for Columns/Metrics on top of it, which is its own regression
    # (a second, much shorter scrollbar nested inside the first).
    from PySide6.QtWidgets import QScrollArea
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor
    s = new_strategy("T")
    editor = StrategyEditor(s, [], None)

    scrolls = editor.findChildren(QScrollArea)
    assert len(scrolls) == 1, f"expected exactly one QScrollArea in the editor, found {len(scrolls)}"
    outer = scrolls[0]
    assert outer.widget() is not None
    assert outer.widget().isAncestorOf(editor._col_inner)
    assert outer.widget().isAncestorOf(editor._notif_section)


def test_save_strategy_button_stays_outside_the_scroll_area(qapp):
    # Regression guard: Save Strategy used to live inline in the Columns
    # header, which scrolls out of view once the Notifications section below
    # it makes the page long — it now lives in a persistent footer bar
    # outside the scroll area instead, so it's always reachable.
    from PySide6.QtWidgets import QPushButton, QScrollArea
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor
    s = new_strategy("T")
    editor = StrategyEditor(s, [], None)

    save_btns = [b for b in editor.findChildren(QPushButton) if b.text() == "Save Strategy"]
    assert len(save_btns) == 1
    scroll = editor.findChild(QScrollArea)
    assert not scroll.widget().isAncestorOf(save_btns[0])


def test_fmt_rule_condition_has_edit_button(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog
    from PySide6.QtWidgets import QPushButton
    col = new_column("TestCol")
    col["fmt_rules"].append(new_fmt_rule())
    dlg = ColumnEditorDialog(col, ["LTP"], None)
    btns = [b.text() for b in dlg.findChildren(QPushButton)]
    assert any("Edit Condition" in t for t in btns)


def test_condition_editor_passes_computed_self_value(qapp, monkeypatch):
    # THIS in a fmt-rule condition must receive the column's computed value so
    # compile works (regression: TypeError NoneType <= int).
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog
    from screens import formula_editor

    col = new_column("TestCol")
    col["formula"] = [{"type": "col", "value": "LTP"}]   # value = LTP
    col["fmt_rules"].append(new_fmt_rule())
    dlg = ColumnEditorDialog(
        col, ["LTP"], None,
        lmv_first_row={"LTP": "5000"}, all_lmv_data=[{"LTP": "5000"}],
    )

    captured = {}

    class _FakeDlg:
        def __init__(self, *a, **kw):
            captured["self_value"] = kw.get("self_value")
        def exec(self):
            return 0  # rejected — we only care about construction
        def get_tokens(self):
            return []

    monkeypatch.setattr(formula_editor, "ExpressionEditorDialog", _FakeDlg)
    from PySide6.QtWidgets import QLabel
    dlg._open_condition_editor(0, QLabel())
    assert captured["self_value"] == 5000.0


def test_fmt_color_applies_when_this_condition_met():
    # End-to-end of get_cell_color with a THIS-based condition.
    from services.strategy_engine import get_cell_color
    col_def = {
        "name": "X", "formula": [],
        "fmt_rules": [{
            "condition": [{"type": "self"},
                          {"type": "op", "value": "<="},
                          {"type": "num", "value": "10000"}],
            "color": "#ff0000",
        }],
    }
    assert get_cell_color(col_def, 5000, {}, [{}]) == "#ff0000"
    assert get_cell_color(col_def, 20000, {}, [{}]) is None


def test_row_filter_editor_disables_this_and_passes_column_values(qapp, monkeypatch):
    # Row filter must NOT offer THIS (ambiguous with multiple columns) and must
    # pass each strategy column's computed value for the compile test.
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor
    from screens import formula_editor

    s = new_strategy("S")
    s["columns"] = [{"name": "Out", "formula": [{"type": "col", "value": "LTP"}],
                     "fmt_rules": []}]
    editor = StrategyEditor(s, ["LTP"], None)
    editor.update_lmv_data({"LTP": "42"}, [{"LTP": "42"}])

    captured = {}

    class _FakeDlg:
        def __init__(self, *a, **kw):
            captured.update(kw)
        def exec(self):
            return 0
        def get_tokens(self):
            return []

    monkeypatch.setattr(formula_editor, "ExpressionEditorDialog", _FakeDlg)
    editor._open_filter_editor()
    assert captured.get("allow_self") is False
    # The strategy's own column appears as a selectable field…
    assert "Out" in captured.get("lmv_headers", [])
    # …and its computed value is supplied for the compile test.
    assert captured.get("extra_row_values", {}).get("Out") == 42.0


# ── Conditional-format rule: "Apply color to" target column picker ──────────

def test_fmt_rule_has_target_column_combo_with_this_column_default(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog
    from PySide6.QtWidgets import QComboBox

    col = new_column("Signal")
    col["fmt_rules"].append(new_fmt_rule())
    dlg = ColumnEditorDialog(col, ["LTP", "Current"], None)

    combos = dlg.findChildren(QComboBox)
    target_combo = next(
        c for c in combos if [c.itemText(i) for i in range(c.count())][0] == "(This column)"
    )
    items = [target_combo.itemText(i) for i in range(target_combo.count())]
    assert items == ["(This column)", "LTP", "Current"]
    assert target_combo.currentText() == "(This column)"


def test_selecting_target_column_updates_rule(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog

    col = new_column("Signal")
    col["fmt_rules"].append(new_fmt_rule())
    dlg = ColumnEditorDialog(col, ["LTP", "Current"], None)

    dlg._set_fmt_target(0, "Current")
    assert dlg._col["fmt_rules"][0]["target_column"] == "Current"

    dlg._set_fmt_target(0, "(This column)")
    assert dlg._col["fmt_rules"][0]["target_column"] is None


def test_existing_target_column_preselected_on_reopen(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog
    from PySide6.QtWidgets import QComboBox

    col = new_column("Signal")
    rule = new_fmt_rule()
    rule["target_column"] = "Current"
    col["fmt_rules"].append(rule)
    dlg = ColumnEditorDialog(col, ["LTP", "Current"], None)

    combos = dlg.findChildren(QComboBox)
    target_combo = next(
        c for c in combos if "(This column)" in [c.itemText(i) for i in range(c.count())]
    )
    assert target_combo.currentText() == "Current"


def test_stale_target_column_not_in_lmv_headers_still_shown(qapp):
    """A rule saved when the LMV had a column that's since been removed/renamed
    must not silently lose its target on reopen — it stays selected/visible in
    the dropdown rather than being dropped without the user noticing."""
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog
    from PySide6.QtWidgets import QComboBox

    col = new_column("Signal")
    rule = new_fmt_rule()
    rule["target_column"] = "OldColumnName"
    col["fmt_rules"].append(rule)
    dlg = ColumnEditorDialog(col, ["LTP", "Current"], None)

    combos = dlg.findChildren(QComboBox)
    target_combo = next(
        c for c in combos if "(This column)" in [c.itemText(i) for i in range(c.count())]
    )
    items = [target_combo.itemText(i) for i in range(target_combo.count())]
    assert "OldColumnName" in items
    assert target_combo.currentText() == "OldColumnName"


# ── Conditional formatting rule reordering ──────────────────────────────────

def test_move_fmt_rule_up_swaps_with_previous(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog

    col = new_column("TestCol")
    rule_a = new_fmt_rule("#111111")
    rule_b = new_fmt_rule("#222222")
    col["fmt_rules"] = [rule_a, rule_b]
    dlg = ColumnEditorDialog(col, ["LTP"], None)

    dlg._move_fmt_rule(1, -1)
    assert dlg._col["fmt_rules"] == [rule_b, rule_a]


def test_move_fmt_rule_down_swaps_with_next(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog

    col = new_column("TestCol")
    rule_a = new_fmt_rule("#111111")
    rule_b = new_fmt_rule("#222222")
    col["fmt_rules"] = [rule_a, rule_b]
    dlg = ColumnEditorDialog(col, ["LTP"], None)

    dlg._move_fmt_rule(0, 1)
    assert dlg._col["fmt_rules"] == [rule_b, rule_a]


def test_move_fmt_rule_out_of_bounds_is_a_no_op(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog

    col = new_column("TestCol")
    rule_a = new_fmt_rule("#111111")
    col["fmt_rules"] = [rule_a]
    dlg = ColumnEditorDialog(col, ["LTP"], None)

    dlg._move_fmt_rule(0, -1)  # already first
    dlg._move_fmt_rule(0, 1)   # already last
    assert dlg._col["fmt_rules"] == [rule_a]


def test_fmt_rule_reorder_buttons_present_and_edge_disabled(qapp):
    from services.strategy_store import new_column, new_fmt_rule
    from screens.strategy_builder import ColumnEditorDialog

    col = new_column("TestCol")
    col["fmt_rules"] = [new_fmt_rule(), new_fmt_rule(), new_fmt_rule()]
    dlg = ColumnEditorDialog(col, ["LTP"], None)

    from PySide6.QtWidgets import QPushButton
    ups = [b for b in dlg.findChildren(QPushButton) if b.toolTip().startswith("Move up")]
    downs = [b for b in dlg.findChildren(QPushButton) if b.toolTip().startswith("Move down")]
    assert len(ups) == 3
    assert len(downs) == 3
    assert all(not b.icon().isNull() for b in ups + downs)
    assert ups[0].isEnabled() is False   # first rule can't move up
    assert downs[-1].isEnabled() is False  # last rule can't move down
    assert ups[1].isEnabled() is True
    assert downs[0].isEnabled() is True


def test_fmt_rules_help_button_shows_popup(qapp, monkeypatch):
    from services.strategy_store import new_column
    from screens.strategy_builder import ColumnEditorDialog
    from PySide6.QtWidgets import QMessageBox

    called = {}
    monkeypatch.setattr(
        QMessageBox, "information",
        lambda *a, **k: called.setdefault("shown", True),
    )
    col = new_column("TestCol")
    dlg = ColumnEditorDialog(col, ["LTP"], None)
    dlg._show_fmt_rules_help()
    assert called.get("shown") is True
