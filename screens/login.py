from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class LoginScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker File Sync — Login")
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
        card.setFixedWidth(420)
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
        title.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = QLabel("Excel Processing Software")
        subtitle.setFont(QFont("Courier New", 11))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(16)

        email_label = QLabel("EMAIL")
        email_label.setFont(QFont("Courier New", 10))
        email_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(email_label)

        self._email = QLineEdit()
        self._email.setPlaceholderText("Enter your email")
        self._email.setFixedHeight(38)
        card_layout.addWidget(self._email)

        pwd_label = QLabel("PASSWORD")
        pwd_label.setFont(QFont("Courier New", 10))
        pwd_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(pwd_label)

        self._password = QLineEdit()
        self._password.setPlaceholderText("Enter your password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setFixedHeight(38)
        card_layout.addWidget(self._password)

        card_layout.addSpacing(8)

        login_btn = QPushButton("Login")
        login_btn.setFixedHeight(42)
        login_btn.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        login_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px;"
        )
        login_btn.clicked.connect(self._controller.show_main_window)
        card_layout.addWidget(login_btn)

        signup_link = QPushButton("Don't have an account? Sign Up")
        signup_link.setFlat(True)
        signup_link.setCursor(Qt.CursorShape.PointingHandCursor)
        signup_link.setFont(QFont("Courier New", 11))
        signup_link.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        signup_link.clicked.connect(self._controller.show_signup)
        card_layout.addWidget(signup_link, alignment=Qt.AlignmentFlag.AlignCenter)

        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()
