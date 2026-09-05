"""Inception > Strategy Builder — same visual layout and category/card
sidebar as today's LMV Strategy Builder (screens.strategy_builder), reusing
its generic (non-LMV-specific) building blocks directly: StrategyCard,
_CategorySection, _AddCategoryDialog, _tokens_to_display, _btn/_sep/
_apply_dialog_bg/_svg_icon. Formula editing reuses the actual Expression
Editor (screens.formula_editor.ExpressionEditorDialog/VariablesManagerDialog)
— the same searchable Functions/Historic Value/Operators/Fields/Rows/
Constants/Variables catalogue LMV's Strategy Builder uses — via four
small, backward-compatible additions to those classes (`sections`/
`variable_store`/`historic_value_catalogue`/`row_symbol_col` params, all
defaulting to prior LMV behavior; see that module for the full rationale):
`sections` includes "Rows" (cross-instrument "[Field] of Symbol"
references — resolved generically by services.strategy_engine, same
engine LMV uses, once `row_symbol_col`/`symbol_col` is set to "Symbol"
instead of LMV's "Scrip Name", see INCEPTION_ROW_SYMBOL_COL below);
`historic_value_catalogue` narrows THAT section to
INCEPTION_HISTORIC_VALUE_CATALOGUE below — VALUE_DAYS_AGO/VALUE_ON_DATE/
VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES
(services.inception_day_history resolves all six for raw OHLCV fields,
same as the "Functions" section's own AVG_DAYS/etc — the _AT_ four
additionally need their DRIVER column to be raw too) plus Inception-only
VALUE_BEFORE_CHANGE (services.inception_value_before_change — "the value
this column had before its current value last changed") and its sibling
VALUE_BEFORE_CHANGE_N ("the n-th such value back", n=1 being the same as
VALUE_BEFORE_CHANGE's own auto form); `variable_store` points the
Variables tab/"Save as Variable" at
services.inception_formula_variable_store instead of LMV's.

Backed by its own store (services.inception_strategy_store) and its own
category list — kept fully separate from LMV's, per the Inception feature's
design. Deliberately excludes the Notifications section LMV's editor has
(per project decision: Inception has no live price ticking, so there's no
signal source for it yet).

Every strategy here is evaluated entirely on THIS client, exactly like LMV's
own Strategy Builder — the backend (`/inception/strategies`) is
storage/sync only, never computation. See screens.inception_view_by_date/
screens.inception_hmv for where active strategies actually get applied to
displayed rows (services.strategy_engine.apply_strategies, the same local
engine LMV's live/historical views use), and this module's own
"Test Formula" (ExpressionEditorDialog's built-in Compile & Test, via
services.strategy_engine.compile_check — also local) for validating a
formula against a real row of Inception data when one's available.

── Real sample data ─────────────────────────────────────────────────────────
Unlike LMV's Strategy Builder (screens.strategy_builder), which gets real
sheet rows pushed in from DataImportScreen the moment a file loads
(set_lmv_data), Inception's has nothing pushing data in — so this screen
kicks off its OWN background load (_start_sample_load, same
_SnapshotLoadWorker screens.inception_view_by_date's View action uses, as of
whatever this device's most recently synced trading day is), with a
progress bar + "Inception data is loading…" message while it runs. Once it
lands, every field the offered *fields* list a real per-instrument row
(self._sample_rows) is threaded down into every ExpressionEditorDialog/
VariablesManagerDialog this screen opens (see _open_expression_editor),
so "Test Formula"/field previews reflect real values instead of every field
reading 1.0. Falls back to the old all-1.0 dummy row when nothing's synced
locally yet (_dummy_row) — same "blank/placeholder rather than crash"
convention used everywhere else in Inception.

Triggered from showEvent (guarded to run once), not __init__ — every screen
is constructed once at app startup (app_window._register_screens) whether
or not the user ever opens it, long before it's actually shown; spawning a
real background QThread that early/eagerly would be wasted work for a
screen nobody's visited yet, and (worse, the reason this specifically isn't
a bare QTimer.singleShot(0, ...) in __init__ the way the cheap, threadless
_reload_all is) a bound-method singleShot keeps its receiver alive only
until it fires — construct-many/never-show-them-all patterns (exactly what
a test suite does) can end up firing it against an otherwise-abandoned
screen and starting an unmonitored QThread with nothing left holding a
reference to it once that single call returns, which Qt aborts hard on if
the thread is still running when it's garbage-collected. showEvent only
fires when something actually calls .show() on this widget (or shows an
ancestor it's inside), which normal navigation does but construction alone
never does — sidestepping that failure mode entirely.
"""

import copy
import font_scale

from PySide6.QtCore import Qt, QSize, QTimer, Signal
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit, QFrame, QScrollArea,
    QDialog, QComboBox, QColorDialog, QMessageBox, QPushButton, QProgressBar,
)

from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from services import formula_engine, inception_bars_store, inception_columns
from services import inception_strategy_store as store
from services import inception_formula_variable_store as var_store
from screens.strategy_builder import (
    StrategyCard, _CategorySection, _AddCategoryDialog,
    _ADD_CATEGORY_SENTINEL, _tokens_to_display, _btn, _sep, _apply_dialog_bg,
    _svg_icon, _t, _pick_compile_test_row,
)
from screens.formula_editor import (
    ExpressionEditorDialog, VariablesManagerDialog, POINT_LOOKUP_CATALOGUE,
)

# Rows (cross-instrument "[Field] of Symbol") — the shared engine
# (services.strategy_engine) already resolves this generically once
# symbol_col is threaded through (which it now is everywhere: evaluate_
# compiled/_tokens_to_expr/compile_check, plus apply_strategies' own
# symbol_col="Symbol" already used by inception_hmv.py/inception_view_
# by_date.py — see that module's own docstring). Was previously left out
# of this nav on the (by-then-stale) belief that Inception had no
# cross-row support at all — see issue #16: it was really just this
# nav list + ROW_CATALOGUE_FROM_DATA's own symbol_col never being passed
# "Symbol" here. Historic Value is scoped down to
# INCEPTION_HISTORIC_VALUE_CATALOGUE below rather than the LMV-only full
# POINT_LOOKUP_CATALOGUE.
INCEPTION_SECTIONS = ["Functions", "Historic Value", "Operators", "Fields", "Rows", "Constants", "Variables"]

