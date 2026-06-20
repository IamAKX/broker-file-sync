from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class SignupScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker File Sync — Sign Up")
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        h = QHBoxLayout()
        h.addStretch()

        card = QFrame()
        card.setFixedWidth(420)
        card.setObjectName("signupCard")
        t = self._controller.theme
        card.setStyleSheet(
            f"QFrame#signupCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 40, 40, 40)
        card_layout.setSpacing(14)

        title = QLabel("CREATE ACCOUNT")
        title.setFont(QFont("", 26, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = QLabel("Broker File Sync")
        subtitle.setFont(QFont("", 11))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(12)

        for field_label, placeholder, echo in [
            ("FULL NAME",        "Enter your full name",      False),
            ("EMAIL",            "Enter your email",          False),
            ("PASSWORD",         "Create a password",         True),
            ("CONFIRM PASSWORD", "Confirm your password",     True),
        ]:
            lbl = QLabel(field_label)
            lbl.setFont(QFont("", 10))
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            card_layout.addWidget(lbl)

            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFixedHeight(36)
            if echo:
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            card_layout.addWidget(inp)

        card_layout.addSpacing(8)

        create_btn = QPushButton("Create Account")
        create_btn.setFixedHeight(42)
        create_btn.setFont(QFont("", 13, QFont.Weight.Bold))
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px;"
        )
        create_btn.clicked.connect(self._controller.show_main_window)
        card_layout.addWidget(create_btn)

        login_link = QPushButton("Already have an account? Login")
        login_link.setFlat(True)
        login_link.setCursor(Qt.CursorShape.PointingHandCursor)
        login_link.setFont(QFont("", 11))
        login_link.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        login_link.clicked.connect(self._controller.show_login)
        card_layout.addWidget(login_link, alignment=Qt.AlignmentFlag.AlignCenter)

        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()
