import sys, os
import pytest
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def test_function_catalogue_has_abs():
    from screens.formula_editor import FUNCTION_CATALOGUE
    names = [f["name"] for f in FUNCTION_CATALOGUE]
    assert "Abs" in names


def test_function_catalogue_has_round():
    from screens.formula_editor import FUNCTION_CATALOGUE
    names = [f["name"] for f in FUNCTION_CATALOGUE]
    assert "Round" in names


def test_function_catalogue_has_if():
    from screens.formula_editor import FUNCTION_CATALOGUE
    names = [f["name"] for f in FUNCTION_CATALOGUE]
    assert "IIf" in names


def test_operator_catalogue_has_plus():
    from screens.formula_editor import OPERATOR_CATALOGUE
    syms = [o["name"] for o in OPERATOR_CATALOGUE]
    assert "+" in syms


def test_operator_catalogue_has_and():
    from screens.formula_editor import OPERATOR_CATALOGUE
    syms = [o["name"] for o in OPERATOR_CATALOGUE]
    assert "And" in syms


def test_field_catalogue_wraps_headers():
    from screens.formula_editor import FIELD_CATALOGUE_FROM_HEADERS
    fields = FIELD_CATALOGUE_FROM_HEADERS(["LTP", "CLOSE"])
    assert fields[0]["name"] == "[LTP]"
    assert fields[0]["token"] == {"type": "col", "value": "LTP"}


def test_constants_catalogue_has_true_false():
    from screens.formula_editor import CONSTANTS_CATALOGUE
    names = [c["name"] for c in CONSTANTS_CATALOGUE]
    assert "True" in names
    assert "False" in names


def test_compile_check_valid_formula():
    from services.strategy_engine import compile_check
    tokens = [
        {"type": "col", "value": "LTP"},
        {"type": "op",  "value": "*"},
        {"type": "num", "value": "1.05"},
    ]
    ok, msg = compile_check(tokens, {"LTP": 100.0}, [{"LTP": 100.0}])
    assert ok is True
    assert "105" in msg


def test_compile_check_division_by_zero():
    from services.strategy_engine import compile_check
    tokens = [
        {"type": "num", "value": "1"},
        {"type": "op",  "value": "/"},
        {"type": "num", "value": "0"},
    ]
    ok, msg = compile_check(tokens, {}, [])
    assert ok is False


def test_compile_check_empty_tokens():
    from services.strategy_engine import compile_check
    ok, msg = compile_check([], {}, [])
    assert ok is False
    assert "empty" in msg.lower()


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    import sys
    return QApplication.instance() or QApplication(sys.argv)


