import font_scale
import re
import os
from datetime import time as dtime
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy, QTableWidget,
    QTableWidgetItem, QHeaderView, QAbstractItemView, QCheckBox,
    QDialog, QTimeEdit, QToolButton, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QByteArray, QSize, Signal, QPropertyAnimation, QEasingCurve, Property, QTime, QTimer, QUrl
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QPen, QBrush, QDesktopServices
from PySide6.QtSvg import QSvgRenderer

import requests

from api import notifications_api
from api.exceptions import ApiError, NetworkError
from api.token_store import token_manager
from components.error_popup import show_api_error
from services import notification_channels, slack_config, trigger_config
from services.notifications.channels.slack import send_to_webhook

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


class _SlackConfigDialog(QDialog):
    """Slack's Configure dialog. Unlike the generic _ChannelConfigDialog
    (used by Email, where the user already knows their own address), most
    users have never created a Slack Incoming Webhook before — this walks
    them through it step by step inside the app instead of assuming they'll
    go find Slack's own docs, and validates what gets pasted back in before
    accepting it, since a bad URL would otherwise fail silently at real
    delivery time (see channels/slack.py's swallowed-error behavior).

    Same values()/constructor shape as _ChannelConfigDialog ({"Webhook URL":
    text}) so ChannelRow can use either interchangeably via dialog_factory.
    """

    _SETUP_URL = "https://api.slack.com/apps?new_app=1"
    _WEBHOOK_PREFIX = "https://hooks.slack.com/services/"
    _STEPS = [
        'Click "Open Slack Setup" below — it opens Slack\'s app creation page in your browser.',
        'Name the app (e.g. "Broker File Sync"), pick your workspace, then click "Create App".',
        'In the app\'s settings, open "Incoming Webhooks" and turn it On.',
        'Click "Add New Webhook to Workspace", choose the channel you want alerts in, and click "Allow".',
        f'Copy the URL Slack shows you (starts with {_WEBHOOK_PREFIX}) and paste it below.',
    ]

    def __init__(self, values: dict, theme, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Configure Slack")
        from screens.strategy_builder import _apply_dialog_bg
        _apply_dialog_bg(self, theme)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 20)
        layout.setSpacing(10)

        intro = QLabel("Connect a Slack channel to receive alerts:")
        intro.setFont(font_scale.font(font_scale.MEDIUM, True))
        layout.addWidget(intro)

        for i, step in enumerate(self._STEPS, start=1):
            step_lbl = QLabel(f"{i}.  {step}")
            step_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            step_lbl.setWordWrap(True)
            step_lbl.setStyleSheet(f"color: {theme.get('text_secondary')};")
            layout.addWidget(step_lbl)

        open_btn = QPushButton("Open Slack Setup")
        open_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        open_btn.setStyleSheet(
            f"background: transparent; color: {theme.get('accent')};"
            f"border: 1px solid {theme.get('accent')}; border-radius: 4px; padding: 6px 12px;"
        )
        open_btn.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(self._SETUP_URL)))
        layout.addWidget(open_btn)

        url_lbl = QLabel("WEBHOOK URL")
        url_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        url_lbl.setStyleSheet(f"color: {theme.get('text_secondary')};")
        layout.addWidget(url_lbl)

        self._input = QLineEdit(values.get("Webhook URL", ""))
        self._input.setPlaceholderText(f"{self._WEBHOOK_PREFIX}...")
        self._input.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._input.setFixedHeight(38)
        layout.addWidget(self._input)

        self._error_lbl = QLabel("")
        self._error_lbl.setStyleSheet("color: #e5484d;")
        self._error_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._error_lbl.setWordWrap(True)
        self._error_lbl.setVisible(False)
        layout.addWidget(self._error_lbl)

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
        save_btn.clicked.connect(self._try_accept)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(save_btn)
        layout.addLayout(btn_row)

    def _try_accept(self):
        url = self._input.text().strip()
        # Blank is allowed through (clears the webhook — same as never having
        # configured one); only a non-empty, wrong-shaped value is rejected,
        # since that's the case that would otherwise fail silently later at
        # real delivery time.
        if url and not url.startswith(self._WEBHOOK_PREFIX):
            self._error_lbl.setText(
                f"That doesn't look like a Slack webhook URL — it should start with {self._WEBHOOK_PREFIX}"
            )
            self._error_lbl.setVisible(True)
            return
        self._error_lbl.setVisible(False)
        self.accept()

    def values(self) -> dict:
        return {"Webhook URL": self._input.text().strip()}


