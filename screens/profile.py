import font_scale
import re
import os
from datetime import datetime, timezone
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy, QMessageBox, QApplication
)
from PySide6.QtCore import Qt, QByteArray, QSize, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QBrush
from PySide6.QtSvg import QSvgRenderer
from api import auth_api
from api.token_store import token_manager
from api.exceptions import ApiError, NetworkError
from components.sidebar import _initials
from components.error_popup import show_api_error
from screens.notifications import ToggleSwitch
from services import autostart

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")


def _format_member_since(iso_str: str | None) -> str:
    if not iso_str:
        return "—"
    try:
        dt = datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc).astimezone()
        return dt.strftime("%b %Y")
    except (ValueError, TypeError):
        return "—"


def _format_last_login(iso_str: str | None) -> str:
    if not iso_str:
        return "First login"
    try:
        dt = datetime.fromisoformat(iso_str).replace(tzinfo=timezone.utc).astimezone()
        return dt.strftime("%b %d, %Y %I:%M %p")
    except (ValueError, TypeError):
        return "—"


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


def _section_label(text: str, theme) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(font_scale.font(font_scale.SMALL, True))
    lbl.setStyleSheet(f"color: {theme.get('text_secondary')};")
    return lbl


def _field_label(text: str, theme) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(font_scale.font(font_scale.SMALL, False))
    lbl.setStyleSheet(f"color: {theme.get('text_secondary')};")
    return lbl


class ProfileScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
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

        # ── Header row ──────────────────────────────────────────────────────
        header_row = QHBoxLayout()
        title_col = QVBoxLayout()
        title_col.setSpacing(4)
        title = QLabel("My Profile")
        title.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        subtitle = QLabel("Manage account details and application preferences")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        save_btn = QPushButton("  Save Changes")
        save_btn.setFixedHeight(38)
        save_btn.setFont(font_scale.font(font_scale.MEDIUM, True))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setIcon(_svg_icon("save.svg", t.get("background")))
        save_btn.setIconSize(QSize(16, 16))
        save_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; padding: 0 20px;"
        )
        save_btn.clicked.connect(self._save_profile)
        self._save_btn = save_btn

        header_row.addLayout(title_col, 1)
        header_row.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignVCenter)
        layout.addLayout(header_row)

        # ── Two-column body ──────────────────────────────────────────────────
        body = QHBoxLayout()
        body.setSpacing(16)
        body.setAlignment(Qt.AlignmentFlag.AlignTop)

        # ── LEFT: Avatar card ────────────────────────────────────────────────
        left_card = QFrame()
        left_card.setObjectName("brokerPanel")
        left_card.setFixedWidth(260)
        left_card.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Preferred)
        left_layout = QVBoxLayout(left_card)
        left_layout.setContentsMargins(24, 28, 24, 24)
        left_layout.setSpacing(12)
        left_layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        # Avatar
        user_name = token_manager.get_user_name() or "Unknown User"
        user_email = token_manager.get_user_email() or ""
        user_phone = token_manager.get_user_phone_number() or ""

        avatar = QLabel(_initials(user_name))
        avatar.setFixedSize(72, 72)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        avatar.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border-radius: 8px;"
        )
        left_layout.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignHCenter)
        self._avatar_lbl = avatar

        name_lbl = QLabel(user_name)
        name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(name_lbl)
        self._card_name_lbl = name_lbl

        email_lbl = QLabel(user_email)
        email_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        email_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        email_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(email_lbl)
        self._card_email_lbl = email_lbl

        left_layout.addSpacing(8)

        # Stats — values are fetched from GET /auth/me (see showEvent) since
        # created_at/last_login_at aren't JWT claims and would go stale in the token
        div1 = QWidget(); div1.setFixedHeight(1)
        div1.setStyleSheet(f"background-color: {t.get('divider')};")
        left_layout.addWidget(div1)

        self._member_since_lbl = None
        self._last_login_lbl = None
        for stat_label, attr in [
            ("Member since", "_member_since_lbl"),
            ("Last login",   "_last_login_lbl"),
        ]:
            row = QHBoxLayout()
            sl = QLabel(stat_label)
            sl.setFont(font_scale.font(font_scale.SMALL, False))
            sl.setStyleSheet(f"color: {t.get('text_secondary')};")
            sv = QLabel("—")
            sv.setFont(font_scale.font(font_scale.SMALL, False))
            sv.setAlignment(Qt.AlignmentFlag.AlignRight)
            setattr(self, attr, sv)
            row.addWidget(sl)
            row.addStretch()
            row.addWidget(sv)
            left_layout.addLayout(row)

        left_layout.addSpacing(8)

        # Start on login
        if autostart.is_supported():
            div_autostart = QWidget(); div_autostart.setFixedHeight(1)
            div_autostart.setStyleSheet(f"background-color: {t.get('divider')};")
            left_layout.addWidget(div_autostart)

            autostart_row = QHBoxLayout()
            autostart_lbl = QLabel("Start on login")
            autostart_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            self._autostart_toggle = ToggleSwitch(autostart.is_enabled())
            self._autostart_toggle.toggled.connect(self._on_autostart_toggled)
            autostart_row.addWidget(autostart_lbl)
            autostart_row.addStretch()
            autostart_row.addWidget(self._autostart_toggle)
            left_layout.addLayout(autostart_row)

            left_layout.addSpacing(8)

        # Sign Out
        signout_btn = QPushButton("  Sign Out")
        signout_btn.setFixedHeight(38)
        signout_btn.setFont(font_scale.font(font_scale.MEDIUM, False))
        signout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        signout_btn.setIconSize(QSize(16, 16))
        signout_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t.get('status_red')};"
            f"border: 1px solid {t.get('status_red')}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t.get('status_red')}; color: #ffffff; }}"
        )
        red = t.get("status_red")
        signout_btn.setIcon(_svg_icon("logout.svg", red))
        signout_btn.enterEvent = lambda _: signout_btn.setIcon(_svg_icon("logout.svg", "#ffffff"))
        signout_btn.leaveEvent = lambda _: signout_btn.setIcon(_svg_icon("logout.svg", red))
        signout_btn.clicked.connect(self._controller.show_login)
        left_layout.addWidget(signout_btn)

        body.addWidget(left_card, 0, Qt.AlignmentFlag.AlignTop)

        # ── RIGHT: Account + Password cards ──────────────────────────────────
        right_col = QVBoxLayout()
        right_col.setSpacing(16)

        # Account Information
        acc_card = QFrame()
        acc_card.setObjectName("brokerPanel")
        acc_layout = QVBoxLayout(acc_card)
        acc_layout.setContentsMargins(24, 20, 24, 20)
        acc_layout.setSpacing(14)

        acc_layout.addWidget(_section_label("ACCOUNT INFORMATION", t))

        div2 = QWidget(); div2.setFixedHeight(1)
        div2.setStyleSheet(f"background-color: {t.get('divider')};")
        acc_layout.addWidget(div2)

        # Full Name + Email (2-column row)
        row1 = QHBoxLayout(); row1.setSpacing(16)
        name_col = QVBoxLayout(); name_col.setSpacing(4)
        name_col.addWidget(_field_label("FULL NAME", t))
        self._name_inp = QLineEdit(user_name)
        self._name_inp.setFixedHeight(38)
        name_col.addWidget(self._name_inp)

        email_col = QVBoxLayout(); email_col.setSpacing(4)
        email_col.addWidget(_field_label("EMAIL ADDRESS", t))
        self._email_inp = QLineEdit(user_email)
        self._email_inp.setFixedHeight(38)
        email_col.addWidget(self._email_inp)

        row1.addLayout(name_col, 1)
        row1.addLayout(email_col, 1)
        acc_layout.addLayout(row1)

        # Phone number
        row2 = QHBoxLayout(); row2.setSpacing(16)
        phone_col = QVBoxLayout(); phone_col.setSpacing(4)
        phone_col.addWidget(_field_label("PHONE NUMBER", t))
        self._phone_inp = QLineEdit(user_phone)
        self._phone_inp.setFixedHeight(38)
        phone_col.addWidget(self._phone_inp)
        row2.addLayout(phone_col, 1)
        row2.addStretch(1)
        acc_layout.addLayout(row2)

        right_col.addWidget(acc_card)

        # Password card
        pwd_card = QFrame()
        pwd_card.setObjectName("brokerPanel")
        pwd_layout = QVBoxLayout(pwd_card)
        pwd_layout.setContentsMargins(24, 20, 24, 20)
        pwd_layout.setSpacing(14)

        pwd_layout.addWidget(_section_label("UPDATE PASSWORD", t))

        div3 = QWidget(); div3.setFixedHeight(1)
        div3.setStyleSheet(f"background-color: {t.get('divider')};")
        pwd_layout.addWidget(div3)

        current_pwd_row = QHBoxLayout(); current_pwd_row.setSpacing(16)
        current_col = QVBoxLayout(); current_col.setSpacing(4)
        current_col.addWidget(_field_label("CURRENT PASSWORD", t))
        self._current_pwd_inp = QLineEdit()
        self._current_pwd_inp.setPlaceholderText("Enter current password")
        self._current_pwd_inp.setEchoMode(QLineEdit.EchoMode.Password)
        self._current_pwd_inp.setFixedHeight(38)
        current_col.addWidget(self._current_pwd_inp)
        current_pwd_row.addLayout(current_col, 1)
        current_pwd_row.addStretch(1)
        pwd_layout.addLayout(current_pwd_row)

        pwd_row = QHBoxLayout(); pwd_row.setSpacing(16)
        for label, placeholder, attr in [
            ("NEW PASSWORD",     "Enter new password",   "_pwd_inp"),
            ("CONFIRM PASSWORD", "Confirm new password", "_pwd_confirm_inp"),
        ]:
            col = QVBoxLayout(); col.setSpacing(4)
            col.addWidget(_field_label(label, t))
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setEchoMode(QLineEdit.EchoMode.Password)
            inp.setFixedHeight(38)
            setattr(self, attr, inp)
            col.addWidget(inp)
            pwd_row.addLayout(col, 1)
        pwd_layout.addLayout(pwd_row)

        upd_btn = QPushButton("  Update Password")
        upd_btn.setFixedHeight(36)
        upd_btn.setFont(font_scale.font(font_scale.SMALL, False))
        upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upd_btn.setIcon(_svg_icon("password.svg", t.get("text_primary")))
        upd_btn.setIconSize(QSize(16, 16))
        upd_btn.clicked.connect(self._update_password)
        pwd_layout.addWidget(upd_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        self._upd_btn = upd_btn

        right_col.addWidget(pwd_card)
        right_col.addStretch()

        body.addLayout(right_col, 1)
        layout.addLayout(body)
        layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _on_autostart_toggled(self, enabled: bool):
        try:
            autostart.set_enabled(enabled)
        except OSError as exc:
            QMessageBox.warning(self, "Error", f"Couldn't update login startup setting: {exc}")
            self._autostart_toggle.setChecked(not enabled)

    def showEvent(self, event):
        super().showEvent(event)
        self._load_profile_stats()

    def _load_profile_stats(self):
        try:
            profile = auth_api.get_me()
        except (ApiError, NetworkError):
            self._member_since_lbl.setText("—")
            self._last_login_lbl.setText("—")
            return
        self._member_since_lbl.setText(_format_member_since(profile.get("created_at")))
        self._last_login_lbl.setText(_format_last_login(profile.get("last_login_at")))

    def _save_profile(self):
        name = self._name_inp.text().strip()
        email = self._email_inp.text().strip()
        phone = self._phone_inp.text().strip()
        if not name or not email or not phone:
            QMessageBox.warning(self, "Error", "Name, email and phone number are required.")
            return

        self._save_btn.setEnabled(False)
        self._save_btn.setText("  Saving...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(0, lambda: self._do_save_profile(name, email, phone))

    def _do_save_profile(self, name, email, phone):
        try:
            result = auth_api.update_profile(name, email, phone)
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._save_btn.setEnabled(True)
            self._save_btn.setText("  Save Changes")

        token_manager.update_access_token(result["access_token"])
        self._controller.refresh_user_display()
        self._avatar_lbl.setText(_initials(name))
        self._card_name_lbl.setText(name)
        self._card_email_lbl.setText(email)
        QMessageBox.information(self, "Saved", "Profile saved successfully.")

    def _update_password(self):
        current = self._current_pwd_inp.text()
        new = self._pwd_inp.text()
        confirm = self._pwd_confirm_inp.text()
        if not current:
            QMessageBox.warning(self, "Error", "Please enter your current password.")
            return
        if not new:
            QMessageBox.warning(self, "Error", "Please enter a new password.")
            return
        if new != confirm:
            QMessageBox.warning(self, "Error", "Passwords do not match.")
            return

        self._upd_btn.setEnabled(False)
        self._upd_btn.setText("  Updating...")
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QTimer.singleShot(0, lambda: self._do_update_password(current, new))

    def _do_update_password(self, current, new):
        try:
            auth_api.change_password(current, new)
        except (ApiError, NetworkError) as exc:
            show_api_error(self._controller.theme, self, exc)
            return
        finally:
            QApplication.restoreOverrideCursor()
            self._upd_btn.setEnabled(True)
            self._upd_btn.setText("  Update Password")

        self._current_pwd_inp.clear()
        self._pwd_inp.clear()
        self._pwd_confirm_inp.clear()
        QMessageBox.information(self, "Success", "Password updated successfully.")
