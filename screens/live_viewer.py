import font_scale
import html
import os
import re
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from components.column_filter_popup import ColumnFilterPopup
from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QTableView, QHeaderView, QAbstractItemView, QFrame,
    QCheckBox, QSizePolicy, QComboBox, QScrollArea, QLineEdit, QColorDialog,
    QDialog, QListWidget, QListWidgetItem, QProgressBar
)
from PySide6.QtCore import (
    Qt, QTimer, QFileSystemWatcher, Signal, QObject, QThread, QEvent, QByteArray, QSize
)
from PySide6.QtGui import QColor, QBrush, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer


_DEBOUNCE_MS   = 300    # ms to wait after file event before re-reading
_COM_POLL_MS   = 200    # active COM polling interval — near-real-time live sync
_COM_IDLE_MS   = 1000   # relaxed interval after a quiet spell (adaptive backoff)
_IDLE_TICKS    = 15     # consecutive no-change ticks before backing off (~3s)
_HIGHLIGHT_MS  = 4000   # how long a changed cell stays amber
_SWEEP_MS      = 500    # how often expired highlights are cleared
_FILE_SETTLE_S = 0.2    # brief wait so disk writes finish before re-reading
_REFRESH_STALL_S = 30   # a read in flight longer than this = wedged worker; force-reset

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")

# Every cell in the table gets this same alignment — computed once here
# rather than re-evaluating the Qt.AlignmentFlag `|` operator (surprisingly
# not free: Python enum flag combination goes through several method calls
# each time) once per cell, every render. Profiling a 220-row x 85-column
# rebuild showed this actually mattering at that scale.
_CELL_ALIGNMENT = Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft


def _svg_icon(filename: str, color: str) -> QIcon:
    """Load an assets/icons/*.svg file, recolored to match the current theme
    (the on-disk files are all fill="#000000" placeholders — same pattern as
    components/sidebar.py, components/topbar.py, screens/strategy_builder.py)."""
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


def _contrasting_text(hex_color: str) -> str:
    """Black or white — whichever reads better on *hex_color* — so a
    user-picked highlight background (see HighlightColorManagerDialog) never
    lands on illegible text the way a fixed black would for a dark pick."""
    c = QColor(hex_color)
    luminance = 0.299 * c.red() + 0.587 * c.green() + 0.114 * c.blue()
    return "#000000" if luminance > 140 else "#ffffff"


def _swatch_icon(hex_color: str, size: int = 14) -> QIcon:
    """A small solid-color square icon — used for the color dot next to
    each row in HighlightColorManagerDialog's column list."""
    pixmap = QPixmap(size, size)
    pixmap.fill(QColor(hex_color))
    return QIcon(pixmap)


# Concrete preset colors offered everywhere a highlight color is picked.
# Each picker prepends its own contextual "reset to X" entry (color=None) —
# there's no single "default" entry here since what None means depends on
# whether the target is the LMV-wide default or one column's override.
_HIGHLIGHT_PRESETS = [
    ("Yellow",  "#e8c400"),
    ("Orange",  "#e3691a"),
    ("Red",     "#f85149"),
    ("Green",   "#39d353"),
    ("Blue",    "#58a6ff"),
    ("Purple",  "#a371f7"),
    ("Pink",    "#f778ba"),
]


# ── Off-thread reader worker ────────────────────────────────────────────────

def _log_worker_error(context: str) -> None:
    """Append the current exception (with full traceback) to error.log.

    _LiveDataWorker's failure paths only emit a short, truncated message to
    the status bar, which then scrolls away — this keeps a permanent,
    appended record with the real stack trace in the app-root error.log
    (see services.error_logging), which is the only durable trail a
    packaged build leaves. Best-effort: logging must never itself break a
    tick, hence the guard."""
    try:
        from services.error_logging import error_logger
        error_logger.exception(context)
    except Exception:
        pass


def _inject_sector_rows(headers: list, data: list, sector_map: dict) -> tuple:
    """Prepend a Sector column to headers and every data row. Module-level
    (not a LiveViewerWindow method) so the worker thread can call it too,
    without touching any GUI-thread-owned state beyond the read-only
    sector_map passed in."""
    scrip_idx = headers.index("Scrip Name") if "Scrip Name" in headers else -1
    new_headers = ["Sector"] + list(headers)
    new_data = []
    for row in data:
        scrip = row[scrip_idx] if scrip_idx >= 0 and scrip_idx < len(row) else ""
        sector = sector_map.get(str(scrip).strip().upper(), "—")
        new_data.append([sector] + list(row))
    return new_headers, new_data


def _inject_opening_range_columns(headers: list, data: list, or_map: dict,
                                  name_to_symbol: dict) -> tuple:
    """Append OR.High/OR.Low columns — today's Opening Range High/Low
    capture (services/scheduled_jobs.py::run_opening_range_capture), keyed
    by the same symbol resolution used when that job uploaded it, so a row
    here lines up with the matching row uploaded from this exact LMV.
    Module-level, like _inject_sector_rows, so the worker thread can call it
    without touching GUI-thread-owned state beyond the read-only dicts
    passed in. Blank ("—") before today's capture has run, or for a stock
    added after it did."""
    scrip_idx = headers.index("Scrip Name") if "Scrip Name" in headers else -1
    new_headers = list(headers) + ["OR.High", "OR.Low"]
    new_data = []
    for row in data:
        raw_name = str(row[scrip_idx]) if scrip_idx >= 0 and scrip_idx < len(row) else ""
        display_name = _strip_rolling_suffix(raw_name) or raw_name
        symbol = name_to_symbol.get(display_name.lower()) or display_name
        high, low = or_map.get(symbol, ("—", "—"))
        new_data.append(list(row) + [high, low])
    return new_headers, new_data


class _LiveDataWorker(QObject):
    """
    Runs the read+merge, and the strategy-formula computation on top of it,
    entirely on a worker thread — so neither the network calls (ExternalImport
    "database" mode especially) nor the O(rows x strategies x columns) formula
    evaluation ever blocks the GUI thread, on the first load or any later
    tick.  Owns a :class:`services.live_merge.LiveDataReader`; the reader's
    COM handles are created and used entirely on this thread.
    """

    result = Signal(list, list, list, list)   # headers, data, disp_headers, disp_data
    failed = Signal(str)                      # error message, already prefixed

    # Strategy-toggle / category-change recompute — same apply_strategies()
    # work as do_read, but over data already in hand (no new read). Separate
    # signals from result/failed so a recompute error can't be mistaken for
    # a read error by _on_read_failed (which resets unrelated state).
    recompute_result = Signal(list, list)     # disp_headers, disp_data
    recompute_failed = Signal(str)            # error message, already prefixed

    opening_range_ready = Signal()            # fresh OR.High/OR.Low data is available

    # _refresh_day_history_from_store's worker-side result — day_history
    # dict, plus the strategy list reloaded from the store (see
    # refresh_day_history below). day_history's keys are (col_name, days)
    # tuples — a plain Signal(dict) marshals cross-thread by converting to
    # QVariantMap, which requires *string* keys and silently drops anything
    # it can't convert (Shiboken prints "_pythonToCppCopy: Cannot
    # copy-convert ... (dict) to C++" and the slot receives {} instead —
    # no crash, just data loss, which is exactly what made "the column is
    # empty" so hard to spot). Signal(object) sidesteps QVariant entirely
    # and passes the real Python dict through unchanged — see
    # _request_read/_request_recompute below for the same fix.
    day_history_result = Signal(object, list)
    day_history_failed = Signal(str, list)    # error message (already prefixed), strategies

    def __init__(self, reader, sector_map: dict, name_to_symbol: dict):
        super().__init__()
        self._reader         = reader
        self._sector_map     = sector_map
        self._name_to_symbol = name_to_symbol
        self._opening_range_map: dict = {}
        self._started        = False

    def refresh_opening_range(self) -> None:
        """Pull today's Opening Range High/Low snapshot from the server.
        Triggered on a coarse timer from the GUI thread (see
        LiveViewerWindow._setup_watcher's _or_timer) rather than on every
        do_read tick, since the snapshot only changes once a day. Runs on
        this same worker thread as do_read, so do_read's read of
        self._opening_range_map never races this write — Qt's event loop
        serializes queued slot calls landing on one thread. Best-effort: a
        network hiccup just keeps the last-known map rather than blanking
        the columns."""
        from datetime import date
        from api import opening_range_api
        from api.exceptions import ApiError, NetworkError
        try:
            snapshot = opening_range_api.get_snapshot(date.today())
        except (ApiError, NetworkError):
            return
        self._opening_range_map = {
            s["symbol"]: (s.get("high"), s.get("low"))
            for s in snapshot.get("stocks", [])
        }
        # do_read only runs on a live tick (COM poll or a detected broker-file
        # change) — with neither happening right now (e.g. a quiet feed, or
        # COM unavailable on this platform), this freshly-fetched map would
        # otherwise sit here unused, never reaching the table. Ask the GUI
        # thread to force one read so it's reflected without waiting on
        # unrelated market-data activity.
        self.opening_range_ready.emit()

    def recompute(self, headers: list, data: list, strategies: list,
                 day_history: dict | None = None) -> None:
        """Re-run apply_strategies() on already-fetched data (no new read) —
        used for the interactive strategy-toggle / category-change path so
        the O(rows x strategies x columns) formula evaluation runs off the
        GUI thread instead of blocking it synchronously (see
        LiveViewerWindow._recompute_display). ``day_history`` is a snapshot
        (see LiveViewerWindow._day_history) resolving any _DAYS historic
        aggregate functions — never fetched here, just forwarded."""
        try:
            active = [s for s in strategies if s.get("active")]
            if active:
                from services.strategy_engine import apply_strategies
                from services import lmv_inception_fields
                disp_headers, disp_data = apply_strategies(
                    active, headers, data, day_history,
                    inception_values=lmv_inception_fields.current_snapshot(),
                )
            else:
                disp_headers, disp_data = headers, data
        except Exception as exc:
            _log_worker_error("LMV strategy recompute failed (toggle/category change)")
            self.recompute_failed.emit(f"Strategy error: {exc}"[:200])
            return
        self.recompute_result.emit(disp_headers, disp_data)

    def refresh_day_history(self, strategies: list, selected_category: str,
                            reload_from_store: bool) -> None:
        """Recomputes the _DAYS historic-aggregate cache (see
        LiveViewerWindow._refresh_day_history/_refresh_day_history_from_store)
        entirely on this worker thread — collect_day_requests' notif_configs
        input (services.strategy_alerts.config_store.load_configs(), a
        network call the first time it's called after login/reload_cache())
        AND compute_day_history's own historic-snapshot fetch AND (when
        *reload_from_store* is set) services.strategy_store.load_all()'s own
        network call all happen here, off the GUI thread, so a strategy
        toggle/category change/initial load/"↻ N-Day Data" click never
        blocks the window regardless of how slow any of them are — see the
        module docstring's own note on why this used to be split into a
        "cheap, synchronous-on-the-GUI-thread" path (no store reload) and
        this worker-routed one (with a reload): a row-filter's automatic
        "Days True" streak (services.strategy_engine's Row-Filter Streak)
        made a day_history recompute fire on nearly every active-strategy
        toggle, not just the rare "this strategy uses AVG_DAYS" case the
        synchronous path's "acceptable, only runs occasionally" reasoning
        depended on — so BOTH paths now route through here.

        *reload_from_store* (False = the toggle/category-change path,
        True = initial load / "↻ N-Day Data") controls only whether
        strategy definitions are reloaded from services.strategy_store
        first — see LiveViewerWindow._refresh_day_history_from_store's own
        docstring for why that reload matters (picks up a column/formula
        added or edited in Strategy Builder since this window opened) and
        why the toggle/category-change path deliberately skips it (so those
        more frequent interactions don't gain an extra server round trip on
        top of the day-history fetch itself). *strategies* is the window's
        full (unfiltered) list either way; when *reload_from_store* is
        False it's returned unchanged (nothing to merge) — the result
        signal's shape stays identical for both callers regardless.

        Each reloaded strategy's "active" flag is overwritten with
        *strategies*' own per-session value — disk's copy isn't
        authoritative for that flag (LMV forces every strategy inactive on
        open regardless of what was last saved — see app_window.py's
        _on_lmv_ready), so trusting disk here would silently turn a
        strategy the user just toggled on back off.

        *selected_category* is applied only when deciding which _DAYS
        requests to fetch (mirroring LiveViewerWindow._filtered_strategies()),
        not to what's returned, so a strategy outside the current category
        filter keeps its real active flag instead of being reported back as
        inactive.
        """
        from services import strategy_store
        from services.strategy_alerts import config_store as alerts_config_store
        from services.strategy_engine import collect_day_requests
        from services.formula_stats_engine import compute_day_history
        from api import lmv_snapshot_api
        from api.exceptions import ApiError, NetworkError

        try:
            if reload_from_store:
                try:
                    fresh = strategy_store.load_all()
                except (ApiError, NetworkError):
                    # A store-refresh hiccup shouldn't block a day-history
                    # recompute for whatever strategies/columns were already
                    # known to this window.
                    merged = strategies
                else:
                    merged = strategy_store.merge_session_active(fresh, strategies)
            else:
                merged = strategies

            in_view = [
                s for s in merged
                if selected_category == "All" or s.get("category", "Daily") == selected_category
            ]
            active = [s for s in in_view if s.get("active")]
            notif_configs = alerts_config_store.load_configs()
            requests = collect_day_requests(active, notif_configs)
            if not requests:
                self.day_history_result.emit({}, merged)
                return
            try:
                day_history = compute_day_history(requests, lmv_snapshot_api.get_range)
            except (ApiError, NetworkError) as exc:
                self.day_history_failed.emit(f"N-day column refresh failed: {exc}"[:200], merged)
                return
            self.day_history_result.emit(day_history, merged)
        except Exception as exc:
            # Never let an unexpected error here kill the worker thread —
            # do_read/recompute are equally defensive; keep the window
            # usable (whatever day-history/strategies it already had) rather
            # than dying silently.
            _log_worker_error("LMV N-day/day-history refresh failed unexpectedly")
            self.day_history_failed.emit(f"N-day column refresh failed: {exc}"[:200], strategies)

    def do_read(self, force_slow: bool, settle_s: float, strategies: list,
               day_history: dict | None = None) -> None:
        if not self._started:
            try:
                self._reader.start()
            except Exception:
                pass
            self._started = True
        # Settle delay runs here on the worker thread, never blocking the UI.
        if settle_s > 0:
            time.sleep(settle_s)
        # One catch-all around the whole tick: anything that escapes here
        # (previously the _inject_* calls and any other un-try'd line) reaches
        # the global sys.excepthook, gets swallowed, and — because nothing
        # emits result/failed — leaves LiveViewerWindow._refreshing stuck True,
        # which silently wedges the 200ms poll loop for the rest of the
        # session with the status bar frozen on the last "Updated: …". Every
        # exit path from here must emit exactly one of result/failed so the
        # window always resets _refreshing and the next tick can run.
        try:
            try:
                headers, data = self._reader.read_merged(force_slow=force_slow)
                headers, data = _inject_sector_rows(headers, data, self._sector_map)
                headers, data = _inject_opening_range_columns(
                    headers, data, self._opening_range_map, self._name_to_symbol
                )
            except Exception as exc:
                _log_worker_error("LMV live read/merge failed")
                self.failed.emit(f"Read error: {exc}"[:200])
                return
            try:
                active = [s for s in strategies if s.get("active")]
                if active:
                    from services.strategy_engine import apply_strategies
                    from services import lmv_inception_fields
                    disp_headers, disp_data = apply_strategies(
                        active, headers, data, day_history,
                        inception_values=lmv_inception_fields.current_snapshot(),
                    )
                else:
                    disp_headers, disp_data = headers, data
            except Exception as exc:
                _log_worker_error("LMV strategy evaluation failed on a live tick")
                self.failed.emit(f"Strategy error: {exc}"[:200])
                return
            self.result.emit(headers, data, disp_headers, disp_data)
        except Exception as exc:
            # Belt-and-braces: a failure in an emit slot's cross-thread
            # marshaling, or anything else not covered above, still self-heals.
            _log_worker_error("LMV live tick failed unexpectedly")
            self.failed.emit(f"Live update error: {exc}"[:200])

    def shutdown(self) -> None:
        if self._started:
            try:
                self._reader.stop()
            except Exception:
                pass
            self._started = False


