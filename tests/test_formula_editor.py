import sys, os
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
