import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSizePolicy, QCheckBox, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from api import auth_api
from api.exceptions import ApiError, NetworkError
from api.token_store import token_manager
from components.error_popup import show_api_error


class LoginScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker Sync — Login")
        self.resize(1000, 650)
        self.setMinimumSize(800, 550)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        h = QHBoxLayout()
        h.addStretch()

        card = QFrame()
        card.setFixedWidth(480)
        card.setObjectName("loginCard")
        t = self._controller.theme
        card.setStyleSheet(
            f"QFrame#loginCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 40, 40, 40)
        card_layout.setSpacing(16)

        title = QLabel("BROKER FILE SYNC")
        title.setFont(font_scale.font(font_scale.DISPLAY_LG, True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = QLabel("Excel Processing Software")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(16)

        email_label = QLabel("EMAIL")
        email_label.setFont(font_scale.font(font_scale.MEDIUM, False))
        email_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(email_label)

        self._email = QLineEdit()
        self._email.setPlaceholderText("Enter your email")
        self._email.setFixedHeight(44)
        self._email.setFont(font_scale.font(font_scale.MEDIUM, False))
        card_layout.addWidget(self._email)

        pwd_label = QLabel("PASSWORD")
        pwd_label.setFont(font_scale.font(font_scale.MEDIUM, False))
        pwd_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(pwd_label)

        self._password = QLineEdit()
        self._password.setPlaceholderText("Enter your password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setFixedHeight(44)
        self._password.setFont(font_scale.font(font_scale.MEDIUM, False))
        card_layout.addWidget(self._password)

        self._keep_logged_in = QCheckBox("Keep me logged in")
        self._keep_logged_in.setFont(font_scale.font(font_scale.SMALL, False))
        self._keep_logged_in.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(self._keep_logged_in)

        card_layout.addSpacing(8)

        self._login_btn = QPushButton("Login")
        self._login_btn.setFixedHeight(48)
        self._login_btn.setFont(font_scale.font(font_scale.LARGE, True))
        self._login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._login_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')}; "
            "border: none; border-radius: 4px; }"
            f"QPushButton:disabled {{ background: {t.get('button_bg')}; color: {t.get('text_secondary')}; }}"
        )
        self._login_btn.clicked.connect(self._on_login_clicked)
        card_layout.addWidget(self._login_btn)

        signup_link = QPushButton("Don't have an account? Sign Up")
        signup_link.setFlat(True)
        signup_link.setCursor(Qt.CursorShape.PointingHandCursor)
        signup_link.setFont(font_scale.font(font_scale.MEDIUM, False))
        signup_link.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        signup_link.clicked.connect(self._controller.show_signup)
        card_layout.addWidget(signup_link, alignment=Qt.AlignmentFlag.AlignCenter)

        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()

    def _on_login_clicked(self):
        self._login_btn.setEnabled(False)
        self._login_btn.setText("Logging in...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(0, self._do_login)

    def _do_login(self):
        email = self._email.text().strip()
        password = self._password.text()
        try:
            result = auth_api.login(email, password)
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._login_btn.setEnabled(True)
            self._login_btn.setText("Login")
        token_manager.set(
            result["access_token"], result["refresh_token"],
            persist=self._keep_logged_in.isChecked(),
        )
        self._controller.show_main_window()
