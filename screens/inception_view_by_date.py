"""Inception > View by Date — calendar view of the shared historical EOD
dataset (see docs/INCEPTION_DATA.md in the backend repo): a green dot marks
a trading day that has data, and clicking View pops up that day's raw +
computed metrics for every instrument, reusing screens.historic_viewer's
generic table popup (same widget the existing Data > Historic Upload >
Browse by Date tab uses) rather than a bespoke one.

Unlike Historic Upload's Browse tab, there's no per-day Delete here —
Inception's dataset is a shared, centrally-loaded market-data table (not
something a user uploads/removes day by day), so this screen is read-only.
"""

import calendar as _cal
import font_scale
from datetime import date

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt, QTimer

from api import inception_api
from api.exceptions import ApiError, NetworkError
from components.availability_calendar import AvailabilityCalendar, themed_calendar_stylesheet
from components.error_popup import show_api_error
from screens.historic_viewer import HistoricDataViewer


class InceptionViewByDateScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_date = date.today()
        self._available_days: set = set()
        self._viewers = []
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
        try:
            result = inception_api.get_snapshot(self._selected_date)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        except (KeyError, ValueError, TypeError):
            self._status_lbl.setText("Couldn't parse response from server.")
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        rows = result.get("rows", [])
        if not rows:
            self._status_lbl.setText(f"No data for {self._selected_date.strftime('%d-%b-%Y')}.")
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        metric_keys = sorted({k for r in rows for k in r.get("values", {})})
        headers = ["Symbol"] + metric_keys
        table_rows = [
            [r["symbol"]] + [r.get("values", {}).get(k) for k in metric_keys]
            for r in rows
        ]

        viewer = HistoricDataViewer(
            headers, table_rows, self._selected_date.strftime("%d-%b-%Y"), theme=t,
            title=f"Inception — {self._selected_date.strftime('%d-%b-%Y')}",
        )
        viewer.show()
        self._viewers.append(viewer)
        self._status_lbl.setText("")

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        if not self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._calendar.setStyleSheet(themed_calendar_stylesheet(t))
        for viewer in self._viewers:
            if viewer.isVisible():
                viewer.refresh_theme()
