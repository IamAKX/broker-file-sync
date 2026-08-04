"""
Live Alerts screen — a read-only log of strategy-notification signals (see
services/strategy_alerts): both still-open/pending signals and resolved
history, filterable by a recency window. Purely a viewer over
services.strategy_alerts.state_store; all the actual trigger/lifecycle logic
lives in services/strategy_alerts/engine.py, invoked from
screens/live_viewer.py's render loop.
"""

from datetime import datetime, time as dtime, timedelta

import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy, QComboBox, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QMessageBox, QDialog,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from services.strategy_alerts import state_store

_MARKET_OPEN_TIME = dtime(9, 15)

_RECENCY_OPTIONS = [
    ("Last 5 minutes", timedelta(minutes=5)),
    ("Last 10 minutes", timedelta(minutes=10)),
    ("Last 15 minutes", timedelta(minutes=15)),
    ("Last 30 minutes", timedelta(minutes=30)),
    ("Last 1 hour", timedelta(hours=1)),
    ("Last 2 hours", timedelta(hours=2)),
    ("Last 3 hours", timedelta(hours=3)),
    ("Since Market Open", None),   # resolved per-call against today's date
    ("All", None),
]


def _cutoff_for(label: str) -> datetime | None:
    """None means "no lower bound" (the "All" option)."""
    if label == "All":
        return None
    if label == "Since Market Open":
        return datetime.combine(datetime.now().date(), _MARKET_OPEN_TIME)
    for opt_label, delta in _RECENCY_OPTIONS:
        if opt_label == label:
            return datetime.now() - delta
    return None


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
    # A resolved record (alert history) keeps whatever "state" it had right
    # before resolving (engine.py only adds resolution/resolved_at, it never
    # clears "state") — so resolution must be checked first, not state.
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
        self._recency_combo: QComboBox = None
        self._rows: list = []   # signal dicts backing the table's current rows, by row index
        self._build()

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

        toolbar = QHBoxLayout()
        recency_lbl = QLabel("Show:")
        self._recency_combo = QComboBox()
        self._recency_combo.addItems([label for label, _ in _RECENCY_OPTIONS])
        self._recency_combo.setCurrentText("All")
        self._recency_combo.currentTextChanged.connect(lambda _: self._refresh_table())
        toolbar.addWidget(recency_lbl)
        toolbar.addWidget(self._recency_combo)
        toolbar.addStretch()

        refresh_btn = QPushButton("Refresh")
        refresh_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        refresh_btn.clicked.connect(self._refresh_table)
        clear_btn = QPushButton("Clear History")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._on_clear_history)
        toolbar.addWidget(refresh_btn)
        toolbar.addWidget(clear_btn)
        layout.addLayout(toolbar)

        panel = QFrame()
        panel.setObjectName("brokerPanel")
        panel.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        panel_layout = QVBoxLayout(panel)
        panel_layout.setContentsMargins(12, 12, 12, 12)

        self._table = QTableWidget(0, len(self._COLUMNS))
        self._table.setHorizontalHeaderLabels(self._COLUMNS)
        self._table.verticalHeader().setVisible(False)
        self._table.verticalHeader().setDefaultSectionSize(34)
        # Selectable-by-row (not NoSelection) so a click gives visible
        # feedback before the detail popup opens — a truncated/one-line
        # Details cell is never going to fit everything, so the real fix for
        # "can't see the details" is a click-through to the full picture,
        # not just a wider column.
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
        # Every column stays user-resizable (Interactive) even with a default
        # width set — narrow the Strategy column, widen Details, etc. — and if
        # the total exceeds the viewport the table scrolls horizontally
        # instead of squeezing every column to fit.

        panel_layout.addWidget(self._table)
        layout.addWidget(panel, 1)

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        self._refresh_table()

    def showEvent(self, event):
        super().showEvent(event)
        self._refresh_table()

    def reload_alerts(self):
        """Called on every login (see app_window.py's reload_per_user_data),
        not just the first — state_store's data is per logged-in user."""
        self._refresh_table()

    def _on_clear_history(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Clear Alert History")
        msg.setText("Clear all open signals and resolved alert history? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return
        state_store.clear_all()
        self._refresh_table()

    def _refresh_table(self):
        cutoff = _cutoff_for(self._recency_combo.currentText())

        rows = list(state_store.get_open_signals().values()) + list(state_store.get_alert_history())
        if cutoff is not None:
            rows = [r for r in rows if _sort_key(r) >= cutoff]
        rows.sort(key=_sort_key, reverse=True)
        self._rows = rows   # index-aligned with the table's rows, for _on_row_clicked

        t = self._controller.theme
        self._table.setRowCount(len(rows))
        for r, signal in enumerate(rows):
            when = _parse_iso(signal.get("entry_time")) or _parse_iso(signal.get("first_true_at"))
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
                # Full text on hover — a column narrower than its content
                # (or a Details cell with many metrics) is still fully
                # readable, just not all at once in the grid.
                item.setToolTip(str(value))
                if self._COLUMNS[c] == "Status":
                    color_token = _STATUS_COLOR_TOKEN.get(status)
                    if color_token:
                        item.setForeground(QColor(t.get(color_token)))
                self._table.setItem(r, c, item)

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

        # A QHBoxLayout per field (fixed-width label + wrapped value, stretch
        # on the value) rather than a QGridLayout — the same pattern used
        # elsewhere in this app (e.g. NotificationSection's rows in
        # strategy_builder.py). A word-wrapped QLabel inside a QGridLayout
        # column doesn't reliably reserve height for its wrapped lines before
        # the dialog's first layout pass, which is what made a long value
        # (Risk:Reward) overlap the content below it instead of pushing it
        # down; stacking each field as its own row sidesteps that entirely.
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
