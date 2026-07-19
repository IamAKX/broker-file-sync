import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QCheckBox, QApplication
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont

from api import auth_api
from api.exceptions import ApiError, NetworkError
from api.token_store import token_manager
from components.error_popup import show_api_error


class SignupScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker Sync — Sign Up")
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
        card.setFixedWidth(480)
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
        title.setFont(font_scale.font(font_scale.DISPLAY_LG, True))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = QLabel("Broker Sync")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(12)

        self._fields: dict[str, QLineEdit] = {}
        for key, field_label, placeholder, echo in [
            ("name",     "FULL NAME",        "Enter your full name",  False),
            ("email",    "EMAIL",             "Enter your email",      False),
            ("phone",    "PHONE NUMBER",      "Enter your phone number", False),
            ("password", "PASSWORD",          "Create a password",     True),
            ("confirm",  "CONFIRM PASSWORD",  "Confirm your password", True),
        ]:
            lbl = QLabel(field_label)
            lbl.setFont(font_scale.font(font_scale.MEDIUM, False))
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            card_layout.addWidget(lbl)

            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFixedHeight(44)
            inp.setFont(font_scale.font(font_scale.MEDIUM, False))
            if echo:
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            card_layout.addWidget(inp)
            self._fields[key] = inp

        self._keep_logged_in = QCheckBox("Keep me logged in")
        self._keep_logged_in.setFont(font_scale.font(font_scale.SMALL, False))
        self._keep_logged_in.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(self._keep_logged_in)

        card_layout.addSpacing(8)

        self._create_btn = QPushButton("Create Account")
        self._create_btn.setFixedHeight(48)
        self._create_btn.setFont(font_scale.font(font_scale.LARGE, True))
        self._create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._create_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: {t.get('background')}; "
            "border: none; border-radius: 4px; }"
            f"QPushButton:disabled {{ background: {t.get('button_bg')}; color: {t.get('text_secondary')}; }}"
        )
        self._create_btn.clicked.connect(self._on_create_clicked)
        card_layout.addWidget(self._create_btn)

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
        self._status_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(self._status_lbl)

        login_link = QPushButton("Already have an account? Login")
        login_link.setFlat(True)
        login_link.setCursor(Qt.CursorShape.PointingHandCursor)
        login_link.setFont(font_scale.font(font_scale.MEDIUM, False))
        login_link.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        login_link.clicked.connect(self._controller.show_login)
        card_layout.addWidget(login_link, alignment=Qt.AlignmentFlag.AlignCenter)

        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()

    def _on_create_clicked(self):
        phone = self._fields["phone"].text().strip()
        password = self._fields["password"].text()
        confirm = self._fields["confirm"].text()

        if not phone:
            self._status_lbl.setText("Please enter your phone number.")
            return
        if password != confirm:
            self._status_lbl.setText("Passwords do not match.")
            return
        self._status_lbl.setText("")

        self._create_btn.setEnabled(False)
        self._create_btn.setText("Creating account...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(0, self._do_create)

    def _do_create(self):
        name = self._fields["name"].text().strip()
        email = self._fields["email"].text().strip()
        phone = self._fields["phone"].text().strip()
        password = self._fields["password"].text()
        try:
            result = auth_api.signup(name, email, phone, password)
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._create_btn.setEnabled(True)
            self._create_btn.setText("Create Account")
        token_manager.set(
            result["access_token"], result["refresh_token"],
            persist=self._keep_logged_in.isChecked(),
        )
        self._controller.show_main_window()