# ── Strategy selector popup ────────────────────────────────────────────────

class StrategyPickerPopup(QWidget):
    """Floating popup to enable/disable individual strategies on the LMV."""

    applied = Signal(list)   # emits updated strategy list

    def __init__(self, strategies: list, theme=None, parent=None):
        super().__init__(parent,
                         Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._strategies = [dict(s) for s in strategies]
        self._theme      = theme
        self._checks: list[QCheckBox] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg        = t.get("card_bg")        if t else "#1c2128"
        win_bg    = t.get("background")    if t else "#0d1117"
        bd        = t.get("border")        if t else "#30363d"
        txt       = t.get("text_primary")  if t else "#e6edf3"
        txts      = t.get("text_secondary")if t else "#8b949e"
        accent    = t.get("accent")        if t else "#39d353"
        inp_bg    = t.get("input_bg")      if t else "#0d1117"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(260)
        card.setObjectName("liveViewerCard")
        card.setStyleSheet(
            f"QFrame#liveViewerCard{{background:{bg};border:1px solid {bd};border-radius:10px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        # Title
        hdr_row = QHBoxLayout()
        title = QLabel("Strategies")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color:{txt};border:none;")
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        lay.addLayout(hdr_row)

        if not self._strategies:
            empty = QLabel("No strategies defined yet.\nGo to Strategy Builder.")
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setStyleSheet(f"color:{txts};border:none;")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        else:
            # Search box — filters the checkbox list below by name, so a
            # large strategy count stays navigable.
            search = QLineEdit()
            search.setPlaceholderText("Search strategies…")
            search.setFixedHeight(28)
            search.setFont(font_scale.font(font_scale.SMALL, False))
            search.setStyleSheet(
                f"QLineEdit{{background:{inp_bg};color:{txt};"
                f"border:1px solid {bd};border-radius:6px;padding:0 8px;}}"
                f"QLineEdit:focus{{border-color:{accent};}}"
            )
            search.textChanged.connect(self._filter_checks)
            lay.addWidget(search)

            # Checkbox per strategy, in a bounded, scrollable list so the
            # popup doesn't grow off-screen when there are many strategies.
            list_widget = QWidget()
            list_lay = QVBoxLayout(list_widget)
            list_lay.setContentsMargins(0, 0, 0, 0)
            list_lay.setSpacing(2)
            for strat in self._strategies:
                cb = QCheckBox(strat.get("name", "Unnamed"))
                cb.setChecked(strat.get("active", True))
                cb.setFont(font_scale.font(font_scale.SMALL, False))
                cb.setFixedHeight(30)
                cb.setStyleSheet(
                    f"QCheckBox{{color:{txt};background:transparent;border:none;"
                    "padding:0 4px;border-radius:4px;spacing:8px;}"
                    f"QCheckBox:hover{{background:{accent}12;}}"
                    f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
                    f"border:1.5px solid {bd};background:{inp_bg};}}"
                    f"QCheckBox::indicator:checked{{background:{accent};"
                    f"border-color:{accent};}}"
                )
                self._checks.append(cb)
                list_lay.addWidget(cb)
            list_lay.addStretch()

            scroll = QScrollArea()
            scroll.setWidget(list_widget)
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QFrame.Shape.NoFrame)
            scroll.setMaximumHeight(320)
            scroll.setStyleSheet("QScrollArea{background:transparent;border:none;}")
            lay.addWidget(scroll)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{bd};border:none;")
        lay.addWidget(div)

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(32)
        apply_btn.setFont(font_scale.font(font_scale.SMALL, True))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{accent};color:{win_bg};"
            "border:none;border-radius:6px;}}"
            f"QPushButton:hover{{background:{accent}dd;}}"
        )
        apply_btn.clicked.connect(self._apply)
        lay.addWidget(apply_btn)

        outer.addWidget(card)

    def _filter_checks(self, text: str):
        q = text.strip().lower()
        for cb in self._checks:
            cb.setVisible(q in cb.text().lower())

    def _apply(self):
        for i, cb in enumerate(self._checks):
            if i < len(self._strategies):
                self._strategies[i]["active"] = cb.isChecked()
        self.applied.emit(self._strategies)
        self.close()


