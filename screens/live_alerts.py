"""
Live Alerts screen — a log of strategy-notification signals (see
services/strategy_alerts), filterable (Strategy / Direction / Stock / Sector /
Status / Date-Time range, combined with AND) and paginated. The
Open/Targets-Achieved/Stopped-Out history shown here is backend-driven —
services/strategy_alerts/backend_sync.py pushes each real event (entry,
target, stop-out) to broker-sync-api's durable, tenant-scoped StrategySignal
table, and every filter/page change here re-queries it via
api/strategy_signals_api.py — so it isn't capped at the local 500-entry
history and follows the account across devices.

Still-pending signals (inside their debounce window, no alert fired yet) are
deliberately NEVER synced to the backend — see StrategySignal's own docstring
for why — so they're shown separately, in a small unfiltered strip sourced
straight from services.strategy_alerts.state_store (this device's own live
state), not part of the filtered/paginated table below it.

All the actual trigger/lifecycle logic lives in
services/strategy_alerts/engine.py, invoked from screens/live_viewer.py's
render loop.
"""

from datetime import datetime

import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QDialog,
    QCheckBox, QDateTimeEdit,
)
from PySide6.QtCore import Qt, QDateTime, QTime
from PySide6.QtGui import QColor

from api import strategy_signals_api
from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from services.strategy_alerts import state_store

_PAGE_SIZES = (25, 50, 100)

# (label, backend query value) — "Pending" is deliberately absent: the
# backend never stores that status (see StrategySignal's docstring), so it
# has no place in a query against it. Pending signals get their own strip.
_STATUS_OPTIONS = [
    ("All", None),
    ("Open", "open"),
    ("Targets Achieved", "all_targets_achieved"),
    ("Stopped Out", "stopped_out"),
]
_DIRECTION_OPTIONS = [("All", None), ("BUY", "BUY"), ("SELL", "SELL")]


