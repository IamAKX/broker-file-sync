import font_scale
import os
from datetime import date
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QFileDialog, QTabWidget, QCalendarWidget, QToolButton,
    QCheckBox, QScrollArea
)
from PySide6.QtCore import Qt, QDate, QTimer
from PySide6.QtGui import QPainter, QColor, QBrush

from config_defaults import SCRIPT_NAME_DATA
from services import config_store
from services.file_reader import read_historic_sheet
from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix
from api import historic_api, holidays_api
from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error
from screens.historic_viewer import HistoricDataViewer

# Only columns C through M (0-based indices 2-12, inclusive) of the historic upload
# sheet are eligible for the metrics checkboxes — everything else (A/B structural
# columns, and N onward) is never offered for upload.
_METRIC_COL_START = 2   # column C
_METRIC_COL_END = 12    # column M (inclusive)


def _themed_calendar_stylesheet(theme) -> str:
    bg     = theme.get('card_bg')
    txt    = theme.get('text_primary')
    txt_s  = theme.get('text_secondary')
    bd     = theme.get('border')
    accent = theme.get('accent')
    btn_bg = theme.get('button_bg')
    return f"""
        QCalendarWidget {{
            background: {bg};
            color: {txt};
            border: 1px solid {bd};
        }}
        QCalendarWidget QWidget#qt_calendar_navigationbar {{
            background: {btn_bg};
            border-bottom: 1px solid {bd};
        }}
        QCalendarWidget QToolButton {{
            color: {txt};
            background: {btn_bg};
            border: 1px solid {bd};
            border-radius: 4px;
            padding: 4px 8px;
            min-width: 40px;
        }}
        QCalendarWidget QToolButton:hover {{
            border-color: {accent};
            color: {accent};
        }}
        QCalendarWidget QToolButton:pressed {{
            background: {accent};
            color: {bg};
        }}
        QCalendarWidget QSpinBox {{
            background: {bg};
            color: {txt};
            border: 1px solid {bd};
            border-radius: 4px;
            padding: 2px 4px;
        }}
        QCalendarWidget QAbstractItemView {{
            background: {bg};
            color: {txt};
            selection-background-color: {accent};
            selection-color: {bg};
            border: none;
            outline: none;
        }}
        QCalendarWidget QAbstractItemView:enabled {{
            color: {txt};
        }}
        QCalendarWidget QAbstractItemView:disabled {{
            color: {txt_s};
        }}
        QCalendarWidget QWidget {{
            alternate-background-color: {bg};
        }}
        QCalendarWidget QLabel {{
            color: {txt};
            background: transparent;
        }}
        QCalendarWidget QHeaderView {{
            background: {btn_bg};
        }}
        QCalendarWidget QHeaderView::section {{
            color: {txt_s};
            background: {btn_bg};
            border: none;
        }}
    """


