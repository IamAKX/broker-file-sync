"""Shared QCalendarWidget dressing: theme-matched stylesheet, plus a
subclass that dots days which have saved data.

Extracted from screens/historic_upload.py (originally private to that
screen) so other pickers can reuse the exact same look/behavior instead of
a second copy — see screens/formula_editor.py's VALUE_ON_DATE picker for
the other consumer.
"""
from PySide6.QtWidgets import QCalendarWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QPainter, QColor, QBrush


def themed_calendar_stylesheet(theme) -> str:
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


class AvailabilityCalendar(QCalendarWidget):
    """QCalendarWidget that draws a dot under days with saved data —
    set_available_days() takes the day-of-month numbers for whichever
    month is currently shown (caller re-fetches/re-calls on
    currentPageChanged, see screens.historic_upload / screens.
    formula_editor for the fetch-on-month-change wiring)."""

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
