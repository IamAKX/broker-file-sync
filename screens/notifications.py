import font_scale
import re
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QByteArray, QSize, Signal, QPropertyAnimation, QEasingCurve, Property
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QPen, QBrush
from PySide6.QtSvg import QSvgRenderer

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

    def __init__(self, checked: bool = False, parent=None):
        super().__init__(parent)
        self._checked = checked
        self.setFixedSize(50, 28)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

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
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)

        track_color = QColor("#39d353") if self._checked else QColor("#555e68")
        p.setBrush(QBrush(track_color))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(0, 4, 50, 20, 10, 10)

        thumb_x = 26 if self._checked else 2
        p.setBrush(QBrush(QColor("#ffffff")))
        p.drawEllipse(thumb_x, 2, 22, 22)
        p.end()


class ChannelCard(QFrame):
    def __init__(self, title: str, icon_file: str, fields: list, send_label: str, theme, parent=None):
        """
        fields: list of (label, placeholder) tuples
        """
        super().__init__(parent)
        self._theme = theme
        self.setObjectName("brokerPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toggle = ToggleSwitch(False)
        self._inputs: list[QLineEdit] = []
        self._build(title, icon_file, fields, send_label)

    def _build(self, title, icon_file, fields, send_label):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 16, 20, 16)
        layout.setSpacing(16)

        # Header: icon + title + toggle
        header = QHBoxLayout()
        icon_lbl = QLabel()
        icon_lbl.setFixedSize(20, 20)
        icon_lbl.setPixmap(_svg_icon(icon_file, t.get("accent")).pixmap(QSize(20, 20)))
        name_lbl = QLabel(title)
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        header.addWidget(icon_lbl)
        header.addSpacing(8)
        header.addWidget(name_lbl)
        header.addStretch()
        header.addWidget(self._toggle)
        layout.addLayout(header)

        # Divider
        div = QWidget()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background-color: {t.get('divider')};")
        layout.addWidget(div)

        # Input fields
        for label_text, placeholder in fields:
            lbl = QLabel(label_text.upper())
            lbl.setFont(font_scale.font(font_scale.SMALL, False))
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            layout.addWidget(lbl)

            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFont(font_scale.font(font_scale.MEDIUM, False))
            inp.setFixedHeight(38)
            self._inputs.append(inp)
            layout.addWidget(inp)

        layout.addStretch()

        # Send test button
        send_btn = QPushButton(f"  {send_label}")
        send_btn.setFixedHeight(36)
        send_btn.setFont(font_scale.font(font_scale.SMALL, False))
        send_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        send_btn.setIcon(_svg_icon("import.svg", t.get("text_secondary")))
        send_btn.setIconSize(QSize(16, 16))
        send_btn.setStyleSheet(
            f"background: transparent; color: {t.get('text_secondary')};"
            f"border: 1px solid {t.get('border')}; border-radius: 4px; padding: 0 16px;"
        )
        layout.addWidget(send_btn, alignment=Qt.AlignmentFlag.AlignHCenter)

    def is_enabled(self) -> bool:
        return self._toggle.isChecked()

    def connect_toggle(self, slot):
        self._toggle.toggled.connect(slot)


class _TriggerRow:
    """Thin wrapper so status counting works the same way."""
    def __init__(self, toggle: ToggleSwitch):
        self._toggle = toggle

    def is_enabled(self) -> bool:
        return self._toggle.isChecked()


class NotificationsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._sms_card: ChannelCard = None
        self._telegram_card: ChannelCard = None
        self._trigger_cards: list[TriggerCard] = []
        self._sms_status_lbl: QLabel = None
        self._telegram_status_lbl: QLabel = None
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

        subtitle = QLabel("Receive alerts via SMS or Telegram when files are imported or processing completes")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Channel cards row
        channels_row = QHBoxLayout()
        channels_row.setSpacing(16)

        self._sms_card = ChannelCard(
            "SMS", "notification.svg",
            [("Mobile Number", "+91 98765 43210")],
            "Send Test SMS", t
        )
        self._sms_card.connect_toggle(self._on_toggle_changed)

        self._telegram_card = ChannelCard(
            "Telegram", "notification.svg",
            [("Bot Token", "110201543:AAHdqTcvCH1vGWJxfSeofSAsGK5PALDsaw"),
             ("Chat ID",   "-100123456789")],
            "Send Test Message", t
        )
        self._telegram_card.connect_toggle(self._on_toggle_changed)

        channels_row.addWidget(self._sms_card)
        channels_row.addWidget(self._telegram_card)
        layout.addLayout(channels_row)

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

        trigger_defs = [
            ("High Value Met",          "Alert when a stock hits its configured high target price",                          True),
            ("Low Value Met",           "Alert when a stock falls to its configured low threshold price",                    True),
            ("End of Day Report",       "Daily summary of all trades, imports, and processing activity for the day",         True),
            ("Weekly Summary",          "Weekly digest of portfolio activity, import stats, and error counts",               False),
            ("Monthly Report",          "Monthly consolidated report of all broker imports, rows processed, and anomalies",  False),
            ("File Imported",           "Alert when a broker file is successfully uploaded and read",                        True),
            ("Processing Complete",     "Alert when all broker files have been processed and the output is ready",           True),
            ("Import Error",            "Alert immediately when a file fails to import or cannot be parsed",                 True),
            ("Duplicate File Detected", "Alert when the same broker file is submitted for import more than once",            False),
            ("Config Mapping Missing",  "Alert when a required column or script mapping is absent from the config",          False),
            ("Row Count Anomaly",       "Alert when imported row count deviates significantly from the previous import",     False),
            ("New Broker Added",        "Alert when a new broker source is registered or activated in the system",           False),
        ]

        # Scrollable list
        trigger_scroll = QScrollArea()
        trigger_scroll.setWidgetResizable(True)
        trigger_scroll.setFrameShape(QFrame.Shape.NoFrame)
        trigger_scroll.setFixedHeight(260)
        trigger_scroll.setContentsMargins(0, 0, 4, 0)

        trigger_container = QWidget()
        tc_layout = QVBoxLayout(trigger_container)
        tc_layout.setContentsMargins(0, 0, 0, 0)
        tc_layout.setSpacing(0)

        for i, (title_text, desc, checked) in enumerate(trigger_defs):
            # Row tile
            tile = QWidget()
            tile_layout = QHBoxLayout(tile)
            tile_layout.setContentsMargins(12, 12, 12, 12)
            tile_layout.setSpacing(16)

            text_col = QVBoxLayout()
            text_col.setSpacing(3)
            t_title = QLabel(title_text)
            t_title.setFont(font_scale.font(font_scale.MEDIUM, True))
            t_desc = QLabel(desc)
            t_desc.setFont(font_scale.font(font_scale.SMALL, False))
            t_desc.setStyleSheet(f"color: {t.get('text_secondary')};")
            text_col.addWidget(t_title)
            text_col.addWidget(t_desc)

            toggle = ToggleSwitch(checked)
            toggle.toggled.connect(self._on_toggle_changed)

            tile_layout.addLayout(text_col, 1)
            tile_layout.addWidget(toggle)
            tc_layout.addWidget(tile)

            # Store toggle for status counting
            card = _TriggerRow(toggle)
            self._trigger_cards.append(card)

            # Divider between rows (not after last)
            if i < len(trigger_defs) - 1:
                sep = QWidget(); sep.setFixedHeight(1)
                sep.setStyleSheet(f"background-color: {t.get('divider')};")
                tc_layout.addWidget(sep)

        tc_layout.addStretch()
        trigger_scroll.setWidget(trigger_container)
        tp_layout.addWidget(trigger_scroll)
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
        sb_layout.addWidget(self._sms_status_lbl)
        sb_layout.addWidget(self._telegram_status_lbl)
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

        active = sum(1 for c in self._trigger_cards if c.is_enabled())
        total = len(self._trigger_cards)
        color = t.get("accent") if active == total else t.get("text_secondary")
        self._triggers_status_lbl.setText(f"{active} of {total} triggers active")
        self._triggers_status_lbl.setStyleSheet(f"color: {color};")
