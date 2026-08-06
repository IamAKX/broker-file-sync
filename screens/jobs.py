"""
High/Low screen (Data menu > High/Low): configure and browse the Opening Range
High/Low capture background job (see services/scheduled_jobs.py
run_opening_range_capture). Two tabs, same shape as screens/historic_upload.py
and screens/lmv_upload.py:
  - "Opening Range Capture": the job's own config — capture time (reused
    from services.trigger_config, the same store the Notifications screen's
    trigger table uses), enabled toggle, last-run status, and a manual
    "Run Now".
  - "Browse by Date": a calendar with a dot under every day that has saved
    data (see components.availability_calendar.AvailabilityCalendar, shared with historic_upload.py /
    lmv_upload.py), to view or delete a day's capture.
"""

import calendar as _cal
import font_scale
from datetime import date

from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTabWidget, QMessageBox, QDialog
)
from PySide6.QtCore import Qt, QTimer

from api import opening_range_api
from api.exceptions import ApiError, NetworkError
from components.availability_calendar import AvailabilityCalendar, themed_calendar_stylesheet
from components.error_popup import show_api_error
from screens.historic_viewer import HistoricDataViewer
from screens.notifications import ToggleSwitch, _TriggerTimeDialog
from services import scheduled_jobs, trigger_config


class JobsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._configs = trigger_config.load_trigger_configs()
        self._viewers = []
        self._available_days: set = set()
        self._selected_browse_date = date.today()
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _cfg(self):
        for c in self._configs:
            if c.id == scheduled_jobs.OPENING_RANGE_TRIGGER_ID:
                return c
        # Defensive — SCHEDULER_TRIGGER_DEFAULTS always seeds this id, so
        # load_trigger_configs() always returns an entry for it; this is
        # only reachable if that default is ever removed without updating
        # this screen too.
        raise RuntimeError(f"No trigger config found for {scheduled_jobs.OPENING_RANGE_TRIGGER_ID!r}")

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("High/Low")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        self._tabs = QTabWidget()
        self._tabs.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._tabs.addTab(self._build_job_tab(), "Opening Range Capture")
        self._tabs.addTab(self._build_browse_tab(), "Browse by Date")
        layout.addWidget(self._tabs, 1)

    # ── Opening Range Capture tab ───────────────────────────────────────────

    def _build_job_tab(self) -> QWidget:
        t = self._controller.theme
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        card = QFrame()
        card.setObjectName("brokerPanel")
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(20, 16, 20, 16)
        card_lay.setSpacing(10)

        name_row = QHBoxLayout()
        name_lbl = QLabel("Opening Range High/Low Capture")
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        name_row.addWidget(name_lbl)
        name_row.addStretch()
        self._enabled_toggle = ToggleSwitch(self._cfg().system_enabled)
        self._enabled_toggle.toggled.connect(self._on_enabled_toggled)
        name_row.addWidget(self._enabled_toggle)
        card_lay.addLayout(name_row)

        desc_lbl = QLabel(
            "Saves every stock's highest High and lowest Low, as shown in the "
            "Live Master View, for the trading day's opening window (market "
            "open 09:15 to the capture time below). Requires the Live Master "
            "View to already be loaded when the capture time is reached."
        )
        desc_lbl.setWordWrap(True)
        desc_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        desc_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_lay.addWidget(desc_lbl)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {t.get('divider')};")
        card_lay.addWidget(div)

        time_row = QHBoxLayout()
        time_row.setSpacing(10)
        time_caption = QLabel("Capture time")
        time_caption.setFont(font_scale.font(font_scale.SMALL, False))
        time_caption.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._time_lbl = QLabel(self._format_time(self._cfg().time))
        self._time_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        change_btn = QPushButton("Change")
        change_btn.setFixedHeight(28)
        change_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        change_btn.clicked.connect(self._on_edit_time)
        time_row.addWidget(time_caption)
        time_row.addWidget(self._time_lbl)
        time_row.addWidget(change_btn)
        time_row.addStretch()
        card_lay.addLayout(time_row)

        self._window_lbl = QLabel()
        self._window_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._window_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._update_window_label()
        card_lay.addWidget(self._window_lbl)

        self._last_run_lbl = QLabel()
        self._last_run_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._last_run_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._update_last_run_label()
        card_lay.addWidget(self._last_run_lbl)

        btn_row = QHBoxLayout()
        self._run_now_btn = QPushButton("Run Now")
        self._run_now_btn.setFixedHeight(32)
        self._run_now_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._run_now_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_run_now_btn()
        self._run_now_btn.clicked.connect(self._on_run_now)
        btn_row.addWidget(self._run_now_btn)
        btn_row.addStretch()
        card_lay.addLayout(btn_row)

        layout.addWidget(card)
        layout.addStretch()
        return tab

    def _style_run_now_btn(self):
        t = self._controller.theme
        self._run_now_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            f"border: none; border-radius: 4px; padding: 0 16px; }}"
            f"QPushButton:disabled {{ background: {t.get('button_bg')}; color: {t.get('text_secondary')}; }}"
        )

    @staticmethod
    def _format_time(t) -> str:
        return t.strftime("%I:%M %p").lstrip("0")

    def _update_window_label(self):
        minutes = scheduled_jobs._opening_range_window_minutes()
        self._window_lbl.setText(
            f"Window: market open (09:15) to capture time — {minutes} minute(s)."
        )

    def _update_last_run_label(self):
        last_fired = trigger_config.load_last_fired()
        last = last_fired.get(scheduled_jobs.OPENING_RANGE_TRIGGER_ID)
        self._last_run_lbl.setText(
            f"Last scheduled run: {last}" if last else "Last scheduled run: never"
        )

    def _on_enabled_toggled(self, checked: bool):
        self._cfg().system_enabled = checked
        trigger_config.save_trigger_configs(self._configs)

    def _on_edit_time(self):
        cfg = self._cfg()
        dlg = _TriggerTimeDialog(cfg.name, cfg.time, self._controller.theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg.time = dlg.result_time()
            trigger_config.save_trigger_configs(self._configs)
            self._time_lbl.setText(self._format_time(cfg.time))
            self._update_window_label()

    def _on_run_now(self):
        notifier = getattr(self._controller, "_notifier", None)
        if notifier is None:
            QMessageBox.information(
                self, "Not Ready",
                "The app isn't fully started yet — try again in a moment.",
            )
            return
        # Deliberately doesn't touch trigger_config.save_last_fired: the
        # Scheduler keeps its own in-memory copy of "last fired" (loaded once
        # at startup) and never re-reads it mid-session, so writing here
        # wouldn't actually stop today's scheduled run from also firing —
        # it would just make this screen's "Last scheduled run" label lie in
        # the meantime. Run Now is for testing/backfilling; the scheduled
        # trigger remains the single source of truth for "did today's
        # capture happen".
        self._run_now_btn.setEnabled(False)
        self._run_now_btn.setText("Running…")
        try:
            scheduled_jobs.run_opening_range_capture(self._controller, notifier)
        finally:
            self._run_now_btn.setEnabled(True)
            self._run_now_btn.setText("Run Now")
        self._refresh_browse_availability()

    # ── Browse by Date tab ───────────────────────────────────────────────────

    def _build_browse_tab(self) -> QWidget:
        t = self._controller.theme
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self._browse_calendar = AvailabilityCalendar(t)
        self._browse_calendar.setFont(font_scale.font(font_scale.SMALL, False))
        self._browse_calendar.setStyleSheet(themed_calendar_stylesheet(t))
        self._browse_calendar.setMaximumWidth(420)
        self._browse_calendar.clicked.connect(self._on_browse_date_selected)
        self._browse_calendar.currentPageChanged.connect(self._on_browse_page_changed)
        layout.addWidget(self._browse_calendar)

        bottom_row = QHBoxLayout()
        self._browse_status_lbl = QLabel("")
        self._browse_status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._browse_status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        bottom_row.addWidget(self._browse_status_lbl)
        bottom_row.addStretch()

        self._delete_day_btn = QPushButton("Delete")
        self._delete_day_btn.setFixedHeight(32)
        self._delete_day_btn.setFixedWidth(100)
        self._delete_day_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._delete_day_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._style_delete_btn()
        self._delete_day_btn.clicked.connect(self._on_delete_day_clicked)
        bottom_row.addWidget(self._delete_day_btn)

        self._view_btn = QPushButton("View")
        self._view_btn.setFixedHeight(32)
        self._view_btn.setFixedWidth(100)
        self._view_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_btn.clicked.connect(self._on_view_clicked)
        bottom_row.addWidget(self._view_btn)
        layout.addLayout(bottom_row)

        layout.addStretch()

        # Deferred (not called inline) — this can run during MainWindow
        # construction on the auto-login path, before any window is visible,
        # and a blocking network call there would hold up startup.
        QTimer.singleShot(0, self._refresh_browse_availability)
        self._update_browse_buttons_enabled()
        return tab

    def _style_delete_btn(self):
        t = self._controller.theme
        red = t.get("status_red")
        text_s = t.get("text_secondary")
        border = t.get("border")
        self._delete_day_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {red};"
            f"border: 1px solid {red}; border-radius: 4px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {red}22; }}"
            f"QPushButton:disabled {{ color: {text_s}; border-color: {border}; }}"
        )

    def _refresh_browse_availability(self):
        today = date.today()
        year = self._browse_calendar.yearShown() or today.year
        month = self._browse_calendar.monthShown() or today.month
        self._fetch_and_apply_availability(year, month, show_popup_on_error=False)

    def _on_browse_page_changed(self, year, month):
        self._fetch_and_apply_availability(year, month)

    def _fetch_and_apply_availability(self, year: int, month: int, show_popup_on_error: bool = True):
        last_day = _cal.monthrange(year, month)[1]
        date_from = date(year, month, 1)
        date_to = date(year, month, last_day)
        try:
            result = opening_range_api.get_availability(date_from, date_to)
            days = {
                date.fromisoformat(d["trade_date"]).day
                for d in result["dates"] if d["has_data"]
            }
        except (ApiError, NetworkError, KeyError, ValueError, TypeError) as exc:
            if show_popup_on_error and isinstance(exc, (ApiError, NetworkError)):
                show_api_error(self._controller.theme, self, exc)
            elif hasattr(self, "_browse_status_lbl"):
                t = self._controller.theme
                self._browse_status_lbl.setText("Couldn't load availability for this month.")
                self._browse_status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            self._browse_calendar.set_available_days(set())
            self._available_days = set()
            self._update_browse_buttons_enabled()
            return
        self._browse_calendar.set_available_days(days)
        self._available_days = days
        self._update_browse_buttons_enabled()

    def _on_browse_date_selected(self, qdate):
        self._selected_browse_date = date(qdate.year(), qdate.month(), qdate.day())
        self._update_browse_buttons_enabled()

    def _update_browse_buttons_enabled(self):
        has_data = self._selected_browse_date.day in self._available_days
        self._view_btn.setEnabled(has_data)
        self._delete_day_btn.setEnabled(has_data)

    def _on_view_clicked(self):
        t = self._controller.theme
        try:
            result = opening_range_api.get_snapshot(self._selected_browse_date)
            stocks = result.get("stocks", [])
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        except (KeyError, ValueError, TypeError):
            self._browse_status_lbl.setText("Couldn't parse response from server.")
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        date_str = self._selected_browse_date.strftime("%d-%b-%Y")
        if not stocks:
            self._browse_status_lbl.setText(f"No opening-range data saved for {date_str}.")
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        headers = ["Symbol", "Display Name", "High", "Low", "Window (min)"]
        rows = [
            [s["symbol"], s.get("display_name") or "", s.get("high"), s.get("low"),
             s.get("window_minutes")]
            for s in stocks
        ]
        viewer = HistoricDataViewer(
            headers, rows, date_str, theme=t, title=f"Opening Range — {date_str}",
        )
        viewer.show()
        self._viewers.append(viewer)
        self._browse_status_lbl.setText("")

    def _on_delete_day_clicked(self):
        t = self._controller.theme
        day_str = self._selected_browse_date.strftime("%d-%b-%Y")
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete Opening Range Data")
        msg.setText(f"Delete all saved opening-range data for {day_str}? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        self._delete_day_btn.setEnabled(False)
        self._view_btn.setEnabled(False)
        try:
            result = opening_range_api.delete_day(self._selected_browse_date)
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            self._update_browse_buttons_enabled()
            return

        deleted = result.get("values_deleted", 0)
        self._browse_status_lbl.setText(f"Deleted {deleted} value(s) for {day_str}.")
        self._browse_status_lbl.setStyleSheet(f"color: {t.get('accent')};")

        for viewer in list(self._viewers):
            if viewer.isVisible() and viewer.windowTitle().endswith(day_str):
                viewer.close()

        self._refresh_browse_availability()

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        self._style_run_now_btn()
        self._style_delete_btn()
        if hasattr(self, "_browse_calendar"):
            self._browse_calendar.setStyleSheet(themed_calendar_stylesheet(t))
