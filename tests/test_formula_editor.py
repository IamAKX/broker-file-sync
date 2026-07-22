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


def test_expression_editor_has_four_nav_items(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QListWidget
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    # The nav list is the leftmost QListWidget
    nav = dlg._nav_list
    texts = [nav.item(i).text() for i in range(nav.count())]
    assert texts == ["Functions", "Operators", "Fields", "Constants"]


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
    dlg._nav_list.setCurrentRow(3)  # Constants
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
