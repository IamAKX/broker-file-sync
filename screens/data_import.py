import font_scale
import re
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QFileDialog, QSizePolicy,
    QCalendarWidget
)
from PySide6.QtCore import Qt, QTimer, QByteArray, QSize, Signal, QDate, QObject
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from services.file_reader import (
    count_rows_sharekhan,
    count_rows_reliable,
    count_rows_nifty,
    count_rows_external,
    count_rows_market_profile,
)

_BROKER_ROW_COUNTERS = {
    "Sharekhan":        count_rows_sharekhan,
    "ReliableSoftware": count_rows_reliable,
    "NiftyInvest":      count_rows_nifty,
    "ExternalImport":   count_rows_external,
    "MarketProfile":    count_rows_market_profile,
}

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")

BROKERS = [
    ("Sharekhan",        "status_red",    "TradeBook export (.xlsx / .xls)",        (".xlsx", ".xls"),        True,  False),
    ("ReliableSoftware", "status_blue",   "Transactions export (.xlsx / .xls)",     (".xlsx", ".xls"),        True,  False),
    ("NiftyInvest",      "status_orange", "Portfolio export (.csv)",                (".csv",),                False, False),
    ("ExternalImport",   "status_purple", "Any file — columns auto-detected",       (".xlsx", ".xls", ".csv"), False, True),
    ("MarketProfile",    "status_pink",   "Market Profile export (.csv / .xlsx)",   (".csv", ".xlsx", ".xls"), True,  False),
]


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
    svg = re.sub(r'(<svg\b[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect|g)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class BrokerImportCard(QFrame):
    import_done = Signal(str, int)  # broker name, row count
    import_reset = Signal(str)      # broker name when file is deleted
    # broker name, active, rows (-1 when active due to database-mode selection,
    # not an actual file import)
    source_active = Signal(str, bool, int)

    def __init__(self, broker: str, color_token: str, hint: str, theme,
                 exts: tuple = (".xlsx", ".xls"), show_date_picker: bool = False,
                 show_source_toggle: bool = False, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._broker = broker
        self._hint = hint
        self._exts = exts
        self._selected_file = None
        self._row_count = 0
        self._progress_value = 0
        self._show_date_picker = show_date_picker
        self._show_source_toggle = show_source_toggle
        self._source_mode = "file"
        self._formula_viewer = None
        self.setObjectName("brokerPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)
        self._build(color_token, hint)

    # ── Drag & drop (the whole card is the drop target) ────────────────────────
    def dragEnterEvent(self, event):
        if self._source_mode != "file":
            event.ignore()
            return
        if event.mimeData().hasUrls() and any(
            u.toLocalFile().lower().endswith(self._exts) for u in event.mimeData().urls()
        ):
            event.acceptProposedAction()
            return
        event.ignore()

    def dragMoveEvent(self, event):
        if self._source_mode != "file":
            return
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        if self._source_mode != "file":
            return
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(self._exts):
                self._on_file_dropped(path)
                event.acceptProposedAction()
                return

    def mousePressEvent(self, event):
        # Click anywhere on the card (except child buttons) triggers the
        # primary action for the current source mode.
        self._on_primary_action()

    def _build(self, color_token: str, hint: str):
        t = self._theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(12)

        # Status dot
        dot = QLabel("●")
        dot.setFont(font_scale.font(font_scale.MEDIUM, False))
        dot.setStyleSheet(f"color: {t.get(color_token)};")
        dot.setFixedWidth(16)
        layout.addWidget(dot)

        # Name + sub-label (hint, or filename + rows once imported)
        info_col = QVBoxLayout()
        info_col.setSpacing(1)
        name_lbl = QLabel(self._broker)
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        self._file_lbl = QLabel(hint)
        self._file_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._file_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        info_col.addWidget(name_lbl)
        info_col.addWidget(self._file_lbl)
        layout.addLayout(info_col, 1)

        # File / Database source toggle (only for ExternalImport, for now)
        if self._show_source_toggle:
            from screens.notifications import ToggleSwitch

            source_row = QHBoxLayout()
            source_row.setSpacing(6)
            self._file_mode_lbl = QLabel("File")
            self._file_mode_lbl.setFont(font_scale.font(font_scale.SMALL, True))
            self._source_toggle = ToggleSwitch(False)
            self._source_toggle.toggled.connect(self._on_source_toggled)
            self._db_mode_lbl = QLabel("DB")
            self._db_mode_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            source_row.addWidget(self._file_mode_lbl)
            source_row.addWidget(self._source_toggle)
            source_row.addWidget(self._db_mode_lbl)
            layout.addLayout(source_row)
            self._update_source_mode_style()

        # Date picker (Sharekhan: F&O expiry date; ReliableSoftware: plain
        # manual date, no expiry semantics)
        if self._show_date_picker:
            if self._broker == "Sharekhan":
                from services.master_generator import last_tuesday_of_month
                default_date = last_tuesday_of_month()
            else:
                from datetime import date
                default_date = date.today()
            self._expiry_date = default_date

            self._date_btn = QPushButton(default_date.strftime("%d-%b-%Y"))
            self._date_btn.setFixedHeight(30)
            self._date_btn.setFont(font_scale.font(font_scale.SMALL, False))
            self._date_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self._update_date_btn_style()
            self._date_btn.clicked.connect(self._show_calendar)
            layout.addWidget(self._date_btn)

        # Progress bar + percentage (inline, hidden until importing)
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedSize(110, 6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._pct_lbl = QLabel("")
        self._pct_lbl.setFixedWidth(34)
        self._pct_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._pct_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._pct_lbl.setVisible(False)
        layout.addWidget(self._progress)
        layout.addWidget(self._pct_lbl)

        # Browse button
        self._browse_btn = QPushButton("Browse")
        self._browse_btn.setFixedSize(80, 30)
        self._browse_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        accent = t.get('accent')
        self._browse_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {accent};"
            f"border: 1px solid {accent}; border-radius: 4px; padding: 0 14px; }}"
            f"QPushButton:hover {{ background: {accent}22; }}"
        )
        self._browse_btn.clicked.connect(self._on_primary_action)
        layout.addWidget(self._browse_btn)

        # Status badge
        self._status_lbl = QLabel("Awaiting")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setFixedHeight(22)
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._status_lbl.setStyleSheet(
            f"color: {t.get('text_secondary')}; border: 1px solid {t.get('text_secondary')};"
            "border-radius: 4px; padding: 0 8px;"
        )
        layout.addWidget(self._status_lbl)

        # Remove button (hidden until a file is imported)
        self._delete_btn = QPushButton("✕")
        self._delete_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._delete_btn.setFixedSize(26, 26)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setToolTip("Remove file")
        self._delete_btn.setStyleSheet(
            f"color: {t.get('status_red')}; background: transparent; border: none;"
        )
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._reset)
        layout.addWidget(self._delete_btn)

    def _on_file_dropped(self, path: str):
        if self._broker == "ExternalImport" and not self._validate_external_import_headers(path):
            return
        if self._broker == "ReliableSoftware" and not self._validate_reliable_software_date(path):
            return
        if self._broker == "MarketProfile" and not self._validate_market_profile_date(path):
            return
        self._selected_file = path
        counter = _BROKER_ROW_COUNTERS.get(self._broker, count_rows_sharekhan)
        self._row_count = counter(path)
        self._file_lbl.setText(f"Selected: {os.path.basename(path)}")
        self._file_lbl.setStyleSheet(f"color: {self._theme.get('accent')};")
        self._start_import()

    def _validate_external_import_headers(self, path: str) -> bool:
        """ExternalImport's file source must match the same column set the
        database source calculates — reject anything else up front rather
        than silently importing a mismatched sheet."""
        from PySide6.QtWidgets import QMessageBox
        from services.file_reader import read_external_import
        from services import formula_engine

        expected = ["Symbol", "Display Name"] + formula_engine.FORMULA_CODES
        try:
            headers, _rows = read_external_import(path)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid File", f"Could not read {os.path.basename(path)}:\n\n{exc}")
            return False

        actual = [str(h).strip() if h is not None else "" for h in headers]
        if actual != expected:
            missing = [h for h in expected if h not in actual]
            extra = [h for h in actual if h not in expected]
            detail_lines = []
            if missing:
                detail_lines.append("Missing: " + ", ".join(missing))
            if extra:
                detail_lines.append("Unexpected: " + ", ".join(extra))
            if not detail_lines:
                detail_lines.append("Column order doesn't match the required order.")
            QMessageBox.critical(
                self, "Column Mismatch",
                f"{os.path.basename(path)}'s first row doesn't match the required "
                f"ExternalImport columns.\n\n" + "\n".join(detail_lines)
            )
            return False
        return True

    def _validate_broker_file_date(self, path: str, date_reader, date_column_label: str) -> bool:
        """Shared freshness check for brokers whose export carries a
        trade-date column that isn't otherwise read by their normal parser —
        catches an old/wrong-day file before it's silently merged into the
        Live Master View. Only day/month are compared (not year) — same
        idea as Sharekhan's expiry-date check above, applied to freshness
        instead of symbol suffix stripping."""
        from PySide6.QtWidgets import QMessageBox
        from datetime import date

        try:
            file_date = date_reader(path)
        except Exception as exc:
            QMessageBox.critical(self, "Invalid File", f"Could not read {os.path.basename(path)}:\n\n{exc}")
            return False

        if file_date is None:
            QMessageBox.critical(
                self, "Missing Date",
                f"{os.path.basename(path)} has no readable {date_column_label} value in its first data row."
            )
            return False

        today = date.today()
        if (file_date.day, file_date.month) != (today.day, today.month):
            QMessageBox.critical(
                self, "Date Mismatch",
                f"{os.path.basename(path)} is dated {file_date.strftime('%d-%b')}, "
                f"but today is {today.strftime('%d-%b')}. Import a file for today's date."
            )
            return False
        return True

    def _validate_reliable_software_date(self, path: str) -> bool:
        from services.file_reader import read_reliable_software_date
        return self._validate_broker_file_date(path, read_reliable_software_date, "DataTime")

    def _validate_market_profile_date(self, path: str) -> bool:
        from services.file_reader import read_market_profile_date
        return self._validate_broker_file_date(path, read_market_profile_date, "Date")

    def _browse(self):
        if self._exts == (".csv",):
            file_filter = "CSV Files (*.csv)"
        elif ".csv" in self._exts:
            file_filter = "Supported Files (*.xlsx *.xls *.csv)"
        else:
            file_filter = "Excel Files (*.xlsx *.xls)"
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {self._broker} File", "", file_filter
        )
        if path:
            self._on_file_dropped(path)

    def _on_primary_action(self):
        """Dispatch the browse-button/card-click action for the current source mode."""
        if self._source_mode == "database":
            self._open_formula_viewer()
        else:
            self._browse()

    def _on_source_toggled(self, checked: bool):
        self._source_mode = "database" if checked else "file"
        self._browse_btn.setText("View" if checked else "Browse")
        self._update_source_mode_style()
        if self._source_mode == "database":
            # Selecting the database source is itself "configured" — glow
            # regardless of whether a file was ever picked in file mode.
            self._set_status_imported()
            self.source_active.emit(self._broker, True, -1)
        else:
            # Back to file mode: restore whichever status actually applies —
            # a real completed import, or Awaiting if none — since the
            # database-mode toggle may have overwritten it with "Imported".
            if self._selected_file:
                self._set_status_imported()
            else:
                self._set_status_awaiting()
            self.source_active.emit(
                self._broker, bool(self._selected_file), self._row_count
            )

    def _set_status_imported(self):
        acc = self._theme.get('accent')
        self._status_lbl.setText("Imported")
        self._status_lbl.setStyleSheet(
            f"color: {acc}; border: 1px solid {acc};"
            "border-radius: 4px; padding: 0 8px;"
        )

    def _set_status_awaiting(self):
        txt_s = self._theme.get('text_secondary')
        self._status_lbl.setText("Awaiting")
        self._status_lbl.setStyleSheet(
            f"color: {txt_s}; border: 1px solid {txt_s};"
            "border-radius: 4px; padding: 1px 8px;"
        )

    def _update_source_mode_style(self):
        t = self._theme
        active = t.get("text_primary")
        inactive = t.get("text_secondary")
        is_file = self._source_mode == "file"
        self._file_mode_lbl.setFont(font_scale.font(font_scale.SMALL, is_file))
        self._file_mode_lbl.setStyleSheet(f"color: {active if is_file else inactive};")
        self._db_mode_lbl.setFont(font_scale.font(font_scale.SMALL, not is_file))
        self._db_mode_lbl.setStyleSheet(f"color: {inactive if is_file else active};")

    def _open_formula_viewer(self):
        """Fetch stored historic data, run it through the formula engine, and
        show the calculated per-stock table for the database source."""
        if self._formula_viewer is not None and not self._formula_viewer.isHidden():
            self._formula_viewer.raise_()
            self._formula_viewer.activateWindow()
            return

        from datetime import date
        from PySide6.QtWidgets import QApplication, QMessageBox
        from api.exceptions import ApiError, NetworkError
        from components.error_popup import show_api_error
        from services.external_import_source import read_external_import_db
        from screens.historic_viewer import HistoricDataViewer

        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        self._browse_btn.setEnabled(False)
        original_text = self._browse_btn.text()
        self._browse_btn.setText("Loading...")
        try:
            # Always calculate as of today — CWH/CMH/etc. must mean the actual
            # current week/month, not the week of the last upload.
            target = date.today()
            try:
                headers, rows = read_external_import_db(target)
            except (ApiError, NetworkError) as exc:
                show_api_error(self._theme, self, exc)
                return

            if not rows:
                QMessageBox.information(
                    self, "No Data",
                    "No historic data has been saved yet — upload some via "
                    "Historic Upload first."
                )
                return

            target_str = target.strftime("%d-%b-%Y")
            self._formula_viewer = HistoricDataViewer(
                headers, rows, target_str, theme=self._theme,
                title=f"External Import — as of {target_str}",
            )
            self._formula_viewer.setWindowFlag(Qt.WindowType.Window)
            self._formula_viewer.show()
        finally:
            self._browse_btn.setEnabled(True)
            self._browse_btn.setText(original_text)
            QApplication.restoreOverrideCursor()

    def _start_import(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self._progress_value = 0
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._pct_lbl.setText("0%")
        self._pct_lbl.setVisible(True)
        self._delete_btn.setVisible(False)
        self._status_lbl.setText("Importing...")
        self._status_lbl.setStyleSheet(
            f"color: {self._theme.get('accent')}; border: 1px solid {self._theme.get('accent')};"
            "border-radius: 4px; padding: 1px 8px;"
        )
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self):
        self._progress_value += 2
        self._progress.setValue(self._progress_value)
        self._pct_lbl.setText(f"{self._progress_value}%")
        if self._progress_value >= 100:
            self._timer.stop()
            self._progress.setVisible(False)
            self._pct_lbl.setVisible(False)
            self._set_status_imported()
            rows = self._row_count
            self._file_lbl.setText(f"1 file imported · {rows:,} rows")
            self._file_lbl.setStyleSheet(f"color: {self._theme.get('accent')};")
            self._delete_btn.setVisible(True)
            self.import_done.emit(self._broker, rows)

    def _reset(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self._selected_file = None
        self._row_count = 0
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._pct_lbl.setVisible(False)
        self._delete_btn.setVisible(False)
        self._browse_btn.setVisible(True)
        self._set_status_awaiting()
        self._file_lbl.setText(self._hint)
        self._file_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        self.import_reset.emit(self._broker)

    def get_expiry_date(self):
        """Return the selected expiry date as a datetime.date object."""
        if self._show_date_picker and hasattr(self, "_expiry_date"):
            return self._expiry_date
        return None

    def refresh_theme(self):
        """Re-apply styles to match current theme after a toggle."""
        if self._show_date_picker and hasattr(self, "_date_btn"):
            self._update_date_btn_style()
        if self._show_source_toggle:
            self._update_source_mode_style()

    def _show_calendar(self):
        """Show a themed calendar popup to pick the expiry date."""
        t = self._theme
        bg = t.get('card_bg')
        txt = t.get('text_primary')
        txt_s = t.get('text_secondary')
        bd = t.get('border')
        accent = t.get('accent')
        btn_bg = t.get('button_bg')

        cal = QCalendarWidget()
        cal.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        cal.setFont(font_scale.font(font_scale.SMALL, False))
        cal.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        cal.setStyleSheet(f"""
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
        """)

        if self._expiry_date:
            from PySide6.QtCore import QDate
            qd = QDate(self._expiry_date.year, self._expiry_date.month, self._expiry_date.day)
            cal.setSelectedDate(qd)
            cal.setCurrentPage(qd.year(), qd.month())

        def on_date_selected(date_obj):
            from datetime import date
            self._expiry_date = date(date_obj.year(), date_obj.month(), date_obj.day())
            self._date_btn.setText(self._expiry_date.strftime("%d-%b-%Y"))
            self._update_date_btn_style()
            self._close_calendar()

        cal.clicked.connect(on_date_selected)
        cal.show()
        self._calendar = cal
        # Timer to detect outside clicks and close the calendar
        self._cal_outside_timer = QTimer()
        self._cal_outside_timer.setInterval(100)
        self._cal_outside_timer.timeout.connect(self._check_calendar_outside_click)
        self._cal_outside_timer.start()

    def _close_calendar(self):
        if hasattr(self, "_cal_outside_timer"):
            self._cal_outside_timer.stop()
        if hasattr(self, "_calendar") and self._calendar is not None:
            self._calendar.close()

    def _check_calendar_outside_click(self):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QApplication
        if not hasattr(self, "_calendar") or self._calendar is None or not self._calendar.isVisible():
            if hasattr(self, "_cal_outside_timer"):
                self._cal_outside_timer.stop()
            return
        # Check if any mouse button is pressed
        if QApplication.mouseButtons() != Qt.MouseButton.NoButton:
            if not self._calendar.geometry().contains(QCursor.pos()):
                self._close_calendar()

    def _update_date_btn_style(self):
        """Re-apply date button style to match current theme."""
        t = self._theme
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
                padding: 4px 12px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {accent};
            }}
        """)


class DataImportScreen(QWidget):
    broker_imported    = Signal(str, int)   # broker name, row count
    broker_reset       = Signal(str)
    broker_source_active = Signal(str, bool, int)  # broker, active, rows (-1 = db-selected)
    lmv_headers_ready  = Signal(list)       # emitted when LMV loads headers
    lmv_data_ready     = Signal(list, list)  # headers, data rows (list[list])
    _REQUIRED_BROKERS = {"Sharekhan", "ReliableSoftware", "NiftyInvest",
                         "ExternalImport", "MarketProfile"}

    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._imported_brokers: set[str] = set()
        self._watcher_btn: QPushButton = None
        self._live_viewer = None
        self._dot_bright = True
        self._pulse_timer = QTimer()
        self._pulse_timer.setInterval(700)
        self._pulse_timer.timeout.connect(self._pulse_dot)
        self._build()
        # Keep button state in sync with watcher lifecycle
        self._controller.watcher.started.connect(self._on_watcher_started)
        self._controller.watcher.stopped.connect(self._on_watcher_stopped)

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Data Import")
        title.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        layout.addWidget(title)

        subtitle = QLabel(
            "Upload all five files to start the watcher. "
            "Sharekhan, ReliableSoftware, NiftyInvest, ExternalImport, and "
            "MarketProfile are all required."
        )
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # Compact vertical list of broker cards — all 5 fit without scrolling.
        cards_col = QVBoxLayout()
        cards_col.setContentsMargins(0, 0, 0, 0)
        cards_col.setSpacing(10)
        self._cards: dict[str, BrokerImportCard] = {}
        for broker, color_token, hint, exts, show_date, show_source_toggle in BROKERS:
            card = BrokerImportCard(broker, color_token, hint, t, exts, show_date, show_source_toggle)
            card.import_done.connect(self.broker_imported)
            card.import_reset.connect(self.broker_reset)
            card.import_done.connect(self._on_card_imported)
            card.import_reset.connect(self._on_card_reset)
            card.source_active.connect(self.broker_source_active)
            card.source_active.connect(self._on_card_source_active)
            self._cards[broker] = card
            cards_col.addWidget(card)
        layout.addLayout(cards_col)
        layout.addStretch()

        # Bottom button row — Run Watcher
        gen_row = QHBoxLayout()
        gen_row.addStretch()

        self._watcher_btn = QPushButton("  Run Watcher")
        self._watcher_btn.setFixedHeight(40)
        self._watcher_btn.setFont(font_scale.font(font_scale.MEDIUM, True))
        self._watcher_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._watcher_btn.setEnabled(False)
        self._watcher_btn.clicked.connect(self._run_watcher)
        self._update_watcher_btn()
        gen_row.addWidget(self._watcher_btn)

        layout.addLayout(gen_row)

    def _on_card_imported(self, broker: str, rows: int):
        self._imported_brokers.add(broker)
        self._update_watcher_btn()

    def _on_card_reset(self, broker: str):
        self._imported_brokers.discard(broker)
        self._update_watcher_btn()

    def _on_card_source_active(self, broker: str, active: bool, rows: int):
        # ExternalImport's File/DB toggle can change whether the required
        # brokers are all "ready" — re-evaluate the Run Watcher gate.
        self._update_watcher_btn()

    def _on_watcher_started(self):
        self._pulse_timer.start()
        self._dot_bright = True
        self._apply_watcher_running_style(bright=True)

    def _on_watcher_stopped(self):
        self._pulse_timer.stop()
        self._update_watcher_btn()

    def _pulse_dot(self):
        self._dot_bright = not self._dot_bright
        self._apply_watcher_running_style(bright=self._dot_bright)

    def _apply_watcher_running_style(self, bright: bool):
        if self._watcher_btn is None:
            return
        dot_color = "#39d353" if bright else "#1a5c28"
        self._watcher_btn.setText(f"  ● Watcher Running")
        self._watcher_btn.setEnabled(False)
        self._watcher_btn.setStyleSheet(
            f"QPushButton {{ background: transparent;"
            f"color: {dot_color};"
            f"border: 1px solid {dot_color};"
            "border-radius: 4px; padding: 0 20px; }"
        )

    def _required_brokers_ready(self) -> bool:
        """A broker is "ready" once it has imported a file — except
        ExternalImport in database mode, which never fires import_done since
        there's no file, but is just as valid a source once selected."""
        for broker in self._REQUIRED_BROKERS:
            if broker in self._imported_brokers:
                continue
            card = self._cards.get(broker)
            if broker == "ExternalImport" and card is not None and card._source_mode == "database":
                continue
            return False
        return True

    def _update_watcher_btn(self):
        if self._watcher_btn is None:
            return
        t        = self._controller.theme
        all_done = self._required_brokers_ready()
        if all_done:
            self._watcher_btn.setText("  Run Watcher")
            self._watcher_btn.setEnabled(True)
            self._watcher_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t.get('accent')};"
                f"border: 1px solid {t.get('accent')}; border-radius: 4px; padding: 0 20px; }}"
                f"QPushButton:hover {{ background: {t.get('accent')}22; }}"
            )
        else:
            self._watcher_btn.setText("  Run Watcher")
            self._watcher_btn.setEnabled(False)
            self._watcher_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #555e68;"
                "border: 1px solid #555e68; border-radius: 4px; padding: 0 20px; }"
            )

    def _run_watcher(self):
        from config_defaults import SCRIPT_NAME_DATA
        from screens.live_viewer import LiveViewerWindow

        sharekhan_path = self._cards["Sharekhan"]._selected_file
        reliable_path  = self._cards["ReliableSoftware"]._selected_file
        nifty_path     = self._cards["NiftyInvest"]._selected_file
        external_card  = self._cards["ExternalImport"]
        external_path  = external_card._selected_file
        external_mode  = external_card._source_mode
        market_profile_path = self._cards["MarketProfile"]._selected_file
        expiry_date    = self._cards["Sharekhan"].get_expiry_date()
        # Reuse existing window if already open
        if self._live_viewer is not None and not self._live_viewer.isHidden():
            self._live_viewer.raise_()
            self._live_viewer.activateWindow()
            return

        self._live_viewer = LiveViewerWindow(
            sharekhan_path, reliable_path, nifty_path,
            SCRIPT_NAME_DATA,
            expiry_date=expiry_date,
            external_path=external_path,
            external_mode=external_mode,
            market_profile_path=market_profile_path,
            theme=self._controller.theme,
            controller=self._controller,
        )
        self._live_viewer.show()
        # Share LMV column headers and row data with strategy builder
        if self._live_viewer._headers:
            self.lmv_headers_ready.emit(list(self._live_viewer._headers))
            self.lmv_data_ready.emit(
                list(self._live_viewer._headers),
                [list(r) for r in self._live_viewer._data],
            )
        # Keep strategy builder in sync as live data refreshes
        self._live_viewer.data_updated.connect(
            lambda headers, data: self.lmv_data_ready.emit(
                list(headers), [list(r) for r in data]
            )
        )
        # Notify the rest of the UI that the watcher is now active
        self._controller.watcher.started.emit()

    def refresh_theme(self):
        """Re-apply styles on all child cards after a theme toggle."""
        for card in self._cards.values():
            card.refresh_theme()

