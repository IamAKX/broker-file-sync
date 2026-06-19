from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from theme import ThemeManager

NAV_ITEMS = [
    ("dashboard",     "⊞  Dashboard"),
    ("data_import",   "⬆  Data Import"),
    ("config_editor", "⚙  Config Editor"),
    ("notifications", "🔔  Notifications"),
    ("profile",       "👤  My Profile"),
]

BROKERS = [
    ("Sharekhan",       "status_red"),
    ("ReliableSoftware","status_blue"),
    ("NiftyInvest",     "status_orange"),
]


class Sidebar(QWidget):
    navigate = Signal(str)

    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._buttons: dict[str, QPushButton] = {}
        self._active = "dashboard"
        self.setMinimumWidth(180)
        self.setMaximumWidth(180)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo
        logo = QLabel("BROKER\nFILE SYNC")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        logo.setContentsMargins(0, 20, 0, 20)
        layout.addWidget(logo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Nav items
        for key, label in NAV_ITEMS:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setFixedHeight(40)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._on_nav(k))
            btn.setStyleSheet(self._nav_style(key == self._active))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addSpacing(16)

        # Broker Files section
        broker_label = QLabel("BROKER FILES")
        broker_label.setFont(QFont("Courier New", 9))
        broker_label.setContentsMargins(14, 4, 0, 4)
        layout.addWidget(broker_label)

        self._dot_labels = []
        for name, color_token in BROKERS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 4, 8, 4)
            row_layout.setSpacing(8)

            dot = QLabel("●")
            dot.setFont(QFont("Courier New", 10))
            dot.setStyleSheet(f"color: {self._theme.get(color_token)};")
            dot.setFixedWidth(14)
            self._dot_labels.append((dot, color_token))

            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Courier New", 11))

            row_layout.addWidget(dot)
            row_layout.addWidget(name_lbl)
            row_layout.addStretch()
            layout.addWidget(row)

        layout.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # User widget
        user_widget = QWidget()
        user_widget.setObjectName("userWidget")
        user_layout = QHBoxLayout(user_widget)
        user_layout.setContentsMargins(10, 8, 10, 8)
        user_layout.setSpacing(8)

        avatar = QLabel("RJ")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        avatar.setStyleSheet(
            f"background: {self._theme.get('accent')}; color: {self._theme.get('background')};"
            "border-radius: 16px;"
        )
        self._avatar_label = avatar

        user_info = QVBoxLayout()
        user_info.setSpacing(0)
        name_lbl2 = QLabel("Rajesh")
        name_lbl2.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        email_lbl = QLabel("rajesh.kumar@exa...")
        email_lbl.setFont(QFont("Courier New", 9))
        user_info.addWidget(name_lbl2)
        user_info.addWidget(email_lbl)

        user_layout.addWidget(avatar)
        user_layout.addLayout(user_info)
        layout.addWidget(user_widget)

    def _nav_style(self, active: bool) -> str:
        if active:
            return (
                f"background: {self._theme.get('accent')};"
                f"color: {self._theme.get('background')};"
                "text-align: left; padding-left: 14px; border: none;"
                "font-family: 'Courier New', monospace; font-size: 13px;"
            )
        return (
            f"color: {self._theme.get('text_secondary')};"
            "background: transparent; text-align: left; padding-left: 14px;"
            "border: none; font-family: 'Courier New', monospace; font-size: 13px;"
        )

    def _on_nav(self, key: str):
        self.set_active(key)
        self.navigate.emit(key)

    def set_active(self, screen_name: str):
        self._active = screen_name
        for key, btn in self._buttons.items():
            btn.setStyleSheet(self._nav_style(key == screen_name))
            btn.setChecked(key == screen_name)

    def refresh_theme(self):
        for dot, color_token in self._dot_labels:
            dot.setStyleSheet(f"color: {self._theme.get(color_token)};")
        self._avatar_label.setStyleSheet(
            f"background: {self._theme.get('accent')}; color: {self._theme.get('background')};"
            "border-radius: 16px;"
        )
