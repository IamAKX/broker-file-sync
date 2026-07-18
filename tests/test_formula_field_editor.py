import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def theme(qapp):
    from app import AppController
    return AppController(qapp).theme


def test_builder_starts_with_given_tokens(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    tokens = [{"type": "field", "value": "HIGH"}]
    b = FieldFormulaBuilder(tokens, theme)
    assert b.get_tokens() == tokens


def test_clicking_raw_field_chip_appends_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    from PySide6.QtWidgets import QPushButton
    b = FieldFormulaBuilder([], theme)
    high_btn = next(btn for btn in b.findChildren(QPushButton) if btn.text() == "HIGH")
    high_btn.click()
    assert b.get_tokens() == [{"type": "field", "value": "HIGH"}]


def test_clicking_operator_appends_op_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    from PySide6.QtWidgets import QPushButton
    b = FieldFormulaBuilder([{"type": "field", "value": "HIGH"}], theme)
    plus_btn = next(btn for btn in b.findChildren(QPushButton) if btn.text() == "+")
    plus_btn.click()
    assert b.get_tokens()[-1] == {"type": "op", "value": "+"}


def test_clicking_paren_appends_paren_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    from PySide6.QtWidgets import QPushButton
    b = FieldFormulaBuilder([], theme)
    open_btn = next(btn for btn in b.findChildren(QPushButton) if btn.text() == "(")
    open_btn.click()
    assert b.get_tokens()[-1] == {"type": "paren", "value": "("}


def test_add_number_appends_num_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    b = FieldFormulaBuilder([], theme)
    b._num_input.setText("1.1")
    b._add_number()
    assert b.get_tokens() == [{"type": "num", "value": "1.1"}]


def test_clear_empties_tokens(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    b = FieldFormulaBuilder([{"type": "num", "value": "1"}], theme)
    b._clear()
    assert b.get_tokens() == []


def test_remove_chip_removes_matching_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    tokens = [{"type": "field", "value": "HIGH"}, {"type": "op", "value": "+"}]
    b = FieldFormulaBuilder(tokens, theme)
    chip = b._chips[0]
    b._remove_chip(chip)
    assert b.get_tokens() == [{"type": "op", "value": "+"}]


def test_other_codes_excludes_self():
    from screens.formula_field_editor import FieldFormulaBuilder
    b = FieldFormulaBuilder([], theme=None, exclude_code="CMH")
    codes = b._other_codes()
    assert "CMH" not in codes
    assert "PWC" in codes


def test_window_agg_picker_inserts_func_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder, _TwoStepPickerDialog
    from PySide6.QtWidgets import QDialog

    b = FieldFormulaBuilder([], theme)

    class _Fake:
        def exec(self):
            return QDialog.DialogCode.Accepted
        def selected(self):
            return "HIGH", "CURRENT_MONTH"

    import screens.formula_field_editor as mod
    orig = mod._TwoStepPickerDialog
    mod._TwoStepPickerDialog = lambda *a, **k: _Fake()
    try:
        b._add_window_agg("MAX_OF(")
    finally:
        mod._TwoStepPickerDialog = orig

    assert b.get_tokens() == [{"type": "func", "value": "MAX_OF(", "field": "HIGH", "window": "CURRENT_MONTH"}]


def test_at_picker_inserts_func_token(theme):
    from screens.formula_field_editor import FieldFormulaBuilder
    from PySide6.QtWidgets import QDialog

    b = FieldFormulaBuilder([], theme)

    class _Fake:
        def exec(self):
            return QDialog.DialogCode.Accepted
        def selected(self):
            return "CLOSE", "PREVIOUS_TRADING_DAY"

    import screens.formula_field_editor as mod
    orig = mod._TwoStepPickerDialog
    mod._TwoStepPickerDialog = lambda *a, **k: _Fake()
    try:
        b._add_at()
    finally:
        mod._TwoStepPickerDialog = orig

    assert b.get_tokens() == [{"type": "func", "value": "AT(", "field": "CLOSE", "timepoint": "PREVIOUS_TRADING_DAY"}]


def test_dialog_wraps_builder_and_returns_tokens(theme):
    from screens.formula_field_editor import FormulaFieldEditorDialog
    dlg = FormulaFieldEditorDialog([{"type": "field", "value": "HIGH"}], theme)
    assert dlg.get_tokens() == [{"type": "field", "value": "HIGH"}]