class _StrategyNamesPopup(QWidget):
    """Read-only, vertically scrollable list of every active strategy name —
    opened from LiveViewerWindow's bottom-right "view more" link when there
    are more active strategies than fit inline (see
    LiveViewerWindow._update_strategy_names_label)."""

    _MAX_HEIGHT = 260

    def __init__(self, names: list, theme=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._names = names
        self._theme = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg     = t.get("card_bg")        if t else "#1c2128"
        border = t.get("border")         if t else "#30363d"
        txt    = t.get("text_primary")   if t else "#e6edf3"
        txt_s  = t.get("text_secondary") if t else "#8b949e"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(260)
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(8)

        title = QLabel(f"Active Strategies ({len(self._names)})")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color: {txt}; border: none;")
        lay.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFixedHeight(self._MAX_HEIGHT)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        list_lay = QVBoxLayout(list_widget)
        list_lay.setContentsMargins(0, 0, 0, 0)
        list_lay.setSpacing(4)
        for name in self._names:
            lbl = QLabel(name)
            lbl.setFont(font_scale.font(font_scale.SMALL, False))
            lbl.setStyleSheet(f"color: {txt_s}; border: none;")
            lbl.setWordWrap(True)
            list_lay.addWidget(lbl)
        list_lay.addStretch()
        scroll.setWidget(list_widget)
        lay.addWidget(scroll)

        outer.addWidget(card)


class FilterPanelPopup(QWidget):
    """Unified floating filter panel — columns, category, and sector in one place."""

    columns_requested = Signal()
    category_changed  = Signal(str)
    sector_changed    = Signal(str)
    cleared           = Signal()

    def __init__(self, current_category: str, current_sector: str,
                 sectors: list, col_visible: int, col_total: int,
                 theme=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._current_category = current_category
        self._current_sector   = current_sector
        self._sectors          = sectors
        self._col_visible      = col_visible
        self._col_total        = col_total
        self._theme            = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg     = t.get("card_bg")        if t else "#1c2128"
        border = t.get("border")         if t else "#30363d"
        txt    = t.get("text_primary")   if t else "#e6edf3"
        txt_s  = t.get("text_secondary") if t else "#8b949e"
        accent = t.get("accent")         if t else "#39d353"
        inp_bg = t.get("input_bg")       if t else "#0d1117"
        red    = t.get("status_red")     if t else "#f85149"

        any_active = (self._current_category != "All"
                      or self._current_sector != "All"
                      or self._col_visible < self._col_total)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(300)
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Filters")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color: {txt}; border: none;")
        hdr.addWidget(title)
        hdr.addStretch()
        if any_active:
            clear_btn = QPushButton("Clear all")
            clear_btn.setFixedHeight(24)
            clear_btn.setFont(font_scale.font(font_scale.SMALL, False))
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {txt_s};"
                f"border: 1px solid {border}; border-radius: 4px; padding: 0 8px; }}"
                f"QPushButton:hover {{ color: {red}; border-color: {red}; }}"
            )
            clear_btn.clicked.connect(self._on_clear)
            hdr.addWidget(clear_btn)
        lay.addLayout(hdr)

        # ── Divider ───────────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {border}; border: none;")
        lay.addWidget(div)

        combo_ss = (
            f"QComboBox {{ background: {inp_bg}; color: {txt};"
            f"border: 1px solid {border}; border-radius: 6px; padding: 0 10px; }}"
            f"QComboBox:hover {{ border-color: {accent}; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        )

        def _row(label_text, widget):
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(72)
            lbl.setFont(font_scale.font(font_scale.SMALL, False))
            lbl.setStyleSheet(f"color: {txt_s}; border: none;")
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            return row

        # ── Columns row ───────────────────────────────────────────────────────
        col_label = ("All visible" if self._col_visible == self._col_total
                     else f"{self._col_visible} / {self._col_total} visible")
        col_btn = QPushButton(f"⊞  {col_label}")
        col_btn.setFixedHeight(32)
        col_btn.setFont(font_scale.font(font_scale.SMALL, False))
        col_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        col_color = accent if self._col_visible < self._col_total else txt
        col_btn.setStyleSheet(
            f"QPushButton {{ background: {inp_bg}; color: {col_color};"
            f"border: 1px solid {border}; border-radius: 6px; padding: 0 10px; text-align: left; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        col_btn.clicked.connect(self._on_columns_clicked)
        lay.addLayout(_row("Columns", col_btn))

        # ── Category row ──────────────────────────────────────────────────────
        cat_combo = QComboBox()
        cat_combo.addItems(["All", "Daily", "Weekly", "Monthly", "Common"])
        cat_combo.setCurrentText(self._current_category)
        cat_combo.setFixedHeight(32)
        cat_combo.setFont(font_scale.font(font_scale.SMALL, False))
        cat_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        cat_combo.setStyleSheet(combo_ss)
        cat_combo.currentTextChanged.connect(self.category_changed)
        lay.addLayout(_row("Category", cat_combo))

        # ── Sector row ────────────────────────────────────────────────────────
        sec_combo = QComboBox()
        sec_combo.addItem("All")
        for s in self._sectors:
            sec_combo.addItem(s)
        sec_combo.setCurrentText(self._current_sector)
        sec_combo.setFixedHeight(32)
        sec_combo.setFont(font_scale.font(font_scale.SMALL, False))
        sec_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        sec_combo.setStyleSheet(combo_ss)
        sec_combo.currentTextChanged.connect(self.sector_changed)
        lay.addLayout(_row("Sector", sec_combo))

        outer.addWidget(card)

    def _on_columns_clicked(self):
        self.close()
        self.columns_requested.emit()

    def _on_clear(self):
        self.cleared.emit()
        self.close()


# ── Value-change highlight colors manager ───────────────────────────────────

class HighlightColorManagerDialog(QDialog):
    """Per-column value-change highlight colors.

    A "Default" row (used by any column with no override of its own) plus
    one row per column currently on screen. Selecting a row shows a preset
    swatch grid + custom-color button scoped to that row; picking one
    applies immediately (emits default_changed / column_changed) so the
    dialog can stay open while colors are picked for several columns in a
    row, instead of a multi-field form with a separate Save step.
    """

    default_changed = Signal(object)         # str "#rrggbb" or None ("theme default")
    column_changed  = Signal(str, object)     # column name, str or None ("use default")

    def __init__(self, columns: list, default_color: str | None,
                 column_colors: dict, theme=None, parent=None):
        super().__init__(parent)
        self._columns        = list(columns)
        self._default_color  = default_color
        self._column_colors  = dict(column_colors)
        self._theme          = theme
        self._selected_target = None   # None = the "Default" row
        self.setWindowTitle("Value-Change Highlight Colors")
        self.setFixedSize(440, 480)
        self._build()
        self._refresh_list()

    def _theme_amber(self) -> str:
        t = self._theme
        try:
            return t.get("status_amber") if t else "#d29922"
        except KeyError:
            return "#d29922"

    def _effective(self, target: str | None) -> str:
        if target is None:
            return self._default_color or self._theme_amber()
        return self._column_colors.get(target) or self._default_color or self._theme_amber()

    def _build(self):
        t      = self._theme
        bg     = t.get("background")     if t else "#0d1117"
        cbd    = t.get("card_bg")        if t else "#1c2128"
        border = t.get("border")         if t else "#30363d"
        txt    = t.get("text_primary")   if t else "#e6edf3"
        txt_s  = t.get("text_secondary") if t else "#8b949e"
        accent = t.get("accent")         if t else "#39d353"

        self.setStyleSheet(
            f"QDialog {{ background: {bg}; color: {txt}; }}"
            f"QWidget {{ background: {bg}; color: {txt}; }}"
            f"QLabel {{ background: transparent; }}"
            f"QPushButton {{ background: {cbd}; color: {txt}; border: 1px solid {border};"
            f"border-radius: 4px; padding: 4px 10px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
            f"QListWidget {{ background: {cbd}; color: {txt}; border: 1px solid {border}; outline: none; }}"
            f"QListWidget::item {{ padding: 6px 10px; }}"
            f"QListWidget::item:selected {{ background: {accent}; color: {bg}; }}"
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("Value-Change Highlight Colors")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        root.addWidget(title)

        hint = QLabel("Pick a column to give it its own flash color, or set "
                      "the Default used by every column without one.")
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color: {txt_s};")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self._list = QListWidget()
        self._list.setFixedHeight(180)
        self._list.currentRowChanged.connect(self._on_row_changed)
        root.addWidget(self._list)

        self._target_lbl = QLabel()
        self._target_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        root.addWidget(self._target_lbl)

        self._grid_container = QWidget()
        self._grid_lay = QHBoxLayout(self._grid_container)
        self._grid_lay.setContentsMargins(0, 0, 0, 0)
        self._grid_lay.setSpacing(8)
        root.addWidget(self._grid_container)

        self._custom_btn = QPushButton("Custom color…")
        self._custom_btn.setFixedHeight(30)
        self._custom_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._custom_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._custom_btn.clicked.connect(self._pick_custom)
        root.addWidget(self._custom_btn)

        root.addStretch()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: {bg};"
            f"border: none; border-radius: 4px; padding: 4px 20px; }}"
        )
        close_btn.clicked.connect(self.accept)
        close_row.addWidget(close_btn)
        root.addLayout(close_row)

    def _refresh_list(self):
        self._list.blockSignals(True)
        prev_row = max(self._list.currentRow(), 0)
        self._list.clear()

        default_item = QListWidgetItem(_swatch_icon(self._effective(None)),
                                       "Default (all other columns)")
        default_item.setData(Qt.ItemDataRole.UserRole, None)
        self._list.addItem(default_item)

        for col in self._columns:
            label = f"{col}  (custom)" if col in self._column_colors else col
            item = QListWidgetItem(_swatch_icon(self._effective(col)), label)
            item.setData(Qt.ItemDataRole.UserRole, col)
            self._list.addItem(item)

        self._list.blockSignals(False)
        self._list.setCurrentRow(min(prev_row, self._list.count() - 1))

    def _on_row_changed(self, row: int):
        item = self._list.item(row)
        self._selected_target = item.data(Qt.ItemDataRole.UserRole) if item else None
        self._rebuild_detail()

    def _rebuild_detail(self):
        target = self._selected_target
        self._target_lbl.setText(
            "Default color" if target is None else f"Highlight color for [{target}]"
        )
        while self._grid_lay.count():
            item = self._grid_lay.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()

        t      = self._theme
        border = t.get("border") if t else "#30363d"
        accent = t.get("accent") if t else "#39d353"
        # The override actually stored for this target — distinct from
        # _effective(), which also folds in the fallback chain. Comparing
        # against the raw override (not the resolved color) is what lets the
        # "reset" swatch (color=None) show as selected exactly when there
        # isn't one, rather than never (a fallback color could coincidentally
        # match a preset).
        override = self._default_color if target is None else self._column_colors.get(target)

        reset_label = "Theme Default" if target is None else "Use Default"
        presets = [(reset_label, None)] + _HIGHLIGHT_PRESETS
        for label, color in presets:
            swatch = QPushButton()
            swatch.setFixedSize(28, 28)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.setToolTip(label)
            fill = color if color else self._theme_amber()
            ring = accent if color == override else border
            swatch.setStyleSheet(
                f"QPushButton {{ background: {fill}; border: 2px solid {ring};"
                f"border-radius: 6px; }}"
                f"QPushButton:hover {{ border-color: {accent}; }}"
            )
            swatch.clicked.connect(lambda _, c=color: self._apply(c))
            self._grid_lay.addWidget(swatch)
        self._grid_lay.addStretch()

    def _pick_custom(self):
        initial = QColor(self._effective(self._selected_target))
        color = QColorDialog.getColor(initial, self, "Pick Highlight Color")
        if color.isValid():
            self._apply(color.name())

    def _apply(self, color: str | None):
        target = self._selected_target
        if target is None:
            self._default_color = color
            self.default_changed.emit(color)
        else:
            if color is None:
                self._column_colors.pop(target, None)
            else:
                self._column_colors[target] = color
            self.column_changed.emit(target, color)
        self._refresh_list()
        self._rebuild_detail()


class LiveViewerWindow(QWidget):
    """
    Standalone window showing the merged master table in real-time.

    Two update drivers:
      * QFileSystemWatcher (OS-level events) for disk-based broker exports.
      * On Windows, a fast COM poll for the in-memory DDE values Sharekhan
        never flushes to disk (the only driver for its live prices).

    Reads/merges run on a worker thread so a slow read never freezes the UI.
    Changed cells are highlighted amber for ~4 seconds.
    """

    # Emitted from the GUI thread to drive work on the worker thread.
    # The day_history/notif_configs args are declared `object`, not `dict` —
    # day_history's keys are (col_name, days) tuples, and a plain
    # Signal(dict) marshals cross-thread via QVariantMap, which requires
    # string keys and silently converts anything else to {} instead of
    # raising (Shiboken logs "_pythonToCppCopy: Cannot copy-convert ...
    # (dict) to C++" to stderr, easy to miss) — the exact reason a _DAYS
    # column could render empty with no visible error. `object` passes the
    # real Python dict through unchanged. See day_history_result above.
    _request_read      = Signal(bool, float, list, object)  # force_slow, settle_seconds, strategies, day_history
    _request_recompute = Signal(list, list, list, object)   # headers, data, strategies, day_history
    _request_shutdown  = Signal()              # release COM on the worker thread
    _request_or_refresh = Signal()             # re-pull today's Opening Range snapshot
    # strategies, selected_category, reload_from_store — see
    # _refresh_day_history/_refresh_day_history_from_store and
    # _LiveDataWorker.refresh_day_history. Drives BOTH the toggle/category-
    # change path (reload_from_store=False) and the initial-load/"↻ N-Day
    # Data" path (True) — notif_configs is no longer a GUI-thread input,
    # the worker fetches it itself (see refresh_day_history's docstring).
    _request_day_history = Signal(list, str, bool)
    data_updated       = Signal(list, list)    # headers, data — for downstream consumers
    # self._day_history, whenever it's (re)computed — for downstream
    # consumers (Strategy Builder's compile-test) that need the same
    # _DAYS/VALUE_DAYS_AGO/VALUE_ON_DATE cache this window uses, instead of
    # always seeing an empty one. See _refresh_day_history/
    # _on_day_history_from_store_ready.
    day_history_updated = Signal(object)
    # Fired (queued, from a daemon thread) by services.lmv_inception_fields
    # when the Inception historical-field snapshot finishes loading, so any
    # strategy formula referencing [52WH]/[ATH]/etc. re-renders with real
    # values instead of blanks. See __init__'s ensure_loaded_async wiring.
    _inception_fields_ready = Signal()

    def __init__(self, sharekhan_path: str, reliable_path: str,
                 nifty_paths, script_name_data: list,
                 expiry_date=None, external_path=None,
                 market_profile_path=None, external_mode: str = "file",
                 reliable_mode: str = "file", nifty_mode: str = "file",
                 market_profile_mode: str = "file",
                 theme=None, controller=None, parent=None):
        super().__init__(parent)
        self._sharekhan_path   = sharekhan_path
        self._reliable_path    = reliable_path
        # A single path (str) or a list — LiveDataReader normalizes either.
        self._nifty_paths      = nifty_paths
        self._external_path    = external_path
        self._external_mode    = external_mode
        self._reliable_mode    = reliable_mode
        self._nifty_mode       = nifty_mode
        self._market_profile_mode = market_profile_mode
        self._market_profile_path = market_profile_path
        self._script_name_data = script_name_data
        self._expiry_date      = expiry_date
        self._theme            = theme
        self._controller       = controller

        self._headers: list      = []
        self._data: list[list]   = []
        self._row_key_index: int = 0
        self._dot_state          = True
        self._visible_cols: set  = set()   # populated after first load
        self._sized_col_names: set = set()  # column names already auto-sized — see _populate_table
        self._strategies: list   = []      # injected by DataImportScreen
        self._selected_category: str = "All"
        self._strat_col_defs: list = []    # set each render — see _populate_table
        self._base_col_count: int  = 0     # columns >= this are strategy-formula columns
        # {(col_name, days): {symbol: {agg_name: value}}} — resolves _DAYS
        # historic aggregate functions (services.strategy_engine). Recomputed
        # on load/strategy-toggle/manual refresh, NOT every live tick (each
        # refresh is a historic-snapshot network fetch) — see
        # _refresh_day_history.
        self._day_history: dict = {}
        # Guards _refresh_day_history/_refresh_day_history_from_store (both
        # route through the same worker-thread call — see
        # _request_day_history_refresh) the way self._refreshing guards
        # _request_refresh — a day-history fetch in flight shouldn't launch
        # a second, concurrent one. A request that arrives while one's
        # already running is remembered (_day_history_pending), not
        # dropped, and re-issued once the in-flight one lands — same
        # "coalesce, don't queue, don't drop" pattern _recompute_pending
        # uses for the recompute side of this exact same user action (a
        # strategy toggle triggers both). _day_history_pending_reload
        # tracks whether any of the coalesced requests needed
        # reload_from_store=True (a superset of the False case — it wins).
        self._day_history_refreshing = False
        self._day_history_pending = False
        self._day_history_pending_reload = False

        # Column sort — a snapshot of row order (by "Scrip Name") captured
        # at the moment the user clicks a header, not a live re-sort every
        # tick. Keeping row *position* stable between ticks this way lets
        # the existing position-based live-update fast path (see
        # _update_cells_in_place) keep working correctly while sorted —
        # values still update in place, they just don't jump rows around
        # on every poll. See _resort_now / _on_header_clicked.
        self._sort_col_name: str | None = None
        self._sort_descending: bool = False
        self._row_order: list | None = None    # captured Scrip Name order, or None

        # Build sector lookup from Config Editor's persisted "sector_stock"
        # tab override if the user has saved one, else config_defaults —
        # previously read config_defaults.SECTOR_STOCK_DATA directly, so a
        # rename saved in Config Editor's Sector Stock tab (e.g. LTIM -> LTM
        # to match a vendor feed's own spelling) silently had no effect here
        # even though it looked saved.
        from config_defaults import SECTOR_STOCK_DATA
        from services import config_store
        sector_stock_data = config_store.load_tab("sector_stock", SECTOR_STOCK_DATA)
        # .strip().upper() the key here — _inject_sector_rows looks up by
        # str(scrip).strip().upper() (the live Scrip Name is what's
        # normalized there, not user-typed data), so a stock saved in
        # Config Editor in anything but that exact case/whitespace (e.g.
        # "AtherEnerg" or "Sagility" typed naturally, vs. "MAHABANK" typed
        # in caps) silently never matched — see issue #19.
        self._sector_map: dict = {
            stock.strip().upper(): sector for sector, stock in sector_stock_data
        }

        # Same symbol resolution used by the Opening Range capture job
        # (services/scheduled_jobs.py::_build_opening_range_payload) — needed
        # so the OR.High/OR.Low columns injected below join back to the
        # right row by symbol, not by display name.
        self._or_name_to_symbol: dict = _build_script_name_lookup(self._script_name_data)

        # Live-update bookkeeping
        self._render_sig         = None    # signature of last full rebuild
        self._sized_cols         = set()   # columns already auto-sized once
        self._prev_disp: list[list] = []   # last displayed values (for diffing)
        self._highlights: dict   = {}      # (r, c) → expiry tick count
        self._idle_count         = 0       # consecutive no-change ticks
        self._worker             = None
        self._worker_thread      = None
        self._initial_load_done  = False   # set on the first successful read
        self._initial_render_done = False  # set once _render_initial_table has run
        self._recomputing        = False   # a strategy-toggle recompute is in flight
        self._recompute_pending  = False   # another one was requested while it was

        # Value-change highlight color — a persisted LMV-wide default (None
        # tracks the theme's own status_amber), plus per-column overrides
        # that win over the default when present.
        from services import config_store
        self._highlight_color: str | None = config_store.load_lmv_highlight_color()
        self._column_highlight_colors: dict = config_store.load_lmv_column_highlight_colors()

        self.setWindowTitle("Live Master View")
        self.resize(1300, 700)
        self._build()
        self._setup_watcher()
        self._load_initial()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        t      = self._theme
        accent = t.get("accent")        if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider")       if t else "#30363d"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Top bar ───────────────────────────────────────────────────────────
        top = QHBoxLayout()

        title = QLabel("Live Master View")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        top.addWidget(title)
        top.addStretch()

        self._dot = QLabel("●")
        self._dot.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._dot.setStyleSheet(f"color: {accent};")

        self._status_lbl = QLabel("Watching for changes…")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {text_s};")

        # Hidden combos — keep as instance attrs so existing logic / tests can
        # read their current selection without touching the toolbar layout.
        self._cat_combo = QComboBox(self)
        self._cat_combo.addItems(["All", "Daily", "Weekly", "Monthly", "Common"])
        self._cat_combo.setCurrentText("All")
        self._cat_combo.hide()
        self._cat_combo.currentTextChanged.connect(self._on_category_changed)

        self._sector_combo = QComboBox(self)
        self._sector_combo.addItem("All")
        for s in sorted(set(self._sector_map.values())):
            self._sector_combo.addItem(s)
        self._sector_combo.setCurrentText("All")
        self._sector_combo.hide()
        self._sector_combo.currentTextChanged.connect(self._apply_sector_filter)

        self._filter_btn = QPushButton("⊞  Filters")
        self._filter_btn.setFixedHeight(30)
        self._filter_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._filter_btn.clicked.connect(self._show_filter_panel)

        self._strat_btn = QPushButton("⚡  Strategies")
        self._strat_btn.setFixedHeight(30)
        self._strat_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._strat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._strat_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._strat_btn.clicked.connect(self._show_strategy_picker)

        # Manually re-fetch _DAYS historic aggregate columns (see
        # _refresh_day_history) — those never recompute on a live tick, only
        # on load/strategy-toggle/category-change, so this is the way to
        # pull a fresher N-day value without one of those happening.
        self._day_history_btn = QPushButton("↻  N-Day Data")
        self._day_history_btn.setFixedHeight(30)
        self._day_history_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._day_history_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._day_history_btn.setToolTip(
            "Re-fetch AVG_DAYS/MIN_DAYS/etc. historic aggregate columns — "
            "these don't update on every live tick like other columns do. "
            "Also picks up any new/edited historic-aggregate column saved "
            "in Strategy Builder since this window was opened."
        )
        self._day_history_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._day_history_btn.clicked.connect(self._refresh_day_history_from_store)

        self._export_btn = QPushButton("⭳  Export")
        self._export_btn.setFixedHeight(30)
        self._export_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._export_btn.clicked.connect(self._export)

        self._highlight_btn = QPushButton()
        self._highlight_btn.setFixedSize(30, 30)
        self._highlight_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._highlight_btn.setToolTip("Value-change highlight color")
        self._highlight_btn.clicked.connect(self._show_highlight_color_manager)
        self._refresh_highlight_btn_style()

        self._reset_btn = QPushButton()
        self._reset_btn.setIcon(_svg_icon("reset.svg", text_s))
        self._reset_btn.setIconSize(QSize(15, 15))
        self._reset_btn.setFixedSize(30, 30)
        self._reset_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._reset_btn.setToolTip(
            "Reset view — turns off all strategies, clears the category/sector "
            "filters, column visibility and sort, and puts columns back in "
            "their original order."
        )
        self._reset_btn.setStyleSheet(
            f"QPushButton {{ background: transparent;"
            f"border: 1px solid {divclr}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border-color: {accent}; }}"
        )
        self._reset_btn.clicked.connect(self._reset_view)

        top.addWidget(self._dot)
        top.addSpacing(4)
        top.addWidget(self._status_lbl)
        top.addSpacing(12)
        top.addWidget(self._filter_btn)
        top.addSpacing(8)
        top.addWidget(self._strat_btn)
        top.addSpacing(8)
        top.addWidget(self._day_history_btn)
        top.addSpacing(8)
        top.addWidget(self._export_btn)
        top.addSpacing(8)
        top.addWidget(self._highlight_btn)
        top.addSpacing(8)
        top.addWidget(self._reset_btn)
        root.addLayout(top)

        # ── Divider ───────────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {divclr};")
        root.addWidget(div)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setFont(font_scale.font(font_scale.SMALL, False))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        hdr.setStretchLastSection(True)
        hdr.setSectionsMovable(True)
        hdr.sectionMoved.connect(self._on_section_moved)
        hdr.sectionResized.connect(self._on_section_resized)
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.sectionClicked.connect(self._on_header_clicked)
        self._table.setShowGrid(True)
        self._table.cellClicked.connect(self._on_cell_clicked)
        root.addWidget(self._table, 1)

        self._setup_frozen_column()

        # ── Busy indicator ───────────────────────────────────────────────────
        # A thin, otherwise-invisible strip that appears only while a
        # strategy toggle/category change's background work (day-history
        # refresh and/or recompute — both run entirely on the worker thread,
        # see _request_day_history_refresh/_recompute_display) is in flight.
        # Indeterminate (setRange(0, 0) — no meaningful "% done" for this),
        # just enough to tell the user something's happening instead of the
        # table appearing to sit there doing nothing for however long a
        # large sheet/strategy set takes. See _update_busy_indicator.
        self._busy_bar = QProgressBar()
        self._busy_bar.setFixedHeight(3)
        self._busy_bar.setTextVisible(False)
        self._busy_bar.setRange(0, 0)
        self._busy_bar.setVisible(False)
        root.addWidget(self._busy_bar)

        # ── Bottom bar ────────────────────────────────────────────────────────
        bottom = QHBoxLayout()
        self._stock_count_lbl = QLabel("Stocks : 0")
        self._stock_count_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._stock_count_lbl.setStyleSheet(f"color: {text_s};")
        bottom.addWidget(self._stock_count_lbl)
        bottom.addStretch()
        self._strategy_names_lbl = QLabel("")
        self._strategy_names_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._strategy_names_lbl.setStyleSheet(f"color: {text_s};")
        self._strategy_names_lbl.setTextInteractionFlags(Qt.TextInteractionFlag.LinksAccessibleByMouse)
        self._strategy_names_lbl.linkActivated.connect(self._show_strategy_names_popup)
        self._all_active_strategy_names: list = []
        bottom.addWidget(self._strategy_names_lbl)
        root.addLayout(bottom)

        # ── Pulse timer ───────────────────────────────────────────────────────
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(800)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start()

    # ── File watching / COM polling ───────────────────────────────────────────

    def _setup_watcher(self):
        from services.com_reader import is_available as com_available
        from services.live_merge import LiveDataReader

        self._use_com    = com_available()
        self._refreshing = False   # re-entrancy guard so fast ticks don't pile up
        self._refresh_started_at = None   # when the in-flight read began (stall watchdog)

        # Stateful reader: caches COM handles + slow sources (Reliable/Nifty).
        # Used exclusively by the worker thread — including the very first
        # read, so a slow ExternalImport "database" fetch never blocks the
        # GUI thread even on initial load.
        self._reader = LiveDataReader(
            self._sharekhan_path, self._reliable_path, self._nifty_paths,
            self._script_name_data, expiry_date=self._expiry_date,
            use_com=self._use_com, external_path=self._external_path,
            market_profile_path=self._market_profile_path,
            external_mode=self._external_mode,
            reliable_mode=self._reliable_mode, nifty_mode=self._nifty_mode,
            market_profile_mode=self._market_profile_mode,
        )

        # Worker thread: all reads/merges AND strategy-formula computation run
        # here so neither a slow read nor a large apply_strategies() call ever
        # blocks the UI.  Requests go out via _request_read; results come
        # back via queued signals (thread-safe).
        self._worker_thread = QThread(self)
        self._worker        = _LiveDataWorker(self._reader, self._sector_map, self._or_name_to_symbol)
        self._worker.moveToThread(self._worker_thread)
        self._request_read.connect(self._worker.do_read)
        self._request_recompute.connect(self._worker.recompute)
        self._request_shutdown.connect(self._worker.shutdown)
        self._request_or_refresh.connect(self._worker.refresh_opening_range)
        self._request_day_history.connect(self._worker.refresh_day_history)
        self._worker.result.connect(self._on_data_ready)
        self._worker.failed.connect(self._on_read_failed)
        self._worker.recompute_result.connect(self._on_recompute_ready)
        self._worker.recompute_failed.connect(self._on_recompute_failed)
        self._worker.opening_range_ready.connect(self._on_opening_range_ready)
        self._worker.day_history_result.connect(self._on_day_history_from_store_ready)
        self._worker.day_history_failed.connect(self._on_day_history_from_store_failed)
        self._worker_thread.start()

        # Load HMV's historical Group A/B fields (52WH, ATH, gap codes, ...)
        # for the "Inception Field" formula section, off the GUI thread and
        # disk-cached (see services.lmv_inception_fields). LMV renders now;
        # these fields are blank until the walk finishes, then _recompute_
        # display() re-runs apply_strategies with the real values. Queued so
        # the daemon-thread (or already-loaded synchronous) callback always
        # lands on the GUI thread's event loop, never mid-__init__.
        self._inception_fields_ready.connect(
            self._recompute_display, Qt.ConnectionType.QueuedConnection
        )
        try:
            from services import lmv_inception_fields
            lmv_inception_fields.ensure_loaded_async(self._inception_fields_ready.emit)
        except Exception:
            pass

        # Opening Range High/Low only changes once a day (the capture job
        # fires once, ~15min after market open) — a coarse 60s poll here,
        # decoupled from the fast COM/disk tick rate above, is enough to
        # pick it up shortly after it lands without hammering the server.
        self._or_timer = QTimer(self)
        self._or_timer.setInterval(60_000)
        self._or_timer.timeout.connect(self._request_or_refresh.emit)
        self._or_timer.start()
        QTimer.singleShot(0, self._request_or_refresh.emit)

        # Safety net for teardown that bypasses closeEvent (e.g. the widget is
        # garbage-collected directly).  Qt emits destroyed() before deleting
        # child objects, so the thread is still alive here and can be stopped.
        # Capture the thread only — never self, which is mid-destruction.
        _t = self._worker_thread
        self.destroyed.connect(lambda: (_t.quit(), _t.wait(2000)))

        # Always watch the Sharekhan file on disk — covers saves from any broker software.
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.addPath(self._sharekhan_path)
        self._fs_watcher.fileChanged.connect(self._on_file_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        # Disk path: data may still be mid-write, so let it settle first.
        self._debounce.timeout.connect(self._refresh_from_disk)

        if self._use_com:
            # Windows + pywin32: poll COM for the in-memory DDE values (Sharekhan
            # live prices + TradeTiger Snap) that are never flushed to disk.  This
            # is the only driver for Sharekhan's live updates, so it polls fast.
            # COM reads Excel's in-memory state, which is always consistent — no
            # settle delay needed, keeping the LMV in lock-step with the sheet.
            self._com_timer = QTimer(self)
            self._com_timer.setInterval(_COM_POLL_MS)
            self._com_timer.timeout.connect(self._refresh_live)
            self._com_timer.start()

        # Highlight sweep: revert expired amber cells back to normal.
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(_SWEEP_MS)
        self._sweep_timer.timeout.connect(self._sweep_highlights)
        self._sweep_timer.start()

    def _on_file_changed(self, path: str):
        # Re-add watch if the app briefly removed the file on save
        if path not in self._fs_watcher.files():
            if os.path.exists(path):
                self._fs_watcher.addPath(path)
        self._debounce.start()

    # ── Data ─────────────────────────────────────────────────────────────────

    def _load_initial(self):
        # Synchronous first read so callers (DataImportScreen) can read
        # _headers immediately after construction.  Runs on the GUI thread,
        # so it does NOT start COM here — COM is initialised and used solely on
        # the worker thread (COM apartment affinity).  This first read therefore
        # uses the disk fallback; the worker's COM reads take over thereafter.
        #
        # This is intentionally NOT routed through the worker thread like
        # regular ticks are: doing so once made every construction dispatch
        # real cross-thread work immediately, and tearing the window down
        # (e.g. test teardown, or a user closing it right after opening)
        # before that in-flight work finished crashed the process — Qt
        # delivering a queued signal to a receiver mid-destruction. A
        # synchronous first read has no such race.
        try:
            headers, data = self._reader.read_merged(force_slow=True)
        except Exception as exc:
            self._status_lbl.setText(f"Error loading: {exc}")
            return
        headers, data = self._inject_sector(headers, data)
        # No server round-trip on this synchronous first read (see this
        # method's docstring on why it stays off the worker thread) — the
        # worker's periodic _or_timer fetch (started in _setup_watcher,
        # which already ran before this) fills OR.High/OR.Low in shortly
        # after via the first live tick. Empty map here just means "—" for
        # one frame.
        headers, data = _inject_opening_range_columns(headers, data, {}, self._or_name_to_symbol)
        self._headers = headers
        self._data    = data
        self._initial_load_done = True
        # All columns visible by default
        self._visible_cols = set(range(len(headers)))
        # Defer the actual table build (strategy evaluation across every row
        # plus creating thousands of QTableWidgetItems) to the next event-loop
        # turn, so the window can be shown and painted first instead of
        # blocking behind it — this synchronous build-before-show was what
        # produced a blank / "Not Responding" window while it ran.
        QTimer.singleShot(0, self._render_initial_table)

    def _render_initial_table(self):
        try:
            self._populate_table(self._data, changed_keys=set())
            self._apply_sector_filter()
            self._update_filter_btn_label()
        except Exception as exc:
            # A malformed strategy (e.g. from a schema-less import) must not
            # leave the window construction path half-finished — report it
            # and keep the window usable instead of crashing/going blank.
            from services.error_logging import error_logger
            error_logger.exception("LMV initial render failed")
            self._status_lbl.setText(f"Render error: {exc}")
        finally:
            # Set even on failure — otherwise a set_strategies() call after a
            # bad initial render would wait forever for a render pass that
            # already happened (see set_strategies below).
            self._initial_render_done = True
        # Deferred (not inline above) so the just-built table paints first —
        # this is a historic-snapshot network fetch (plus, on this path, a
        # strategy-store reload — see _refresh_day_history_from_store), and
        # _DAYS columns are rare enough that most windows pay nothing here
        # (collect_day_requests returns empty, the worker call is a no-op
        # recompute). Runs on the worker thread either way, so it never
        # blocks this first paint.
        QTimer.singleShot(0, self._refresh_day_history_from_store)

    def _inject_sector(self, headers: list, data: list) -> tuple:
        """Prepend a Sector column to headers and every data row."""
        return _inject_sector_rows(headers, data, self._sector_map)

    def _refresh_from_disk(self):
        # Disk-based saves (e.g. Sharekhan export on macOS) may still be
        # flushing — let the worker settle briefly before reading.
        self._request_refresh(settle=_FILE_SETTLE_S)

    def _refresh_live(self):
        # COM reads Excel's in-memory state, which is always consistent — no
        # settle delay, keeping the LMV in lock-step with the sheet.
        self._request_refresh(settle=0.0)

    def _on_opening_range_ready(self):
        """The worker just refreshed its OR.High/OR.Low map (see
        _LiveDataWorker.refresh_opening_range) — force one read so it's
        injected and rendered right away, instead of waiting on the next
        market-data-driven tick, which may not come for a while (or at all,
        e.g. COM unavailable and a quiet broker file)."""
        self._request_refresh(settle=0.0)

    def _request_refresh(self, settle: float, force: bool = False):
        # Skip if a previous read is still in flight, so fast ticks collapse
        # instead of queueing up and lagging behind.
        if self._worker is None:
            return
        if self._refreshing:
            # Stall watchdog: a read that's been "in flight" far longer than
            # any real tick could take means the worker is wedged — a COM
            # .Value call blocking on a busy Excel, or a do_read exit path
            # that emitted nothing (shouldn't happen after the guards there,
            # but this is the last line of defence). Force-reset so the poll
            # loop recovers instead of freezing on the last "Updated: …" for
            # the rest of the session.
            started = getattr(self, "_refresh_started_at", None)
            if started is None or (time.monotonic() - started) < _REFRESH_STALL_S:
                return
            from services.error_logging import error_logger
            error_logger.error(
                "LMV refresh stalled %.0fs — force-resetting the poll loop",
                time.monotonic() - started,
            )
        self._refreshing = True
        self._refresh_started_at = time.monotonic()
        # Snapshot, not a live reference — the worker thread must never touch
        # GUI-thread-owned state concurrently. If building the snapshot or the
        # emit itself throws, reset _refreshing here — otherwise it stays True
        # and every later tick early-returns above, silently wedging the poll
        # loop for the rest of the session (the worker's do_read has the same
        # guarantee for its own exit paths).
        try:
            strategies_snapshot = list(self._filtered_strategies())
            self._request_read.emit(force, settle, strategies_snapshot, dict(self._day_history))
        except Exception as exc:
            self._refreshing = False
            _log_worker_error("LMV refresh dispatch failed")
            self._status_lbl.setText(f"Live update error: {exc}"[:200])

    def _on_read_failed(self, msg: str):
        self._refreshing = False
        self._status_lbl.setText(msg)

    def _update_busy_indicator(self):
        """Shows/hides self._busy_bar (the thin strip at the bottom of the
        window, see _build) based on whether a strategy toggle/category
        change's background work — a day-history refresh
        (_day_history_refreshing) and/or a recompute (_recomputing), plus
        anything coalesced behind either while it was running
        (_day_history_pending/_recompute_pending) — is currently in flight.
        Both now run entirely on the worker thread (see
        _request_day_history_refresh/_recompute_display's own docstrings on
        why that used to freeze the window), so without this a user
        applying a strategy on a large sheet/strategy set would see the
        table just sit there for however long that takes, with nothing on
        screen indicating anything is actually happening. Called from every
        point any of those four flags changes."""
        busy = (self._recomputing or self._recompute_pending
                or self._day_history_refreshing or self._day_history_pending)
        self._busy_bar.setVisible(busy)

    def _request_day_history_refresh(self, reload_from_store: bool):
        """Shared trigger for _refresh_day_history/_refresh_day_history_from_store
        below — both route through the same worker-thread call
        (_LiveDataWorker.refresh_day_history) now. This USED to be split
        into a "cheap, synchronous-on-the-GUI-thread" path (no store
        reload, for the strategy-toggle/category-change case) and a
        worker-routed one (with a reload, for initial load/"↻ N-Day Data")
        on the reasoning that the synchronous one only ran "occasionally,
        not per tick" — invalidated by services.strategy_engine's Row-Filter
        Streak feature, which made a day-history recompute fire on nearly
        every active-strategy toggle (any row-filtered strategy, not just
        the rare "uses AVG_DAYS" case), turning "occasionally" into "on
        pretty much every strategy toggle" and making that synchronous path
        the actual cause of "LMV strategy apply/load is laggy, sometimes
        Not Responding" reports.

        One request in flight at a time; a request that arrives while one's
        already running is remembered (not dropped) and re-issued once the
        in-flight one lands — same "coalesce, don't queue, don't drop"
        pattern _recompute_display uses for the recompute side of this
        exact same user action (a strategy toggle triggers both).
        reload_from_store=True "wins" if requests of both kinds pile up
        before the in-flight one finishes — it's a superset of the work
        the False case does.
        """
        if self._worker is None:
            # Shouldn't happen once the window is visible — nothing sensible
            # to fall back to for a network-touching call; just skip it.
            return
        if self._day_history_refreshing:
            self._day_history_pending = True
            self._day_history_pending_reload = self._day_history_pending_reload or reload_from_store
            return
        self._day_history_refreshing = True
        self._update_busy_indicator()
        # The full (unfiltered) list, not _filtered_strategies() — the
        # worker applies self._selected_category itself just to decide which
        # requests to fetch, but still needs every strategy's real "active"
        # flag (including ones outside the current category filter — see
        # refresh_day_history's docstring). A snapshot, not a live
        # reference — the worker thread must never touch GUI-thread-owned
        # state concurrently (same rationale as _request_refresh/
        # _recompute_display).
        self._request_day_history.emit(
            list(self._strategies), self._selected_category, reload_from_store)

    def _refresh_day_history(self):
        """Recompute self._day_history — the lookup _DAYS historic aggregate
        functions (services.strategy_engine) resolve against — from scratch,
        then re-render. Runs on a strategy toggle and a category change.

        Resolves requests against self._strategies as already known to this
        window, NOT reloaded from services.strategy_store first (see
        _refresh_day_history_from_store below for the reloading variant,
        used on initial load and by "↻ N-Day Data") — so this won't notice
        a _DAYS column added/edited in Strategy Builder since this window
        opened, trading that for one less server round trip on every
        toggle/category-change, the more frequent of the two occasions.
        """
        self._request_day_history_refresh(reload_from_store=False)

    def _refresh_day_history_from_store(self):
        """Like _refresh_day_history, but also reloads strategy definitions
        from services.strategy_store first (see _LiveDataWorker.
        refresh_day_history) — this is what makes a new/edited AVG_DAYS/
        MIN_DAYS/etc. column show up without closing and reopening Live
        Master View: self._strategies is otherwise only ever injected once
        (set_strategies, called when this window is first built) and
        nothing keeps it in sync with Strategy Builder afterward — plain
        _refresh_day_history() above can't see a request that isn't in that
        stale copy yet.

        Used on initial load and by the "↻ N-Day Data" button only — not by
        the strategy-toggle/category-change paths, which stay on the
        cheaper _refresh_day_history() above so those more frequent
        interactions don't gain an extra server round trip.
        """
        self._request_day_history_refresh(reload_from_store=True)

    def _on_day_history_from_store_ready(self, day_history: dict, strategies: list):
        self._day_history_refreshing = False
        self._day_history = day_history
        self.day_history_updated.emit(self._day_history)
        self._strategies = strategies
        self._update_strat_btn_label()
        self._recompute_display()
        self._run_pending_day_history_refresh()
        self._update_busy_indicator()

    def _on_day_history_from_store_failed(self, msg: str, strategies: list):
        self._day_history_refreshing = False
        # Still apply the reloaded strategy definitions — a failure here is
        # specifically the historic-snapshot fetch (see
        # _LiveDataWorker.refresh_day_history), not the store reload, so a
        # new/edited column's header/other-column values shouldn't be held
        # back by it. self._day_history itself is left untouched, same
        # "keep the previous cache on failure" rule as _refresh_day_history.
        self._strategies = strategies
        self._update_strat_btn_label()
        self._status_lbl.setText(msg)
        self._recompute_display()
        self._run_pending_day_history_refresh()
        self._update_busy_indicator()

    def _run_pending_day_history_refresh(self):
        """See _request_day_history_refresh's docstring on why a request
        that arrived while one was already in flight is coalesced here
        rather than dropped."""
        if not self._day_history_pending:
            return
        reload_from_store = self._day_history_pending_reload
        self._day_history_pending = False
        self._day_history_pending_reload = False
        self._request_day_history_refresh(reload_from_store)

    def _recompute_display(self):
        """Re-render the table after a strategy toggle or category change.

        apply_strategies() — the O(rows x strategies x columns) formula
        evaluation _populate_table's docstring warns about — runs on the
        worker thread via _request_recompute instead of inline here, so a
        large sheet/strategy set doesn't freeze the GUI thread for the whole
        rebuild the way it used to. self._data/_headers aren't changing (no
        new read), only the strategy output columns are being recomputed.

        Falls back to the old synchronous path if the worker isn't up yet —
        shouldn't happen once the window is visible, but keeps this callable
        safely at any point.
        """
        if self._worker is None:
            self._populate_table(self._data, set())
            self._apply_sector_filter()
            self._update_filter_btn_label()
            return
        if self._recomputing:
            # A recompute is already in flight — don't queue a second worker
            # call, just remember to run once more with the latest state
            # when this one lands (see _on_recompute_ready/_on_recompute_failed).
            self._recompute_pending = True
            return
        self._recomputing = True
        self._update_busy_indicator()
        # Snapshots, not live references — the worker thread must never touch
        # GUI-thread-owned state concurrently (same rationale as _request_refresh).
        self._request_recompute.emit(
            list(self._headers), [list(r) for r in self._data],
            [dict(s) for s in self._filtered_strategies()],
            dict(self._day_history),
        )

    def _on_recompute_ready(self, disp_headers: list, disp_data: list):
        try:
            self._populate_table(self._data, changed_keys=set(),
                                 precomputed_disp=(disp_headers, disp_data))
            self._apply_sector_filter()
            self._update_filter_btn_label()
        except Exception as exc:
            from services.error_logging import error_logger
            error_logger.exception("LMV strategy recompute render failed")
            self._status_lbl.setText(f"Render error: {exc}")
        finally:
            self._recomputing = False
            if self._recompute_pending:
                self._recompute_pending = False
                self._recompute_display()
            self._update_busy_indicator()

    def _on_recompute_failed(self, msg: str):
        self._recomputing = False
        self._status_lbl.setText(msg)
        if self._recompute_pending:
            self._recompute_pending = False
            self._recompute_display()
        self._update_busy_indicator()

    def _on_data_ready(self, headers: list, new_data: list,
                      disp_headers: list, disp_data: list):
        from datetime import datetime
        try:
            self._data    = new_data
            self._headers = headers
            if not self._initial_load_done:
                self._initial_load_done = True
                self._visible_cols = set(range(len(headers)))
            # disp_headers/disp_data already have apply_strategies() applied
            # (computed on the worker thread) — _populate_table only needs to
            # turn them into Qt widgets here.
            self._populate_table(new_data, changed_keys=None,
                                 precomputed_disp=(disp_headers, disp_data))
            self._apply_sector_filter()
            self._update_filter_btn_label()
            self._status_lbl.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
            self._adapt_poll_rate(getattr(self, "_last_change_count", 0))
            self.data_updated.emit(self._headers, self._data)
        except Exception as exc:
            # A bad tick (e.g. a malformed strategy formula) must not crash
            # the poll loop or leave the table stuck half-rendered/blank —
            # report it and keep polling; the next good tick self-heals it.
            from services.error_logging import error_logger
            error_logger.exception("LMV render failed for this tick")
            self._status_lbl.setText(f"Render error: {exc}")
        finally:
            self._refreshing = False

    def _adapt_poll_rate(self, changed: int):
        """
        Back off the COM poll when the data is quiet, and snap back to the fast
        rate the instant something changes.  Reduces idle COM load (e.g. when
        the market is closed) without ever adding lag to live ticks.
        """
        if not hasattr(self, "_com_timer"):
            return
        if changed > 0:
            self._idle_count = 0
            if self._com_timer.interval() != _COM_POLL_MS:
                self._com_timer.setInterval(_COM_POLL_MS)
        else:
            self._idle_count += 1
            if (self._idle_count >= _IDLE_TICKS
                    and self._com_timer.interval() != _COM_IDLE_MS):
                self._com_timer.setInterval(_COM_IDLE_MS)


    # ── Table rendering ───────────────────────────────────────────────────────

    @staticmethod
    def _fmt_cell(val) -> str:
        if isinstance(val, float):
            return f"{val:.2f}"
        if val is None:
            return ""
        return str(val)

    def _run_strategy_alert_checks(self, active_strategies: list, all_dicts: list,
                                    sym_index: dict, agg_cache: dict) -> None:
        """Evaluates every strategy with an enabled notification config
        against this render pass's rows (services.strategy_alerts.engine),
        reusing the same all_dicts/sym_index/agg_cache just built for
        conditional-formatting colors — cheap relative to apply_strategies's
        own already-budgeted per-tick cost, since only strategies with a
        notification config actually configured pay anything extra. Runs on
        the GUI thread (unlike apply_strategies, which runs on the worker
        thread) since delivery itself — the OS tray, a sound effect — needs
        to be on the GUI thread anyway; see the plan this feature followed
        for why that trade-off was made deliberately for a first version.

        Every event this tick is delivered as ONE notification per channel,
        not one per event — a market-wide move can cross several strategies'
        triggers on the same tick, and showing/sounding N separate alerts
        back to back (each also a real network call for the Email channel —
        see services/notifications/channels/email.py) is both a worse
        experience and was, before that channel's send() moved to a
        background thread, the actual cause of the app freezing solid.
        Exactly one event still goes out exactly as before (nothing to
        combine); System tray gets a compact per-kind summary (real,
        OS-enforced space limits — services.strategy_alerts.messages caps
        and marks "+N more" rather than let the OS truncate silently), Email
        gets the full per-stock detail for every event, unabridged.
        """
        from services.strategy_alerts import config_store as alerts_config_store
        from services.strategy_alerts import state_store as alerts_state_store
        from services.strategy_alerts.engine import evaluate_tick

        # peek_configs(), not load_configs() — this runs on the GUI thread,
        # on EVERY render pass (every live tick), so it must never risk a
        # live network round trip (see peek_configs' own docstring for the
        # "first tick after login/reload_cache()" scenario that used to
        # block here). Worst case with peek_configs is one tick with no
        # live-alert coverage while the cache is still cold, not a frozen
        # window.
        configs = alerts_config_store.peek_configs()
        if not configs:
            return
        events = evaluate_tick(active_strategies, configs, all_dicts, sym_index,
                               agg_cache, day_history=self._day_history)
        if not events:
            return

        alerts_state_store.flush()

        # Durable, tenant-scoped backend copy of each transition (entry,
        # target achieved, stop-out) — see services/strategy_alerts/
        # backend_sync.py. Dispatched to a background thread per event, same
        # as the notification channels below; never blocks this loop and a
        # sync failure never stops the tray/Email/Slack delivery that follows.
        from services.strategy_alerts import backend_sync
        for event in events:
            backend_sync.sync_event(event)

        notifier = getattr(self._controller, "_notifier", None)
        if notifier is None:
            return
        from services import notification_channels
        from services.notifications.channels.system import SystemChannel

        enabled_channels = notification_channels.enabled_channel_ids()
        if not enabled_channels:
            return

        if len(events) == 1:
            event = events[0]
            notifier.notify(
                event.payload.get("title", event.strategy_name),
                event.payload.get("message", ""),
                channels=enabled_channels,
            )
            return

        from services.strategy_alerts import messages as alert_messages

        title = alert_messages.render_batch_title(events)
        level = alert_messages.render_batch_level(events)

        system_channels = enabled_channels & {SystemChannel.CHANNEL_ID}
        if system_channels:
            notifier.notify(
                title, alert_messages.render_batch_tray_message(events),
                level=level, channels=system_channels,
            )

        other_channels = enabled_channels - {SystemChannel.CHANNEL_ID}
        if other_channels:
            notifier.notify(
                title, alert_messages.render_batch_email_message(events),
                level=level, channels=other_channels,
            )

    def _populate_table(self, data: list[list], changed_keys=set(), precomputed_disp=None):
        """
        Render *data* into the table.

        ``changed_keys=None`` marks a live-data tick: cells whose displayed
        value changed are diffed against the table's current contents and
        flashed amber.  A real set (incl. the empty set) marks a structural
        re-render (theme/strategy/category change) where no highlight is wanted.

        ``precomputed_disp``, when given, is the ``(disp_headers, disp_data)``
        already computed by apply_strategies() on the worker thread (see
        _LiveDataWorker.do_read/recompute and _on_data_ready/_on_recompute_ready)
        — the live-tick, initial-load, and interactive (strategy toggle,
        category change) paths all pass this now, so the O(rows x strategies
        x columns) formula evaluation never runs on the GUI thread. Only a
        direct/manual call (tests, or the _worker-not-ready fallback in
        _recompute_display) omits it and computes inline here instead.
        """
        from services.strategy_engine import apply_strategies, get_row_fmt_colors, build_symbol_index

        highlight = changed_keys is None
        self._last_change_count = 0

        active_strategies = [s for s in self._filtered_strategies() if s.get("active")]
        if precomputed_disp is not None:
            disp_headers, disp_data = precomputed_disp
        elif active_strategies:
            # Apply active strategies — may extend headers and data
            from services import lmv_inception_fields
            disp_headers, disp_data = apply_strategies(
                active_strategies, self._headers, data, self._day_history,
                inception_values=lmv_inception_fields.current_snapshot(),
            )
        else:
            disp_headers, disp_data = self._headers, data

        disp_data = self._apply_row_order(disp_headers, disp_data)

        base_col_count = len(self._headers)

        # Read theme at render time so light/dark toggle is always current
        t = self._theme
        norm_bg  = QColor(t.get("card_bg")      if t else "#1c2128")
        norm_txt = QColor(t.get("text_primary")  if t else "#e6edf3")
        # Built once per render pass and reused for every cell's default
        # (non-highlighted, non-conditionally-formatted) style, rather than
        # a fresh QBrush(norm_bg)/QBrush(norm_txt) per cell — profiling a
        # 220-row x 85-column rebuild showed that allocation adding up at
        # this scale (see _apply_cell_style, called once per cell on every
        # render, including every ordinary live tick's fast in-place path).
        norm_bg_brush  = QBrush(norm_bg)
        norm_txt_brush = QBrush(norm_txt)
        win_bg   = t.get("background")           if t else "#0d1117"
        hdr_bg   = t.get("button_bg")            if t else "#21262d"
        strat_hdr = t.get("accent") + "22"       if t else "#39d35322"
        # One (bg, txt) brush pair per displayed column — built once per
        # render pass (not once per row/cell) and indexed by column position
        # in _update_cells_in_place, so a per-column highlight override costs
        # nothing beyond a handful of extra QBrush allocations per tick.
        self._amber_bg_by_col  = []
        self._amber_txt_by_col = []
        for col_name in disp_headers:
            amber = self._effective_highlight_color(col_name)
            self._amber_bg_by_col.append(QBrush(QColor(amber)))
            self._amber_txt_by_col.append(QBrush(QColor(_contrasting_text(amber))))

        # Build per-column info for strategy columns (for conditional formatting)
        strat_col_defs = []   # list of col_def dicts for strategy cols in order
        for s in active_strategies:
            for col in s.get("columns", []):
                strat_col_defs.append(col)

        # Stashed for _on_cell_clicked (columns >= base_col_count are
        # strategy-formula columns, clickable for a last-N-days popup) —
        # this render pass's values are current until the next one replaces
        # them, which is exactly the window a click needs to stay accurate.
        self._strat_col_defs  = strat_col_defs
        self._base_col_count  = base_col_count

        all_dicts = [dict(zip(disp_headers, row)) for row in disp_data]
        # Memoizes SUM_ALL/AVG_ALL/etc. fmt-rule aggregates for this render
        # pass, so a conditional-format rule referencing an aggregate is
        # computed once instead of once per cell.
        agg_cache: dict = {}
        # Symbol -> row-dict lookup for "[Col of Symbol]" fmt-rule conditions,
        # built once per render pass instead of once per row.
        sym_index = build_symbol_index(all_dicts)

        self._run_strategy_alert_checks(active_strategies, all_dicts, sym_index, agg_cache)

        # ── Fast path ───────────────────────────────────────────────────────
        # When only cell values changed (same headers, same row count, same
        # theme) — the common live-tick case — update existing items in place.
        # This skips item recreation, header relabelling, stylesheet resets and
        # the costly resizeColumnsToContents(), keeping the LMV in lock-step
        # with the source sheet.
        sig = (tuple(disp_headers), len(disp_data),
               id(t), norm_bg.name(), norm_txt.name())
        fast = (
            getattr(self, "_render_sig", None) == sig
            and self._table.rowCount() == len(disp_data)
            and self._table.columnCount() == len(disp_headers)
        )
        if fast:
            self._update_cells_in_place(
                disp_data, disp_headers, all_dicts, strat_col_defs,
                base_col_count, norm_bg_brush, norm_txt_brush, strat_hdr,
                highlight, agg_cache, sym_index,
            )
            self._update_strat_btn_label()
            return

        # ── Full rebuild ────────────────────────────────────────────────────
        # Items are recreated, so any pending highlights no longer map to live
        # items — drop them.
        self._highlights.clear()

        self.setStyleSheet(f"background: {win_bg};")
        table_style = (
            f"QTableWidget {{ background: {norm_bg.name()}; color: {norm_txt.name()}; }}"
            f"QTableWidget QHeaderView::section {{ background: {hdr_bg}; color: {norm_txt.name()}; }}"
        )
        self._table.setStyleSheet(table_style)

        # setItem() below runs 200+ rows x 80+ columns worth of QTableWidgetItem
        # creation whenever the header set changes (any strategy toggle,
        # category change, or column added/removed) — the "fast path" above
        # can't be used since existing items no longer line up 1:1 with the
        # new column layout. Left un-batched, every individual setItem/
        # setColumnHidden call can trigger its own layout/repaint pass on a
        # widget this wide, which is exactly the "LMV gets slow when I apply
        # a strategy" report this traces to. setUpdatesEnabled(False) defers
        # all of that to one repaint when re-enabled — standard Qt batching
        # for exactly this "populate a widget from scratch" shape, and safe
        # here since nothing in this block reads back anything the paint
        # event itself would have produced.
        self._table.setUpdatesEnabled(False)
        try:
            self._table.setColumnCount(len(disp_headers))
            self._table.setHorizontalHeaderLabels(disp_headers)
            self._table.setRowCount(len(disp_data))

            bold_font   = font_scale.font(font_scale.SMALL, True)
            scrip_col   = disp_headers.index("Scrip Name") if "Scrip Name" in disp_headers else -1
            for r, row in enumerate(disp_data):
                row_dict = all_dicts[r]
                row_colors = get_row_fmt_colors(
                    strat_col_defs, row, base_col_count, row_dict, all_dicts,
                    agg_cache, sym_index, self._day_history)
                for c, val in enumerate(row):
                    item = QTableWidgetItem(self._fmt_cell(val))
                    item.setTextAlignment(_CELL_ALIGNMENT)
                    if c == scrip_col:
                        item.setFont(bold_font)
                    self._apply_cell_style(
                        item, c, disp_headers, row_colors, strat_col_defs,
                        base_col_count, norm_bg_brush, norm_txt_brush, strat_hdr,
                    )
                    self._table.setItem(r, c, item)

            # Ensure visible_cols covers strategy columns too
            if len(disp_headers) > len(self._headers):
                for c in range(len(self._headers), len(disp_headers)):
                    self._visible_cols.add(c)

            # Apply column visibility
            for c in range(len(disp_headers)):
                self._table.setColumnHidden(c, c not in self._visible_cols)

            # Auto-size only NEWLY-seen columns, not resizeColumnsToContents()
            # for the whole table on every render — that re-measures EVERY
            # column (text width of every cell in it) even when only a
            # strategy toggle added/removed its OWN one or two columns, with
            # the ~80 base sheet columns unchanged. Profiling a realistic
            # 220-row x 85-column rebuild showed resizeColumnsToContents()
            # alone costing as much as populating every cell in the table
            # combined — exactly the "LMV gets slow when I apply a
            # strategy" report this traces to, since applying/toggling ANY
            # strategy changes disp_headers' shape and so re-triggered a
            # full-table remeasure every time. self._sized_col_names is a
            # persistent set (by column NAME, across the window's whole
            # life, not reset per-render) — a base column is measured once,
            # ever; a strategy column is measured once, the first render it
            # appears in, and skipped on every later render even if the
            # strategy is toggled off and back on (same "user-adjusted
            # widths survive re-renders" intent the old per-render-tuple
            # check aimed for, just without re-measuring untouched columns
            # to get there).
            new_names = [h for h in disp_headers if h not in self._sized_col_names]
            if new_names:
                name_to_idx = {h: i for i, h in enumerate(disp_headers)}
                for name in new_names:
                    self._table.resizeColumnToContents(name_to_idx[name])
                self._sized_col_names.update(new_names)

            self._render_sig = sig
            self._restore_column_order()
            frozen_style = (
                f"QTableView {{ background: {norm_bg.name()}; color: {norm_txt.name()}; "
                f"border-right: 2px solid palette(mid); }}"
                f"QTableView QHeaderView::section {{ background: {hdr_bg}; color: {norm_txt.name()}; }}"
            )
            self._configure_frozen_column(scrip_col, frozen_style)
        finally:
            self._table.setUpdatesEnabled(True)
        self._update_strat_btn_label()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        """Persist the new column order whenever the user drags a header."""
        hdr = self._table.horizontalHeader()
        # Moves this class makes itself (freeze pinning, restoring the saved
        # order) must not be re-persisted as if the user had dragged a
        # column — that would bake a snap-back into the saved order instead
        # of just reverting it for this one render.
        if getattr(self, "_programmatic_reorder", False):
            return
        # "Scrip Name" is frozen at the left edge (see _setup_frozen_column) —
        # any drag that would bump it off visual index 0 (either dragging it
        # away, or dragging another column in front of it) is undone here,
        # without persisting the reverted position.
        col = getattr(self, "_frozen_logical_col", None)
        if col is not None:
            visual = hdr.visualIndex(col)
            if visual != 0:
                self._move_section_programmatically(hdr, visual, 0)
                return
        ordered = [
            self._table.horizontalHeaderItem(hdr.logicalIndex(v)).text()
            for v in range(hdr.count())
            if self._table.horizontalHeaderItem(hdr.logicalIndex(v))
        ]
        from services.config_store import save_column_order
        save_column_order(ordered)

    def _move_section_programmatically(self, hdr, frm: int, to: int):
        """moveSection() re-enters _on_section_moved via its signal — set
        while the move is in flight so that handler knows not to persist it
        as a user-initiated reorder."""
        self._programmatic_reorder = True
        try:
            hdr.moveSection(frm, to)
        finally:
            self._programmatic_reorder = False

    # ── Strategy-column history popup ───────────────────────────────────────

    def _on_cell_clicked(self, row: int, col: int):
        """Click a strategy column cell whose formula references a _DAYS
        historic aggregate function (AVG_DAYS, MIN_DAYS, ...) or a
        VALUE_DAYS_AGO/VALUE_ON_DATE point lookup to see that stock's
        historic value(s) behind the first such reference — no dedicated
        "day-aggregate column type" is needed since AVG_DAYS(...)/
        VALUE_DAYS_AGO(...) IS the column's own formula
        (services.strategy_engine's "Historic (N days) aggregates"/
        "Historic value (point lookup)"). Any other strategy column, or a
        native sheet column, isn't clickable this way."""
        idx = col - self._base_col_count
        if idx < 0 or idx >= len(self._strat_col_defs):
            return
        col_def = self._strat_col_defs[idx]

        from services.strategy_engine import scan_day_funcs
        day_refs = scan_day_funcs(col_def.get("formula", []))
        if not day_refs:
            return
        source_col, window = day_refs[0]

        scrip_col = self._headers.index("Scrip Name") if "Scrip Name" in self._headers else -1
        if scrip_col < 0:
            return
        symbol_item = self._table.item(row, scrip_col)
        if symbol_item is None or not symbol_item.text():
            return
        self._open_formula_history(symbol_item.text(), source_col, window,
                                   col_def.get("name", ""))

    def _resolve_day_source_formula(self, col_name: str) -> list:
        """Mirrors services.strategy_engine.collect_day_requests's own
        resolution: if *col_name* names one of the active strategies' own
        columns, use ITS formula — so "any custom formula over N days"
        drills into the real formula behind AVG_DAYS([MyComputedCol], 20),
        not a literal raw column named "MyComputedCol". Otherwise it's
        treated as a raw sheet/historic column reference."""
        for strat in self._filtered_strategies():
            if not strat.get("active"):
                continue
            for c in strat.get("columns", []):
                if c.get("name") == col_name:
                    return c.get("formula", [])
        return [{"type": "col", "value": col_name}]

    def _open_formula_history(self, symbol: str, source_col_name: str,
                              window, display_name: str):
        """*window* is an int (_DAYS/VALUE_DAYS_AGO: last N days) or a
        (date, date) tuple (VALUE_ON_DATE: one fixed date) — see
        _on_cell_clicked/scan_day_funcs."""
        from components.formula_stats_panel import FormulaStatsPanel, apply_dialog_bg

        t = self._theme
        formula = self._resolve_day_source_formula(source_col_name)
        dlg = QDialog(self)
        dlg.setWindowTitle(f"{symbol} — {display_name}")
        apply_dialog_bg(dlg, t)
        dlg.resize(560, 520)
        lay = QVBoxLayout(dlg)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        is_range = isinstance(window, tuple)
        window_desc = (f"on {window[0]}" if is_range else f"last {window} day(s)")
        desc = QLabel(
            f'"{source_col_name}" behind {display_name} for {symbol}, '
            f"{window_desc}, computed from saved historic data. Right-click "
            f"the row for the day-by-day values."
        )
        desc.setWordWrap(True)
        desc.setFont(font_scale.font(font_scale.SMALL, False))
        desc.setStyleSheet(f"color:{t.get('text_secondary') if t else '#8b949e'};")
        lay.addWidget(desc)

        panel_kwargs = (
            {"initial_date_range": window} if is_range else {"initial_days": window}
        )
        panel = FormulaStatsPanel(
            t, columns=[{"name": source_col_name, "formula": formula}],
            symbol_filter=symbol, parent=dlg, **panel_kwargs,
        )
        lay.addWidget(panel, 1)
        # Click-through convenience: the stock and column are already known
        # from the click, so run immediately instead of waiting on a second
        # Compute click.
        panel.compute()

        close_row = QHBoxLayout()
        close_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dlg.accept)
        close_row.addWidget(close_btn)
        lay.addLayout(close_row)

        dlg.exec()

    # ── Column sort ───────────────────────────────────────────────────────────

    def _on_header_clicked(self, logical_index: int):
        if logical_index is None or logical_index < 0:
            return
        item = self._table.horizontalHeaderItem(logical_index)
        if item is None:
            return
        name = item.text()
        if self._sort_col_name == name:
            self._sort_descending = not self._sort_descending
        else:
            self._sort_col_name = name
            self._sort_descending = False
        self._resort_now()

        order = (Qt.SortOrder.DescendingOrder if self._sort_descending
                 else Qt.SortOrder.AscendingOrder)
        self._table.horizontalHeader().setSortIndicator(logical_index, order)
        self._frozen_table.horizontalHeader().setSortIndicator(logical_index, order)

        self._populate_table(self._data, set())

    def _resort_now(self):
        """Capture the current on-screen order for self._sort_col_name as a
        list of "Scrip Name" values — a one-time snapshot, not a continuous
        live re-sort (see the state comment in __init__ for why)."""
        col_idx = scrip_idx = None
        for c in range(self._table.columnCount()):
            hdr_item = self._table.horizontalHeaderItem(c)
            if hdr_item is None:
                continue
            if hdr_item.text() == self._sort_col_name:
                col_idx = c
            if hdr_item.text() == "Scrip Name":
                scrip_idx = c
        if col_idx is None or scrip_idx is None:
            self._row_order = None
            return
        rows = []
        for r in range(self._table.rowCount()):
            scrip_item = self._table.item(r, scrip_idx)
            if scrip_item is None:
                continue
            val_item = self._table.item(r, col_idx)
            rows.append((scrip_item.text(), val_item.text() if val_item else ""))

        # Split off blanks first — they always sort last regardless of
        # direction (spreadsheet convention), so they must never take part
        # in the reverse= toggle below.
        blanks    = [pair for pair in rows if not pair[1]]
        non_blank = [pair for pair in rows if pair[1]]

        # A negation trick (like -num) works for numeric descending order
        # but has no string equivalent, so reverse= is what actually needs
        # to flip for text columns — figure out once whether this column is
        # numeric or text and sort accordingly, instead of relying on a
        # single key function to encode both cases (the previous version
        # only handled numeric columns, so descending never took effect
        # for text columns like "Scrip Name"/"Sector").
        numeric = True
        for _, text in non_blank:
            try:
                float(text)
            except (TypeError, ValueError):
                numeric = False
                break
        if numeric:
            non_blank.sort(key=lambda pair: float(pair[1]), reverse=self._sort_descending)
        else:
            non_blank.sort(key=lambda pair: pair[1].lower(), reverse=self._sort_descending)

        self._row_order = [scrip for scrip, _ in non_blank] + [scrip for scrip, _ in blanks]

    def _apply_row_order(self, disp_headers: list, disp_data: list) -> list:
        """Reorder disp_data to match the captured sort snapshot (by "Scrip
        Name"), keeping row position stable tick-to-tick so the live-update
        fast path stays valid while sorted. Stocks not in the snapshot (new
        since the sort was taken) are appended at the end, in their natural
        order; stocks that disappeared are simply absent — no error."""
        if not self._row_order or "Scrip Name" not in disp_headers:
            return disp_data
        scrip_idx = disp_headers.index("Scrip Name")
        by_scrip = {}
        for row in disp_data:
            key = row[scrip_idx]
            by_scrip.setdefault(key, row)
        known = set(self._row_order)
        ordered = [by_scrip[s] for s in self._row_order if s in by_scrip]
        remaining = [row for row in disp_data if row[scrip_idx] not in known]
        return ordered + remaining

    # ── Frozen "Scrip Name" column ───────────────────────────────────────────
    # A second, non-scrolling QTableView overlaid on top of the main table's
    # left edge, sharing its model — so cell content/colors/selection stay in
    # sync automatically and only scroll position + geometry need manual
    # syncing. Standard Qt "frozen column" pattern (see Qt's own Frozen Column
    # example), adapted to QTableWidget's built-in model.

    def _setup_frozen_column(self):
        self._frozen_logical_col = None
        self._frozen_table = QTableView(self._table)
        self._frozen_table.setModel(self._table.model())
        self._frozen_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._frozen_table.setFont(font_scale.font(font_scale.SMALL, False))
        self._frozen_table.verticalHeader().setVisible(False)
        self._frozen_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._frozen_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._frozen_table.setAlternatingRowColors(False)
        self._frozen_table.setShowGrid(True)
        self._frozen_table.setFrameShape(QFrame.Shape.NoFrame)
        self._frozen_table.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._frozen_table.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fhdr = self._frozen_table.horizontalHeader()
        fhdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        fhdr.setSectionsMovable(False)
        fhdr.setSectionsClickable(True)
        fhdr.setSortIndicatorShown(True)
        # The overlay has its own header instance, so a click on it needs
        # its own connection — it always represents _frozen_logical_col.
        fhdr.sectionClicked.connect(
            lambda: self._on_header_clicked(self._frozen_logical_col))
        self._frozen_table.hide()

        # The two views are otherwise fully independent even though they
        # share a model — keep vertical scrolling in lock-step by hand.
        self._table.verticalScrollBar().valueChanged.connect(
            self._frozen_table.verticalScrollBar().setValue)
        self._frozen_table.verticalScrollBar().valueChanged.connect(
            self._table.verticalScrollBar().setValue)

        self._table.installEventFilter(self)

    def eventFilter(self, obj, event):
        if obj is self._table and event.type() in (
            QEvent.Type.Resize, QEvent.Type.Show
        ):
            self._update_frozen_geometry()
        return super().eventFilter(obj, event)

    def _on_section_resized(self, logical: int, old_size: int, new_size: int):
        if logical == getattr(self, "_frozen_logical_col", None):
            self._update_frozen_geometry()

    def _configure_frozen_column(self, scrip_col: int, style_sheet: str):
        """Called after every full rebuild: point the overlay at the "Scrip
        Name" logical column (its logical index is stable across renders —
        only its *visual* position can move) and pin that column to visual
        index 0 so the overlay always lines up with the real leftmost column.
        """
        self._frozen_logical_col = scrip_col if scrip_col >= 0 else None
        if self._frozen_logical_col is None:
            self._frozen_table.hide()
            return
        for c in range(self._table.model().columnCount()):
            self._frozen_table.setColumnHidden(c, c != self._frozen_logical_col)
        self._frozen_table.setStyleSheet(style_sheet)
        hdr = self._table.horizontalHeader()
        visual = hdr.visualIndex(self._frozen_logical_col)
        if visual != 0:
            self._move_section_programmatically(hdr, visual, 0)
        self._update_frozen_geometry()
        # Re-assert one event-loop turn later too, in case anything here
        # (setStyleSheet's repolish, column auto-sizing) settles its final
        # layout asynchronously rather than within this call.
        QTimer.singleShot(0, self._update_frozen_geometry)

    def _update_frozen_geometry(self):
        col = getattr(self, "_frozen_logical_col", None)
        if col is None or self._table.isColumnHidden(col):
            self._frozen_table.hide()
            return
        hdr = self._table.horizontalHeader()
        vh = self._table.verticalHeader()
        vh_width = vh.width() if vh.isVisible() else 0
        x = vh_width + self._table.frameWidth()
        y = self._table.frameWidth()
        width = self._table.columnWidth(col)
        self._frozen_table.setColumnWidth(col, width)
        height = self._table.viewport().height() + hdr.height()
        self._frozen_table.setGeometry(x, y, width, height)
        self._frozen_table.verticalScrollBar().setValue(self._table.verticalScrollBar().value())
        self._frozen_table.show()
        self._frozen_table.raise_()

    def _restore_column_order(self):
        """Reorder columns to match the saved order (by column name)."""
        from services.config_store import load_column_order
        saved = load_column_order()
        if not saved:
            return
        hdr = self._table.horizontalHeader()
        n = hdr.count()
        # Build name → logical index map
        name_to_logical = {}
        for logical in range(n):
            item = self._table.horizontalHeaderItem(logical)
            if item:
                name_to_logical[item.text()] = logical
        # Walk the saved order; skip names not present in the current table.
        # load_column_order() already filters to strings (see its
        # docstring), but a non-string entry here would crash this loop
        # outright (dict.get on an unhashable key) rather than just being
        # skipped like every other unmatched name — guard directly too,
        # belt-and-suspenders against any other path that might someday
        # write this key in a different shape.
        target_visual = 0
        for name in saved:
            if not isinstance(name, str):
                continue
            logical = name_to_logical.get(name)
            if logical is None:
                continue
            current_visual = hdr.visualIndex(logical)
            if current_visual != target_visual:
                self._move_section_programmatically(hdr, current_visual, target_visual)
            target_visual += 1

    def _apply_cell_style(self, item, c, disp_headers, row_colors,
                          strat_col_defs, base_col_count,
                          norm_bg_brush, norm_txt_brush, strat_hdr):
        """Set foreground/background for one cell, incl. strategy formatting.

        row_colors ({target_column_name: color}, from
        services.strategy_engine.get_row_fmt_colors) is looked up by this
        cell's own column name — a conditional-format rule can paint ANY
        column, not just the strategy column that owns it (see
        services.strategy_store's fmt_rule "target_column").

        *norm_bg_brush*/*norm_txt_brush* are pre-built QBrush objects (one
        pair for the whole render pass — see _populate_table), reused as-is
        for the common case rather than constructing a fresh QBrush per
        cell — this runs once per cell on EVERY render, including the fast
        in-place path every live tick takes, so the allocation adds up
        across a wide sheet."""
        item.setForeground(norm_txt_brush)
        item.setBackground(norm_bg_brush)
        header = disp_headers[c] if c < len(disp_headers) else None
        cell_color = row_colors.get(header) if header is not None else None
        if cell_color:
            item.setBackground(QBrush(QColor(cell_color)))
            qc = QColor(cell_color)
            lum = 0.299 * qc.red() + 0.587 * qc.green() + 0.114 * qc.blue()
            item.setForeground(QBrush(QColor("#000000" if lum > 128 else "#ffffff")))
        else:
            strat_idx = c - base_col_count
            if 0 <= strat_idx < len(strat_col_defs):
                item.setBackground(QBrush(QColor(strat_hdr)))

    def _update_cells_in_place(self, disp_data, disp_headers, all_dicts,
                               strat_col_defs, base_col_count,
                               norm_bg_brush, norm_txt_brush, strat_hdr,
                               highlight, agg_cache=None, sym_index=None):
        """
        Update existing QTableWidgetItems in place (no recreation).

        When *highlight* is set, cells whose displayed value changed are
        flashed amber; the steady-state brushes are stashed so the sweep timer
        can restore them after the highlight window.
        """
        from services.strategy_engine import get_row_fmt_colors
        import time as _time
        now = _time.monotonic()
        changed = 0
        for r, row in enumerate(disp_data):
            row_dict = all_dicts[r]
            row_colors = get_row_fmt_colors(
                strat_col_defs, row, base_col_count, row_dict, all_dicts,
                agg_cache, sym_index, self._day_history)
            for c, val in enumerate(row):
                item = self._table.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(_CELL_ALIGNMENT)
                    self._table.setItem(r, c, item)
                    old_text = None
                else:
                    old_text = item.text()
                new_text = self._fmt_cell(val)
                item.setText(new_text)

                # Recompute the steady-state ("base") style every tick so the
                # restored colour reflects current strategy formatting.
                self._apply_cell_style(
                    item, c, disp_headers, row_colors, strat_col_defs,
                    base_col_count, norm_bg_brush, norm_txt_brush, strat_hdr,
                )

                if not highlight:
                    continue

                key = (r, c)
                cell_changed = old_text is not None and new_text != old_text
                if cell_changed:
                    changed += 1
                    self._highlights[key] = (
                        now + _HIGHLIGHT_MS / 1000.0,
                        item.background(), item.foreground(),
                    )
                    item.setBackground(self._amber_bg_by_col[c])
                    item.setForeground(self._amber_txt_by_col[c])
                elif key in self._highlights:
                    # Still within the highlight window: keep amber, but refresh
                    # the stashed base brushes to the latest computed values.
                    exp, _, _ = self._highlights[key]
                    self._highlights[key] = (exp, item.background(), item.foreground())
                    item.setBackground(self._amber_bg_by_col[c])
                    item.setForeground(self._amber_txt_by_col[c])

        self._last_change_count = changed

    def _sweep_highlights(self):
        """Revert amber cells whose highlight window has expired."""
        # Re-assert the frozen-column overlay's geometry on this existing
        # periodic tick — cheap, and a safety net against it drifting out
        # of sync with the real column's width/position from something
        # other than the events _update_frozen_geometry is already wired
        # to (window resize, column drag-resize, a full re-render).
        if getattr(self, "_frozen_logical_col", None) is not None:
            self._update_frozen_geometry()

        if not self._highlights:
            return
        import time as _time
        now = _time.monotonic()
        expired = [k for k, (exp, _, _) in self._highlights.items() if now >= exp]
        for key in expired:
            _, base_bg, base_fg = self._highlights.pop(key)
            r, c = key
            item = self._table.item(r, c)
            if item is not None:
                item.setBackground(base_bg)
                item.setForeground(base_fg)

    # ── Strategy picker ───────────────────────────────────────────────────────

    def set_strategies(self, strategies: list):
        """Inject strategies from StrategyBuilderScreen.

        Called synchronously right after construction+show() (see
        DataImportScreen._run_watcher / app_window._on_lmv_ready) — i.e.
        typically before the event loop has had a turn to run the deferred
        initial render scheduled by _load_initial. Rendering here too would
        both re-block the GUI thread (the exact freeze _load_initial's
        QTimer.singleShot defers around) and duplicate that render's work.
        The deferred render reads self._strategies fresh when it runs, so
        setting it and returning is enough — it picks the assignment up in
        its one pass. Once that first render has happened, later calls (if
        any) trigger an off-thread recompute — see _recompute_display.
        """
        self._strategies = [dict(s) for s in strategies]
        self._update_strat_btn_label()
        if not self._initial_render_done:
            return
        self._recompute_display()

    def _filtered_strategies(self) -> list:
        if self._selected_category == "All":
            return self._strategies
        return [s for s in self._strategies if s.get("category", "Daily") == self._selected_category]

    def _on_category_changed(self, text: str):
        self._selected_category = text
        self._update_strat_btn_label()
        # Don't reset _visible_cols here — that would undo any column filter
        # the user has applied. _populate_table already extends _visible_cols
        # to cover any new strategy columns while leaving the rest untouched.
        # The category filter changes which strategies count as "active" for
        # _filtered_strategies() (see collect_day_requests's caller), so a
        # _DAYS request set can change here too.
        self._refresh_day_history()
        self._recompute_display()

    def _show_strategy_picker(self):
        self._sync_strategies_from_store()
        popup = StrategyPickerPopup(self._filtered_strategies(), self._theme, self)
        popup.applied.connect(self._on_strategies_applied)
        btn_pos = self._strat_btn.mapToGlobal(self._strat_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _sync_strategies_from_store(self):
        """Reloads strategy definitions from services.strategy_store right
        before the picker opens, so a strategy just switched on in Strategy
        Builder shows up immediately instead of needing the unrelated
        "↻ N-Day Data" button first (previously the only thing that resynced
        self._strategies — see _refresh_day_history_from_store's docstring).
        Synchronous rather than routed through the worker thread: this is a
        discrete click, not a per-tick path, same rationale as
        _refresh_day_history. A store-refresh hiccup here just means the
        picker opens with whatever it already had, same as any other
        best-effort reload in this window."""
        from services import strategy_store
        from api.exceptions import ApiError, NetworkError
        try:
            fresh = strategy_store.load_all()
        except (ApiError, NetworkError):
            return
        self._strategies = strategy_store.merge_session_active(fresh, self._strategies)
        self._update_strat_btn_label()

    def _on_strategies_applied(self, updated: list):
        # Merge updated strategies back by ID so strategies outside the current
        # category filter are not overwritten.
        updated_by_id = {s["id"]: s for s in updated}
        self._strategies = [updated_by_id.get(s["id"], s) for s in self._strategies]
        # Deliberately NOT persisted via store.save_strategy() — "active" here
        # is this window's own SESSION-local "applied to this table" flag
        # (see merge_session_active's docstring: LMV forces every strategy
        # session-inactive on open regardless of what was last saved), not
        # Strategy Builder's persisted "active" field, even though they're
        # the same dict key. A previous version DID call save_strategy() for
        # every strategy in *updated* here — which is every strategy that was
        # visible in the picker at Apply time, not just the ones the user
        # actually changed — so applying ANY subset silently persisted
        # active=False for every other, unchecked-but-otherwise-active
        # strategy in that same category. Strategy Builder's own list (the
        # SAME "active" field) would then show them as deactivated, and the
        # picker would stop offering them at all on its next open (see
        # merge_session_active's own `if s.get("active")` filter on the
        # freshly-reloaded list) — exactly the "I applied 6 strategies, then
        # activated a 7th, and the 6 just disappeared" report this traces to.
        # Persisting a strategy's real Active flag is Strategy Builder's own
        # toggle's job (screens.strategy_builder._on_toggled) exclusively.
        # Don't reset _visible_cols here — that would undo any column filter
        # the user has applied. _populate_table already extends _visible_cols
        # to cover any new strategy columns while leaving the rest untouched.
        # A toggle can change which _DAYS requests are needed (a newly-active
        # strategy referencing one, or the last one going inactive) — refresh
        # that cache first; it recomputes display itself when something
        # actually changed, and the plain call below still covers every
        # ordinary (non-historic) column regardless.
        self._refresh_day_history()
        self._recompute_display()

    def _update_strat_btn_label(self):
        filtered = self._filtered_strategies()
        active = sum(1 for s in filtered if s.get("active"))
        total  = len(filtered)
        if total == 0:
            self._strat_btn.setText("⚡  Strategies")
        elif active == 0:
            self._strat_btn.setText("⚡  Strategies  off")
        else:
            self._strat_btn.setText(f"⚡  Strategies  {active}/{total}")
        self._update_strategy_names_label()

    _MAX_INLINE_STRATEGY_NAMES = 10

    def _update_strategy_names_label(self):
        """Bottom-right counterpart to the bottom-left stock count — names
        the currently active (applied) strategies, same font/style as
        self._stock_count_lbl. Beyond _MAX_INLINE_STRATEGY_NAMES, the extra
        names are truncated inline and a "view more" link opens the full,
        scrollable list (see _show_strategy_names_popup)."""
        names = [s.get("name", "Unnamed") for s in self._filtered_strategies() if s.get("active")]
        self._all_active_strategy_names = names
        if not names:
            self._strategy_names_lbl.setText("")
            return
        shown = names[:self._MAX_INLINE_STRATEGY_NAMES]
        text = f"Strategies : {', '.join(html.escape(n) for n in shown)}"
        if len(names) > self._MAX_INLINE_STRATEGY_NAMES:
            accent = self._theme.get("accent") if self._theme else "#39d353"
            text += f", <a href='more' style='color:{accent};'>view more</a>"
        self._strategy_names_lbl.setText(text)

    def _show_strategy_names_popup(self, _link: str):
        popup = _StrategyNamesPopup(self._all_active_strategy_names, self._theme, self)
        pos = self._strategy_names_lbl.mapToGlobal(self._strategy_names_lbl.rect().topRight())
        popup.adjustSize()
        popup.move(pos.x() - popup.width(), pos.y() - popup.height())
        popup.show()

    # ── Filter panel ──────────────────────────────────────────────────────────

    def _current_column_labels(self) -> list:
        """Header text for every column actually rendered right now — base
        merged columns plus any active strategy's output columns — read
        straight from the table so it always matches what's on screen,
        regardless of whether strategies are active."""
        return [
            self._table.horizontalHeaderItem(c).text() if self._table.horizontalHeaderItem(c) else ""
            for c in range(self._table.columnCount())
        ]

    def _show_filter_panel(self):
        sectors = sorted(set(self._sector_map.values()))
        col_total   = self._table.columnCount()
        col_visible = len(self._visible_cols)
        popup = FilterPanelPopup(
            current_category=self._cat_combo.currentText(),
            current_sector=self._sector_combo.currentText(),
            sectors=sectors,
            col_visible=col_visible,
            col_total=col_total,
            theme=self._theme,
            parent=self,
        )
        popup.columns_requested.connect(self._show_col_filter)
        popup.category_changed.connect(self._cat_combo.setCurrentText)
        popup.sector_changed.connect(self._sector_combo.setCurrentText)
        popup.cleared.connect(self._clear_all_filters)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _clear_all_filters(self):
        self._cat_combo.setCurrentText("All")
        self._sector_combo.setCurrentText("All")
        col_count = self._table.columnCount()
        if col_count:
            self._visible_cols = set(range(col_count))
            for c in range(col_count):
                self._table.setColumnHidden(c, False)
        self._update_filter_btn_label()
        self._update_frozen_geometry()

    # ── Value-change highlight colors ───────────────────────────────────────

    def _effective_highlight_color(self, column_name: str | None = None) -> str:
        """The color actually used for the amber flash right now for
        *column_name* — that column's own override if it has one, else the
        LMV-wide default, else the theme's own status_amber. Single source
        of truth for both _populate_table (the table repaint) and the
        toolbar swatch button (which always previews the default)."""
        if column_name is not None:
            override = self._column_highlight_colors.get(column_name)
            if override:
                return override
        if self._highlight_color:
            return self._highlight_color
        t = self._theme
        try:
            return t.get("status_amber") if t else "#d29922"
        except KeyError:
            return "#d29922"

    def _refresh_highlight_btn_style(self):
        t      = self._theme
        divclr = t.get("divider") if t else "#30363d"
        accent = t.get("accent")  if t else "#39d353"
        fill   = self._effective_highlight_color()
        self._highlight_btn.setStyleSheet(
            f"QPushButton {{ background: {fill};"
            f"border: 1px solid {divclr}; border-radius: 4px; }}"
            f"QPushButton:hover {{ border-color: {accent}; }}"
        )

    def _show_highlight_color_manager(self):
        dlg = HighlightColorManagerDialog(
            columns=self._current_column_labels(),
            default_color=self._highlight_color,
            column_colors=self._column_highlight_colors,
            theme=self._theme,
            parent=self,
        )
        dlg.default_changed.connect(self._set_highlight_color)
        dlg.column_changed.connect(self._set_column_highlight_color)
        dlg.exec()

    def _set_highlight_color(self, color):
        self._highlight_color = color
        from services import config_store
        config_store.save_lmv_highlight_color(color)
        self._refresh_highlight_btn_style()

    def _set_column_highlight_color(self, column: str, color):
        if color is None:
            self._column_highlight_colors.pop(column, None)
        else:
            self._column_highlight_colors[column] = color
        from services import config_store
        config_store.save_lmv_column_highlight_colors(self._column_highlight_colors)

    def _reset_view(self):
        """Reset the LMV to its default view: every strategy off, category/
        sector filters and column visibility cleared, columns back in their
        original (un-reordered) positions, and any column sort cleared.
        Doesn't touch the underlying data — this only undoes on-screen
        customization."""
        from services import strategy_store as store
        from services.config_store import save_column_order

        for s in self._strategies:
            if s.get("active"):
                s["active"] = False
                store.save_strategy(s)

        # Column order — drop the saved drag order and put every column
        # back at its natural (logical) position. _clear_all_filters()
        # doesn't touch this; only column *visibility* and the two combos.
        save_column_order([])
        hdr = self._table.horizontalHeader()
        for target_visual in range(hdr.count()):
            current_visual = hdr.visualIndex(target_visual)
            if current_visual != target_visual:
                self._move_section_programmatically(hdr, current_visual, target_visual)

        # The loop above puts "Scrip Name" at its natural *logical* position
        # (e.g. index 1, right after "Sector") — but the frozen overlay
        # always assumes visual index 0 is Scrip Name, and the render below
        # can take the fast-update path (no active strategies means headers/
        # row count are unchanged), which skips the pin logic that normally
        # fixes this. Re-pin explicitly so the overlay isn't left covering
        # the wrong column while the real Scrip Name column sits one to the
        # right of it, uncovered — the exact "overlapping, not fully
        # visible" symptom this was causing after every reset.
        if self._frozen_logical_col is not None:
            visual = hdr.visualIndex(self._frozen_logical_col)
            if visual != 0:
                self._move_section_programmatically(hdr, visual, 0)

        # Row sort.
        self._sort_col_name = None
        self._sort_descending = False
        self._row_order = None
        hdr.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
        self._frozen_table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)

        # setCurrentText("All") is a no-op (no signal fires, no re-render)
        # when a combo is already showing "All" — so the strategy/column
        # changes above wouldn't otherwise be reflected on screen. Force a
        # render regardless of what _clear_all_filters happens to trigger.
        self._clear_all_filters()
        self._populate_table(self._data, set())
        self._apply_sector_filter()
        self._update_strat_btn_label()

    def _show_col_filter(self):
        headers = self._current_column_labels()
        if not headers:
            return
        popup = ColumnFilterPopup(headers, self._visible_cols, self._theme, self)
        popup.columns_changed.connect(self._apply_col_filter)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _apply_col_filter(self, visible: set):
        # Always keep Scrip Name visible regardless of user selection
        if "Scrip Name" in self._headers:
            visible.add(self._headers.index("Scrip Name"))
        self._visible_cols = visible
        for c in range(self._table.columnCount()):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        self._update_filter_btn_label()
        self._update_frozen_geometry()

    def _update_col_btn_label(self):
        self._update_filter_btn_label()

    def _update_filter_btn_label(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider")        if t else "#30363d"

        active = 0
        if self._cat_combo.currentText() != "All":
            active += 1
        if self._sector_combo.currentText() != "All":
            active += 1
        total   = self._table.columnCount()
        visible = len(self._visible_cols)
        if total > 0 and visible < total:
            active += 1

        if active:
            label = f"⊞  Filters · {active}"
            color = accent
            border = accent
        else:
            label = "⊞  Filters"
            color = text_s
            border = divclr

        self._filter_btn.setText(label)
        self._filter_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color};"
            f"border: 1px solid {border}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )

    def _repopulate_sector_combo(self):
        """Rebuild sector combo items from the current sector map."""
        sectors = sorted(set(self._sector_map.values()))
        self._sector_combo.blockSignals(True)
        current = self._sector_combo.currentText()
        self._sector_combo.clear()
        self._sector_combo.addItem("All")
        for s in sectors:
            self._sector_combo.addItem(s)
        # Restore previous selection if still valid
        idx = self._sector_combo.findText(current)
        self._sector_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._sector_combo.blockSignals(False)

    def _visible_table_data(self) -> tuple:
        """
        Scrape the table for exactly what's on screen: visible columns in
        visual (display) order and visible (non-filtered) rows.
        Returns (headers, rows).
        """
        hdr = self._table.horizontalHeader()
        n = self._table.columnCount()
        # Collect logical column indices in visual order, skipping hidden ones
        cols = [
            hdr.logicalIndex(v)
            for v in range(n)
            if not self._table.isColumnHidden(hdr.logicalIndex(v))
        ]
        headers = []
        for logical in cols:
            item = self._table.horizontalHeaderItem(logical)
            headers.append(item.text() if item else "")

        rows = []
        for r in range(self._table.rowCount()):
            if self._table.isRowHidden(r):
                continue
            row = []
            for logical in cols:
                item = self._table.item(r, logical)
                row.append(item.text() if item else "")
            rows.append(row)
        return headers, rows

    def _export(self):
        """Export the currently displayed table to an .xlsx file, applying the
        'Main Column Name' rename overrides to the headers."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services.lmv_export import export_xlsx

        headers, rows = self._visible_table_data()
        if not headers:
            QMessageBox.information(self, "Export", "Nothing to export yet.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Live Master View", "lmv_export.xlsx",
            "Excel Workbook (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_xlsx(path, headers, rows)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not export:\n\n{exc}")
            return
        QMessageBox.information(self, "Export",
                               f"Exported {len(rows)} rows to:\n{path}")

    def _apply_sector_filter(self):
        """Show/hide rows based on the selected sector. No table re-render."""
        selected = self._sector_combo.currentText()
        for r in range(self._table.rowCount()):
            if selected == "All":
                hidden = False
            else:
                item = self._table.item(r, 0)   # Sector is always col 0
                hidden = item is None or item.text() != selected
            self._table.setRowHidden(r, hidden)
            # The frozen "Scrip Name" overlay shares the model but not view
            # state — row visibility has to be mirrored by hand.
            self._frozen_table.setRowHidden(r, hidden)
        self._update_filter_btn_label()
        self._update_stock_count_label()

    def _update_stock_count_label(self):
        """Count of currently visible (non-filtered-out) rows — kept in sync
        wherever row visibility can change (sector filter, strategy apply,
        category change, live ticks all end in _apply_sector_filter)."""
        visible = sum(
            1 for r in range(self._table.rowCount())
            if not self._table.isRowHidden(r)
        )
        self._stock_count_lbl.setText(f"Stocks : {visible}")

    # ── Controls ─────────────────────────────────────────────────────────────

    def _stop(self):
        self._fs_watcher.removePaths(self._fs_watcher.files())
        self._debounce.stop()
        if hasattr(self, "_com_timer"):
            self._com_timer.stop()
        if hasattr(self, "_sweep_timer"):
            self._sweep_timer.stop()
        if hasattr(self, "_or_timer"):
            self._or_timer.stop()
        self._pulse_timer.stop()
        self._shutdown_worker()
        t   = self._theme
        red = t.get("status_red") if t else "#f85149"
        self._dot.setStyleSheet(f"color: {red};")
        self._status_lbl.setText("Stopped")

    def _shutdown_worker(self):
        """Tear down the reader worker thread and release its COM handles."""
        if self._worker_thread is None:
            return
        # Release COM on the worker thread (queued), then stop its event loop.
        if self._worker is not None:
            self._request_shutdown.emit()
        self._worker_thread.quit()
        self._worker_thread.wait(2000)
        self._worker        = None
        self._worker_thread = None

    def _pulse(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        muted  = t.get("text_secondary") if t else "#8b949e"
        self._dot_state = not self._dot_state
        self._dot.setStyleSheet(f"color: {accent if self._dot_state else muted};")

    def refresh_theme(self):
        """Re-render table and window chrome with the current theme."""
        self._populate_table(self._data, set())
        self._apply_sector_filter()
        self._refresh_highlight_btn_style()

    def closeEvent(self, event):
        self._stop()
        if self._controller is not None:
            # Emit stopped regardless of whether configure() was called
            self._controller.watcher.stopped.emit()
        super().closeEvent(event)
