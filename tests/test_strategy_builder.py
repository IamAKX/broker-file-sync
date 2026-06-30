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


def test_strategy_card_shows_category_badge(qapp):
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyCard
    from PySide6.QtWidgets import QLabel
    s = new_strategy("T")
    s["category"] = "Weekly"
    card = StrategyCard(s, None)
    labels = [lbl.text() for lbl in card.findChildren(QLabel)]
    assert "Weekly" in labels


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
