"""Inception > View by Date — calendar view of the shared historical EOD
dataset (see docs/INCEPTION_DATA.md in the backend repo): a green dot marks
a trading day that has data, and clicking View pops up that day's raw +
computed (Group A/B + Formula Builder) metrics for every locally-synced
instrument, reusing screens.historic_viewer's generic table popup (same
widget the existing Data > Historic Upload > Browse by Date tab uses)
rather than a bespoke one.

The day's row values come from services.inception_compute_service (Group
A/B, computed locally from services.inception_bars_store's synced bar
cache) plus _SnapshotLoadWorker._merge_formula_builder_columns' own merge of
LMV's ~56 Formula Builder columns (same one screens.inception_hmv does for
its grid — see that method's docstring) — the latter matters beyond just
this screen's own display: Strategy Builder for Inception can only
reference a column that's actually present in a row it evaluates, so this
is also what makes those columns available to build Inception strategies
against. See screens.inception_settings for the sync status/Sync Now action
this all depends on. Only the green-dot availability check (does the SERVER
have data for this day at all, useful even before this client has synced
it) and "has this been synced locally yet" still touch the network/local
store directly here.

Unlike Historic Upload's Browse tab, there's no per-day Delete here —
Inception's dataset is a shared, centrally-loaded market-data table (not
something a user uploads/removes day by day), so this screen is read-only.

Like screens.inception_hmv, a "⚡ Strategies" button (screens.live_viewer.
StrategyPickerPopup, reused as-is) lets more than one strategy be picked and
applied at once instead of silently unioning together every strategy marked
"active" in Strategy Builder — see inception_hmv's module docstring for why
that matters for row filters specifically. Sector + Symbol are frozen at the
popup's left edge via components.frozen_table_columns, same as HMV's grid.
"""

import calendar as _cal
import font_scale
from datetime import date

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar
from PySide6.QtCore import Qt, QTimer, QThread, Signal

from api import inception_api
from api.exceptions import ApiError, NetworkError
from components.availability_calendar import AvailabilityCalendar, themed_calendar_stylesheet
from components.error_popup import show_api_error
from screens.historic_viewer import HistoricDataViewer
from services import (
    inception_bars_store, inception_change_highlight, inception_compute_service,
    inception_day_history, inception_formula_builder_columns, inception_sector,
    inception_strategy_store, inception_value_before_change,
)
from services.formula_engine import FORMULA_CODES
from services.strategy_engine import apply_strategies, build_symbol_index, get_row_fmt_colors

_FROZEN_HEADERS = ["Sector", "Symbol"]

# Local sync only ever pulls the canonical ('_I') roll series (see
# services.inception_sync_service / the backend's get_bars default) — so
# every symbol in the local store ends with this suffix, and stripping it
# is exactly "the underlying symbol" with no extra network round trip.
_CANONICAL_SUFFIX = "_I"


def _display_symbol(symbol: str) -> str:
    return symbol[: -len(_CANONICAL_SUFFIX)] if symbol.endswith(_CANONICAL_SUFFIX) else symbol


def _remap_to_display_symbols(source: dict) -> dict:
    """Re-keys a {(col_name, window): {symbol: {...}}} dict's per-symbol
    entries from the RAW "_I"-suffixed symbol to the DISPLAY symbol.
    Needed for services.inception_value_before_change.resolve_group_a_b's
    own output: it's built straight from services.inception_compute_
    service.range_rows, whose own docstring explicitly leaves suffix-
    stripping to "a screens-layer concern" — so its stock entries (and
    this function's own symbol keys) come back RAW ("ABB_I"). Every row
    lookup this feeds into (services.strategy_engine.evaluate_compiled's
    day_history param, via row_data["Symbol"]) uses the DISPLAY symbol
    ("ABB") instead — the same one resolve_formula_builder's own callers
    already pass in directly (see this method's per-row loop below).
    Without this remap, VALUE_BEFORE_CHANGE([HIGH]) (or any other Group
    A/B or raw-field reference — anything that isn't a Formula Builder
    code) builds a real, correct value under a symbol key no row lookup
    can ever match, leaving the whole column silently blank."""
    return {key: {_display_symbol(sym): vals for sym, vals in entry.items()}
            for key, entry in source.items()}


