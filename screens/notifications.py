import font_scale
import re
import os
from datetime import time as dtime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox,
    QDialog, QTimeEdit, QToolButton
)
from PySide6.QtCore import Qt, QByteArray, QSize, Signal, QPropertyAnimation, QEasingCurve, Property, QTime
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtSvg import QSvgRenderer

from services import trigger_config

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
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


class ToggleSwitch(QWidget):
    toggled = Signal(bool)

    _WIDTH = 44
    _HEIGHT = 24
    _THUMB_MARGIN = 3

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(self._WIDTH, self._HEIGHT)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        # Without this the widget paints an opaque background rectangle
        # behind the rounded track, showing as a hard-edged box around it.
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def isChecked(self) -> bool:
        return self._checked

    def setChecked(self, val: bool):
        self._checked = val
        self.update()

    def mousePressEvent(self, event):
        self._checked = not self._checked
        self.toggled.emit(self._checked)
        self.update()

    def paintEvent(self, event):
        from PySide6.QtCore import QRectF

        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)

        track_rect = QRectF(0, 0, self._WIDTH, self._HEIGHT)
        track_color = QColor("#39d353") if self._checked else QColor("#555e68")
        p.setBrush(QBrush(track_color))
        p.drawRoundedRect(track_rect, self._HEIGHT / 2, self._HEIGHT / 2)

        thumb_d = self._HEIGHT - 2 * self._THUMB_MARGIN
        thumb_x = (self._WIDTH - self._THUMB_MARGIN - thumb_d) if self._checked else self._THUMB_MARGIN
        thumb_rect = QRectF(thumb_x, self._THUMB_MARGIN, thumb_d, thumb_d)
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(thumb_rect)
        p.end()


class _ChannelConfigDialog(QDialog):
    def __init__(self, title: str, fields: list, values: dict, theme, parent=None):
        """
        fields: list of (label, placeholder) tuples
        values: dict of label -> current text value
        """
        super().__init__(parent)
        self.setWindowTitle(f"Configure {title}")
        from screens.strategy_builder import _apply_dialog_bg
        _apply_dialog_bg(self, theme)

        self._inputs: dict[str, QLineEdit] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        for label_text, placeholder in fields:
            lbl = QLabel(label_text.upper())
            lbl.setFont(font_scale.font(font_scale.SMALL, False))
            lbl.setStyleSheet(f"color: {theme.get('text_secondary')};")
            layout.addWidget(lbl)

            inp = QLineEdit(values.get(label_text, ""))
            inp.setPlaceholderText(placeholder)
            inp.setFont(font_scale.font(font_scale.MEDIUM, False))
            inp.setFixedHeight(38)
            self._inputs[label_text] = inp
            layout.addWidget(inp)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"background: {theme.get('accent')}; color: {theme.get('background')}; border: none;"
        )
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def values(self) -> dict:
        return {label: inp.text() for label, inp in self._inputs.items()}