class ChannelRow(QFrame):
    """Compact single-line channel control — config fields live in a popup
    dialog instead of being shown inline, to keep the page header short."""

    def __init__(self, title: str, icon_file: str, fields: list, send_label: str, theme,
                 default_enabled: bool = False, default_values: dict | None = None, parent=None,
                 dialog_factory=None):
        """
        fields: list of (label, placeholder) tuples — still used to decide
        whether the Configure button appears at all (empty = no popup, e.g.
        System), even when dialog_factory overrides what that popup shows.

        dialog_factory: optional callable(values: dict, theme, parent) -> a
        dialog with the same .exec()/.values() contract as
        _ChannelConfigDialog, e.g. _SlackConfigDialog's guided walkthrough.
        Defaults to the generic plain-fields _ChannelConfigDialog.
        """
        super().__init__(parent)
        self._theme = theme
        self._title = title
        self._fields = fields
        self._dialog_factory = dialog_factory
        self._values: dict = dict(default_values) if default_values else {}
        self._config_saved_slot = None
        self.setObjectName("brokerPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._toggle = ToggleSwitch(default_enabled)
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
        if self._dialog_factory is not None:
            dlg = self._dialog_factory(self._values, self._theme, parent=self)
        else:
            dlg = _ChannelConfigDialog(self._title, self._fields, self._values, self._theme, parent=self)
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._values = dlg.values()
            if self._config_saved_slot is not None:
                self._config_saved_slot(self._values)

    def get_value(self, label: str) -> str:
        return self._values.get(label, "")

    def is_enabled(self) -> bool:
        return self._toggle.isChecked()

    def connect_toggle(self, slot):
        self._toggle.toggled.connect(slot)

    def connect_send(self, slot):
        self._send_btn.clicked.connect(slot)

    def connect_config_saved(self, slot):
        """*slot* is called with the full {label: value} dict whenever the
        Configure dialog is accepted — unlike Email's address field (which
        only ever affects its own Test Notification button), a channel like
        Slack needs its configured value persisted immediately since it's
        what real delivery actually uses."""
        self._config_saved_slot = slot


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
        self._email_card: ChannelCard = None
        self._slack_card: ChannelCard = None
        self._system_card: ChannelCard = None
        self._configs: list = []
        self._table: QTableWidget = None
        self._email_status_lbl: QLabel = None
        self._slack_status_lbl: QLabel = None
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

        subtitle = QLabel("Receive alerts via System, Email, or Slack when files are imported or processing completes")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Channel rows — compact, config fields live behind the "Configure" popup
        channels_col = QVBoxLayout()
        channels_col.setSpacing(10)

        enabled_channels = notification_channels.load_enabled_channels()

        self._email_card = ChannelRow(
            "Email", "notification.svg",
            [("Email Address", "you@example.com")],
            "Test Notification", t,
            default_enabled=enabled_channels["email"],
            # Prefilled with the logged-in user's own email — real notifications
            # always go there regardless of this field; it only controls where
            # the Test Notification button sends, so it can be pointed anywhere.
            default_values={"Email Address": token_manager.get_user_email() or ""},
        )
        self._email_card.connect_toggle(self._on_toggle_changed)
        self._email_card.connect_send(self._on_test_email_notification)

        self._slack_card = ChannelRow(
            "Slack", "notification.svg",
            [("Webhook URL", "https://hooks.slack.com/services/T000/B000/XXXXXXXX")],
            "Test Notification", t,
            default_enabled=enabled_channels["slack"],
            # Prefilled with the already-saved webhook, if any — real
            # delivery always reads services.slack_config fresh at send time
            # (see channels/slack.py), this just seeds the Configure dialog
            # and the Test Notification target.
            default_values={"Webhook URL": slack_config.load_webhook_url()},
            # Guided step-by-step walkthrough instead of a bare text field —
            # most users have never created a Slack Incoming Webhook before
            # (see _SlackConfigDialog).
            dialog_factory=_SlackConfigDialog,
        )
        self._slack_card.connect_toggle(self._on_toggle_changed)
        self._slack_card.connect_send(self._on_test_slack_notification)
        self._slack_card.connect_config_saved(self._on_slack_config_saved)

        self._system_card = ChannelRow(
            "System", "notification.svg",
            [],   # nothing to configure — delivered via the local OS tray
            "Test Notification", t,
            default_enabled=enabled_channels["system"],
        )
        self._system_card.connect_toggle(self._on_toggle_changed)
        self._system_card.connect_send(self._on_test_system_notification)

        channels_col.addWidget(self._email_card)
        channels_col.addWidget(self._slack_card)
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
        table.setHorizontalHeaderLabels(["Trigger", "Time", "System", "Slack", "Email"])
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

        self._email_status_lbl = self._make_status_dot("Email: Disabled", t.get("text_secondary"))
        self._slack_status_lbl = self._make_status_dot("Slack: Disabled", t.get("text_secondary"))
        self._system_status_lbl = self._make_status_dot("System: Enabled", t.get("accent"))
        sb_layout.addWidget(self._email_status_lbl)
        sb_layout.addWidget(self._slack_status_lbl)
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

        email_on = self._email_card.is_enabled()
        self._email_status_lbl.setText(f"● Email: {'Enabled' if email_on else 'Disabled'}")
        self._email_status_lbl.setStyleSheet(
            f"color: {t.get('accent') if email_on else t.get('text_secondary')};"
        )

        slack_on = self._slack_card.is_enabled()
        self._slack_status_lbl.setText(f"● Slack: {'Enabled' if slack_on else 'Disabled'}")
        self._slack_status_lbl.setStyleSheet(
            f"color: {t.get('accent') if slack_on else t.get('text_secondary')};"
        )

        sys_on = self._system_card.is_enabled()
        self._system_status_lbl.setText(f"● System: {'Enabled' if sys_on else 'Disabled'}")
        self._system_status_lbl.setStyleSheet(
            f"color: {t.get('accent') if sys_on else t.get('text_secondary')};"
        )

        notification_channels.save_enabled_channels(
            {"system": sys_on, "email": email_on, "slack": slack_on}
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

    def _on_test_email_notification(self):
        """Sends to whatever address is set in the Email row's gear-icon
        Configure dialog (defaults to the logged-in user's own email — see
        _build). Real notifications always go to the logged-in user
        automatically regardless of this field; it only controls where the
        test send goes, so it can be pointed at any inbox to verify
        delivery."""
        to_email = self._email_card.get_value("Email Address").strip()
        if not to_email:
            QMessageBox.warning(
                self, "Error", "Set an email address via Email's Configure button first.",
            )
            return

        self._email_card._send_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(0, lambda: self._do_send_test_email(to_email))

    def _do_send_test_email(self, to_email: str):
        try:
            notifications_api.send_test_email(
                to_email, "Test Notification",
                "This is a test notification from Broker File Sync.",
            )
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._email_card._send_btn.setEnabled(True)
        QMessageBox.information(self, "Test Email Sent", f"A test email was sent to {to_email}.")

    def _on_slack_config_saved(self, values: dict):
        """Unlike Email's address field (only ever used by its own Test
        Notification button), Slack's webhook URL is what real delivery
        actually reads (services.slack_config, via channels/slack.py) — so
        it has to be persisted the moment the Configure dialog is accepted,
        not just held in the row's in-memory _values."""
        slack_config.save_webhook_url(values.get("Webhook URL", ""))

    def _on_test_slack_notification(self):
        """Sends to whatever URL is set in the Slack row's gear-icon
        Configure dialog — which, unlike Email's test-only address field, is
        also the real delivery target (see _on_slack_config_saved)."""
        webhook_url = self._slack_card.get_value("Webhook URL").strip()
        if not webhook_url:
            QMessageBox.warning(
                self, "Error", "Set a Webhook URL via Slack's Configure button first.",
            )
            return

        self._slack_card._send_btn.setEnabled(False)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(0, lambda: self._do_send_test_slack(webhook_url))

    def _do_send_test_slack(self, webhook_url: str):
        try:
            send_to_webhook(
                webhook_url, "Test Notification",
                "This is a test notification from Broker File Sync.",
            )
        except requests.RequestException as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._slack_card._send_btn.setEnabled(True)
        QMessageBox.information(self, "Test Message Sent", "A test message was sent to Slack.")

    def reload_configs(self):
        """Re-reads trigger configs from the server/cache — called on every
        successful login (not just the first), since trigger_config.py's
        data is now per-user: a second user logging in on the same running
        app instance must not keep seeing the first user's config (see
        app_window.py::MainWindow.reload_per_user_data)."""
        self._configs = trigger_config.load_trigger_configs()
        self._populate_trigger_table()
        self._on_toggle_changed()

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
            table.setCellWidget(row, 3, self._make_checkbox_widget(cfg, "slack"))
            table.setCellWidget(row, 4, self._make_checkbox_widget(cfg, "email"))

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