def _reorder_by_saved_column_order(headers: list, rows: list) -> tuple:
    """Reorders *headers* (and every row in *rows* to match) to the Config
    Editor > "Inception Column Order" tab's saved list (services.
    config_store.INCEPTION_HMV_COLUMN_ORDER — the same key screens.
    inception_hmv's own "⚡"-free "Load" path reads via its
    _restore_saved_column_order; one shared list rather than a second tab,
    since the two screens' column universes overlap almost entirely).

    Columns named in the saved list move to the front, in that order;
    anything not listed keeps its current relative position after them —
    same partial-list convention as inception_hmv/live_viewer's own column-
    order restores. Unlike those two (which reorder VISUAL sections on an
    already-built, persistent QHeaderView), View by Date builds a brand new
    HistoricDataViewer popup — and its headers/rows as brand new Python
    lists — on every View click, so there's no live header to move
    sections on; permuting these two lists before HistoricDataViewer ever
    sees them has the same effect. A no-op ([]) when nothing's been saved.
    """
    from services import config_store
    saved = config_store.load_column_order(key=config_store.INCEPTION_HMV_COLUMN_ORDER)
    if not saved:
        return headers, rows
    name_to_idx = {name: i for i, name in enumerate(headers)}
    ordered_idx = [name_to_idx[name] for name in saved if name in name_to_idx]
    seen = set(ordered_idx)
    final_idx = ordered_idx + [i for i in range(len(headers)) if i not in seen]
    new_headers = [headers[i] for i in final_idx]
    new_rows = [[row[i] for i in final_idx] for row in rows]
    return new_headers, new_rows


class _SnapshotLoadWorker(QThread):
    """Runs inception_compute_service.snapshot on a background thread — see
    that module's docstring on why a cold Group A/B walk across the full
    instrument universe can take a while, and screens.inception_settings.
    _SyncWorker for the same pattern used for syncing."""
    progress = Signal(int, int)   # done, total instruments
    # day_history declared `object`, not `dict` — see screens.inception_hmv's
    # identical _HmvLoadWorker.succeeded fix for the full rationale (a
    # Signal(dict) with non-string keys silently marshals to {} cross-
    # thread instead of raising).
    succeeded = Signal(list, object)    # rows, day_history
    failed = Signal(str)

    def __init__(self, as_of_date: date, parent=None):
        super().__init__(parent)
        self._as_of_date = as_of_date

    def run(self):
        try:
            rows = inception_compute_service.snapshot(
                self._as_of_date, progress_cb=lambda done, total: self.progress.emit(done, total),
            )
            day_history = self._merge_formula_builder_columns_and_day_history(rows, self._as_of_date)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(rows, day_history)

    @staticmethod
    def _merge_formula_builder_columns_and_day_history(rows: list, as_of_date: date) -> dict:
        """Adds LMV's ~56 Formula Builder columns (MT, MB, DT, DB, PMH, the
        camarilla pivot ladders, ...) to every row's values dict — same
        merge screens.inception_hmv._HmvLoadWorker does (see that module's
        docstring for the full rationale), now also here so those columns
        are available to View by Date and, in turn, to Strategy Builder for
        Inception (a formula can only reference a column that's actually
        present in the row it's evaluating against). Also builds this
        View's day_history from three sources sharing one dict: services.
        inception_day_history (a raw-OHLCV-only analogue of services.
        formula_stats_engine.compute_day_history — build() for VALUE_DAYS_
        AGO/_DAYS-family, e.g. the "200 Average" strategy's AVG_DAYS(CLOSE,
        200); build_extreme() for VALUE_AT_MAX_DAYS/VALUE_AT_MIN_DAYS/
        VALUE_AT_MAX_DATES/VALUE_AT_MIN_DATES) and services.
        inception_value_before_change (VALUE_BEFORE_CHANGE — "the value
        this column had before it last changed"), all reusing the SAME
        per-symbol bars fetched for the Formula Builder merge rather than
        querying them again. Combined via inception_day_history.merge_into
        (not a bare dict.update) so a formula referencing both a plain
        _DAYS function and a VALUE_AT_MAX_DAYS/etc call on the identical
        (column, window) doesn't have one clobber the other's entry — see
        merge_into's own docstring. Runs on this background thread for the
        same reason HMV's does: bars_for_symbol is a cheap indexed query,
        but the calendar-bucket arithmetic still adds up across the full
        instrument universe (and resolve_group_a_b's own extra range_rows
        pass, when a VALUE_BEFORE_CHANGE spec needs it, more so — still
        bounded to once per View, not once per month scanned) so none of
        this ever blocks the GUI thread.
        """
        strategies = inception_strategy_store.load_all()
        specs = inception_day_history.raw_day_specs(strategies)
        extreme_specs = inception_day_history.raw_extreme_specs(strategies)
        vbc_specs = inception_value_before_change.specs_for_strategies(strategies)
        vbc_fb_specs = [(c, m) for c, m in vbc_specs if c in FORMULA_CODES]
        vbc_other_specs = [(c, m) for c, m in vbc_specs if c not in FORMULA_CODES]
        vbc_n_specs = inception_value_before_change.n_specs_for_strategies(strategies)
        vbc_n_fb_specs = [(c, n) for c, n in vbc_n_specs if c in FORMULA_CODES]
        vbc_n_other_specs = [(c, n) for c, n in vbc_n_specs if c not in FORMULA_CODES]

        day_history: dict = {}
        for row in rows:
            bars = inception_bars_store.bars_for_symbol(row["symbol"], date_to=as_of_date)
            row["values"].update(inception_formula_builder_columns.compute_for_bars(row["symbol"], bars))
            if specs or extreme_specs or vbc_fb_specs or vbc_n_fb_specs:
                # Keyed by the DISPLAY symbol (suffix stripped), not
                # row["symbol"] (the raw "_I" roll-series name) — that's
                # what ends up in the "Symbol" column apply_strategies'
                # symbol_col="Symbol" actually looks up against (see
                # _on_view_succeeded), so building this with the raw name
                # would leave every entry unreachable, day_history
                # correctly populated but never found.
                symbol = _display_symbol(row["symbol"])
                if specs:
                    inception_day_history.merge_into(
                        day_history, inception_day_history.build(specs, symbol, bars))
                if extreme_specs:
                    inception_day_history.merge_into(
                        day_history, inception_day_history.build_extreme(extreme_specs, symbol, bars))
                if vbc_fb_specs:
                    inception_day_history.merge_into(
                        day_history, inception_value_before_change.resolve_formula_builder(
                            vbc_fb_specs, symbol, bars))
                if vbc_n_fb_specs:
                    inception_day_history.merge_into(
                        day_history, inception_value_before_change.resolve_formula_builder_n(
                            vbc_n_fb_specs, symbol, bars))
        if vbc_other_specs:
            inception_day_history.merge_into(
                day_history, _remap_to_display_symbols(
                    inception_value_before_change.resolve_group_a_b(
                        vbc_other_specs, as_of_date)))
        if vbc_n_other_specs:
            inception_day_history.merge_into(
                day_history, _remap_to_display_symbols(
                    inception_value_before_change.resolve_group_a_b_n(
                        vbc_n_other_specs, as_of_date)))
        return day_history


class InceptionViewByDateScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_date = date.today()
        self._available_days: set = set()
        self._viewers = []
        self._worker: _SnapshotLoadWorker | None = None
        self._strategies: list = []
        # "Changed since last View" cell highlighting — see services.
        # inception_change_highlight and _on_view_succeeded below. Kept at
        # the SCREEN level (not on the HistoricDataViewer popup itself,
        # which is a fresh instance every View click) so it survives across
        # popups the same way self._strategies does.
        from services import config_store
        self._highlight_color = config_store.load_inception_highlight_color()
        self._column_highlight_colors = config_store.load_inception_column_highlight_colors()
        self._previous_headers: list = []
        self._previous_data: list = []
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Inception — View by Date")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        subtitle = QLabel("A green dot marks a trading day with data. Select a date, then View.")
        subtitle.setFont(font_scale.font(font_scale.SMALL, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        self._calendar = AvailabilityCalendar(t)
        self._calendar.setFont(font_scale.font(font_scale.SMALL, False))
        self._calendar.setStyleSheet(themed_calendar_stylesheet(t))
        self._calendar.setMaximumWidth(420)
        self._calendar.clicked.connect(self._on_date_selected)
        self._calendar.currentPageChanged.connect(self._on_page_changed)
        layout.addWidget(self._calendar)

        bottom_row = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        bottom_row.addWidget(self._status_lbl)
        bottom_row.addStretch()

        self._strat_btn = QPushButton("⚡  Strategies")
        self._strat_btn.setFixedHeight(32)
        self._strat_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._strat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._strat_btn.clicked.connect(self._show_strategy_picker)
        bottom_row.addWidget(self._strat_btn)
        bottom_row.addSpacing(8)

        self._highlight_btn = QPushButton()
        self._highlight_btn.setFixedSize(32, 32)
        self._highlight_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._highlight_btn.setToolTip("Changed-since-last-View highlight color")
        self._highlight_btn.clicked.connect(self._show_highlight_color_manager)
        bottom_row.addWidget(self._highlight_btn)
        bottom_row.addSpacing(8)

        self._view_btn = QPushButton("View")
        self._view_btn.setFixedHeight(32)
        self._view_btn.setFixedWidth(100)
        self._view_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_btn.clicked.connect(self._on_view_clicked)
        bottom_row.addWidget(self._view_btn)
        layout.addLayout(bottom_row)

        self._progress_bar = QProgressBar()
        self._progress_bar.setFixedHeight(6)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        layout.addWidget(self._progress_bar)

        layout.addStretch()

        self._refresh_highlight_btn_style()

        # Deferred, same rationale as historic_upload's browse tab: don't
        # block widget construction (this can happen during app startup) on
        # a network call.
        QTimer.singleShot(0, self._refresh_availability)
        self._update_view_btn_enabled()

    # ── availability ─────────────────────────────────────────────────────────

    def _refresh_availability(self):
        today = date.today()
        year = self._calendar.yearShown() or today.year
        month = self._calendar.monthShown() or today.month
        self._fetch_and_apply_availability(year, month, show_popup_on_error=False)

    def _on_page_changed(self, year, month):
        self._fetch_and_apply_availability(year, month)

    def _fetch_and_apply_availability(self, year: int, month: int, show_popup_on_error: bool = True):
        last_day = _cal.monthrange(year, month)[1]
        date_from = date(year, month, 1)
        date_to = date(year, month, last_day)
        t = self._controller.theme
        try:
            result = inception_api.get_availability(date_from, date_to)
            days = {
                date.fromisoformat(d["trade_date"]).day
                for d in result["dates"] if d["has_data"]
            }
        except (ApiError, NetworkError, KeyError, ValueError, TypeError) as exc:
            if show_popup_on_error and isinstance(exc, (ApiError, NetworkError)):
                show_api_error(t, self, exc)
            else:
                self._status_lbl.setText("Couldn't load availability for this month.")
                self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            self._calendar.set_available_days(set())
            self._available_days = set()
            self._update_view_btn_enabled()
            return
        self._calendar.set_available_days(days)
        self._available_days = days
        self._update_view_btn_enabled()

    def _on_date_selected(self, qdate):
        self._selected_date = date(qdate.year(), qdate.month(), qdate.day())
        self._update_view_btn_enabled()

    def _update_view_btn_enabled(self):
        self._view_btn.setEnabled(self._selected_date.day in self._available_days)

    # ── strategies ───────────────────────────────────────────────────────────

    def _show_strategy_picker(self):
        from screens.live_viewer import StrategyPickerPopup
        t = self._controller.theme
        try:
            fresh = inception_strategy_store.load_all()
            self._strategies = inception_strategy_store.merge_session_active(fresh, self._strategies)
        except (ApiError, NetworkError):
            pass   # best-effort refresh — picker still opens with whatever it already had
        popup = StrategyPickerPopup(self._strategies, t, self)
        popup.applied.connect(self._on_strategies_applied)
        btn_pos = self._strat_btn.mapToGlobal(self._strat_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _on_strategies_applied(self, updated: list):
        # Deliberately NOT persisted — see screens.inception_hmv's identical
        # fix / screens.live_viewer's _on_strategies_applied for why: "active"
        # here is this screen's own SESSION-local "applied right now" flag,
        # not Strategy Builder's persisted one, even though they're the same
        # dict key — persisting every strategy the picker showed (not just
        # the ones actually toggled) would silently deactivate every other,
        # unchecked strategy in Strategy Builder too.
        updated_by_id = {s["id"]: s for s in updated}
        self._strategies = [updated_by_id.get(s["id"], s) for s in self._strategies]
        self._update_strat_btn_label()

    def _update_strat_btn_label(self):
        active = sum(1 for s in self._strategies if s.get("active"))
        total = len(self._strategies)
        self._strat_btn.setText("⚡  Strategies" if total == 0 else f"⚡  Strategies  {active}/{total}")

    # ── "changed since last View" highlight colors ──────────────────────────

    def _effective_highlight_color(self, column_name: str | None = None) -> str:
        """See screens.inception_hmv's identical method — same convention,
        kept as a per-screen copy rather than shared since each owns its
        own _highlight_color/_column_highlight_colors state (this is a
        small pure function, not worth a shared service module for)."""
        if column_name is not None:
            override = self._column_highlight_colors.get(column_name)
            if override:
                return override
        if self._highlight_color:
            return self._highlight_color
        t = self._controller.theme
        try:
            return t.get("status_amber") if t else "#d29922"
        except KeyError:
            return "#d29922"

    def _refresh_highlight_btn_style(self):
        t      = self._controller.theme
        divclr = t.get("divider") if t else "#30363d"
        accent = t.get("accent")  if t else "#39d353"
        fill   = self._effective_highlight_color()
        self._highlight_btn.setStyleSheet(
            f"QPushButton {{ background: {fill};"
            f"border: 1px solid {divclr}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border-color: {accent}; }}"
        )

    def _show_highlight_color_manager(self):
        from screens.live_viewer import HighlightColorManagerDialog
        dlg = HighlightColorManagerDialog(
            columns=self._previous_headers,
            default_color=self._highlight_color,
            column_colors=self._column_highlight_colors,
            theme=self._controller.theme,
            parent=self,
        )
        dlg.default_changed.connect(self._set_highlight_color)
        dlg.column_changed.connect(self._set_column_highlight_color)
        dlg.exec()

    def _set_highlight_color(self, color):
        from services import config_store
        self._highlight_color = color
        config_store.save_inception_highlight_color(color)
        self._refresh_highlight_btn_style()

    def _set_column_highlight_color(self, column: str, color):
        from services import config_store
        if color is None:
            self._column_highlight_colors.pop(column, None)
        else:
            self._column_highlight_colors[column] = color
        config_store.save_inception_column_highlight_colors(self._column_highlight_colors)

    # ── view popup ───────────────────────────────────────────────────────────

    def _on_view_clicked(self):
        t = self._controller.theme
        if inception_bars_store.last_synced_date() is None:
            self._status_lbl.setText(
                "No Inception data synced to this device yet — open Inception > "
                "Data & Settings and click Sync Now."
            )
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        if self._worker is not None and self._worker.isRunning():
            return

        self._view_btn.setEnabled(False)
        self._status_lbl.setText("Computing…")
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._progress_bar.setRange(0, 0)   # busy/indeterminate until the first progress tick arrives
        self._progress_bar.setValue(0)
        self._progress_bar.setVisible(True)

        self._worker = _SnapshotLoadWorker(self._selected_date, parent=self)
        self._worker.progress.connect(self._on_view_progress)
        self._worker.succeeded.connect(self._on_view_succeeded)
        self._worker.failed.connect(self._on_view_failed)
        self._worker.start()

    def _on_view_progress(self, done: int, total: int):
        self._progress_bar.setRange(0, total)
        self._progress_bar.setValue(done)
        self._status_lbl.setText(f"Computing… {done}/{total} instruments")

    def _on_view_succeeded(self, rows: list, day_history: dict):
        t = self._controller.theme
        self._view_btn.setEnabled(True)
        self._progress_bar.setVisible(False)

        if not rows:
            self._status_lbl.setText(
                f"No synced data for {self._selected_date.strftime('%d-%b-%Y')} — try syncing again "
                f"(Inception > Data & Settings)."
            )
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        metric_keys = sorted({k for r in rows for k in r.get("values", {})})
        headers = ["Symbol"] + metric_keys
        table_rows = [
            # Display the underlying symbol (e.g. "ABB") rather than the raw
            # roll-series symbol ("ABB_I") — that suffix is an internal
            # detail of which continuous-futures series was picked as
            # canonical, not something a user browsing by date needs to see.
            [_display_symbol(r["symbol"])] + [r.get("values", {}).get(k) for k in metric_keys]
            for r in rows
        ]
        headers, table_rows = inception_sector.inject_sector_rows(headers, table_rows)

        # Active Inception strategies are evaluated entirely here, on the
        # client — the snapshot response above is base (raw + precomputed)
        # values only. Same engine/appending shape LMV's own live/historical
        # viewers use for their own strategy columns. Reloaded fresh here
        # (same as before) so a strategy toggled in Strategy Builder since
        # this screen last used the picker still takes effect without an
        # extra step; the "⚡ Strategies" picker (see _show_strategy_picker)
        # additionally lets more than one be selected and applied at once
        # for this session, same as screens.inception_hmv. load_all() already
        # falls back to its local cache on a network error, so this can't
        # raise. Merged through merge_session_active (not a plain overwrite)
        # so a deselect made via the picker earlier this session — never
        # persisted to the store, see _on_strategies_applied — survives this
        # reload instead of being silently reverted back to Strategy
        # Builder's own persisted "active" flag on every View click.
        fresh = inception_strategy_store.load_all()
        self._strategies = inception_strategy_store.merge_session_active(fresh, self._strategies)
        self._update_strat_btn_label()
        strategies = [s for s in self._strategies if s.get("active")]
        # include_streak_columns=False — the "Days True"/"Since" streak pair
        # needs a row filter evaluated via day_history too (services.
        # strategy_engine.collect_day_requests' synthetic streak request),
        # which is beyond day_history's raw-OHLCV-only scope (see services.
        # inception_day_history's module docstring) — would always read
        # "0"/blank here, dead weight, not a useful feature.
        # symbol_col="Symbol" — Inception's row-identity column is "Symbol",
        # not apply_strategies' LMV-default "Scrip Name" (which Inception
        # rows don't have at all); without this, day_history's symbol-keyed
        # lookup would never find a match, no matter how correctly it was
        # built (see services.strategy_engine.apply_strategies' symbol_col
        # docstring).
        base_col_count = len(headers)
        headers, table_rows = apply_strategies(strategies, headers, table_rows,
                                               day_history=day_history, include_streak_columns=False,
                                               symbol_col="Symbol")
        # Conditional formatting (services.strategy_engine.get_row_fmt_
        # colors) — same mechanism screens.inception_hmv's own Load path
        # now uses (see that module's _recompute_display for the full
        # rationale), previously never wired up here either. Computed
        # BEFORE the column reorder below: get_row_fmt_colors reads
        # row[base_col_count + strat_idx] to find each strategy column's
        # OWN computed value, which only lines up with strat_col_defs'
        # order right after apply_strategies appended them, not after
        # they've potentially been shuffled elsewhere in the row.
        strat_col_defs = [col for s in strategies for col in s.get("columns", [])]
        all_dicts = [dict(zip(headers, row)) for row in table_rows]
        agg_cache: dict = {}
        sym_index = build_symbol_index(all_dicts)
        fmt_colors_by_row = [
            get_row_fmt_colors(strat_col_defs, row, base_col_count, row_dict, all_dicts,
                               agg_cache, sym_index, day_history)
            for row, row_dict in zip(table_rows, all_dicts)
        ]

        headers, table_rows = _reorder_by_saved_column_order(headers, table_rows)

        # "Changed since last View" (services.inception_change_highlight) —
        # diffed against whatever was shown the last time THIS screen
        # succeeded a View (a different date, a re-View of the same date
        # after new data synced, ...), symbol-matched so a changed universe
        # doesn't produce false positives. Computed AFTER the column
        # reorder above so the (row, col) indices line up with what
        # HistoricDataViewer is actually about to build.
        changed = inception_change_highlight.changed_cells(
            self._previous_headers, self._previous_data, headers, table_rows,
        )
        cell_highlights = {
            (r, c): self._effective_highlight_color(headers[c]) for r, c in changed
        }
        # Conditional formatting wins over the "changed" amber highlight
        # for the same cell (a color the user deliberately configured is
        # more informative than "this happened to differ from last View")
        # — fmt_colors_by_row stayed row-index-aligned across the reorder
        # (which only permutes COLUMNS, not rows); target_column names are
        # resolved against the now-reordered headers.
        col_index_by_name = {h: i for i, h in enumerate(headers)}
        for r, colors in enumerate(fmt_colors_by_row):
            for target_name, color in colors.items():
                c = col_index_by_name.get(target_name)
                if c is not None:
                    cell_highlights[(r, c)] = color
        self._previous_headers = list(headers)
        self._previous_data = [list(row) for row in table_rows]

        viewer = HistoricDataViewer(
            headers, table_rows, self._selected_date.strftime("%d-%b-%Y"), theme=t,
            title=f"Inception — {self._selected_date.strftime('%d-%b-%Y')}",
            frozen_headers=_FROZEN_HEADERS, cell_highlights=cell_highlights,
        )
        viewer.show()
        self._viewers.append(viewer)
        self._status_lbl.setText("")

    def _on_view_failed(self, message: str):
        t = self._controller.theme
        self._view_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_lbl.setText(f"Load failed: {message}")
        self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        if not self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._calendar.setStyleSheet(themed_calendar_stylesheet(t))
        self._refresh_highlight_btn_style()
        for viewer in self._viewers:
            if viewer.isVisible():
                viewer.refresh_theme()
