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
