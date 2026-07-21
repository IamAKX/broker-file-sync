"""
Data > LMV Upload: construct a historical Live Master View for an arbitrary
past trade date from the 4 browsable broker files (Sharekhan,
ReliableSoftware, NiftyInvest, MarketProfile) plus ExternalImport computed
as of that date (services.external_import_source.read_external_import_db),
or browse/view/delete previously-saved days via a calendar.

Both flows open the same screens.lmv_snapshot_viewer.LmvSnapshotViewer popup
(Strategies/Filters/Export — same toolbar as the live LMV). Saving reuses the
exact same payload builders (services.scheduled_jobs._build_rows_payload /
_build_lmv_snapshot_payload) the automatic Daily Historic Save job uses, so a
manual save here can never drift from what the scheduled job would have
written for the same date.
"""

import font_scale
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QMessageBox
)
from PySide6.QtCore import Qt, QDate, QTimer

from config_defaults import SCRIPT_NAME_DATA, SECTOR_STOCK_DATA
from services import config_store
from api import historic_api, lmv_snapshot_api, holidays_api
from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from screens.data_import import BrokerImportCard
from screens.historic_upload import (
    _AvailabilityCalendar, _HolidayCalendar, _themed_calendar_stylesheet,
)
from screens.lmv_snapshot_viewer import LmvSnapshotViewer

# broker, color_token, hint, exts, show_date_picker, show_multi_file — same
# values as screens.data_import.BROKERS, minus ExternalImport (computed
# automatically here, never browsed) and ExternalImport's file/DB toggle.
_CARDS = [
    ("Sharekhan",        "status_red",    "TradeBook export (.xlsx / .xls)",            (".xlsx", ".xls"),          True,  False),
    ("ReliableSoftware", "status_blue",   "Transactions export (.xlsx / .xls)",         (".xlsx", ".xls"),          False, False),
    ("NiftyInvest",      "status_orange", "Portfolio export (.csv) — multiple allowed", (".csv",),                  False, True),
    ("MarketProfile",    "status_pink",   "Market Profile export (.csv / .xlsx)",       (".csv", ".xlsx", ".xls"), False, False),
]
_REQUIRED_CARDS = {"Sharekhan", "ReliableSoftware", "NiftyInvest", "MarketProfile"}


class LmvUploadScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_date = date.today()
        self._picker_holidays: set = set()
        self._viewers = []
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("LMV Upload")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        self._tabs = QTabWidget()
        self._tabs.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._tabs.addTab(self._build_upload_tab(), "Upload New")
        self._tabs.addTab(self._build_browse_tab(), "Browse by Date")
        layout.addWidget(self._tabs, 1)

    # ── Upload New tab ───────────────────────────────────────────────────────

    def _build_upload_tab(self) -> QWidget:
        t = self._controller.theme
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        date_row = QHBoxLayout()
        date_lbl = QLabel("As-of Date")
        date_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        date_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._date_btn = QPushButton(self._selected_date.strftime("%d-%b-%Y"))
        self._date_btn.setFixedHeight(30)
        self._date_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_date_btn_style()
        self._date_btn.clicked.connect(self._show_date_picker)
        date_row.addWidget(date_lbl)
        date_row.addWidget(self._date_btn)
        date_row.addStretch()
        layout.addLayout(date_row)

        subtitle = QLabel(
            "Browse Sharekhan, ReliableSoftware, NiftyInvest, and MarketProfile for "
            "the date above. ExternalImport's columns are computed automatically as of "
            "that date from stored historic data — nothing to browse for it here."
        )
        subtitle.setFont(font_scale.font(font_scale.SMALL, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        cards_col = QVBoxLayout()
        cards_col.setContentsMargins(0, 0, 0, 0)
        cards_col.setSpacing(10)
        self._cards: dict[str, BrokerImportCard] = {}
        for broker, color_token, hint, exts, show_date, show_multi_file in _CARDS:
            card = BrokerImportCard(
                broker, color_token, hint, t, exts,
                show_date_picker=show_date, show_multi_file=show_multi_file,
                compare_date_provider=lambda: self._selected_date,
            )
            card.import_done.connect(lambda name, rows: self._update_view_btn())
            card.import_reset.connect(lambda name: self._update_view_btn())
            self._cards[broker] = card
            cards_col.addWidget(card)
        layout.addLayout(cards_col)

        layout.addStretch()

        bottom_row = QHBoxLayout()
        self._upload_status_lbl = QLabel("")
        self._upload_status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._upload_status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        bottom_row.addWidget(self._upload_status_lbl)
        bottom_row.addStretch()
        self._view_btn = QPushButton("View")
        self._view_btn.setFixedHeight(32)
        self._view_btn.setFixedWidth(120)
        self._view_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_btn.setEnabled(False)
        self._view_btn.clicked.connect(self._on_view_clicked)
        bottom_row.addWidget(self._view_btn)
        layout.addLayout(bottom_row)

        return tab

    def _update_date_btn_style(self):
        t = self._controller.theme
        self._date_btn.setStyleSheet(f"""
            QPushButton {{
                background: {t.get('input_bg')};
                color: {t.get('text_primary')};
                border: 1px solid {t.get('border')};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                border-color: {t.get('accent')};
                color: {t.get('accent')};
            }}
        """)

    def _show_date_picker(self):
        t = self._controller.theme
        cal = _HolidayCalendar(t)
        cal.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        cal.setFont(font_scale.font(font_scale.SMALL, False))
        cal.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        cal.setStyleSheet(_themed_calendar_stylesheet(t))

        qd = QDate(self._selected_date.year, self._selected_date.month, self._selected_date.day)
        cal.setSelectedDate(qd)
        cal.setCurrentPage(qd.year(), qd.month())

        def refresh_holidays(year, month):
            try:
                rows = holidays_api.list_holidays(year)
            except (ApiError, NetworkError):
                self._picker_holidays = set()
                cal.set_holiday_days(set())
                return
            self._picker_holidays = {date.fromisoformat(r["holiday_date"]) for r in rows}
            days_this_month = {d.day for d in self._picker_holidays if d.month == month}
            cal.set_holiday_days(days_this_month)

        def on_date_selected(date_obj):
            selected = date(date_obj.year(), date_obj.month(), date_obj.day())
            if selected in self._picker_holidays:
                self._upload_status_lbl.setText(
                    f"{selected.strftime('%d-%b-%Y')} is a market holiday — pick another date."
                )
                self._upload_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
                return
            if selected > date.today():
                self._upload_status_lbl.setText("Can't build an LMV for a future date.")
                self._upload_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
                return
            self._selected_date = selected
            self._date_btn.setText(self._selected_date.strftime("%d-%b-%Y"))
            self._upload_status_lbl.setText("")
            self._close_date_picker()

        cal.currentPageChanged.connect(refresh_holidays)
        cal.clicked.connect(on_date_selected)
        refresh_holidays(qd.year(), qd.month())
        cal.show()
        self._date_picker = cal
        self._date_picker_outside_timer = QTimer()
        self._date_picker_outside_timer.setInterval(100)
        self._date_picker_outside_timer.timeout.connect(self._check_date_picker_outside_click)
        self._date_picker_outside_timer.start()

    def _close_date_picker(self):
        if hasattr(self, "_date_picker_outside_timer"):
            self._date_picker_outside_timer.stop()
        if hasattr(self, "_date_picker") and self._date_picker is not None:
            self._date_picker.close()

    def _check_date_picker_outside_click(self):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        if not hasattr(self, "_date_picker") or self._date_picker is None or not self._date_picker.isVisible():
            if hasattr(self, "_date_picker_outside_timer"):
                self._date_picker_outside_timer.stop()
            return
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            if not self._date_picker.geometry().contains(QCursor.pos()):
                self._close_date_picker()

    def _update_view_btn(self):
        ready = all(
            self._cards[b]._selected_file or self._cards[b]._selected_files
            for b in _REQUIRED_CARDS
        )
        self._view_btn.setEnabled(ready)

    def _on_view_clicked(self):
        from services.historic_lmv_merge import read_merged_static

        script_name_data = config_store.load_tab("script_name", SCRIPT_NAME_DATA)
        sector_map = {stock: sector for sector, stock in SECTOR_STOCK_DATA}
        try:
            headers, data = read_merged_static(
                self._cards["Sharekhan"]._selected_file,
                self._cards["ReliableSoftware"]._selected_file,
                self._cards["NiftyInvest"]._selected_files,
                self._cards["MarketProfile"]._selected_file,
                script_name_data,
                target=self._selected_date,
                expiry_date=self._cards["Sharekhan"].get_expiry_date(),
                sector_map=sector_map,
            )
        except Exception as exc:
            QMessageBox.critical(self, "Read Failed", f"Could not build the LMV:\n\n{exc}")
            return

        viewer = LmvSnapshotViewer(
            headers, data, self._selected_date, theme=self._controller.theme,
            on_save=lambda: self._on_save_clicked(headers, data),
            title=f"LMV Preview — {self._selected_date.strftime('%d-%b-%Y')}",
        )
        viewer.show()
        self._viewers.append(viewer)

    def _on_save_clicked(self, headers: list, data: list):
        from services.scheduled_jobs import _build_lmv_snapshot_payload, _build_rows_payload

        script_name_data = config_store.load_tab("script_name", SCRIPT_NAME_DATA)
        rows_payload = _build_rows_payload(headers, data, script_name_data)
        snapshot_payload = _build_lmv_snapshot_payload(headers, data, script_name_data)

        errors = []
        try:
            historic_api.upload_daily(self._selected_date, rows_payload)
        except (ApiError, NetworkError) as exc:
            errors.append(f"Historic Save failed: {exc}")
        try:
            lmv_snapshot_api.upload_daily(self._selected_date, snapshot_payload)
        except (ApiError, NetworkError) as exc:
            errors.append(f"LMV Snapshot Save failed: {exc}")

        if errors:
            QMessageBox.warning(self, "Save Failed", "\n\n".join(errors))
            return
        QMessageBox.information(
            self, "Saved", f"Saved LMV for {self._selected_date.strftime('%d-%b-%Y')}."
        )
        if hasattr(self, "_refresh_browse_availability"):
            self._refresh_browse_availability()

    # ── Browse by Date tab ───────────────────────────────────────────────────

    def _build_browse_tab(self) -> QWidget:
        t = self._controller.theme
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(14)

        self._browse_calendar = _AvailabilityCalendar(t)
        self._browse_calendar.setFont(font_scale.font(font_scale.SMALL, False))
        self._browse_calendar.setStyleSheet(_themed_calendar_stylesheet(t))
        self._browse_calendar.setMaximumWidth(420)
        self._browse_calendar.clicked.connect(self._on_browse_date_selected)
        self._browse_calendar.currentPageChanged.connect(self._on_browse_page_changed)
        layout.addWidget(self._browse_calendar)

        self._selected_browse_date = date.today()

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
        self._update_delete_day_btn_style()
        self._delete_day_btn.clicked.connect(self._on_delete_day_clicked)
        bottom_row.addWidget(self._delete_day_btn)
        self._view_btn_browse = QPushButton("View")
        self._view_btn_browse.setFixedHeight(32)
        self._view_btn_browse.setFixedWidth(100)
        self._view_btn_browse.setFont(font_scale.font(font_scale.SMALL, True))
        self._view_btn_browse.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_btn_browse.clicked.connect(self._on_browse_view_clicked)
        bottom_row.addWidget(self._view_btn_browse)
        layout.addLayout(bottom_row)

        layout.addStretch()

        # Deferred, same reasoning as screens.historic_upload.HistoricUploadScreen.
        QTimer.singleShot(0, self._refresh_browse_availability)
        self._update_browse_buttons_enabled()
        return tab

    def _update_delete_day_btn_style(self):
        t = self._controller.theme
        red = t.get('status_red')
        text_s = t.get('text_secondary')
        border = t.get('border')
        self._delete_day_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent;
                color: {red};
                border: 1px solid {red};
                border-radius: 4px;
                padding: 0 14px;
            }}
            QPushButton:hover {{ background: {red}22; }}
            QPushButton:disabled {{ color: {text_s}; border-color: {border}; }}
        """)

    def _refresh_browse_availability(self):
        today = date.today()
        year = self._browse_calendar.yearShown() or today.year
        month = self._browse_calendar.monthShown() or today.month
        self._fetch_and_apply_availability(year, month, show_popup_on_error=False)

    def _on_browse_page_changed(self, year, month):
        self._fetch_and_apply_availability(year, month)

    def _fetch_and_apply_availability(self, year: int, month: int, show_popup_on_error: bool = True):
        import calendar as _cal
        last_day = _cal.monthrange(year, month)[1]
        date_from = date(year, month, 1)
        date_to = date(year, month, last_day)
        try:
            result = lmv_snapshot_api.get_availability(date_from, date_to)
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
        days = getattr(self, "_available_days", set())
        has_data = self._selected_browse_date.day in days
        self._view_btn_browse.setEnabled(has_data)
        self._delete_day_btn.setEnabled(has_data)

    def _on_browse_view_clicked(self):
        t = self._controller.theme
        try:
            result = lmv_snapshot_api.get_snapshot(self._selected_browse_date)
            stocks = result.get("stocks", [])
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        except (KeyError, ValueError, TypeError):
            self._browse_status_lbl.setText("Couldn't parse response from server.")
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        if not stocks:
            self._browse_status_lbl.setText(
                f"No LMV snapshot saved for {self._selected_browse_date.strftime('%d-%b-%Y')}."
            )
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        headers, rows = _pivot_snapshot_for_viewer(stocks)
        viewer = LmvSnapshotViewer(
            headers, rows, self._selected_browse_date, theme=t, on_save=None,
            title=f"Historical LMV — {self._selected_browse_date.strftime('%d-%b-%Y')}",
        )
        viewer.show()
        self._viewers.append(viewer)
        self._browse_status_lbl.setText("")

    def _on_delete_day_clicked(self):
        t = self._controller.theme
        day_str = self._selected_browse_date.strftime("%d-%b-%Y")
        msg = QMessageBox(self)
        msg.setWindowTitle("Delete LMV Snapshot")
        msg.setText(f"Delete the saved LMV snapshot for {day_str}? This cannot be undone.")
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() != QMessageBox.StandardButton.Yes:
            return

        self._delete_day_btn.setEnabled(False)
        self._view_btn_browse.setEnabled(False)
        try:
            result = lmv_snapshot_api.delete_day(self._selected_browse_date)
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
        self._update_date_btn_style()
        self._update_delete_day_btn_style()
        self._browse_calendar.setStyleSheet(_themed_calendar_stylesheet(t))


def _pivot_snapshot_for_viewer(stocks: list) -> tuple:
    """Reconstruct (headers, rows) for LmvSnapshotViewer from a
    GET /lmv-snapshot/snapshot response.

    The saved snapshot is EAV storage (metric name -> value per stock), which
    doesn't preserve the live merge's exact column order — metric names are
    sorted alphabetically here for a stable, predictable order instead.
    "Sector" isn't persisted at all (see services/scheduled_jobs.py's
    _LMV_SNAPSHOT_EXCLUDED_HEADERS) so it's approximated here via the same
    local sector_stock lookup, keyed by display_name since the original raw
    Scrip Name isn't stored either — less exact than the live/preview merge,
    but Sector was never a "from file or DB" column to begin with.
    """
    sector_map = {stock: sector for sector, stock in SECTOR_STOCK_DATA}
    metric_keys = sorted({k for s in stocks for k in s.get("metrics", {})})
    headers = ["Sector", "Scrip Name"] + metric_keys
    rows = []
    for s in stocks:
        display_name = s.get("display_name") or s["symbol"]
        sector = sector_map.get(display_name.strip().upper(), "—")
        row = [sector, display_name] + [s.get("metrics", {}).get(k) for k in metric_keys]
        rows.append(row)
    return headers, rows
