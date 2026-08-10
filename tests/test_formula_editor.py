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


def test_expression_editor_has_seven_nav_items(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QListWidget
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    # The nav list is the leftmost QListWidget
    nav = dlg._nav_list
    texts = [nav.item(i).text() for i in range(nav.count())]
    assert texts == ["Functions", "Historic Value", "Operators", "Fields",
                     "Rows", "Constants", "Variables"]


def test_expression_editor_get_tokens_empty(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    assert dlg.get_tokens() == []


def test_editor_add_token_via_operator_updates_preview(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP"], [], {})
    dlg._add_token({"type": "op", "value": "+"})
    assert "+" in dlg._preview_edit.toPlainText()


# ── real_lmv_headers / historic field references (see compile_check's own
# lmv_headers tests in test_strategy_engine_functions.py for the underlying
# logic) — these cover the dialog's threading of it through.

def test_real_lmv_headers_defaults_to_lmv_headers_when_omitted(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP", "Last5Day"], [], {})
    assert dlg._real_lmv_headers == ["LTP", "Last5Day"]


def test_real_lmv_headers_can_be_narrower_than_lmv_headers(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], ["LTP", "Last5Day"], [],
                                 {"LTP": 100.0}, real_lmv_headers=["LTP"])
    assert dlg._real_lmv_headers == ["LTP"]


def test_compile_and_test_succeeds_for_historic_field_when_real_lmv_headers_narrower(qapp, monkeypatch):
    # Reproduces: [Last5Day]*1, where Last5Day is a Formula Builder field
    # (MAX_OF([DAY TO], LAST_5_TRADING_DAYS)) offered in the Fields list
    # but not one of the sheet's own loaded columns — used to always fail
    # Compile & Test with "tried to do math with an empty cell" even though
    # nothing about the formula was actually wrong.
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QMessageBox
    shown = {}
    monkeypatch.setattr(QMessageBox, "information",
                        lambda *a, **k: shown.setdefault("msg", a[-1] if a else ""))
    dlg = ExpressionEditorDialog(
        [], ["Scrip Name", "Last5Day"], [], {"Scrip Name": "INFY", "Last5Day": None},
        real_lmv_headers=["Scrip Name"],
    )
    dlg._preview_edit.setPlainText("[Last5Day]*1")
    dlg._compile_and_test()
    assert dlg._compiled_ok is True
    assert "historic" in shown.get("msg", "").lower()


def test_compile_and_test_still_fails_for_blank_real_lmv_column(qapp, monkeypatch):
    # A genuinely-loaded LMV column that's blank for this row must still be
    # reported as a real problem — real_lmv_headers only exempts fields
    # outside that set.
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QMessageBox
    shown = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda *a, **k: shown.setdefault("msg", a[-1] if a else ""))
    dlg = ExpressionEditorDialog(
        [], ["Scrip Name", "OR.High"], [], {"Scrip Name": "INFY", "OR.High": None},
        real_lmv_headers=["Scrip Name", "OR.High"],
    )
    dlg._preview_edit.setPlainText("[OR.High]*1")
    dlg._compile_and_test()
    assert dlg._compiled_ok is False
    assert "empty cell" in shown.get("msg", "").lower()


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
    dlg._nav_list.setCurrentRow(3)  # Fields
    items = [dlg._item_list.item(i).text() for i in range(dlg._item_list.count())]
    assert "[LTP]" in items
    assert "[CLOSE]" in items


def test_editor_constants_include_true_false(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    dlg = ExpressionEditorDialog([], [], [], {})
    dlg._nav_list.setCurrentRow(5)  # Constants
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


# ── _DAYS historic aggregate functions: AVG_DAYS(column, days) ──────────────

def test_parse_days_agg_captures_column_and_days_bracket_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("AVG_DAYS([High], 20)")
    assert tokens == [{"type": "func", "value": "AVG_DAYS(", "col_arg": "High", "days_arg": 20}]


def test_parse_days_agg_captures_column_and_days_bare_word_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("AVG_DAYS(High, 20)")
    assert tokens == [{"type": "func", "value": "AVG_DAYS(", "col_arg": "High", "days_arg": 20}]


def test_parse_days_agg_without_days_falls_back_to_bare_func_token():
    """Missing the required ", <days>" arg — not a crash, just falls through
    to normal tokenization (the column becomes a separate [Field] token) —
    same graceful-degradation spirit as everywhere else in this parser."""
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("AVG_DAYS([High])")
    assert tokens[0] == {"type": "func", "value": "AVG_DAYS("}
    assert {"type": "col", "value": "High"} in tokens


@pytest.mark.parametrize("fname", [
    "MIN_DAYS", "MAX_DAYS", "SUM_DAYS", "COUNT_DAYS", "STDDEV_DAYS",
    "MEDIAN_DAYS", "VARIANCE_DAYS", "RANGE_DAYS",
])
def test_parse_every_days_aggregate_function_name(fname):
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text(f"{fname}([Close], 5)")
    assert tokens == [{"type": "func", "value": f"{fname}(", "col_arg": "Close", "days_arg": 5}]


def test_days_agg_token_renders_back_to_two_arg_text():
    from screens.formula_editor import _tokens_to_text
    tokens = [{"type": "func", "value": "AVG_DAYS(", "col_arg": "High", "days_arg": 20}]
    assert _tokens_to_text(tokens) == "AVG_DAYS([High], 20)"


def test_days_agg_token_with_spaced_column_name_renders_bracketed():
    # Bug repro: MAX_DAYS([DAY TO], 10), saved then reopened for editing,
    # used to redisplay as MAX_DAYS(DAY TO, 10) — missing brackets around a
    # column name containing a space — which the parser then rejected,
    # forcing the user to manually re-add them. col_arg must always render
    # bracketed so it round-trips regardless of what characters the column
    # name contains (spaces, dots, ...).
    from screens.formula_editor import _tokens_to_text
    tokens = [{"type": "func", "value": "MAX_DAYS(", "col_arg": "DAY TO", "days_arg": 10}]
    assert _tokens_to_text(tokens) == "MAX_DAYS([DAY TO], 10)"


def test_days_agg_tokens_round_trip_through_dialog(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    original = [{"type": "func", "value": "AVG_DAYS(", "col_arg": "High", "days_arg": 20}]
    dlg = ExpressionEditorDialog(original, ["High"], [], {"High": 100.0})
    assert dlg.get_tokens() == original


def test_days_agg_tokens_with_spaced_column_round_trip_through_dialog(qapp):
    # The actual reported bug: MAX_DAYS([DAY TO], 10), saved then reopened
    # for editing. Before the fix, the preview box redisplayed it as
    # MAX_DAYS(DAY TO, 10) (col_arg missing its brackets) — the parser
    # can't tell "DAY TO" apart from two bare identifiers without them, so
    # get_tokens() came back empty/wrong and the user had to manually
    # retype the brackets before it would compile again.
    from screens.formula_editor import ExpressionEditorDialog
    original = [{"type": "func", "value": "MAX_DAYS(", "col_arg": "DAY TO", "days_arg": 10}]
    dlg = ExpressionEditorDialog(original, ["DAY TO"], [], {"DAY TO": 12.3})
    assert dlg._preview_edit.toPlainText() == "MAX_DAYS([DAY TO], 10)"
    assert dlg.get_tokens() == original


def test_compile_and_test_succeeds_immediately_on_reopened_spaced_column_formula(qapp, monkeypatch):
    # Same repro as above, but through the actual Compile & Test button
    # rather than get_tokens()'s own re-parse fallback — this is what the
    # user hit: reopening a saved formula and clicking Compile & Test
    # without touching the text at all used to fail.
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    original = [{"type": "func", "value": "MAX_DAYS(", "col_arg": "DAY TO", "days_arg": 10}]
    dlg = ExpressionEditorDialog(original, ["DAY TO"], [], {"DAY TO": 12.3})
    dlg._compile_and_test()
    assert dlg._compiled_ok is True


def test_function_catalogue_has_avg_days():
    from screens.formula_editor import FUNCTION_CATALOGUE
    names = [f["name"] for f in FUNCTION_CATALOGUE]
    assert "AVG_DAYS" in names


# ── VALUE_DAYS_AGO(column, days) / VALUE_ON_DATE(column, date) point lookups

def test_parse_value_days_ago_captures_column_and_days_bracket_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_DAYS_AGO([High], 2)")
    assert tokens == [{"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": "High", "days_arg": 2}]


def test_parse_value_days_ago_captures_column_and_days_bare_word_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_DAYS_AGO(High, 2)")
    assert tokens == [{"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": "High", "days_arg": 2}]


def test_parse_value_on_date_captures_column_and_date_bracket_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_ON_DATE([High], 2026-07-15)")
    assert tokens == [{"type": "func", "value": "VALUE_ON_DATE(", "col_arg": "High", "date_arg": "2026-07-15"}]


def test_parse_value_on_date_captures_column_and_date_bare_word_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_ON_DATE(High, 2026-07-15)")
    assert tokens == [{"type": "func", "value": "VALUE_ON_DATE(", "col_arg": "High", "date_arg": "2026-07-15"}]


def test_parse_value_on_date_without_date_falls_back_to_bare_func_token():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_ON_DATE([High])")
    assert tokens[0] == {"type": "func", "value": "VALUE_ON_DATE("}
    assert {"type": "col", "value": "High"} in tokens


def test_value_days_ago_token_renders_back_to_two_arg_text():
    from screens.formula_editor import _tokens_to_text
    tokens = [{"type": "func", "value": "VALUE_DAYS_AGO(", "col_arg": "High", "days_arg": 2}]
    assert _tokens_to_text(tokens) == "VALUE_DAYS_AGO([High], 2)"


def test_value_on_date_token_renders_back_to_two_arg_text():
    from screens.formula_editor import _tokens_to_text
    tokens = [{"type": "func", "value": "VALUE_ON_DATE(", "col_arg": "High", "date_arg": "2026-07-15"}]
    assert _tokens_to_text(tokens) == "VALUE_ON_DATE([High], 2026-07-15)"


def test_point_lookup_tokens_round_trip_through_dialog(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    original = [{"type": "func", "value": "VALUE_ON_DATE(", "col_arg": "High",
                "date_arg": "2026-07-15"}]
    dlg = ExpressionEditorDialog(original, ["High"], [], {"High": 100.0})
    assert dlg.get_tokens() == original


def test_point_lookup_catalogue_has_both_functions():
    from screens.formula_editor import POINT_LOOKUP_CATALOGUE
    names = {f["name"] for f in POINT_LOOKUP_CATALOGUE}
    assert names == {"VALUE_DAYS_AGO", "VALUE_ON_DATE", "VALUE_AT_MAX_DAYS", "VALUE_AT_MIN_DAYS"}
    pickers = {f["name"]: f["token"]["needs_point_picker"] for f in POINT_LOOKUP_CATALOGUE}
    assert pickers == {
        "VALUE_DAYS_AGO": "days_ago", "VALUE_ON_DATE": "on_date",
        "VALUE_AT_MAX_DAYS": "extreme_days", "VALUE_AT_MIN_DAYS": "extreme_days",
    }


def test_historic_value_nav_section_lists_point_lookup_functions(qapp):
    from screens.formula_editor import ExpressionEditorDialog, POINT_LOOKUP_CATALOGUE
    dlg = ExpressionEditorDialog([], ["High"], [], {})
    dlg._nav_list.setCurrentRow(1)  # Historic Value
    items = [dlg._item_list.item(i).text() for i in range(dlg._item_list.count())]
    assert len(items) == len(POINT_LOOKUP_CATALOGUE)
    assert "VALUE_DAYS_AGO" in items
    assert "VALUE_ON_DATE" in items
    assert "VALUE_AT_MAX_DAYS" in items
    assert "VALUE_AT_MIN_DAYS" in items


# ── VALUE_AT_MAX_DAYS(column, driver_column, days) / VALUE_AT_MIN_DAYS(...) ──

def test_parse_value_at_max_days_captures_both_columns_and_days_bracket_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_AT_MAX_DAYS([High], [CWTO], 5)")
    assert tokens == [{"type": "func", "value": "VALUE_AT_MAX_DAYS(",
                       "col_arg": "High", "driver_col_arg": "CWTO", "days_arg": 5}]


def test_parse_value_at_min_days_captures_both_columns_and_days_bare_word_form():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_AT_MIN_DAYS(Low, CWTO, 5)")
    assert tokens == [{"type": "func", "value": "VALUE_AT_MIN_DAYS(",
                       "col_arg": "Low", "driver_col_arg": "CWTO", "days_arg": 5}]


def test_parse_value_at_max_days_mixed_bracket_and_bare_forms():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_AT_MAX_DAYS([DAY TO], CWTO, 5)")
    assert tokens == [{"type": "func", "value": "VALUE_AT_MAX_DAYS(",
                       "col_arg": "DAY TO", "driver_col_arg": "CWTO", "days_arg": 5}]


def test_parse_value_at_max_days_without_driver_falls_back_to_bare_func_token():
    from screens.formula_editor import parse_expression_text
    tokens = parse_expression_text("VALUE_AT_MAX_DAYS([High])")
    assert tokens[0] == {"type": "func", "value": "VALUE_AT_MAX_DAYS("}
    assert {"type": "col", "value": "High"} in tokens


def test_value_at_max_days_token_renders_back_to_three_arg_text():
    from screens.formula_editor import _tokens_to_text
    tokens = [{"type": "func", "value": "VALUE_AT_MAX_DAYS(", "col_arg": "High",
               "driver_col_arg": "CWTO", "days_arg": 5}]
    assert _tokens_to_text(tokens) == "VALUE_AT_MAX_DAYS([High], [CWTO], 5)"


def test_value_at_extreme_tokens_round_trip_through_dialog(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    original = [{"type": "func", "value": "VALUE_AT_MAX_DAYS(", "col_arg": "High",
                "driver_col_arg": "CWTO", "days_arg": 5}]
    dlg = ExpressionEditorDialog(original, ["High", "CWTO"], [], {"High": 100.0, "CWTO": 0.01})
    assert dlg.get_tokens() == original


def test_extreme_days_picker_inserts_full_call_text(qapp):
    """The value column and driver column pickers draw from the same full
    column list (self._lmv_headers + self._strategy_col_headers) — any LMV
    column or the strategy's own computed columns, not a restricted set."""
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QDialog

    dlg = ExpressionEditorDialog([], ["High", "CWTO"], ["MyCol"], {"High": 100.0})

    picks = iter(["High", "CWTO"])

    class _FakeColDlg:
        def __init__(self, *a, **k): pass
        def setWindowTitle(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def selected_column(self): return next(picks)

    class _FakeNDlg:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def selected_n(self): return 5

    import screens.formula_editor as mod
    orig_col, orig_n = mod._ColumnPickerDialog, mod._DaysCountPickerDialog
    mod._ColumnPickerDialog = _FakeColDlg
    mod._DaysCountPickerDialog = _FakeNDlg
    try:
        dlg._open_point_lookup_picker("VALUE_AT_MAX_DAYS", "extreme_days")
    finally:
        mod._ColumnPickerDialog = orig_col
        mod._DaysCountPickerDialog = orig_n

    assert dlg._preview_edit.toPlainText() == "VALUE_AT_MAX_DAYS([High], [CWTO], 5)"


def test_extreme_days_picker_cancelled_driver_step_inserts_nothing(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QDialog

    dlg = ExpressionEditorDialog([], ["High", "CWTO"], [], {"High": 100.0})

    calls = {"n": 0}

    class _FakeColDlg:
        def __init__(self, *a, **k): pass
        def setWindowTitle(self, *a, **k): pass
        def exec(self):
            calls["n"] += 1
            # First call (value column) accepts, second (driver) cancels.
            return QDialog.DialogCode.Accepted if calls["n"] == 1 else QDialog.DialogCode.Rejected
        def selected_column(self): return "High"

    import screens.formula_editor as mod
    orig_col = mod._ColumnPickerDialog
    mod._ColumnPickerDialog = _FakeColDlg
    try:
        dlg._open_point_lookup_picker("VALUE_AT_MAX_DAYS", "extreme_days")
    finally:
        mod._ColumnPickerDialog = orig_col

    assert dlg._preview_edit.toPlainText() == ""


# ── _open_point_lookup_picker: column + (N-days-back / date) picker ────────

def test_days_ago_picker_inserts_full_call_text(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QDialog

    dlg = ExpressionEditorDialog([], ["High"], [], {"High": 100.0})

    class _FakeColDlg:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def selected_column(self): return "High"

    class _FakeNDlg:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def selected_n(self): return 2

    import screens.formula_editor as mod
    orig_col, orig_n = mod._ColumnPickerDialog, mod._DaysAgoPickerDialog
    mod._ColumnPickerDialog = _FakeColDlg
    mod._DaysAgoPickerDialog = _FakeNDlg
    try:
        dlg._open_point_lookup_picker("VALUE_DAYS_AGO", "days_ago")
    finally:
        mod._ColumnPickerDialog = orig_col
        mod._DaysAgoPickerDialog = orig_n

    assert dlg._preview_edit.toPlainText() == "VALUE_DAYS_AGO([High], 2)"


def test_on_date_picker_inserts_full_call_text(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QDialog
    from datetime import date

    dlg = ExpressionEditorDialog([], ["High"], [], {"High": 100.0})

    class _FakeColDlg:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def selected_column(self): return "High"

    class _FakeDateDlg:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Accepted
        def selected_date(self): return date(2026, 7, 15)

    import screens.formula_editor as mod
    orig_col, orig_date = mod._ColumnPickerDialog, mod._OnDatePickerDialog
    mod._ColumnPickerDialog = _FakeColDlg
    mod._OnDatePickerDialog = _FakeDateDlg
    try:
        dlg._open_point_lookup_picker("VALUE_ON_DATE", "on_date")
    finally:
        mod._ColumnPickerDialog = orig_col
        mod._OnDatePickerDialog = orig_date

    assert dlg._preview_edit.toPlainText() == "VALUE_ON_DATE([High], 2026-07-15)"


def test_point_lookup_picker_no_columns_shows_message_and_inserts_nothing(qapp, monkeypatch):
    from screens.formula_editor import ExpressionEditorDialog
    import screens.formula_editor as mod

    dlg = ExpressionEditorDialog([], [], [], {})
    monkeypatch.setattr(mod.QMessageBox, "information", lambda *a, **k: None)
    dlg._open_point_lookup_picker("VALUE_DAYS_AGO", "days_ago")
    assert dlg._preview_edit.toPlainText() == ""


def test_point_lookup_picker_cancelled_column_step_inserts_nothing(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    from PySide6.QtWidgets import QDialog

    dlg = ExpressionEditorDialog([], ["High"], [], {"High": 100.0})

    class _FakeColDlg:
        def __init__(self, *a, **k): pass
        def exec(self): return QDialog.DialogCode.Rejected

    import screens.formula_editor as mod
    orig_col = mod._ColumnPickerDialog
    mod._ColumnPickerDialog = _FakeColDlg
    try:
        dlg._open_point_lookup_picker("VALUE_DAYS_AGO", "days_ago")
    finally:
        mod._ColumnPickerDialog = orig_col

    assert dlg._preview_edit.toPlainText() == ""


def test_row_catalogue_lists_distinct_scrip_names(qapp):
    from screens.formula_editor import ExpressionEditorDialog
    all_data = [{"Scrip Name": "NIFTY", "Open": 100}, {"Scrip Name": "NIFTY", "Open": 100},
                {"Scrip Name": "BANKNIFTY", "Open": 200}]
    dlg = ExpressionEditorDialog([], ["Open"], [], {}, all_lmv_data=all_data)
    dlg._nav_list.setCurrentRow(4)  # Rows
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
    dlg._nav_list.setCurrentRow(6)  # Variables
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