# ROW_CATALOGUE_FROM_DATA's/compile_check's row-identity column — Inception
# rows carry "Symbol" (e.g. "RELIANCE_I"), never LMV's "Scrip Name". Must
# match apply_strategies' own symbol_col="Symbol" (inception_hmv.py/
# inception_view_by_date.py) or a "[Field of Symbol]" formula would
# compile-test fine here yet always evaluate to None in the real HMV/View
# by Date render.
INCEPTION_ROW_SYMBOL_COL = "Symbol"

# Point-lookup functions Inception's own day_history actually resolves —
# see services.inception_day_history's module docstring: all six work for
# raw OHLCV fields (OPEN/HIGH/LOW/CLOSE/VOL/OPENINT) only, same "blank on
# an unresolvable column" convention Functions' own AVG_DAYS/MAX_DAYS/etc
# already carry for Inception, so surfacing them here is not a new risk.
# VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES
# additionally require the DRIVER column to also be a raw field (services.
# inception_day_history.raw_extreme_specs/build_extreme) — a call mixing a
# raw value column with a Group A/B or Formula Builder driver (or vice
# versa) evaluates to None the same way, not an error.
_INCEPTION_POINT_LOOKUPS = {
    "VALUE_DAYS_AGO", "VALUE_ON_DATE",
    "VALUE_AT_MAX_DAYS", "VALUE_AT_MIN_DAYS",
    "VALUE_AT_MAX_DATES", "VALUE_AT_MIN_DATES",
}

# VALUE_BEFORE_CHANGE — Inception-only (services.strategy_engine has no
# engine support for it at all outside Inception's own services.
# inception_value_before_change, see VALUE_BEFORE_CHANGE_TAG's own
# docstring), so it's built here rather than added to screens.formula_editor.
# POINT_LOOKUP_CATALOGUE itself, which every LMV caller also draws from —
# offering it there would let an LMV user insert something that always
# silently evaluates to None. needs_point_picker="months_back" gets it the
# same column-then-N two-step insertion flow VALUE_DAYS_AGO gets, rather
# than the plain "insert bare function name" flow a Functions-section entry
# would have used.
_VALUE_BEFORE_CHANGE_ENTRY = {
    "name": "VALUE_BEFORE_CHANGE",
    "signature": "VALUE_BEFORE_CHANGE(column[, months_back])",
    "description": (
        "This stock's own column value immediately before its CURRENT "
        "value last changed. months_back is OPTIONAL — leave it out (in "
        "the picker, check the \"Just find the previous changed value\" "
        "box) for a field that changes on no fixed schedule (weekly, "
        "irregularly, ...): it then walks back "
        "day by day, up to about a year, and returns the first day whose "
        "value actually differs from today's — e.g. WT changed last "
        "Tuesday: VALUE_BEFORE_CHANGE([WT]) finds that day's value "
        "directly, no need to know or name the interval. Give months_back "
        "instead only if you specifically want a calendar-month-boundary "
        "walk (checks each prior month-end, not every day) — e.g. MT "
        "reads 400 for both August and July but was 382 in June: "
        "VALUE_BEFORE_CHANGE([MT], 6) -> 382. Either form returns None if "
        "nothing differs within range, or there isn't that much synced "
        "history yet. Works for both Group A/B columns (52WH, ATH, ...) "
        "and Formula Builder columns (MT, MB, DT, DB, ...)."
    ),
    "token": {"type": "func", "value": "VALUE_BEFORE_CHANGE(", "needs_point_picker": "months_back"},
}

# VALUE_BEFORE_CHANGE_N — a separate function from VALUE_BEFORE_CHANGE
# above (not a third argument bolted onto it; see services.strategy_engine.
# VALUE_BEFORE_CHANGE_N_TAG's own docstring for why that would be
# ambiguous in typed text). needs_point_picker="changes_ago" gets it the
# same column-then-N two-step flow, via _ChangesAgoPickerDialog instead of
# _MonthsBackPickerDialog.
_VALUE_BEFORE_CHANGE_N_ENTRY = {
    "name": "VALUE_BEFORE_CHANGE_N",
    "signature": "VALUE_BEFORE_CHANGE_N(column, n)",
    "description": (
        "The n-th distinct value this column has had, walking backward — "
        "not just the value right before today's changed (that's what "
        "VALUE_BEFORE_CHANGE([col]) already gives you), but further back "
        "through EARLIER changes too. n=1 is the same as VALUE_BEFORE_"
        "CHANGE([col])'s auto form; n=2 is the value from the change "
        "before that one; n=3 before that; and so on — e.g. if WT read 10 "
        "this week, 8 last week, and 5 the week before: VALUE_BEFORE_"
        "CHANGE_N([WT], 1) -> 8, VALUE_BEFORE_CHANGE_N([WT], 2) -> 5. "
        "Always searches day by day (not month-ends), up to about a year "
        "back in total regardless of n — returns None if that many "
        "distinct changes don't exist within range, or there isn't that "
        "much synced history yet. Works for both Group A/B columns (52WH, "
        "ATH, ...) and Formula Builder columns (MT, MB, DT, DB, ...)."
    ),
    "token": {"type": "func", "value": "VALUE_BEFORE_CHANGE_N(", "needs_point_picker": "changes_ago"},
}

INCEPTION_HISTORIC_VALUE_CATALOGUE = [
    e for e in POINT_LOOKUP_CATALOGUE if e["name"] in _INCEPTION_POINT_LOOKUPS
] + [_VALUE_BEFORE_CHANGE_ENTRY, _VALUE_BEFORE_CHANGE_N_ENTRY]


def _dummy_row(fields: list) -> dict:
    return {f: 1.0 for f in fields}


def _open_expression_editor(tokens: list, fields: list, theme, mode: str,
                             self_value=None, parent=None, sample_rows: list = None,
                             extra_row_values: dict = None) -> list | None:
    """Opens the real Expression Editor scoped to Inception's fields/store —
    returns the resulting token list, or None if the user cancelled.

    *sample_rows*, when given (a non-empty list of {field: value} dicts —
    see this module's "Real sample data" docstring section), is used both as
    the Compile & Test row and as the aggregate-function data set instead of
    the all-1.0 dummy row.

    *extra_row_values* ({sibling_column_name: computed_value}, from
    _InceptionStrategyEditor._extra_column_values) is forwarded to
    ExpressionEditorDialog so Compile & Test can actually resolve a formula
    that references one of this strategy's OTHER columns by name — e.g.
    "Trigger Price" = [FP_10D] * 1.01, [FP_10D] itself defined as a
    separate column — instead of reporting it as an empty cell. LMV's own
    Strategy Builder already does this (screens.strategy_builder.
    StrategyEditor._combined_headers_and_values); this was the one call
    site here that never got it wired up, even though _field_names()
    already offers sibling columns in the Fields list, so the formula
    looked buildable but could never actually compile-test.
    """
    if sample_rows:
        row = _pick_compile_test_row(sample_rows)
        all_data = sample_rows
    else:
        row = _dummy_row(fields)
        all_data = [row]
    dlg = ExpressionEditorDialog(
        tokens, fields, [], row, all_lmv_data=all_data, theme=theme, mode=mode,
        self_value=self_value, extra_row_values=extra_row_values, real_lmv_headers=fields,
        sections=INCEPTION_SECTIONS, variable_store=var_store,
        historic_value_catalogue=INCEPTION_HISTORIC_VALUE_CATALOGUE,
        row_symbol_col=INCEPTION_ROW_SYMBOL_COL, parent=parent,
    )
    if dlg.exec() == QDialog.DialogCode.Accepted:
        return dlg.get_tokens()
    return None