def test_expression_editor_dialog_creates(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP", "CLOSE"], [], {})
    assert dlg is not None


def test_expression_editor_has_six_nav_items(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QListWidget
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    # The nav list is the leftmost QListWidget
    nav = dlg._nav_list
    texts = [nav.item(i).text() for i in range(nav.count())]
    assert texts == ["Functions", "Operators", "Fields", "Rows", "Constants", "Variables"]


def test_expression_editor_get_tokens_empty(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    assert dlg.get_tokens() == []


def test_editor_add_token_via_operator_updates_preview(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    dlg._add_token({"type": "op", "value": "+"})
    assert "+" in dlg._preview_edit.toPlainText()


def test_editor_backspace_removes_character_before_cursor(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    tokens = [{"type": "col", "value": "LTP"}]
    dlg = ExpressionEditorDialog(tokens, ["LTP"], [], {})
    before = dlg._preview_edit.toPlainText()
    assert before == "[LTP]"
    dlg._backspace()
    assert dlg._preview_edit.toPlainText() == before[:-1]


def test_editor_backspace_deletes_at_cursor_not_always_at_end(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtGui import QTextCursor
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    dlg._preview_edit.setPlainText("[LTP]+1")
    cursor = dlg._preview_edit.textCursor()
    cursor.setPosition(5)   # right after "[LTP]", before "+1"
    dlg._preview_edit.setTextCursor(cursor)
    dlg._backspace()
    assert dlg._preview_edit.toPlainText() == "[LTP+1"


def test_editor_clear_empties_tokens(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    tokens = [{"type": "col", "value": "LTP"}]
    dlg = ExpressionEditorDialog(tokens, ["LTP"], [], {})
    dlg._clear()
    assert dlg.get_tokens() == []


def test_editor_save_disabled_before_compile(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    assert not dlg._save_btn.isEnabled()


def test_editor_search_filters_functions(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    # Select Functions nav item (row 0)
    dlg._nav_list.setCurrentRow(0)
    count_all = dlg._item_list.count()
    dlg._search_box.setText("round")
    count_filtered = dlg._item_list.count()
    assert count_filtered < count_all
    assert count_filtered >= 1


def test_editor_field_catalogue_includes_lmv_headers(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP", "CLOSE", "OPEN"], [], {})
    dlg._nav_list.setCurrentRow(2)  # Fields
    items = [dlg._item_list.item(i).text() for i in range(dlg._item_list.count())]
    assert "[LTP]" in items
    assert "[CLOSE]" in items


def test_editor_constants_include_true_false(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], [], [], {})
    dlg._nav_list.setCurrentRow(4)  # Constants
    items = [dlg._item_list.item(i).text() for i in range(dlg._item_list.count())]
    assert "True" in items
    assert "False" in items


def test_compile_check_true_false_constants():
    from services.strategy_engine import compile_check
    tokens = [{"type": "num", "value": "True"}]
    ok, msg = compile_check(tokens, {}, [])
    assert ok is True


def test_tokens_round_trip_through_dialog(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    original = [
        {"type": "col", "value": "LTP"},
        {"type": "op",  "value": "*"},
        {"type": "num", "value": "1.05"},
    ]
    dlg = ExpressionEditorDialog(original, ["LTP"], [], {"LTP": 100.0})
    result = dlg.get_tokens()
    assert result == original


# ── "[Col of Symbol]" cross-row reference ────────────────────────────────────

def test_parse_field_with_of_splits_into_col_and_symbol():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("[Open of Nifty]")
    assert tokens == [{"type": "col", "value": "Open", "of": "Nifty"}]


def test_parse_plain_field_has_no_of_key():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("[Open]")
    assert tokens == [{"type": "col", "value": "Open"}]


def test_parse_field_of_prefers_exact_header_match():
    from screens.formula_editor import parse_expression_text
    # A header that itself contains " of " must not be split apart.
    tokens = parse_expression_text("[% of Day Range]", known_headers=["% of Day Range"])
    assert tokens == [{"type": "col", "value": "% of Day Range"}]


def test_token_insert_text_renders_of_syntax():
    from screens.formula_editor import _token_insert_text
    assert _token_insert_text({"type": "col", "value": "Open", "of": "Nifty"}) == "[Open of Nifty]"
    assert _token_insert_text({"type": "col", "value": "Open"}) == "[Open]"


def test_col_of_tokens_round_trip_through_dialog(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    original = [{"type": "col", "value": "Open", "of": "Nifty"}]
    dlg = ExpressionEditorDialog(original, ["Open"], [], {"Open": 100.0})
    assert dlg.get_tokens() == original


def test_row_catalogue_lists_distinct_scrip_names(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    all_data = [{"Scrip Name": "NIFTY", "Open": 100}, {"Scrip Name": "NIFTY", "Open": 100},
                {"Scrip Name": "BANKNIFTY", "Open": 200}]
    dlg = ExpressionEditorDialog([], ["Open"], [], {}, all_lmv_data=all_data)
    dlg._nav_list.setCurrentRow(3)  # Rows
    items = [dlg._item_list.item(i).text() for i in range(dlg._item_list.count())]
    assert sorted(items) == ["BANKNIFTY", "NIFTY"]


def test_add_row_symbol_after_field_extends_bracket(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([{"type": "col", "value": "Open"}], ["Open"], [], {})
    # Cursor is left at the end after loading tokens, i.e. right after "[Open]".
    dlg._add_row_symbol("Nifty")
    assert dlg._preview_edit.toPlainText() == "[Open of Nifty]"


def test_add_row_symbol_without_field_shows_hint(qapp, monkeypatch):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QMessageBox
    called = {}
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: called.setdefault("shown", True))
    dlg = ExpressionEditorDialog([], ["Open"], [], {})
    dlg._add_row_symbol("Nifty")
    assert called.get("shown") is True
    assert dlg._preview_edit.toPlainText() == ""


# ── Formula variables ("{Name}" tokens) ──────────────────────────────────────

@pytest.fixture
def var_store(tmp_path, monkeypatch):
    from services import formula_variable_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "vars.json"))
    return store


def test_token_insert_text_renders_var_braces():
    from screens.formula_editor import _token_insert_text
    assert _token_insert_text({"type": "var", "value": "Threshold"}) == "{Threshold}"


def test_parse_expression_text_reads_var_braces():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("{Threshold}")
    assert tokens == [{"type": "var", "value": "Threshold"}]


def test_var_token_round_trips_alongside_field(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    original = [
        {"type": "col", "value": "Open"},
        {"type": "op",  "value": ">="},
        {"type": "var", "value": "Threshold"},
    ]
    dlg = ExpressionEditorDialog(original, ["Open"], [], {"Open": 100.0})
    assert dlg.get_tokens() == original


def test_structural_error_flags_unclosed_brace():
    from screens.formula_editor import _find_structural_error
    err = _find_structural_error("{Threshold")
    assert err is not None
    msg, start, end = err
    assert "closing '}'" in msg


def test_variable_catalogue_reflects_store(var_store):
    from screens.formula_editor import VARIABLE_CATALOGUE_FROM_STORE
    assert VARIABLE_CATALOGUE_FROM_STORE() == []
    v = var_store.new_variable("Threshold")
    var_store.save_variable(v)
    entries = VARIABLE_CATALOGUE_FROM_STORE()
    assert entries[0]["name"] == "{Threshold}"
    assert entries[0]["token"] == {"type": "var", "value": "Threshold"}


def test_variables_nav_tab_lists_saved_variable(qapp, var_store):
    from screens.formula_editor import ExpressionEditorDialog
    v = var_store.new_variable("Threshold")
    var_store.save_variable(v)
    dlg = ExpressionEditorDialog([], ["Open"], [], {})
    dlg._nav_list.setCurrentRow(5)  # Variables
    items = [dlg._item_list.item(i).text() for i in range(dlg._item_list.count())]
    assert "{Threshold}" in items


def test_clicking_variable_item_inserts_braces(qapp, var_store):
    from screens.formula_editor import ExpressionEditorDialog
    v = var_store.new_variable("Threshold")
    var_store.save_variable(v)
    dlg = ExpressionEditorDialog([], ["Open"], [], {})
    dlg._add_token({"type": "var", "value": "Threshold"})
    assert dlg._preview_edit.toPlainText() == "{Threshold}"


def test_save_as_variable_button_disabled_before_compile(qapp, var_store):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["Open"], [], {})
    assert not dlg._save_var_btn.isEnabled()


def test_save_as_variable_persists_current_formula(qapp, var_store, monkeypatch):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    tokens = [{"type": "num", "value": "0.998"}]
    dlg = ExpressionEditorDialog(tokens, [], [], {})
    dlg._compiled_ok = True
    dlg._compiled_tokens = tokens
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Threshold", True))
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    dlg._save_as_variable()
    saved = var_store.get_by_name("Threshold")
    assert saved is not None
    assert saved["formula"] == tokens


def test_save_as_variable_rejects_invalid_characters(qapp, var_store, monkeypatch):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    tokens = [{"type": "num", "value": "1"}]
    dlg = ExpressionEditorDialog(tokens, [], [], {})
    dlg._compiled_ok = True
    dlg._compiled_tokens = tokens
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("Bad[Name]", True))
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("shown", True))
    dlg._save_as_variable()
    assert warned.get("shown") is True
    assert var_store.get_by_name("Bad[Name]") is None


# ── Variables manager dialog ─────────────────────────────────────────────────

def test_variables_manager_lists_existing(qapp, var_store):
    from screens.formula_editor import VariablesManagerDialog
    v = var_store.new_variable("Threshold")
    var_store.save_variable(v)
    dlg = VariablesManagerDialog([], {})
    items = [dlg._list.item(i).text() for i in range(dlg._list.count())]
    assert items == ["{Threshold}"]


def test_variables_manager_delete_removes_variable(qapp, var_store, monkeypatch):
    from screens.formula_editor import VariablesManagerDialog
    from PySide6.QtWidgets import QMessageBox
    v = var_store.new_variable("Threshold")
    var_store.save_variable(v)
    dlg = VariablesManagerDialog([], {})
    dlg._list.setCurrentRow(0)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    dlg._delete_selected()
    assert var_store.load_all() == []
    assert dlg._list.count() == 0


def test_variables_manager_rename_rejects_duplicate(qapp, var_store, monkeypatch):
    from screens.formula_editor import VariablesManagerDialog
    from PySide6.QtWidgets import QInputDialog, QMessageBox
    var_store.save_variable(var_store.new_variable("A"))
    var_store.save_variable(var_store.new_variable("B"))
    dlg = VariablesManagerDialog([], {})
    # Select "A" and try to rename it to "B" (already taken).
    for i in range(dlg._list.count()):
        if dlg._list.item(i).text() == "{A}":
            dlg._list.setCurrentRow(i)
            break
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("B", True))
    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: warned.setdefault("shown", True))
    dlg._rename_selected()
    assert warned.get("shown") is True
    assert var_store.get_by_name("A") is not None