class ChannelRow(QFrame):
    """Compact single-line channel control — config fields live in a popup
    dialog instead of being shown inline, to keep the page header short."""

    def __init__(self, title: str, icon_file: str, fields: list, send_label: str, theme, parent=None):
        """
        fields: list of (label, placeholder) tuples
        """
        super().__init__(parent)
        self._theme = theme
        self._title = title
        self._fields = fields
        self._values: dict = {}
        self.setObjectName("brokerPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toggle = ToggleSwitch(False)
        self._build(title, icon_file, send_label)

    def _build(self, title, icon_file, send_label):
        t = self._theme
        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 10, 16, 10)
        layout.setSpacing(10)

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(18, 18)
        icon_lbl.setPixmap(_svg_icon(icon_file, t.get("accent")).pixmap(QSize(18, 18)))
        layout.addWidget(icon_lbl)

        name_lbl = QLabel(title)
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        layout.addWidget(name_lbl)

        layout.addStretch()

        # Channels with nothing to configure (e.g. System, which just uses
        # the local OS tray) skip the popup entirely.
        if self._fields:
            configure_btn = QToolButton()
            configure_btn.setIcon(_svg_icon("config_editor.svg", t.get("text_secondary")))
            configure_btn.setIconSize(QSize(14, 14))
            configure_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            configure_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
            configure_btn.setToolTip(f"Configure {title}")
            configure_btn.clicked.connect(self._open_configure)
            layout.addWidget(configure_btn)

        send_btn = QPushButton(send_label)
        send_btn.setFixedHeight(30)
        send_btn.setFont(font_scale.font(font_scale.SMALL, False))
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setStyleSheet(
            f"background: transparent; color: {t.get('text_secondary')};"
            f"border: 1px solid {t.get('border')}; border-radius: 4px; padding: 0 12px;"
        )
        self._send_btn = send_btn
        layout.addWidget(send_btn)

        layout.addWidget(self._toggle)

    def _open_configure(self):
        dlg = _ChannelConfigDialog(self._title, self._fields, self._values, self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._values = dlg.values()

    def is_enabled(self) -> bool:
        return self._toggle.isChecked()

    def connect_toggle(self, slot):
        self._toggle.toggled.connect(slot)

    def connect_send(self, slot):
        self._send_btn.clicked.connect(slot)


class _TriggerTimeDialog(QDialog):
    def __init__(self, trigger_name: str, current_time: dtime, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Edit Time — {trigger_name}")
        from screens.strategy_builder import _apply_dialog_bg
        _apply_dialog_bg(self, theme)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(14)

        lbl = QLabel("Trigger time")
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        layout.addWidget(lbl)

        self._time_edit = QTimeEdit(QTime(current_time.hour, current_time.minute))
        self._time_edit.setDisplayFormat("hh:mm AP")
        self._time_edit.setFixedHeight(36)
        layout.addWidget(self._time_edit)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        cancel_btn = QPushButton("Cancel")
        cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        cancel_btn.clicked.connect(self.reject)
        save_btn = QPushButton("Save")
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"background: {theme.get('accent')}; color: {theme.get('background')}; border: none;"
        )
        save_btn.clicked.connect(self.accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def result_time(self) -> dtime:
        qt = self._time_edit.time()
        return dtime(qt.hour(), qt.minute())


class NotificationsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._sms_card: ChannelCard = None
        self._telegram_card: ChannelCard = None
        self._system_card: ChannelCard = None
        self._configs: list = []
        self._table: QTableWidget = None
        self._sms_status_lbl: QLabel = None
        self._telegram_status_lbl: QLabel = None
        self._system_status_lbl: QLabel = None
        self._triggers_status_lbl: QLabel = None
        self._build()

    def _build(self):
        t = self._controller.theme

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Title
        title = QLabel("Notification Management")
        title.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        layout.addWidget(title)

        subtitle = QLabel("Receive alerts via System, SMS, or Telegram when files are imported or processing completes")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Channel rows — compact, config fields live behind the "Configure" popup
        channels_col = QVBoxLayout()
        channels_col.setSpacing(10)

        self._sms_card = ChannelRow(
            "SMS", "notification.svg",
            [("Mobile Number", "+91 98765 43210")],
            "Test Notification", t
        )
        self._sms_card.connect_toggle(self._on_toggle_changed)

        self._telegram_card = ChannelRow(
            "Telegram", "notification.svg",
            [("Bot Token", "110201543:AAHdqTcvCH1vGWJxfSeofSAsGK5PALDsaw"),
             ("Chat ID",   "-100123456789")],
            "Test Notification", t
        )
        self._telegram_card.connect_toggle(self._on_toggle_changed)

        self._system_card = ChannelRow(
            "System", "notification.svg",
            [],   # nothing to configure — delivered via the local OS tray
            "Test Notification", t
        )
        self._system_card.connect_toggle(self._on_toggle_changed)
        self._system_card.connect_send(self._on_test_system_notification)

        channels_col.addWidget(self._sms_card)
        channels_col.addWidget(self._telegram_card)
        channels_col.addWidget(self._system_card)
        layout.addLayout(channels_col)

        # Notification Triggers section
        triggers_panel = QFrame()
        triggers_panel.setObjectName("brokerPanel")
        tp_layout = QVBoxLayout(triggers_panel)
        tp_layout.setContentsMargins(20, 16, 20, 16)
        tp_layout.setSpacing(12)

        triggers_title = QLabel("NOTIFICATION TRIGGERS")
        triggers_title.setFont(font_scale.font(font_scale.SMALL, True))
        triggers_title.setStyleSheet(f"color: {t.get('text_secondary')};")
        tp_layout.addWidget(triggers_title)

        div0 = QWidget(); div0.setFixedHeight(1)
        div0.setStyleSheet(f"background-color: {t.get('divider')};")
        tp_layout.addWidget(div0)

        self._configs = trigger_config.load_trigger_configs()

        table = QTableWidget(0, 5)
        table.setHorizontalHeaderLabels(["Trigger", "Time", "System", "Telegram", "SMS"])
        table.verticalHeader().setVisible(False)
        table.setShowGrid(False)
        table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setFixedHeight(3 * 64 + 40)
        header = table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for col in (1, 2, 3, 4):
            header.setSectionResizeMode(col, QHeaderView.ResizeMode.Fixed)
        table.setColumnWidth(1, 140)
        table.setColumnWidth(2, 80)
        table.setColumnWidth(3, 80)
        table.setColumnWidth(4, 80)
        table.setStyleSheet(
            f"QTableWidget {{ background: transparent; border: none;"
            f"gridline-color: {t.get('divider')}; }}"
            f"QHeaderView::section {{ background: transparent; color: {t.get('text_secondary')};"
            f"border: none; border-bottom: 1px solid {t.get('divider')}; padding: 6px; }}"
        )

        self._table = table
        self._populate_trigger_table()
        tp_layout.addWidget(table)
        layout.addWidget(triggers_panel)

        layout.addStretch()

        # Status bar
        status_bar = QFrame()
        status_bar.setObjectName("brokerPanel")
        status_bar.setFixedHeight(44)
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.setContentsMargins(16, 0, 16, 0)
        sb_layout.setSpacing(16)

        self._sms_status_lbl = self._make_status_dot("SMS: Disabled", t.get("text_secondary"))
        self._telegram_status_lbl = self._make_status_dot("Telegram: Disabled", t.get("text_secondary"))
        self._system_status_lbl = self._make_status_dot("System: Disabled", t.get("text_secondary"))
        sb_layout.addWidget(self._sms_status_lbl)
        sb_layout.addWidget(self._telegram_status_lbl)
        sb_layout.addWidget(self._system_status_lbl)
        sb_layout.addStretch()

        self._triggers_status_lbl = QLabel("")
        self._triggers_status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        sb_layout.addWidget(self._triggers_status_lbl)

        layout.addWidget(status_bar)

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        # Set correct initial count after all trigger rows are built
        self._on_toggle_changed()

    def _make_status_dot(self, text: str, color: str) -> QLabel:
        lbl = QLabel(f"● {text}")
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color: {color};")
        return lbl

    def _on_toggle_changed(self):
        t = self._controller.theme

        sms_on = self._sms_card.is_enabled()
        self._sms_status_lbl.setText(f"● SMS: {'Enabled' if sms_on else 'Disabled'}")
        self._sms_status_lbl.setStyleSheet(
            f"color: {t.get('accent') if sms_on else t.get('text_secondary')};"
        )

        tg_on = self._telegram_card.is_enabled()
        self._telegram_status_lbl.setText(f"● Telegram: {'Enabled' if tg_on else 'Disabled'}")
        self._telegram_status_lbl.setStyleSheet(
            f"color: {t.get('accent') if tg_on else t.get('text_secondary')};"
        )

        sys_on = self._system_card.is_enabled()
        self._system_status_lbl.setText(f"● System: {'Enabled' if sys_on else 'Disabled'}")
        self._system_status_lbl.setStyleSheet(
            f"color: {t.get('accent') if sys_on else t.get('text_secondary')};"
        )

        active = sum(1 for c in self._configs if c.system_enabled)
        total = len(self._configs)
        color = t.get("accent") if active == total else t.get("text_secondary")
        self._triggers_status_lbl.setText(f"{active} of {total} triggers active")
        self._triggers_status_lbl.setStyleSheet(f"color: {color};")

    def _on_test_system_notification(self):
        """Fires a real native notification through the same NotificationService
        the background scheduler jobs use (see services/scheduled_jobs.py) —
        so this is a live preview, not a dummy button."""
        notifier = getattr(self._controller, "_notifier", None)
        if notifier is None:
            return
        notifier.notify(
            "This is a test notification",
            "Background job alerts (e.g. missed historic saves) will look like this.",
            action=lambda: self._controller.show_and_navigate("historic_upload"),
        )

    # ── Trigger table ────────────────────────────────────────────────────────

    def _populate_trigger_table(self):
        t = self._controller.theme
        table = self._table
        table.setRowCount(len(self._configs))
        for row, cfg in enumerate(self._configs):
            table.setRowHeight(row, 64)
            table.setCellWidget(row, 0, self._make_name_widget(cfg, t))
            table.setCellWidget(row, 1, self._make_time_widget(cfg, t))
            table.setCellWidget(row, 2, self._make_checkbox_widget(cfg, "system"))
            table.setCellWidget(row, 3, self._make_checkbox_widget(cfg, "telegram"))
            table.setCellWidget(row, 4, self._make_checkbox_widget(cfg, "sms"))

    def _make_name_widget(self, cfg, t) -> QWidget:
        cell = QWidget()
        col = QVBoxLayout(cell)
        col.setContentsMargins(8, 8, 8, 8)
        col.setSpacing(3)
        name_lbl = QLabel(cfg.name)
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        sub_lbl = QLabel(cfg.subtitle)
        sub_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        sub_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        sub_lbl.setWordWrap(True)
        col.addWidget(name_lbl)
        col.addWidget(sub_lbl)
        return cell

    def _make_time_widget(self, cfg, t) -> QWidget:
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(8, 8, 8, 8)
        row.setSpacing(6)

        time_lbl = QLabel(cfg.time.strftime("%I:%M %p").lstrip("0"))
        time_lbl.setFont(font_scale.font(font_scale.SMALL, False))

        edit_btn = QToolButton()
        edit_btn.setIcon(_svg_icon("config_editor.svg", t.get("text_secondary")))
        edit_btn.setIconSize(QSize(14, 14))
        edit_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        edit_btn.setStyleSheet("QToolButton { background: transparent; border: none; }")
        edit_btn.setToolTip("Edit trigger time")
        edit_btn.clicked.connect(lambda: self._open_edit_time(cfg, time_lbl))

        row.addWidget(time_lbl)
        row.addWidget(edit_btn)
        row.addStretch()
        return cell

    def _make_checkbox_widget(self, cfg, channel: str) -> QWidget:
        cell = QWidget()
        row = QHBoxLayout(cell)
        row.setContentsMargins(0, 0, 0, 0)
        row.setAlignment(Qt.AlignmentFlag.AlignCenter)

        cb = QCheckBox()
        cb.setChecked(getattr(cfg, f"{channel}_enabled"))
        cb.setCursor(Qt.CursorShape.PointingHandCursor)
        cb.stateChanged.connect(lambda state, c=cfg, ch=channel: self._on_checkbox_changed(c, ch, bool(state)))
        row.addWidget(cb)
        return cell

    def _on_checkbox_changed(self, cfg, channel: str, checked: bool):
        setattr(cfg, f"{channel}_enabled", checked)
        self._save_configs()

    def _open_edit_time(self, cfg, time_lbl: QLabel):
        dlg = _TriggerTimeDialog(cfg.name, cfg.time, self._controller.theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            cfg.time = dlg.result_time()
            time_lbl.setText(cfg.time.strftime("%I:%M %p").lstrip("0"))
            self._save_configs()

    def _save_configs(self):
        trigger_config.save_trigger_configs(self._configs)
        self._on_toggle_changed()