# ── column editor dialog (name + formula + conditional formatting) ──────────

class _InceptionColumnEditorDialog(QDialog):
    def __init__(self, col_def: dict, fields: list, theme=None, parent=None, sample_rows: list = None,
                 extra_row_values: dict = None):
        super().__init__(parent)
        self._col = copy.deepcopy(col_def)
        self._col.setdefault("fmt_rules", [])
        self._fields = fields
        self._theme = theme
        # {sibling_column_name: computed_value} — forwarded to every
        # ExpressionEditorDialog this dialog opens (Value formula AND
        # fmt-rule conditions) so Compile & Test can resolve a formula
        # referencing another of this strategy's columns. See
        # _open_expression_editor's own docstring.
        self._extra_row_values = dict(extra_row_values or {})
        self._sample_rows = sample_rows
        self.setWindowTitle("Edit Column")
        self.resize(680, 600)
        _apply_dialog_bg(self, theme)
        self._build()

    def _build(self):
        t = self._theme
        txts = _t(t, "text_secondary")
        root = QVBoxLayout(self)
        root.setSpacing(14)
        root.setContentsMargins(20, 20, 20, 20)

        name_row = QHBoxLayout()
        lbl = QLabel("Column name:")
        lbl.setFixedWidth(120)
        self._name_edit = QLineEdit(self._col.get("name", ""))
        self._name_edit.setFixedHeight(34)
        self._name_edit.textChanged.connect(lambda v: self._col.update({"name": v}))
        name_row.addWidget(lbl)
        name_row.addWidget(self._name_edit)
        root.addLayout(name_row)

        root.addWidget(_sep(t))

        formula_row = QHBoxLayout()
        flbl = QLabel("Formula (value):")
        flbl.setFont(font_scale.font(font_scale.SMALL, True))
        flbl.setFixedWidth(130)
        self._formula_preview = QLabel(_tokens_to_display(self._col.get("formula", [])) or "—")
        self._formula_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._formula_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;border:none;")
        self._formula_preview.setWordWrap(True)
        edit_formula_btn = _btn("Edit Formula…", outlined=True, theme=t, small=True)
        edit_formula_btn.clicked.connect(self._open_formula_editor)
        formula_row.addWidget(flbl)
        formula_row.addWidget(self._formula_preview, 1)
        formula_row.addWidget(edit_formula_btn)
        root.addLayout(formula_row)

        root.addWidget(_sep(t))

        fmt_hdr = QHBoxLayout()
        fmt_lbl = QLabel("Conditional Formatting:")
        fmt_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        add_rule = _btn("+ Add Rule", theme=t, small=True)
        add_rule.clicked.connect(self._add_fmt_rule)
        fmt_hdr.addWidget(fmt_lbl)
        fmt_hdr.addStretch()
        fmt_hdr.addWidget(add_rule)
        root.addLayout(fmt_hdr)

        hint = QLabel(
            "Rules are checked top to bottom — the first one whose condition is "
            "true wins. Applied in both HMV and View by Date; \"Apply color to\" "
            "picks which column gets painted — defaults to this column."
        )
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color:{txts};background:transparent;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._fmt_scroll = QScrollArea()
        self._fmt_scroll.setWidgetResizable(True)
        self._fmt_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._fmt_scroll.setMinimumHeight(100)
        self._fmt_inner = QWidget()
        self._fmt_inner.setStyleSheet("background:transparent;")
        self._fmt_layout = QVBoxLayout(self._fmt_inner)
        self._fmt_layout.setSpacing(8)
        self._fmt_layout.setContentsMargins(0, 0, 0, 0)
        self._fmt_layout.addStretch()
        self._fmt_scroll.setWidget(self._fmt_inner)
        root.addWidget(self._fmt_scroll, 1)
        self._refresh_fmt_rules()

        btn_row = QHBoxLayout()
        ok = _btn("Save Column", accent=True, theme=t)
        can = _btn("Cancel", theme=t)
        ok.clicked.connect(self.accept)
        can.clicked.connect(self.reject)
        btn_row.addStretch()
        btn_row.addWidget(can)
        btn_row.addWidget(ok)
        root.addLayout(btn_row)

    def _open_formula_editor(self):
        tokens = _open_expression_editor(
            list(self._col.get("formula", [])), self._fields, self._theme, "value", parent=self,
            sample_rows=self._sample_rows, extra_row_values=self._extra_row_values,
        )
        if tokens is not None:
            self._col["formula"] = tokens
            self._formula_preview.setText(_tokens_to_display(self._col["formula"]) or "—")

    def _add_fmt_rule(self):
        self._col["fmt_rules"].append(store.new_fmt_rule())
        self._refresh_fmt_rules()

    def _remove_fmt_rule(self, idx: int):
        del self._col["fmt_rules"][idx]
        self._refresh_fmt_rules()

    def _move_fmt_rule(self, idx: int, delta: int):
        rules = self._col["fmt_rules"]
        new_idx = idx + delta
        if not (0 <= new_idx < len(rules)):
            return
        rules[idx], rules[new_idx] = rules[new_idx], rules[idx]
        self._refresh_fmt_rules()

    def _refresh_fmt_rules(self):
        t = self._theme
        bg = _t(t, "button_bg")
        bd = _t(t, "border")

        while self._fmt_layout.count() > 1:
            item = self._fmt_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        rules = self._col.get("fmt_rules", [])
        for idx, rule in enumerate(rules):
            rule_frame = QFrame()
            # objectName-scoped (not a bare "QFrame{...}" type selector) —
            # QLabel IS a QFrame subclass, so a bare-type selector here would
            # leak this border onto every label nested inside the frame.
            rule_frame.setObjectName("inceptionFmtRuleFrame")
            rule_frame.setStyleSheet(
                f"QFrame#inceptionFmtRuleFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"
            )
            rlay = QVBoxLayout(rule_frame)
            rlay.setSpacing(6)
            rlay.setContentsMargins(10, 8, 10, 8)

            hdr = QHBoxLayout()
            lbl = QLabel(f"Rule {idx + 1}")
            lbl.setFont(font_scale.font(font_scale.SMALL, True))
            lbl.setStyleSheet("background:transparent;")
            hdr.addWidget(lbl)
            hdr.addStretch()

            color_btn = _colorbutton(rule["color"])
            color_btn.clicked.connect(lambda _, i=idx, cb=color_btn: self._pick_color(i, cb))

            up_btn = _btn("", theme=t, small=True)
            up_btn.setIcon(_svg_icon("up.svg", _t(t, "text_primary")))
            up_btn.setIconSize(QSize(12, 12))
            up_btn.setFixedWidth(28)
            up_btn.setEnabled(idx > 0)
            up_btn.clicked.connect(lambda _, i=idx: self._move_fmt_rule(i, -1))

            down_btn = _btn("", theme=t, small=True)
            down_btn.setIcon(_svg_icon("down.svg", _t(t, "text_primary")))
            down_btn.setIconSize(QSize(12, 12))
            down_btn.setFixedWidth(28)
            down_btn.setEnabled(idx < len(rules) - 1)
            down_btn.clicked.connect(lambda _, i=idx: self._move_fmt_rule(i, 1))

            del_btn = _btn("✕", theme=t, small=True, danger=True)
            del_btn.setFixedWidth(30)
            del_btn.clicked.connect(lambda _, i=idx: self._remove_fmt_rule(i))

            hdr.addWidget(QLabel("Color:"))
            hdr.addWidget(color_btn)
            hdr.addSpacing(8)
            hdr.addWidget(up_btn)
            hdr.addWidget(down_btn)
            hdr.addSpacing(8)
            hdr.addWidget(del_btn)
            rlay.addLayout(hdr)

            target_row = QHBoxLayout()
            target_lbl = QLabel("Apply color to:")
            target_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            target_lbl.setStyleSheet("background:transparent;")
            target_lbl.setMinimumWidth(110)
            target_combo = QComboBox()
            current_target = rule.get("target_column")
            target_options = ["(This column)"] + list(self._fields)
            if current_target and current_target not in target_options:
                target_options.append(current_target)
            target_combo.addItems(target_options)
            target_combo.setCurrentText(current_target or "(This column)")
            target_combo.currentTextChanged.connect(lambda text, i=idx: self._set_fmt_target(i, text))
            target_row.addWidget(target_lbl)
            target_row.addWidget(target_combo, 1)
            rlay.addLayout(target_row)

            cond_row = QHBoxLayout()
            cond_lbl = QLabel("Condition:")
            cond_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            cond_lbl.setStyleSheet("background:transparent;")
            cond_lbl.setMinimumWidth(110)
            cond_preview = QLabel(_tokens_to_display(rule.get("condition", [])) or "—")
            cond_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            cond_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;border:none;")
            cond_preview.setWordWrap(True)
            edit_cond_btn = _btn("Edit Condition…", outlined=True, theme=t, small=True)
            edit_cond_btn.clicked.connect(lambda _, i=idx, lbl=cond_preview: self._open_condition_editor(i, lbl))
            cond_row.addWidget(cond_lbl)
            cond_row.addWidget(cond_preview, 1)
            cond_row.addWidget(edit_cond_btn)
            rlay.addLayout(cond_row)

            self._fmt_layout.insertWidget(self._fmt_layout.count() - 1, rule_frame)

    def _open_condition_editor(self, idx: int, preview_label: QLabel):
        rule = self._col["fmt_rules"][idx]
        # THIS (own value) refers to this column's own computed value — 1.0,
        # same dummy-float convention as every other field in local
        # compile-testing here (see module docstring).
        tokens = _open_expression_editor(
            list(rule.get("condition", [])), self._fields, self._theme, "condition",
            self_value=1.0, parent=self, sample_rows=self._sample_rows,
            extra_row_values=self._extra_row_values,
        )
        if tokens is not None:
            rule["condition"] = tokens
            preview_label.setText(_tokens_to_display(rule["condition"]) or "—")

    def _set_fmt_target(self, idx: int, text: str):
        self._col["fmt_rules"][idx]["target_column"] = None if text == "(This column)" else text

    def _pick_color(self, idx: int, btn):
        current = QColor(self._col["fmt_rules"][idx]["color"])
        color = QColorDialog.getColor(current, self, "Pick Rule Color")
        if color.isValid():
            hex_color = color.name()
            self._col["fmt_rules"][idx]["color"] = hex_color
            btn.setStyleSheet(f"background:{hex_color};border:1px solid #555;border-radius:4px;")

    def result_col(self) -> dict:
        return self._col


