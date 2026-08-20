"""Inception > View by Date — calendar view of the shared historical EOD
dataset (see docs/INCEPTION_DATA.md in the backend repo): a green dot marks
a trading day that has data, and clicking View pops up that day's raw +
computed (Group A/B) metrics for every locally-synced instrument, reusing
screens.historic_viewer's generic table popup (same widget the existing
Data > Historic Upload > Browse by Date tab uses) rather than a bespoke one.

The day's row values come entirely from services.inception_compute_service,
which computes Group A/B locally from services.inception_bars_store's
synced bar cache — see screens.inception_settings for the sync status/Sync
Now action. Only the green-dot availability check (does the SERVER have
data for this day at all, useful even before this client has synced it) and
"has this been synced locally yet" still touch the network/local store
directly here.

Unlike Historic Upload's Browse tab, there's no per-day Delete here —
Inception's dataset is a shared, centrally-loaded market-data table (not
something a user uploads/removes day by day), so this screen is read-only.
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
from services import inception_bars_store, inception_compute_service, inception_strategy_store
from services.strategy_engine import apply_strategies

# Local sync only ever pulls the canonical ('_I') roll series (see
# services.inception_sync_service / the backend's get_bars default) — so
# every symbol in the local store ends with this suffix, and stripping it
# is exactly "the underlying symbol" with no extra network round trip.
_CANONICAL_SUFFIX = "_I"


def _display_symbol(symbol: str) -> str:
    return symbol[: -len(_CANONICAL_SUFFIX)] if symbol.endswith(_CANONICAL_SUFFIX) else symbol


class _SnapshotLoadWorker(QThread):
    """Runs inception_compute_service.snapshot on a background thread — see
    that module's docstring on why a cold Group A/B walk across the full
    instrument universe can take a while, and screens.inception_settings.
    _SyncWorker for the same pattern used for syncing."""
    progress = Signal(int, int)   # done, total instruments
    succeeded = Signal(list)      # rows
    failed = Signal(str)

    def __init__(self, as_of_date: date, parent=None):
        super().__init__(parent)
        self._as_of_date = as_of_date

    def run(self):
        try:
            rows = inception_compute_service.snapshot(
                self._as_of_date, progress_cb=lambda done, total: self.progress.emit(done, total),
            )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(rows)


class InceptionViewByDateScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_date = date.today()
        self._available_days: set = set()
        self._viewers = []
        self._worker: _SnapshotLoadWorker | None = None
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

    def _on_view_succeeded(self, rows: list):
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

        # Active Inception strategies are evaluated entirely here, on the
        # client — the snapshot response above is base (raw + precomputed)
        # values only. Same engine/appending shape LMV's own live/historical
        # viewers use for their own strategy columns. load_all() already
        # falls back to its local cache on a network error, so this can't
        # raise.
        strategies = [s for s in inception_strategy_store.load_all() if s.get("active")]
        headers, table_rows = apply_strategies(strategies, headers, table_rows)

        viewer = HistoricDataViewer(
            headers, table_rows, self._selected_date.strftime("%d-%b-%Y"), theme=t,
            title=f"Inception — {self._selected_date.strftime('%d-%b-%Y')}",
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
        for viewer in self._viewers:
            if viewer.isVisible():
                viewer.refresh_theme()
