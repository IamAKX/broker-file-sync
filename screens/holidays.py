"""Edit menu -> Market Holidays.

Per-tenant CRUD screen for the market holiday calendar. There is no free/
stable public NSE holiday API (checked), so this is maintained manually:
add/edit/delete a (date, name) row per holiday, scoped by year. Backs the
"working day" logic in services/formula_engine.py and the Historic Upload
rejection of a holiday trade_date — both live in broker-sync-api, not here;
this screen only manages the underlying data via the /holidays API.
"""
import os
import re
from datetime import date

import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSpinBox, QMessageBox, QCalendarWidget
)
from PySide6.QtCore import Qt, QByteArray, QSize, QTimer, QDate
from PySide6.QtGui import QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

from api import holidays_api
from api.exceptions import ApiError, NetworkError
from components.error_popup import show_api_error

_ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")
_DATE_FORMAT = "%d-%b-%Y"
_DATE_COL, _NAME_COL, _DEL_COL = 0, 1, 2


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


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(_ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^>]*></rect>', '', svg)
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


class HolidaysScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._theme = controller.theme
        self._build()
        # Defer the initial fetch (blocking network call) so it doesn't hold
        # up widget construction — same pattern as historic_upload.py. Quiet
        # on error: this can fire before the user has navigated here at all
        # (or from a theme toggle while another screen is visible), and a
        # blocking QMessageBox popping up unprompted — with no user present
        # to dismiss it in an automated/headless run — hangs the process.
        QTimer.singleShot(0, lambda: self._load_holidays(show_popup_on_error=False))

    def _build(self):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        title = QLabel("Market Holidays")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        subtitle = QLabel(
            "Trading holidays for your tenant. Historic Upload rejects a save on any "
            "date listed here, and \"working day\" formulas (FH/FL, PMH/PML/PMC, "
            "PWH/PWL/PWC, EWH/EWL, DT/DB) use this list to tell a real holiday apart "
            "from a missing upload."
        )
        subtitle.setFont(font_scale.font(font_scale.SMALL, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        subtitle.setWordWrap(True)
        self._subtitle = subtitle
        layout.addWidget(subtitle)

        top_row = QHBoxLayout()
        year_lbl = QLabel("Year:")
        year_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        self._year_spin = QSpinBox()
        self._year_spin.setRange(2000, 2100)
        self._year_spin.setValue(date.today().year)
        self._year_spin.setFixedHeight(30)
        self._year_spin.setFixedWidth(90)
        self._year_spin.valueChanged.connect(lambda _year: self._load_holidays())
        top_row.addWidget(year_lbl)
        top_row.addWidget(self._year_spin)
        top_row.addSpacing(16)

        add_btn = QPushButton("+ Add Row")
        add_btn.setFixedHeight(30)
        add_btn.setFont(font_scale.font(font_scale.SMALL, False))
        add_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._add_btn = add_btn
        add_btn.clicked.connect(self._add_row)
        top_row.addWidget(add_btn)
        top_row.addStretch()

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        top_row.addWidget(self._status_lbl)
        layout.addLayout(top_row)

        self._table = QTableWidget(0, 3)
        self._table.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._table.setHorizontalHeaderLabels(["Date", "Name", ""])
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked |
            QAbstractItemView.EditTrigger.EditKeyPressed
        )
        hh = self._table.horizontalHeader()
        hh.setSectionResizeMode(_DATE_COL, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(_DATE_COL, 140)
        hh.setSectionResizeMode(_NAME_COL, QHeaderView.ResizeMode.Stretch)
        hh.setSectionResizeMode(_DEL_COL, QHeaderView.ResizeMode.Fixed)
        hh.resizeSection(_DEL_COL, 44)
        layout.addWidget(self._table, 1)

        bottom_row = QHBoxLayout()
        bottom_row.addStretch()
        self._save_btn = QPushButton("Save")
        self._save_btn.setFixedHeight(34)
        self._save_btn.setFixedWidth(110)
        self._save_btn.setFont(font_scale.font(font_scale.MEDIUM, True))
        self._save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; }"
        )
        self._save_btn.clicked.connect(self._save)
        bottom_row.addWidget(self._save_btn)
        layout.addLayout(bottom_row)

    # ── Load ─────────────────────────────────────────────────────────────

    def _load_holidays(self, show_popup_on_error: bool = True):
        try:
            rows = holidays_api.list_holidays(self._year_spin.value())
        except (ApiError, NetworkError) as exc:
            if show_popup_on_error:
                show_api_error(self._theme, self, exc)
            else:
                self._status_lbl.setText("Couldn't load holidays — check your connection.")
                self._status_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
            return
        self._table.setRowCount(0)
        for row in rows:
            d = date.fromisoformat(row["holiday_date"])
            self._insert_row(holiday_id=row["id"], holiday_date=d, name=row["name"])
        self._status_lbl.setText(f"{len(rows)} holiday{'s' if len(rows) != 1 else ''}")

    # ── Row management ───────────────────────────────────────────────────

    def _insert_row(self, holiday_id, holiday_date: date, name: str):
        row = self._table.rowCount()
        self._table.insertRow(row)
        self._table.setRowHeight(row, 38)

        id_item = QTableWidgetItem("")
        id_item.setData(Qt.ItemDataRole.UserRole, holiday_id)
        self._table.setItem(row, _DATE_COL, id_item)
        self._table.setCellWidget(row, _DATE_COL, self._make_date_widget(holiday_date))
        self._table.setItem(row, _NAME_COL, QTableWidgetItem(name))
        self._table.setCellWidget(row, _DEL_COL, self._make_delete_widget())

    def _make_date_widget(self, holiday_date: date) -> QPushButton:
        t = self._theme
        btn = QPushButton(holiday_date.strftime(_DATE_FORMAT))
        btn.date_value = holiday_date
        btn.setFixedHeight(30)
        btn.setFont(font_scale.font(font_scale.SMALL, False))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background: {t.get('input_bg')};
                color: {t.get('text_primary')};
                border: 1px solid {t.get('border')};
                border-radius: 4px;
                padding: 0 8px;
                text-align: left;
            }}
            QPushButton:hover {{
                border-color: {t.get('accent')};
            }}
        """)
        btn.clicked.connect(lambda: self._show_date_picker(btn))
        return btn

    def _make_delete_widget(self) -> QWidget:
        t = self._theme
        destructive = t.get("destructive")
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(6, 0, 6, 0)
        btn = QPushButton()
        btn.setFixedSize(28, 26)
        btn.setIconSize(QSize(14, 14))
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {destructive};"
            f"border-radius: 4px; }} QPushButton:hover {{ background: {destructive}; }}"
        )
        btn.setIcon(_svg_icon("cross.svg", destructive))

        def _on_enter(_, b=btn):
            b.setIcon(_svg_icon("cross.svg", "#ffffff"))

        def _on_leave(_, b=btn, c=destructive):
            b.setIcon(_svg_icon("cross.svg", c))

        btn.enterEvent = _on_enter
        btn.leaveEvent = _on_leave
        btn.clicked.connect(lambda: self._delete_row(btn))
        h.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)
        return w

    def _row_of_widget(self, widget, col: int) -> int:
        for row in range(self._table.rowCount()):
            cw = self._table.cellWidget(row, col)
            if cw is None:
                continue
            if cw is widget or widget in cw.findChildren(QPushButton):
                return row
        return -1

    def _add_row(self):
        default_date = date(self._year_spin.value(), 1, 1)
        self._insert_row(holiday_id=None, holiday_date=default_date, name="")
        self._table.scrollToBottom()

    def _delete_row(self, btn):
        row = self._row_of_widget(btn, _DEL_COL)
        if row < 0:
            return
        holiday_id = self._table.item(row, _DATE_COL).data(Qt.ItemDataRole.UserRole)
        if holiday_id is not None:
            try:
                holidays_api.delete_holiday(holiday_id)
            except (ApiError, NetworkError) as exc:
                show_api_error(self._theme, self, exc)
                return
            self._controller.recheck_holiday_gate()
        self._table.removeRow(row)

    # ── Date picker (popup calendar, mirrors historic_upload.py) ───────────

    def _show_date_picker(self, target_btn: QPushButton):
        t = self._theme
        cal = QCalendarWidget()
        cal.setWindowFlags(Qt.WindowType.Tool | Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint)
        cal.setFont(font_scale.font(font_scale.SMALL, False))
        cal.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        cal.setStyleSheet(_themed_calendar_stylesheet(t))

        current = target_btn.date_value
        qd = QDate(current.year, current.month, current.day)
        cal.setSelectedDate(qd)
        cal.setCurrentPage(qd.year(), qd.month())

        def on_date_selected(date_obj):
            new_date = date(date_obj.year(), date_obj.month(), date_obj.day())
            target_btn.date_value = new_date
            target_btn.setText(new_date.strftime(_DATE_FORMAT))
            self._close_date_picker()

        pos = target_btn.mapToGlobal(target_btn.rect().bottomLeft())
        cal.clicked.connect(on_date_selected)
        cal.move(pos)
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

    # ── Save ─────────────────────────────────────────────────────────────

    def _save(self):
        t = self._theme
        parsed_rows = []
        for row in range(self._table.rowCount()):
            date_btn = self._table.cellWidget(row, _DATE_COL)
            name_item = self._table.item(row, _NAME_COL)
            name_text = name_item.text().strip() if name_item else ""
            if not name_text:
                self._status_lbl.setText(f"Row {row + 1}: name cannot be blank")
                self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
                return
            holiday_id = self._table.item(row, _DATE_COL).data(Qt.ItemDataRole.UserRole)
            parsed_rows.append((row, holiday_id, date_btn.date_value, name_text))

        self._save_btn.setEnabled(False)
        self._save_btn.setText("Saving...")
        try:
            for row, holiday_id, parsed_date, name_text in parsed_rows:
                if holiday_id is None:
                    result = holidays_api.create_holiday(parsed_date, name_text)
                    self._table.item(row, _DATE_COL).setData(Qt.ItemDataRole.UserRole, result["id"])
                else:
                    holidays_api.update_holiday(holiday_id, parsed_date, name_text)
        except (ApiError, NetworkError) as exc:
            show_api_error(self._theme, self, exc)
            return
        finally:
            self._save_btn.setEnabled(True)
            self._save_btn.setText("Save")

        self._load_holidays()
        self._status_lbl.setText("Saved.")
        self._status_lbl.setStyleSheet(f"color: {t.get('accent')};")
        self._controller.recheck_holiday_gate()

    # ── Theme ────────────────────────────────────────────────────────────

    def refresh_theme(self):
        t = self._theme
        self._subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._save_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; }"
        )
        if not self._status_lbl.text():
            self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._load_holidays(show_popup_on_error=False)