def _colorbutton(color: str):
    b = QPushButton()
    b.setFixedSize(28, 22)
    b.setStyleSheet(f"background:{color};border:1px solid #555;border-radius:4px;")
    b.setCursor(Qt.CursorShape.PointingHandCursor)
    return b

# ── strategy editor (right panel) ────────────────────────────────────────────

class _InceptionStrategyEditor(QWidget):
    saved = Signal(dict)

    def __init__(self, strategy: dict, fields: list, theme=None, parent=None, sample_rows: list = None):
        super().__init__(parent)
        self._strategy = copy.deepcopy(strategy)
        self._fields = fields
        self._theme = theme
        self._sample_rows = sample_rows
        self._last_valid_category = self._strategy.get("category", "Daily")
        self._build()

    def _field_names(self) -> list:
        # This strategy's own columns are offered too, same as LMV's
        # _combined_headers_and_values — a later column can reference an
        # earlier one.
        own_cols = [c["name"] for c in self._strategy.get("columns", [])]
        return self._fields + [c for c in own_cols if c not in self._fields]

    def _extra_column_values(self, exclude_idx: int | None = None) -> dict:
        """{sibling_column_name: computed_value} on the compile-test row,
        for every column in this strategy OTHER than exclude_idx — the
        Inception analogue of LMV's screens.strategy_builder.StrategyEditor.
        _combined_headers_and_values (see _open_expression_editor's own
        docstring for why this exists: _field_names() above already offers
        sibling columns to reference, but without this their compile-test
        value was always missing, reported as an empty cell no matter how
        correct the formula actually was).

        Uses the exact same test-row/all-data resolution _open_expression_
        editor itself falls back to (the real "sample_rows" when a sheet's
        loaded, else the all-1.0 dummy row) so a sibling column's compile-
        test value here matches what its OWN Compile & Test would have
        shown."""
        from services.strategy_engine import evaluate
        cols = [c for i, c in enumerate(self._strategy.get("columns", [])) if i != exclude_idx]
        if self._sample_rows:
            row = _pick_compile_test_row(self._sample_rows)
            all_data = self._sample_rows
        else:
            row = _dummy_row(self._fields)
            all_data = [row]
        return {c["name"]: evaluate(c.get("formula", []), row, all_data) for c in cols}

    def _build(self):
        t = self._theme
        txts = _t(t, "text_secondary")

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        editor_scroll = QScrollArea()
        editor_scroll.setWidgetResizable(True)
        editor_scroll.setFrameShape(QFrame.Shape.NoFrame)
        editor_inner = QWidget()
        editor_inner.setStyleSheet("background:transparent;")
        root = QVBoxLayout(editor_inner)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(14)

        name_row = QHBoxLayout()
        lbl = QLabel("Strategy Name:")
        lbl.setFixedWidth(130)
        self._name_edit = QLineEdit(self._strategy.get("name", ""))
        self._name_edit.setFixedHeight(36)
        self._name_edit.setFont(font_scale.font(font_scale.MEDIUM, False))
        name_row.addWidget(lbl)
        name_row.addWidget(self._name_edit)
        root.addLayout(name_row)

        cat_row = QHBoxLayout()
        cat_lbl = QLabel("Category:")
        cat_lbl.setFixedWidth(130)
        self._category_combo = QComboBox()
        self._category_combo.setFixedHeight(36)
        self._refresh_category_items()
        self._category_combo.activated.connect(self._on_category_activated)
        cat_row.addWidget(cat_lbl)
        cat_row.addWidget(self._category_combo)
        root.addLayout(cat_row)

        root.addWidget(_sep(t))

        filter_hdr = QHBoxLayout()
        filter_title = QLabel("Row Filter")
        filter_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        filter_info = QLabel("(leave blank to include all rows)")
        filter_info.setFont(font_scale.font(font_scale.SMALL, False))
        filter_info.setStyleSheet(f"color:{txts};")
        filter_edit_btn = _btn("Edit Filter…", outlined=True, theme=t, small=True)
        filter_edit_btn.clicked.connect(self._open_filter_editor)
        filter_hdr.addWidget(filter_title)
        filter_hdr.addSpacing(8)
        filter_hdr.addWidget(filter_info)
        filter_hdr.addStretch()
        filter_hdr.addWidget(filter_edit_btn)
        root.addLayout(filter_hdr)

        self._filter_preview = QLabel(_tokens_to_display(self._strategy.get("row_filter", [])))
        self._filter_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
        self._filter_preview.setStyleSheet(f"color:{_t(t,'accent')};background:transparent;border:none;padding:2px 4px;")
        self._filter_preview.setWordWrap(True)
        root.addWidget(self._filter_preview)

        root.addWidget(_sep(t))

        col_hdr = QHBoxLayout()
        col_title = QLabel("Columns")
        col_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        add_col = _btn("+ Add Column", outlined=True, theme=t, small=True)
        add_col.clicked.connect(self._add_column)
        col_hdr.addWidget(col_title)
        col_hdr.addStretch()
        col_hdr.addWidget(add_col)
        root.addLayout(col_hdr)

        self._col_inner = QWidget()
        self._col_inner.setStyleSheet("background:transparent;")
        self._col_layout = QVBoxLayout(self._col_inner)
        self._col_layout.setSpacing(8)
        self._col_layout.setContentsMargins(0, 0, 0, 0)
        self._col_layout.addStretch()
        root.addWidget(self._col_inner)
        root.addStretch()

        editor_scroll.setWidget(editor_inner)
        outer.addWidget(editor_scroll, 1)

        footer = QFrame()
        footer.setStyleSheet(f"QFrame {{ background: {_t(t, 'card_bg')}; border-top: 1px solid {_t(t, 'border')}; }}")
        footer_lay = QHBoxLayout(footer)
        footer_lay.setContentsMargins(20, 10, 20, 10)
        footer_lay.addStretch()
        save_btn = _btn("Save Strategy", accent=True, theme=t)
        save_btn.clicked.connect(self._save)
        footer_lay.addWidget(save_btn)
        outer.addWidget(footer)

        self._refresh_columns()

    def _add_column(self):
        col = store.new_column(f"Col{len(self._strategy['columns']) + 1}")
        # Not excluding anything here (unlike _edit_column) — the new
        # column isn't in self._strategy["columns"] yet, so every existing
        # column is a valid sibling to reference.
        dlg = _InceptionColumnEditorDialog(col, self._field_names(), self._theme, parent=self,
                                            sample_rows=self._sample_rows,
                                            extra_row_values=self._extra_column_values())
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["columns"].append(dlg.result_col())
            self._refresh_columns()

    def _edit_column(self, idx: int):
        col = self._strategy["columns"][idx]
        # This column can't reference its own formula.
        fields = [f for f in self._field_names() if f != col.get("name")]
        dlg = _InceptionColumnEditorDialog(col, fields, self._theme, parent=self,
                                            sample_rows=self._sample_rows,
                                            extra_row_values=self._extra_column_values(exclude_idx=idx))
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._strategy["columns"][idx] = dlg.result_col()
            self._refresh_columns()

    def _clone_column(self, idx: int):
        original = self._strategy["columns"][idx]
        cloned = copy.deepcopy(original)
        cloned["name"] = original["name"] + " (Copy)"
        self._strategy["columns"].insert(idx + 1, cloned)
        self._refresh_columns()

    def _delete_column(self, idx: int):
        del self._strategy["columns"][idx]
        self._refresh_columns()

    def _refresh_columns(self):
        t = self._theme
        bd = _t(t, "border")
        bg = _t(t, "button_bg")
        txt = _t(t, "text_primary")
        txts = _t(t, "text_secondary")
        a = _t(t, "accent")

        while self._col_layout.count() > 1:
            item = self._col_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for idx, col in enumerate(self._strategy.get("columns", [])):
            row_frame = QFrame()
            row_frame.setObjectName("inceptionColumnRowFrame")
            row_frame.setStyleSheet(
                f"QFrame#inceptionColumnRowFrame{{background:{bg};border:1px solid {bd};border-radius:6px;}}"
            )
            row_lay = QVBoxLayout(row_frame)
            row_lay.setContentsMargins(12, 8, 12, 8)
            row_lay.setSpacing(4)

            top_row = QHBoxLayout()
            name_lbl = QLabel(col.get("name", f"Col{idx+1}"))
            name_lbl.setFont(font_scale.font(font_scale.SMALL, True))
            name_lbl.setStyleSheet(f"color:{txt};background:transparent;")

            nrules = len(col.get("fmt_rules", []))
            rule_lbl = QLabel(f"{nrules} format rule{'s' if nrules != 1 else ''}")
            rule_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            rule_lbl.setStyleSheet(f"color:{txts};background:transparent;")

            edit_b = _btn("Edit", theme=t, small=True)
            clone_b = _btn("Clone", theme=t, small=True, outlined=True)
            del_b = _btn("✕", theme=t, small=True, danger=True)
            edit_b.setFixedWidth(50)
            clone_b.setFixedWidth(64)
            del_b.setFixedWidth(30)
            edit_b.clicked.connect(lambda _, i=idx: self._edit_column(i))
            clone_b.clicked.connect(lambda _, i=idx: self._clone_column(i))
            del_b.clicked.connect(lambda _, i=idx: self._delete_column(i))

            top_row.addWidget(name_lbl)
            top_row.addSpacing(10)
            top_row.addWidget(rule_lbl)
            top_row.addStretch()
            top_row.addWidget(edit_b)
            top_row.addSpacing(4)
            top_row.addWidget(clone_b)
            top_row.addSpacing(4)
            top_row.addWidget(del_b)
            row_lay.addLayout(top_row)

            formula_preview = QLabel(_tokens_to_display(col.get("formula", [])))
            formula_preview.setFont(QFont("Menlo,Consolas,monospace", 9))
            formula_preview.setStyleSheet(f"color:{a};background:transparent;border:none;padding:2px 4px;")
            formula_preview.setWordWrap(True)
            row_lay.addWidget(formula_preview)

            self._col_layout.insertWidget(self._col_layout.count() - 1, row_frame)

    def _open_filter_editor(self):
        tokens = _open_expression_editor(
            list(self._strategy.get("row_filter", [])), self._field_names(), self._theme,
            "condition", parent=self, sample_rows=self._sample_rows,
            extra_row_values=self._extra_column_values(),
        )
        if tokens is not None:
            self._strategy["row_filter"] = tokens
            self._filter_preview.setText(_tokens_to_display(self._strategy["row_filter"]))

    def _refresh_category_items(self, select: str | None = None):
        target = select if select is not None else self._last_valid_category
        self._category_combo.blockSignals(True)
        self._category_combo.clear()
        categories = store.all_categories()
        self._category_combo.addItems(categories)
        self._category_combo.addItem(_ADD_CATEGORY_SENTINEL)
        if target in categories:
            self._category_combo.setCurrentText(target)
            self._last_valid_category = target
        self._category_combo.blockSignals(False)

    def _on_category_activated(self, index: int):
        if self._category_combo.itemText(index) != _ADD_CATEGORY_SENTINEL:
            self._last_valid_category = self._category_combo.itemText(index)
            return
        self._prompt_add_category()

    def _prompt_add_category(self):
        dlg = _AddCategoryDialog(self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            name = dlg.category_name()
            if name:
                canonical = store.add_custom_category(name)
                self._refresh_category_items(select=canonical)
                return
        self._refresh_category_items()

    def _save(self):
        self._strategy["name"] = self._name_edit.text().strip() or "Untitled"
        self._strategy["category"] = self._category_combo.currentText()
        self.saved.emit(copy.deepcopy(self._strategy))


# ── main screen ───────────────────────────────────────────────────────────────

class InceptionStrategyBuilderScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._theme = controller.theme
        self._strategies: list = []
        self._fields: list = []
        self._sample_rows: list = []
        self._sample_as_of = None
        self._sample_worker = None
        self._sample_load_started = False
        self._active_editor = None
        self._search_query = ""
        self._expanded_categories: set = set()
        self._build()
        QTimer.singleShot(0, self._reload_all)

    def showEvent(self, event):
        super().showEvent(event)
        # See this module's "Real sample data" docstring section for why
        # this is triggered here (once, guarded) rather than from __init__.
        if not self._sample_load_started:
            self._sample_load_started = True
            self._start_sample_load()

    def _build(self):
        t = self._theme
        bd = _t(t, "border")
        bg = _t(t, "background")
        card = _t(t, "card_bg")
        txts = _t(t, "text_secondary")

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        topbar = QFrame()
        topbar.setFixedHeight(56)
        topbar.setObjectName("inceptionTopbar")
        topbar.setStyleSheet(f"QFrame#inceptionTopbar{{background:{card};border-bottom:1px solid {bd};}}")
        top_lay = QHBoxLayout(topbar)
        top_lay.setContentsMargins(20, 0, 20, 0)

        title = QLabel("Inception — Strategy Builder")
        title.setFont(font_scale.font(font_scale.LARGE, True))

        vars_btn = _btn("Variables", theme=t)
        vars_btn.clicked.connect(self._open_variables_manager)

        new_btn = _btn("+ New Strategy", accent=True, theme=t)
        new_btn.clicked.connect(self._new_strategy)

        top_lay.addWidget(title)
        top_lay.addStretch()
        top_lay.addWidget(vars_btn)
        top_lay.addSpacing(8)
        top_lay.addWidget(new_btn)
        root.addWidget(topbar)

        sample_row = QFrame()
        sample_row.setObjectName("inceptionSampleRow")
        sample_row.setStyleSheet(f"QFrame#inceptionSampleRow{{background:{card};}}")
        sample_lay = QVBoxLayout(sample_row)
        sample_lay.setContentsMargins(20, 6, 20, 6)
        sample_lay.setSpacing(4)
        self._sample_status_lbl = QLabel("")
        self._sample_status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._sample_status_lbl.setStyleSheet(f"color:{txts};")
        sample_lay.addWidget(self._sample_status_lbl)
        self._sample_progress = QProgressBar()
        self._sample_progress.setFixedHeight(4)
        self._sample_progress.setTextVisible(False)
        self._sample_progress.setVisible(False)
        sample_lay.addWidget(self._sample_progress)
        root.addWidget(sample_row)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        left_frame = QFrame()
        left_frame.setFixedWidth(300)
        left_frame.setObjectName("inceptionLeftFrame")
        left_frame.setStyleSheet(f"QFrame#inceptionLeftFrame{{background:{card};border-right:1px solid {bd};}}")
        left_root = QVBoxLayout(left_frame)
        left_root.setContentsMargins(12, 12, 12, 12)
        left_root.setSpacing(8)

        list_title = QLabel("Strategies")
        list_title.setFont(font_scale.font(font_scale.MEDIUM, True))
        left_root.addWidget(list_title)

        self._search_box = QLineEdit()
        self._search_box.setPlaceholderText("Search strategies…")
        self._search_box.setFixedHeight(30)
        self._search_box.setFont(font_scale.font(font_scale.SMALL, False))
        self._search_box.setStyleSheet(
            f"QLineEdit{{background:{_t(t,'input_bg')};color:{_t(t,'text_primary')};"
            f"border:1px solid {_t(t,'border')};border-radius:6px;padding:0 8px;}}"
            f"QLineEdit:focus{{border-color:{_t(t,'accent')};}}"
        )
        self._search_box.textChanged.connect(self._on_search_changed)
        left_root.addWidget(self._search_box)

        self._list_scroll = QScrollArea()
        self._list_scroll.setWidgetResizable(True)
        self._list_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._list_inner = QWidget()
        self._list_inner.setStyleSheet("background:transparent;")
        self._list_layout = QVBoxLayout(self._list_inner)
        self._list_layout.setSpacing(8)
        self._list_layout.setContentsMargins(0, 0, 0, 0)
        self._list_layout.addStretch()
        self._list_scroll.setWidget(self._list_inner)
        left_root.addWidget(self._list_scroll, 1)
        body.addWidget(left_frame)

        right_frame = QFrame()
        right_frame.setObjectName("inceptionRightFrame")
        right_frame.setStyleSheet(f"QFrame#inceptionRightFrame{{background:{bg};}}")
        right_root = QVBoxLayout(right_frame)
        right_root.setContentsMargins(0, 0, 0, 0)

        self._placeholder = QLabel("← Select a strategy to edit, or create a new one")
        self._placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._placeholder.setStyleSheet(f"color:{txts};")
        right_root.addWidget(self._placeholder)

        self._editor_container = QWidget()
        self._editor_container.hide()
        editor_lay = QVBoxLayout(self._editor_container)
        editor_lay.setContentsMargins(0, 0, 0, 0)
        self._editor_slot = editor_lay
        right_root.addWidget(self._editor_container, 1)

        body.addWidget(right_frame, 1)
        root.addLayout(body, 1)

    # ── data loading ─────────────────────────────────────────────────────────

    def _reload_all(self):
        # Local now — Group A/B computation (and the field catalogue that
        # describes it) moved entirely to this client, see
        # services.inception_columns/inception_formula_engine. No network
        # call needed here any more.
        self._fields = [c.code for c in inception_columns.column_catalogue()]
        # Plus LMV's ~56 built-in Formula Builder codes (MT, MB, DT, DB,
        # PMH, the camarilla ladders, ...) — services.
        # inception_formula_builder_columns.compute_for_bars is what
        # actually produces these for a row (see screens.inception_hmv /
        # screens.inception_view_by_date, both of which merge them in
        # before a strategy ever sees the row), so they need to be
        # selectable here too or a formula could never reference them.
        # FORMULA_CODES specifically (not services.formula_tokens.
        # all_field_codes's superset) — compute_for_bars only ever computes
        # the built-ins, never a custom External Import formula, so only
        # those are guaranteed to actually resolve to a value here.
        self._fields += [c for c in formula_engine.FORMULA_CODES if c not in self._fields]
        # "Avg Rate" — Inception-only (see services.
        # inception_formula_builder_columns.compute_for_bars's own
        # _LMV_SYNCED_CODE_MAP comment): not one of formula_engine's own
        # FORMULA_CODES outputs, since it's a value Admin Controls >
        # Inception Sync copies onto the bar directly rather than
        # something formula_engine computes. Added here rather than to
        # formula_engine.FORMULA_CODES itself so this doesn't also affect
        # LMV's own (unrelated) Formula Builder field list.
        if "Avg Rate" not in self._fields:
            self._fields.append("Avg Rate")
        self._fields += [v["name"] for v in var_store.load_all()]
        self._strategies = store.load_all()
        self._refresh_list()

    # ── real sample data (background load) ──────────────────────────────────

    def _start_sample_load(self):
        """Kicks off a background snapshot load — see this module's "Real
        sample data" docstring section. No-ops (leaving formula testing on
        the all-1.0 dummy row) when nothing's synced to this device yet;
        there's nothing to load in that case, same message screens.
        inception_hmv/inception_view_by_date show."""
        t = self._theme
        as_of = inception_bars_store.last_synced_date()
        if as_of is None:
            self._sample_status_lbl.setText(
                "No Inception data synced to this device yet — formula testing will use "
                "placeholder values until you sync (Inception > Data & Settings)."
            )
            self._sample_status_lbl.setStyleSheet(f"color:{_t(t,'text_secondary')};")
            return

        self._sample_as_of = as_of
        self._sample_status_lbl.setText("Inception data is loading…")
        self._sample_status_lbl.setStyleSheet(f"color:{_t(t,'text_secondary')};")
        self._sample_progress.setRange(0, 0)   # busy/indeterminate until the first progress tick arrives
        self._sample_progress.setValue(0)
        self._sample_progress.setVisible(True)

        from screens.inception_view_by_date import _SnapshotLoadWorker
        self._sample_worker = _SnapshotLoadWorker(as_of, parent=self)
        self._sample_worker.progress.connect(self._on_sample_progress)
        self._sample_worker.succeeded.connect(self._on_sample_succeeded)
        self._sample_worker.failed.connect(self._on_sample_failed)
        self._sample_worker.start()

    def _on_sample_progress(self, done: int, total: int):
        self._sample_progress.setRange(0, total)
        self._sample_progress.setValue(done)
        self._sample_status_lbl.setText(f"Inception data is loading… {done}/{total} instruments")

    def _on_sample_succeeded(self, rows: list):
        t = self._theme
        self._sample_progress.setVisible(False)
        # INCEPTION_ROW_SYMBOL_COL ("Symbol") injected into each row's own
        # values dict, DISPLAY-form (via _display_symbol, e.g. "RELIANCE"
        # not "RELIANCE_I") — matches exactly what apply_strategies'
        # symbol_col="Symbol" resolves against in the real HMV/View by Date
        # render (screens.inception_hmv/inception_view_by_date build their
        # own "Symbol" column the same way), so a "[Field of Symbol]"
        # reference built/compile-tested here against a real sample row
        # actually matches a real row at render time. Without this, "Rows"
        # would offer no symbols at all (ROW_CATALOGUE_FROM_DATA finds no
        # "Symbol" key in a bare `values` dict) — see issue #16.
        from screens.inception_view_by_date import _display_symbol
        self._sample_rows = [
            dict(r["values"], **{INCEPTION_ROW_SYMBOL_COL: _display_symbol(r["symbol"])})
            for r in rows if r.get("values")
        ]
        if self._sample_rows:
            self._sample_status_lbl.setText(
                f"Testing formulas against real Inception data as of "
                f"{self._sample_as_of.isoformat()} ({len(self._sample_rows)} instruments)."
            )
            self._sample_status_lbl.setStyleSheet(f"color:{_t(t,'text_secondary')};")
        else:
            self._sample_status_lbl.setText(
                "No rows available yet to test formulas against — using placeholder values."
            )
            self._sample_status_lbl.setStyleSheet(f"color:{_t(t,'text_secondary')};")

    def _on_sample_failed(self, message: str):
        t = self._theme
        self._sample_progress.setVisible(False)
        self._sample_status_lbl.setText(f"Couldn't load Inception data ({message}) — using placeholder values.")
        self._sample_status_lbl.setStyleSheet(f"color:{_t(t,'status_red')};")

    # ── strategy list ────────────────────────────────────────────────────────

    def _on_search_changed(self, text: str):
        self._search_query = text
        self._refresh_list()

    def _on_section_toggled(self, category: str, expanded: bool):
        if expanded:
            self._expanded_categories.add(category)
        else:
            self._expanded_categories.discard(category)

    def _refresh_list(self):
        while self._list_layout.count() > 1:
            item = self._list_layout.takeAt(0)
            w = item.widget()
            if w:
                w.hide()
                w.deleteLater()

        query = self._search_query.strip().lower()
        filtered = (
            [s for s in self._strategies if query in s.get("name", "").lower()]
            if query else list(self._strategies)
        )

        by_category: dict = {}
        for strat in filtered:
            by_category.setdefault(strat.get("category", "Daily"), []).append(strat)

        ordered_categories = [c for c in store.all_categories() if c in by_category]
        ordered_categories += [c for c in by_category if c not in ordered_categories]

        if not filtered:
            msg = "No strategies yet.\nClick '+ New Strategy'." if not self._strategies else \
                  f"No strategies match “{self._search_query.strip()}”."
            empty = QLabel(msg)
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setStyleSheet(f"color:{_t(self._theme,'text_secondary')};")
            empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
            empty.setWordWrap(True)
            self._list_layout.insertWidget(0, empty)
            # Still show every category (all empty) so the taxonomy is visible
            # even with zero strategies — matches "categories can be empty now".
            for cat in store.all_categories():
                self._insert_category_section(cat, [])
            return

        for cat in ordered_categories:
            self._insert_category_section(cat, by_category[cat])
        for cat in store.all_categories():
            if cat not in by_category:
                self._insert_category_section(cat, [])

    def _insert_category_section(self, category: str, strategies: list):
        expanded = category in self._expanded_categories
        section = _CategorySection(category, len(strategies), self._theme, expanded, parent=self)
        section.toggled.connect(self._on_section_toggled)
        for strat in strategies:
            card = StrategyCard(strat, self._theme, parent=section)
            card.edit_requested.connect(self._open_editor)
            card.clone_requested.connect(self._on_clone)
            card.delete_requested.connect(self._on_delete)
            card.toggled.connect(self._on_toggle)
            section.add_card(card)
        self._list_layout.insertWidget(self._list_layout.count() - 1, section)

    def _new_strategy(self):
        new = store.new_strategy("New Strategy")
        self._open_editor(new)

    def _open_editor(self, strategy: dict):
        if self._active_editor is not None:
            self._editor_slot.removeWidget(self._active_editor)
            self._active_editor.deleteLater()
        editor = _InceptionStrategyEditor(strategy, self._fields, self._theme, parent=self._editor_container,
                                           sample_rows=self._sample_rows)
        editor.saved.connect(self._on_strategy_saved)
        self._editor_slot.addWidget(editor)
        self._active_editor = editor
        self._placeholder.hide()
        self._editor_container.show()

    def _on_strategy_saved(self, strategy: dict):
        t = self._theme
        try:
            store.save_strategy(strategy)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = store.load_all()
        self._refresh_list()

    def _on_clone(self, strategy: dict):
        cloned = copy.deepcopy(strategy)
        cloned["id"] = store.new_strategy("")["id"]
        cloned["name"] = strategy.get("name", "Strategy") + " (Copy)"
        t = self._theme
        try:
            store.save_strategy(cloned)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = store.load_all()
        self._refresh_list()

    def _on_delete(self, strategy_id: str):
        t = self._theme
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Strategy")
        msg.setText("Delete this strategy? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        try:
            store.delete_strategy(strategy_id)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        self._strategies = store.load_all()
        self._refresh_list()
        if self._active_editor is not None and self._active_editor._strategy.get("id") == strategy_id:
            self._editor_slot.removeWidget(self._active_editor)
            self._active_editor.deleteLater()
            self._active_editor = None
            self._editor_container.hide()
            self._placeholder.show()

    def _on_toggle(self, strategy_id: str, active: bool):
        t = self._theme
        strategy = next((s for s in self._strategies if s["id"] == strategy_id), None)
        if strategy is None:
            return
        strategy["active"] = active
        try:
            store.save_strategy(strategy)
        except (ApiError, NetworkError) as exc:
            strategy["active"] = not active   # revert on failure
            show_api_error(t, self, exc)
            self._refresh_list()

    def _open_variables_manager(self):
        if self._sample_rows:
            row = _pick_compile_test_row(self._sample_rows)
            all_data = self._sample_rows
        else:
            row = _dummy_row(self._fields)
            all_data = [row]
        dlg = VariablesManagerDialog(
            self._fields, row, all_lmv_data=all_data, theme=self._theme,
            sections=INCEPTION_SECTIONS, variable_store=var_store,
            historic_value_catalogue=INCEPTION_HISTORIC_VALUE_CATALOGUE,
            row_symbol_col=INCEPTION_ROW_SYMBOL_COL, parent=self,
        )
        dlg.exec()
        # A variable may have been renamed/added/deleted — refresh the field
        # universe every editor sees on its next open.
        self._fields = [f for f in self._fields if f not in [v["name"] for v in var_store.load_all()]]
        self._fields += [v["name"] for v in var_store.load_all()]

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        pass