def _parse_iso(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None


def _fmt_dt(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.strftime("%d-%b-%Y %I:%M %p").lstrip("0")


def _fmt_price(value) -> str:
    if value is None:
        return "—"
    try:
        return f"{float(value):.2f}"
    except (TypeError, ValueError):
        return str(value)


def _metrics_summary(metrics: dict) -> str:
    parts = []
    for m in metrics.values():
        if m.get("role") == "informational":
            continue
        text = f"{m.get('name', '?')}: {_fmt_price(m.get('value'))}"
        if m.get("role") == "target":
            text += " ✓" if m.get("achieved") else " …"
        parts.append(text)
    return "  |  ".join(parts) if parts else "—"


def _pct_move(signal: dict) -> str:
    entry = signal.get("entry_price")
    direction = signal.get("direction", "BUY")
    extreme = signal.get("running_high") if direction == "BUY" else signal.get("running_low")
    if entry in (None, 0) or extreme is None:
        return "—"
    return f"{(extreme - entry) / entry * 100:.2f}%"


def _status_text(signal: dict) -> str:
    # A resolved record keeps whatever "state" it had right before resolving
    # — resolution must be checked first, not state.
    resolution = signal.get("resolution")
    if resolution == "stopped_out":
        return "Stopped Out"
    if resolution == "all_targets_achieved":
        return "Targets Achieved"
    if signal.get("state") == "pending":
        return "Pending"
    if signal.get("state") == "open":
        return "Open"
    return "Resolved"


def _sort_key(signal: dict) -> datetime:
    return (
        _parse_iso(signal.get("resolved_at"))
        or _parse_iso(signal.get("entry_time"))
        or _parse_iso(signal.get("first_true_at"))
        or datetime.min
    )


def _signal_from_api_item(item: dict) -> dict:
    """Adapts a StrategySignalResponse dict (api/strategy_signals_api.py)
    into the same shape services/strategy_alerts/state_store.py's local
    signals use, so every display helper above/the detail dialog below (built
    against that local shape originally) works unchanged regardless of
    whether a row came from local state or the backend."""
    status = item.get("status")
    resolution = status if status in ("stopped_out", "all_targets_achieved") else None
    return {
        "id": item.get("id"),
        "state": "open",   # the backend never stores "pending" — see module docstring
        "resolution": resolution,
        "strategy_id": item.get("strategy_id"),
        "strategy_name": item.get("strategy_name"),
        "symbol": item.get("symbol"),
        "sector": item.get("sector"),
        "direction": item.get("direction"),
        "entry_time": item.get("entry_time"),
        "entry_price": item.get("entry_price"),
        "resolved_at": item.get("resolved_at"),
        "running_high": item.get("running_high"),
        "running_low": item.get("running_low"),
        "score": item.get("score"),
        "risk_reward": item.get("risk_reward"),
        "metrics": item.get("metrics") or {},
    }


# Status text -> theme token, so the column reads at a glance instead of
# requiring the word itself to be parsed every row.
_STATUS_COLOR_TOKEN = {
    "Targets Achieved": "accent",
    "Stopped Out": "destructive",
    "Open": "status_blue",
    "Pending": "status_orange",
}


class LiveAlertsScreen(QWidget):
    # Fixed, content-sized widths for every column except "Details" (below),
    # which stretches to absorb whatever space is left — a blanket Stretch
    # across all columns divides width evenly regardless of content, which is
    # exactly what was truncating the timestamp/details/high-low columns
    # while leaving short columns (Direction, % Move) with room to spare.
    _COLUMN_WIDTHS = [
        ("Date / Time", 155),
        ("Strategy", 130),
        ("Direction", 70),
        ("Stock", 100),
        ("Sector", 110),
        ("Status", 140),
        ("Entry Price", 95),
        ("Details", None),   # stretch
        ("High", 90),
        ("Low", 90),
        ("% Move", 85),
    ]
    _COLUMNS = [name for name, _ in _COLUMN_WIDTHS]

    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._table: QTableWidget = None
        self._strategy_combo: QComboBox = None
        self._direction_combo: QComboBox = None
        self._stock_combo: QComboBox = None
        self._sector_combo: QComboBox = None
        self._status_combo: QComboBox = None
        self._time_range_check: QCheckBox = None
        self._from_edit: QDateTimeEdit = None
        self._to_edit: QDateTimeEdit = None
        self._page_size_combo: QComboBox = None
        self._page_lbl: QLabel = None
        self._prev_btn: QPushButton = None
        self._next_btn: QPushButton = None
        self._pending_lbl: QLabel = None
        self._filter_dialog: QDialog = None
        self._filter_btn: QPushButton = None
        self._rows: list = []   # signal dicts backing the table's current rows, by row index
        self._page = 1
        self._total = 0
        self._total_pages = 0
        self._build()

    # ── Build ────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Live Alerts")
        title.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        layout.addWidget(title)

        subtitle = QLabel(
            "Strategy notification signals — entry alerts and Target / Stop Loss / "
            "Trailing Exit lifecycle events (see the Notifications section of each "
            "strategy in Strategy Builder to configure these). Double-click any row "
            "for its full details."
        )
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Pending strip — local, live, unfiltered (see module docstring).
        self._pending_lbl = QLabel("")
        self._pending_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._pending_lbl.setStyleSheet(
            f"color: {t.get('status_orange')}; padding: 6px 10px;"
            f"background: {t.get('status_orange')}22; border-radius: 4px;"
        )
        self._pending_lbl.setWordWrap(True)
        self._pending_lbl.setVisible(False)
        layout.addWidget(self._pending_lbl)

        # The filter fields live in a popup dialog (self._filter_dialog),
        # not inline in the page — a "Filter" button in the toolbar below
        # opens it. Building the dialog doesn't add anything to *layout*
        # itself; it just constructs self._strategy_combo etc. as children
        # of that dialog. None of those combos trigger a refresh on change
        # anymore (only the dialog's own Apply Filters button does), so
        # there's no signal-timing hazard around when this happens relative
        # to the toolbar row below.
        self._build_filter_dialog(t)
        layout.addLayout(self._build_toolbar_row(t))

        panel = QFrame()
        panel.setObjectName("brokerPanel")
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)

        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        self._table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setWordWrap(False)
        self._table.setCursor(Qt.CursorShape.PointingHandCursor)
        self._table.cellDoubleClicked.connect(self._on_row_clicked)

        header = self._table.horizontalHeader()
        for col, (name, width) in enumerate(self._COLUMN_WIDTHS):
            if width is None:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Stretch)
            else:
                header.setSectionResizeMode(col, QHeaderView.ResizeMode.Interactive)
                self._table.setColumnWidth(col, width)

        panel_layout.addWidget(self._table)
        layout.addWidget(panel, 1)

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._populate_strategy_combo()
        self._populate_stock_sector_combos()
        self._refresh_pending()
        self._update_filter_button_label()
        self._refresh_table(reset_page=True)

    def _build_filter_dialog(self, t) -> None:
        """Builds self._filter_dialog once — a popup (not embedded inline,
        see the "looks quite large" feedback that motivated this) holding
        every filter control. None of the fields inside trigger a refresh on
        their own; only this dialog's own Apply Filters button does, via
        _on_apply_filters_clicked — so there's no signal-timing hazard to
        worry about around when this gets built relative to anything else,
        unlike the old inline-panel version."""
        dlg = QDialog(self)
        dlg.setWindowTitle("Filter Signals")
        from screens.strategy_builder import _apply_dialog_bg
        _apply_dialog_bg(dlg, t)
        dlg.setMinimumWidth(440)

        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(12)

        self._strategy_combo = self._dialog_combo_row(layout, "Strategy", t)
        self._direction_combo = self._dialog_combo_row(layout, "Direction", t, _DIRECTION_OPTIONS)
        self._stock_combo = self._dialog_combo_row(layout, "Stock", t)
        self._sector_combo = self._dialog_combo_row(layout, "Sector", t)
        self._status_combo = self._dialog_combo_row(layout, "Status", t, _STATUS_OPTIONS)

        layout.addWidget(self._dialog_sep(t.get("divider")))

        self._time_range_check = QCheckBox("Date/Time range")
        self._time_range_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._time_range_check.toggled.connect(self._on_time_range_toggled)
        layout.addWidget(self._time_range_check)

        now = QDateTime.currentDateTime()
        self._from_edit = QDateTimeEdit(QDateTime(now.date(), QTime(0, 0)))
        self._from_edit.setDisplayFormat("dd-MM-yyyy hh:mm AP")
        self._from_edit.setCalendarPopup(True)
        self._from_edit.setFixedHeight(34)
        self._from_edit.setEnabled(False)
        self._to_edit = QDateTimeEdit(now)
        self._to_edit.setDisplayFormat("dd-MM-yyyy hh:mm AP")
        self._to_edit.setCalendarPopup(True)
        self._to_edit.setFixedHeight(34)
        self._to_edit.setEnabled(False)

        range_row = QHBoxLayout()
        range_row.setSpacing(10)
        from_lbl = QLabel("From")
        from_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        to_lbl = QLabel("To")
        to_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        range_row.addWidget(from_lbl)
        range_row.addWidget(self._from_edit)
        range_row.addWidget(to_lbl)
        range_row.addWidget(self._to_edit)
        layout.addLayout(range_row)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        clear_btn = QPushButton("Clear Filters")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setFixedHeight(34)
        clear_btn.setStyleSheet(
            f"background: transparent; color: {t.get('accent')};"
            f"border: 1px solid {t.get('accent')}; border-radius: 4px; padding: 0 16px;"
        )
        clear_btn.clicked.connect(self._on_clear_filters)
        apply_btn = QPushButton("Apply Filters")
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setFixedHeight(34)
        apply_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 16px; font-weight: 600;"
        )
        apply_btn.clicked.connect(self._on_apply_filters_clicked)
        btn_row.addWidget(clear_btn)
        btn_row.addWidget(apply_btn)
        layout.addLayout(btn_row)

        self._filter_dialog = dlg

    def _dialog_combo_row(self, layout: QVBoxLayout, label_text: str, t,
                           options: list | None = None) -> QComboBox:
        """options, when given, is the FULL (label, value) list including
        "All" itself (e.g. _DIRECTION_OPTIONS) — every combo in the dialog
        gets its complete option list up front, so there's no risk of a
        duplicate "All" from a caller appending its own list afterward (a
        real bug the old inline-panel version had for Direction/Status).
        No change signal is connected here at all — see _build_filter_dialog."""
        row = QHBoxLayout()
        row.setSpacing(10)
        lbl = QLabel(label_text)
        lbl.setFixedWidth(80)
        lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        combo = QComboBox()
        combo.setFixedHeight(34)
        for label, value in (options or [("All", None)]):
            combo.addItem(label, value)
        row.addWidget(lbl)
        row.addWidget(combo, 1)
        layout.addLayout(row)
        return combo

    def _open_filter_dialog(self):
        self._filter_dialog.exec()

    def _on_apply_filters_clicked(self):
        self._filter_dialog.accept()
        self._update_filter_button_label()
        self._refresh_table(reset_page=True)

    def _active_filter_count(self) -> int:
        filters = self._current_filters()
        count = sum(
            1 for key in ("strategy_id", "direction", "symbol", "sector", "status")
            if filters.get(key) is not None
        )
        if filters.get("start_time"):
            count += 1
        return count

    def _update_filter_button_label(self):
        count = self._active_filter_count()
        self._filter_btn.setText(f"Filter ({count})" if count else "Filter")

    def _build_toolbar_row(self, t) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(10)

        self._filter_btn = QPushButton("Filter")
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setFixedHeight(32)
        self._filter_btn.setStyleSheet(
            f"background: transparent; color: {t.get('accent')};"
            f"border: 1px solid {t.get('accent')}; border-radius: 4px; padding: 0 14px;"
        )
        self._filter_btn.clicked.connect(self._open_filter_dialog)
        row.addWidget(self._filter_btn)

        row.addSpacing(12)

        size_lbl = QLabel("Page size")
        size_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._page_size_combo = QComboBox()
        self._page_size_combo.setFixedHeight(32)
        for size in _PAGE_SIZES:
            self._page_size_combo.addItem(str(size), size)
        self._page_size_combo.currentIndexChanged.connect(self._on_page_size_changed)
        row.addWidget(size_lbl)
        row.addWidget(self._page_size_combo)

        row.addSpacing(12)

        self._prev_btn = QPushButton("◀ Prev")
        self._prev_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._prev_btn.setFixedHeight(32)
        self._prev_btn.clicked.connect(self._on_prev_page)
        self._next_btn = QPushButton("Next ▶")
        self._next_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._next_btn.setFixedHeight(32)
        self._next_btn.clicked.connect(self._on_next_page)
        self._page_lbl = QLabel("")
        self._page_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._page_lbl.setStyleSheet(f"color: {t.get('text_secondary')}; padding: 0 6px;")
        row.addWidget(self._prev_btn)
        row.addWidget(self._page_lbl)
        row.addWidget(self._next_btn)

        row.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.setFixedHeight(32)
        refresh_btn.clicked.connect(lambda: (self._refresh_pending(), self._refresh_table()))
        clear_btn = QPushButton("Clear History")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.setFixedHeight(32)
        clear_btn.setStyleSheet(
            f"background: transparent; color: {t.get('destructive')};"
            f"border: 1px solid {t.get('destructive')}; border-radius: 4px; padding: 0 14px;"
        )
        clear_btn.clicked.connect(self._on_clear_history)
        row.addWidget(refresh_btn)
        row.addWidget(clear_btn)

        return row

    # ── Filter option population ─────────────────────────────────────────

    def _populate_strategy_combo(self):
        from services import strategy_store
        for s in strategy_store.load_all():
            self._strategy_combo.addItem(s.get("name", ""), s.get("id"))

    def _populate_stock_sector_combos(self):
        from config_defaults import SECTOR_STOCK_DATA
        sectors = sorted({sector for sector, _ in SECTOR_STOCK_DATA})
        stocks = sorted({stock for _, stock in SECTOR_STOCK_DATA})
        for sector in sectors:
            self._sector_combo.addItem(sector, sector)
        for stock in stocks:
            self._stock_combo.addItem(stock, stock)

    def _on_time_range_toggled(self, checked: bool):
        self._from_edit.setEnabled(checked)
        self._to_edit.setEnabled(checked)

    def _on_clear_filters(self):
        # No blockSignals needed — unlike the old inline-panel version,
        # none of these combos have a change signal connected at all (see
        # _dialog_combo_row); only the dialog's own Apply/Clear buttons
        # trigger a refresh.
        for combo in (self._strategy_combo, self._direction_combo, self._stock_combo,
                      self._sector_combo, self._status_combo):
            combo.setCurrentIndex(0)
        self._time_range_check.setChecked(False)
        if self._filter_dialog is not None:
            self._filter_dialog.accept()   # harmless no-op if not currently open
        self._update_filter_button_label()
        self._refresh_table(reset_page=True)

    # ── Lifecycle ────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_pending()
        self._refresh_table()

    def reload_alerts(self):
        """Called on every login (see app_window.py's reload_per_user_data),
        not just the first — both local pending state and the backend's
        signals are per logged-in user."""
        self._on_clear_filters()
        self._refresh_pending()

    # ── Pending strip (local, unfiltered) ───────────────────────────────

    def _refresh_pending(self):
        pending = [
            s for s in state_store.get_open_signals().values()
            if s.get("state") == "pending"
        ]
        if not pending:
            self._pending_lbl.setVisible(False)
            return
        pending.sort(key=_sort_key, reverse=True)
        parts = [
            f"{s.get('symbol', '')} ({s.get('strategy_name', '')}) since "
            f"{_fmt_dt(_parse_iso(s.get('first_true_at')))}"
            for s in pending
        ]
        self._pending_lbl.setText(f"⏳ Pending ({len(pending)}): " + "  ·  ".join(parts))
        self._pending_lbl.setVisible(True)

    # ── Filtered / paginated table (backend-driven) ─────────────────────

    def _current_filters(self) -> dict:
        filters = {
            "strategy_id": self._strategy_combo.currentData(),
            "direction": self._direction_combo.currentData(),
            "symbol": self._stock_combo.currentData(),
            "sector": self._sector_combo.currentData(),
            "status": self._status_combo.currentData(),
            "start_time": None,
            "end_time": None,
        }
        if self._time_range_check.isChecked():
            filters["start_time"] = self._from_edit.dateTime().toPython().isoformat()
            filters["end_time"] = self._to_edit.dateTime().toPython().isoformat()
        return filters

    def _resolved_page_size(self) -> int:
        """Always one of _PAGE_SIZES, regardless of the combo's state —
        the backend rejects anything else with a 422 (see
        api/strategy_signals_api.py's list_signals), so this must never
        forward a raw, unvalidated currentData()."""
        size = self._page_size_combo.currentData() if self._page_size_combo is not None else None
        return size if size in _PAGE_SIZES else _PAGE_SIZES[0]

    def _refresh_table(self, reset_page: bool = False):
        if reset_page:
            self._page = 1
        filters = self._current_filters()
        try:
            response = strategy_signals_api.list_signals(
                **filters, page=self._page, page_size=self._resolved_page_size(),
            )
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return

        self._total = response.get("total", 0)
        self._total_pages = response.get("total_pages", 0)
        self._page = response.get("page", self._page)
        self._rows = [_signal_from_api_item(item) for item in response.get("items", [])]

        t = self._controller.theme
        self._table.setRowCount(len(self._rows))
        for r, signal in enumerate(self._rows):
            when = _parse_iso(signal.get("resolved_at")) or _parse_iso(signal.get("entry_time"))
            status = _status_text(signal)
            details = _metrics_summary(signal.get("metrics", {}))
            values = [
                _fmt_dt(when),
                signal.get("strategy_name", ""),
                signal.get("direction", ""),
                signal.get("symbol", ""),
                signal.get("sector") or "—",
                status,
                _fmt_price(signal.get("entry_price")),
                details,
                _fmt_price(signal.get("running_high")),
                _fmt_price(signal.get("running_low")),
                _pct_move(signal),
            ]
            for c, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                if self._COLUMNS[c] == "Status":
                    color_token = _STATUS_COLOR_TOKEN.get(status)
                    if color_token:
                        item.setForeground(QColor(t.get(color_token)))
                self._table.setItem(r, c, item)

        total_pages_display = max(self._total_pages, 1)
        self._page_lbl.setText(f"Page {self._page} of {total_pages_display} ({self._total} total)")
        self._prev_btn.setEnabled(self._page > 1)
        self._next_btn.setEnabled(self._page < self._total_pages)

    def _on_page_size_changed(self):
        self._refresh_table(reset_page=True)

    def _on_prev_page(self):
        if self._page > 1:
            self._page -= 1
            self._refresh_table()

    def _on_next_page(self):
        if self._page < self._total_pages:
            self._page += 1
            self._refresh_table()

    def _on_clear_history(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Alert History")
        msg.setText(
            "Clear all local open signals AND every synced signal in your account's "
            "history? This cannot be undone."
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        state_store.clear_all()
        try:
            strategy_signals_api.clear_signals()
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
        self._refresh_pending()
        self._refresh_table(reset_page=True)

    # ── Row detail popup ─────────────────────────────────────────────────

    def _on_row_clicked(self, row: int, _col: int):
        if 0 <= row < len(self._rows):
            self._show_detail_dialog(self._rows[row])

    def _show_detail_dialog(self, signal: dict):
        t = self._controller.theme
        bg, txt, txt_s = t.get("background"), t.get("text_primary"), t.get("text_secondary")
        border, accent = t.get("border"), t.get("accent")

        dlg = QDialog(self)
        dlg.setWindowTitle(f"{signal.get('strategy_name', '')} — {signal.get('symbol', '')}")
        dlg.setMinimumWidth(460)
        dlg.setMaximumHeight(640)   # long metric lists scroll instead of growing past the screen
        dlg.setStyleSheet(
            f"QDialog {{ background: {bg}; color: {txt}; }}"
            f"QLabel {{ background: transparent; }}"
            f"QPushButton {{ background: {t.get('button_bg')}; color: {txt};"
            f"border: 1px solid {border}; border-radius: 4px; padding: 6px 14px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
            f"QScrollArea {{ background: transparent; border: none; }}"
        )

        outer = QVBoxLayout(dlg)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        content = QWidget()
        content.setStyleSheet("background: transparent;")
        layout = QVBoxLayout(content)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        header = QLabel(
            f"{signal.get('strategy_name', '')} — {signal.get('direction', '')} Signal: "
            f"{signal.get('symbol', '')}"
        )
        header.setFont(font_scale.font(font_scale.MEDIUM, True))
        header.setWordWrap(True)
        layout.addWidget(header)

        status = _status_text(signal)
        status_lbl = QLabel(status)
        status_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        color_token = _STATUS_COLOR_TOKEN.get(status)
        status_lbl.setStyleSheet(f"color: {t.get(color_token) if color_token else txt_s};")
        layout.addWidget(status_lbl)

        layout.addWidget(self._dialog_sep(border))

        when = _parse_iso(signal.get("entry_time")) or _parse_iso(signal.get("first_true_at"))
        fields = [
            ("Date / Time", _fmt_dt(when)),
            ("Sector", signal.get("sector") or "—"),
            ("Entry Price", _fmt_price(signal.get("entry_price"))),
            ("High since signal", _fmt_price(signal.get("running_high"))),
            ("Low since signal", _fmt_price(signal.get("running_low"))),
            ("% Move", _pct_move(signal)),
        ]
        if signal.get("score") is not None:
            fields.append(("Strength/Weakness Score", signal["score"]))
        rr = signal.get("risk_reward")
        if rr and rr.get("ratio") is not None:
            fields.append((
                "Risk : Reward",
                f"{_fmt_price(rr.get('numerator'))} : {_fmt_price(rr.get('denominator'))} "
                f"({rr['ratio']:.2f})",
            ))

        for label, value in fields:
            layout.addLayout(self._detail_field_row(label, value, txt_s, txt))

        metrics = signal.get("metrics") or {}
        if metrics:
            layout.addWidget(self._dialog_sep(border))
            metrics_title = QLabel("Metrics")
            metrics_title.setFont(font_scale.font(font_scale.SMALL, True))
            layout.addWidget(metrics_title)
            for m in metrics.values():
                layout.addWidget(self._metric_row_label(m, txt, txt_s, t))

        layout.addStretch()
        scroll.setWidget(content)
        outer.addWidget(scroll)

        btn_row = QHBoxLayout()
        btn_row.setContentsMargins(20, 12, 20, 16)
        btn_row.addStretch()
        close_btn = QPushButton("Close")
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(dlg.accept)
        btn_row.addWidget(close_btn)
        outer.addLayout(btn_row)

        dlg.exec()

    @staticmethod
    def _detail_field_row(label: str, value, txt_s: str, txt: str) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(12)
        lbl = QLabel(label)
        lbl.setFixedWidth(160)
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color: {txt_s};")
        val = QLabel(str(value))
        val.setFont(font_scale.font(font_scale.SMALL, True))
        val.setStyleSheet(f"color: {txt};")
        val.setWordWrap(True)
        row.addWidget(lbl)
        row.addWidget(val, 1)
        return row

    @staticmethod
    def _dialog_sep(border_color: str) -> QFrame:
        sep = QFrame()
        sep.setFixedHeight(1)
        sep.setStyleSheet(f"background: {border_color}; border: none;")
        return sep

    @staticmethod
    def _metric_row_label(m: dict, txt: str, txt_s: str, t) -> QLabel:
        role = m.get("role", "")
        parts = [f"{m.get('name', '?')}", role, _fmt_price(m.get("value"))]
        color = txt
        if role == "target":
            if m.get("achieved"):
                achieved_at = _fmt_dt(_parse_iso(m.get("achieved_at")))
                parts.append(f"Achieved ✓ ({achieved_at})")
                color = t.get("accent")
            else:
                parts.append("Not yet achieved …")
                color = txt_s
        lbl = QLabel("  ·  ".join(str(p) for p in parts))
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color: {color};")
        lbl.setWordWrap(True)
        return lbl

    def refresh_theme(self):
        pass