class _AvailabilityCalendar(QCalendarWidget):
    """QCalendarWidget that draws a green dot under days with saved data."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._available_days: set = set()

    def set_available_days(self, days: set):
        self._available_days = days
        self.updateCells()

    def paintCell(self, painter, rect, date_obj):
        super().paintCell(painter, rect, date_obj)
        if (date_obj.year() == self.yearShown() and
                date_obj.month() == self.monthShown() and
                date_obj.day() in self._available_days):
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(QColor(self._theme.get("accent"))))
            painter.setPen(Qt.PenStyle.NoPen)
            dot_r = 3
            cx = rect.center().x()
            cy = rect.bottom() - 8
            painter.drawEllipse(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)
            painter.restore()


class _HolidayCalendar(QCalendarWidget):
    """QCalendarWidget that draws a red dot under market holidays."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._holiday_days: set = set()

    def set_holiday_days(self, days: set):
        self._holiday_days = days
        self.updateCells()

    def paintCell(self, painter, rect, date_obj):
        super().paintCell(painter, rect, date_obj)
        if (date_obj.year() == self.yearShown() and
                date_obj.month() == self.monthShown() and
                date_obj.day() in self._holiday_days):
            painter.save()
            painter.setRenderHint(QPainter.RenderHint.Antialiasing)
            painter.setBrush(QBrush(QColor(self._theme.get("status_red"))))
            painter.setPen(Qt.PenStyle.NoPen)
            # Proportional to cell height (not a fixed pixel offset) — this
            # popup calendar's cells are much shorter than the embedded
            # Browse-by-Date calendar's, so a fixed offset placed the dot on
            # top of the date digit instead of clearly below it.
            dot_r = max(2, min(3, rect.height() // 10))
            cx = rect.center().x()
            cy = rect.bottom() - dot_r - 2
            painter.drawEllipse(cx - dot_r, cy - dot_r, dot_r * 2, dot_r * 2)
            painter.restore()


class HistoricUploadScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_file = None
        self._headers = []
        self._rows = []
        self._row_dates = []
        self._structural_cols = set()   # header indices excluded from metric checkboxes
        self._checkboxes = []
        self._upload_date = date.today()
        self._viewers = []
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)

        title = QLabel("Historic Upload")
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

        # Date row
        date_row = QHBoxLayout()
        self._date_lbl = QLabel("Date")
        self._date_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        self._date_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._date_btn = QPushButton(self._upload_date.strftime("%d-%b-%Y"))
        self._date_btn.setFixedHeight(30)
        self._date_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_date_btn_style()
        self._date_btn.clicked.connect(self._show_date_picker)
        date_row.addWidget(self._date_lbl)
        date_row.addWidget(self._date_btn)
        date_row.addStretch()
        layout.addLayout(date_row)

        # File row
        file_row = QHBoxLayout()
        self._file_lbl = QLabel("No file selected")
        self._file_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._file_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._browse_btn = QPushButton("Browse")
        self._browse_btn.setFixedHeight(30)
        self._browse_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_browse_btn_style()
        self._browse_btn.clicked.connect(self._browse)
        file_row.addWidget(self._browse_btn)
        file_row.addWidget(self._file_lbl, 1)
        layout.addLayout(file_row)

        # Column selection disclosure
        self._columns_toggle = QToolButton()
        self._columns_toggle.setCheckable(True)
        self._columns_toggle.setChecked(False)
        self._columns_toggle.setFont(font_scale.font(font_scale.SMALL, False))
        self._columns_toggle.setCursor(Qt.CursorShape.PointingHandCursor)
        self._columns_toggle.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self._update_columns_toggle_style()
        self._columns_toggle.clicked.connect(self._on_columns_toggle)
        self._set_columns_toggle_text()
        layout.addWidget(self._columns_toggle)

        self._columns_frame = QFrame()
        self._columns_frame.setVisible(False)
        self._columns_layout = QVBoxLayout(self._columns_frame)
        self._columns_layout.setContentsMargins(16, 8, 4, 8)
        self._columns_layout.setSpacing(10)

        columns_scroll = QScrollArea()
        columns_scroll.setWidgetResizable(True)
        columns_scroll.setFrameShape(QFrame.Shape.NoFrame)
        columns_scroll.setWidget(self._columns_frame)
        scroll_size_policy = columns_scroll.sizePolicy()
        scroll_size_policy.setRetainSizeWhenHidden(True)
        columns_scroll.setSizePolicy(scroll_size_policy)
        columns_scroll.setVisible(False)
        self._columns_scroll = columns_scroll
        layout.addWidget(columns_scroll, 1)

        # Status + save
        bottom_row = QHBoxLayout()
        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        bottom_row.addWidget(self._status_lbl)
        bottom_row.addStretch()
        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedHeight(32)
        self._save_btn.setFixedWidth(100)
        self._save_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setEnabled(False)
        self._save_btn.clicked.connect(self._on_save)
        bottom_row.addWidget(self._save_btn)
        layout.addLayout(bottom_row)

        return tab

    def _update_columns_toggle_style(self):
        t = self._controller.theme
        self._columns_toggle.setStyleSheet(
            f"QToolButton {{ color: {t.get('text_primary')}; background: transparent;"
            f"border: none; padding: 4px 0; }}"
        )

    def _update_browse_btn_style(self):
        accent = self._controller.theme.get('accent')
        self._browse_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {accent};"
            f"border: 1px solid {accent}; border-radius: 4px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {accent}22; }}"
        )

    def _set_columns_toggle_text(self):
        checked_count = sum(1 for cb in self._checkboxes if cb.isChecked())
        total = len(self._checkboxes)
        arrow = "▾" if self._columns_toggle.isChecked() else "▸"
        self._columns_toggle.setText(f"{arrow} Columns ({checked_count}/{total} selected)")

    def _on_columns_toggle(self):
        expanded = self._columns_toggle.isChecked()
        self._columns_scroll.setVisible(expanded and bool(self._checkboxes))
        self._set_columns_toggle_text()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Historic File", "", "Supported Files (*.xlsx *.xls *.csv)"
        )
        if not path:
            return
        try:
            headers, rows, row_dates = read_historic_sheet(path)
        except Exception as exc:
            self._status_lbl.setText(f"Failed to read file: {exc}")
            self._status_lbl.setStyleSheet(f"color: {self._controller.theme.get('status_red')};")
            return
        self._selected_file = path
        self._headers = headers
        self._rows = rows
        self._row_dates = row_dates
        self._structural_cols = {
            i for i, h in enumerate(headers) if h in ("ScripName", "DataTime")
        }
        self._file_lbl.setText(f"Selected: {os.path.basename(path)} ({len(rows)} rows)")
        self._file_lbl.setStyleSheet(f"color: {self._controller.theme.get('accent')};")
        self._status_lbl.setText("")
        self._populate_columns()
        self._update_save_enabled()

    def _populate_columns(self):
        while self._columns_layout.count():
            item = self._columns_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._checkboxes = []
        self._checkbox_col_indices = []
        for i, header in enumerate(self._headers):
            if i < _METRIC_COL_START or i > _METRIC_COL_END:
                continue
            if i in self._structural_cols:
                continue
            cb = QCheckBox(str(header) if header else "(unnamed)")
            cb.setChecked(True)
            cb.setFont(font_scale.font(font_scale.SMALL, False))
            cb.stateChanged.connect(self._on_column_toggled)
            self._columns_layout.addWidget(cb)
            self._checkboxes.append(cb)
            self._checkbox_col_indices.append(i)
        self._columns_toggle.setChecked(True)
        self._columns_scroll.setVisible(True)
        self._set_columns_toggle_text()

    def _on_column_toggled(self):
        self._set_columns_toggle_text()
        self._update_save_enabled()

    def _update_save_enabled(self):
        has_file = self._selected_file is not None
        has_column = any(cb.isChecked() for cb in self._checkboxes)
        self._save_btn.setEnabled(has_file and has_column)

    def _on_save(self):
        mismatched_rows = [
            i + 1 for i, d in enumerate(self._row_dates)
            if d is not None and d != self._upload_date
        ]
        if mismatched_rows:
            t = self._controller.theme
            first = mismatched_rows[0]
            sheet_date = self._row_dates[first - 1]
            self._status_lbl.setText(
                f"Sheet date ({sheet_date.strftime('%d-%b-%Y')}) doesn't match "
                f"selected date ({self._upload_date.strftime('%d-%b-%Y')}). "
                f"Row {first}"
                + (f" (+{len(mismatched_rows) - 1} more)" if len(mismatched_rows) > 1 else "") + "."
            )
            self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        scripname_idx = self._headers.index("ScripName") if "ScripName" in self._headers else None
        selected_indices = self._checkbox_col_indices_selected()
        script_name_data = config_store.load_tab("script_name", SCRIPT_NAME_DATA)
        name_to_symbol = _build_script_name_lookup(script_name_data)

        rows_payload = []
        for row in self._rows:
            raw_name = str(row[scripname_idx]) if scripname_idx is not None and scripname_idx < len(row) else ""
            display_name = _strip_rolling_suffix(raw_name) or raw_name
            symbol = name_to_symbol.get(display_name.lower()) or display_name
            metrics = {}
            for idx in selected_indices:
                if idx < len(row):
                    metrics[self._headers[idx]] = row[idx]
            rows_payload.append({
                "symbol": symbol,
                "display_name": display_name or None,
                "metrics": metrics,
            })

        self._save_btn.setEnabled(False)
        self._save_btn.setText("Saving...")
        try:
            result = historic_api.upload_daily(self._upload_date, rows_payload)
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            self._save_btn.setEnabled(True)
            self._save_btn.setText("Save")

        t = self._controller.theme
        self._status_lbl.setText(
            f"Saved {result.get('values_upserted', 0)} values for "
            f"{self._upload_date.strftime('%d-%b-%Y')}."
        )
        self._status_lbl.setStyleSheet(f"color: {t.get('accent')};")
        self._reset_upload_form()

    def _checkbox_col_indices_selected(self) -> list:
        return [
            idx for cb, idx in zip(self._checkboxes, self._checkbox_col_indices)
            if cb.isChecked()
        ]

    def _reset_upload_form(self):
        self._selected_file = None
        self._headers = []
        self._rows = []
        self._row_dates = []
        self._structural_cols = set()
        self._checkboxes = []
        self._file_lbl.setText("No file selected")
        self._file_lbl.setStyleSheet(f"color: {self._controller.theme.get('text_secondary')};")
        while self._columns_layout.count():
            item = self._columns_layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._columns_scroll.setVisible(False)
        self._columns_toggle.setChecked(False)
        self._set_columns_toggle_text()
        self._save_btn.setEnabled(False)
        if hasattr(self, "_browse_refresh_calendar"):
            self._browse_refresh_calendar()

    # ── date picker (popup calendar, mirrors BrokerImportCard) ─────────────

    def _show_date_picker(self):
        t = self._controller.theme
        cal = _HolidayCalendar(t)
        cal.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        cal.setFont(font_scale.font(font_scale.SMALL, False))
        cal.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        cal.setStyleSheet(_themed_calendar_stylesheet(t))

        qd = QDate(self._upload_date.year, self._upload_date.month, self._upload_date.day)
        cal.setSelectedDate(qd)
        cal.setCurrentPage(qd.year(), qd.month())

        self._picker_holidays: set = set()

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
                self._status_lbl.setText(
                    f"{selected.strftime('%d-%b-%Y')} is a market holiday — pick another date."
                )
                self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
                return
            self._upload_date = selected
            self._date_btn.setText(self._upload_date.strftime("%d-%b-%Y"))
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

    def _update_date_btn_style(self):
        t = self._controller.theme
        bg = t.get('input_bg')
        txt = t.get('text_primary')
        bd = t.get('border')
        accent = t.get('accent')
        self._date_btn.setStyleSheet(f"""
            QPushButton {{
                background: {bg};
                color: {txt};
                border: 1px solid {bd};
                border-radius: 4px;
                padding: 4px 10px;
            }}
            QPushButton:hover {{
                border-color: {accent};
                color: {accent};
            }}
        """)

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
        self._view_btn = QPushButton("View")
        self._view_btn.setFixedHeight(32)
        self._view_btn.setFixedWidth(100)
        self._view_btn.setFont(font_scale.font(font_scale.SMALL, True))
        self._view_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._view_btn.clicked.connect(self._on_view_clicked)
        bottom_row.addWidget(self._view_btn)
        layout.addLayout(bottom_row)

        layout.addStretch()

        # Defer the initial availability fetch (a blocking network call) so it
        # doesn't hold up widget construction — this can run during MainWindow
        # construction on the auto-login path, before any window is visible.
        QTimer.singleShot(0, self._refresh_browse_availability)
        self._update_view_btn_enabled()
        self._browse_refresh_calendar = self._refresh_browse_availability
        return tab

    def _refresh_browse_availability(self):
        today = date.today()
        year = self._browse_calendar.yearShown() or today.year
        month = self._browse_calendar.monthShown() or today.month
        # Called during initial widget construction (and after a save, via the
        # _browse_refresh_calendar hook) — a blocking modal popup here would fire
        # before the user has done anything (or right after a successful save),
        # so failures are reported quietly instead of via show_api_error().
        self._fetch_and_apply_availability(year, month, show_popup_on_error=False)

    def _on_browse_page_changed(self, year, month):
        # User-initiated (navigating the calendar month) — a blocking modal on
        # failure is acceptable here since the screen is already visible.
        self._fetch_and_apply_availability(year, month)

    def _fetch_and_apply_availability(self, year: int, month: int, show_popup_on_error: bool = True):
        import calendar as _cal
        last_day = _cal.monthrange(year, month)[1]
        date_from = date(year, month, 1)
        date_to = date(year, month, last_day)
        try:
            result = historic_api.get_availability(date_from, date_to)
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
            self._update_view_btn_enabled()
            return
        self._browse_calendar.set_available_days(days)
        self._available_days = days
        self._update_view_btn_enabled()

    def _on_browse_date_selected(self, qdate):
        self._selected_browse_date = date(qdate.year(), qdate.month(), qdate.day())
        self._update_view_btn_enabled()

    def _update_view_btn_enabled(self):
        days = getattr(self, "_available_days", set())
        self._view_btn.setEnabled(self._selected_browse_date.day in days)

    def _on_view_clicked(self):
        t = self._controller.theme
        try:
            result = historic_api.get_snapshot(self._selected_browse_date)
            stocks = result.get("stocks", [])
            if stocks:
                metric_keys = sorted({k for s in stocks for k in s.get("metrics", {})})
                headers = ["Symbol", "Display Name"] + metric_keys
                rows = [
                    [s["symbol"], s.get("display_name") or ""] +
                    [s.get("metrics", {}).get(k) for k in metric_keys]
                    for s in stocks
                ]
        except (ApiError, NetworkError) as exc:
            show_api_error(t, self, exc)
            return
        except (KeyError, ValueError, TypeError):
            self._browse_status_lbl.setText("Couldn't parse response from server.")
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        if not stocks:
            self._browse_status_lbl.setText(
                f"No data saved for {self._selected_browse_date.strftime('%d-%b-%Y')}."
            )
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
            return

        viewer = HistoricDataViewer(headers, rows, self._selected_browse_date.strftime("%d-%b-%Y"), theme=t)
        viewer.show()
        self._viewers.append(viewer)
        self._browse_status_lbl.setText("")

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._controller.theme
        self._date_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._update_date_btn_style()
        self._update_browse_btn_style()
        self._update_columns_toggle_style()
        if not self._selected_file:
            self._file_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        if not self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        if not self._browse_status_lbl.text():
            self._browse_status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._browse_calendar.setStyleSheet(_themed_calendar_stylesheet(t))
        for viewer in self._viewers:
            if viewer.isVisible():
                viewer.refresh_theme()
