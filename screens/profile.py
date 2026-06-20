import re
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QScrollArea, QSizePolicy, QFileDialog, QMessageBox,
    QSpinBox
)
from PySide6.QtCore import Qt, QByteArray, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter, QColor, QBrush
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


def _section_label(text: str, theme) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("", 10, QFont.Weight.Bold))
    lbl.setStyleSheet(f"color: {theme.get('text_secondary')};")
    return lbl


def _field_label(text: str, theme) -> QLabel:
    lbl = QLabel(text)
    lbl.setFont(QFont("", 9))
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
        title.setFont(QFont("", 24, QFont.Weight.Bold))
        subtitle = QLabel("Manage account details and application preferences")
        subtitle.setFont(QFont("", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        title_col.addWidget(title)
        title_col.addWidget(subtitle)

        save_btn = QPushButton("  Save Changes")
        save_btn.setFixedHeight(38)
        save_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setIcon(_svg_icon("save.svg", t.get("background")))
        save_btn.setIconSize(QSize(16, 16))
        save_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; padding: 0 20px;"
        )
        save_btn.clicked.connect(self._save_profile)

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
        avatar = QLabel("SP")
        avatar.setFixedSize(72, 72)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont("", 22, QFont.Weight.Bold))
        avatar.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border-radius: 8px;"
        )
        left_layout.addWidget(avatar, alignment=Qt.AlignmentFlag.AlignHCenter)

        name_lbl = QLabel("Sunder P.")
        name_lbl.setFont(QFont("", 14, QFont.Weight.Bold))
        name_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(name_lbl)

        email_lbl = QLabel("sunder@gmail.com")
        email_lbl.setFont(QFont("", 11))
        email_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        email_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        left_layout.addWidget(email_lbl)

        left_layout.addSpacing(8)

        # Stats
        div1 = QWidget(); div1.setFixedHeight(1)
        div1.setStyleSheet(f"background-color: {t.get('divider')};")
        left_layout.addWidget(div1)

        for stat_label, stat_value in [
            ("Member since",  "Jan 2024"),
            ("Total imports", "0"),
            ("Last session",  "Today"),
        ]:
            row = QHBoxLayout()
            sl = QLabel(stat_label)
            sl.setFont(QFont("", 10))
            sl.setStyleSheet(f"color: {t.get('text_secondary')};")
            sv = QLabel(stat_value)
            sv.setFont(QFont("", 10))
            sv.setAlignment(Qt.AlignmentFlag.AlignRight)
            row.addWidget(sl)
            row.addStretch()
            row.addWidget(sv)
            left_layout.addLayout(row)

        left_layout.addSpacing(8)

        # Sign Out
        signout_btn = QPushButton("  Sign Out")
        signout_btn.setFixedHeight(38)
        signout_btn.setFont(QFont("", 12))
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
        self._name_inp = QLineEdit("Sunder P.")
        self._name_inp.setFixedHeight(38)
        name_col.addWidget(self._name_inp)

        email_col = QVBoxLayout(); email_col.setSpacing(4)
        email_col.addWidget(_field_label("EMAIL ADDRESS", t))
        self._email_inp = QLineEdit("sunder@gmail.com")
        self._email_inp.setFixedHeight(38)
        email_col.addWidget(self._email_inp)

        row1.addLayout(name_col, 1)
        row1.addLayout(email_col, 1)
        acc_layout.addLayout(row1)

        # Organisation (single field)
        row2 = QHBoxLayout(); row2.setSpacing(16)
        org_col = QVBoxLayout(); org_col.setSpacing(4)
        org_col.addWidget(_field_label("ORGANISATION / FIRM", t))
        self._org_inp = QLineEdit()
        self._org_inp.setPlaceholderText("Optional")
        self._org_inp.setFixedHeight(38)
        org_col.addWidget(self._org_inp)
        row2.addLayout(org_col, 1)
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

        pwd_row = QHBoxLayout(); pwd_row.setSpacing(16)
        for label, placeholder, attr in [
            ("NEW PASSWORD",     "Leave blank to keep current", "_pwd_inp"),
            ("CONFIRM PASSWORD", "Confirm new password",        "_pwd_confirm_inp"),
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
        upd_btn.setFont(QFont("", 11))
        upd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        upd_btn.setIcon(_svg_icon("password.svg", t.get("text_primary")))
        upd_btn.setIconSize(QSize(16, 16))
        upd_btn.clicked.connect(self._update_password)
        pwd_layout.addWidget(upd_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        right_col.addWidget(pwd_card)

        # Preferences card
        pref_card = QFrame()
        pref_card.setObjectName("brokerPanel")
        pref_layout = QVBoxLayout(pref_card)
        pref_layout.setContentsMargins(24, 20, 24, 20)
        pref_layout.setSpacing(14)

        pref_layout.addWidget(_section_label("PREFERENCES", t))

        div_pref = QWidget(); div_pref.setFixedHeight(1)
        div_pref.setStyleSheet(f"background-color: {t.get('divider')};")
        pref_layout.addWidget(div_pref)

        pref_row = QHBoxLayout(); pref_row.setSpacing(16)

        # Output directory
        dir_col = QVBoxLayout(); dir_col.setSpacing(4)
        dir_col.addWidget(_field_label("DEFAULT OUTPUT DIRECTORY", t))
        dir_row = QHBoxLayout(); dir_row.setSpacing(8)
        self._dir_inp = QLineEdit(getattr(self._controller, "output_dir", "") or "./output")
        self._dir_inp.setFixedHeight(38)
        browse_btn = QPushButton()
        browse_btn.setFixedSize(38, 38)
        browse_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        browse_btn.setIcon(_svg_icon("folder.svg", t.get("accent")))
        browse_btn.setIconSize(QSize(18, 18))
        browse_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; border: 1px solid {t.get('accent')}; border-radius: 4px; }}"
            f"QPushButton:hover {{ background: {t.get('accent')}20; }}"
        )
        browse_btn.clicked.connect(self._browse_dir)
        dir_row.addWidget(self._dir_inp, 1)
        dir_row.addWidget(browse_btn)
        dir_col.addLayout(dir_row)

        # Watch interval
        interval_col = QVBoxLayout(); interval_col.setSpacing(4)
        interval_col.addWidget(_field_label("WATCHER INTERVAL (SECONDS)", t))
        self._interval_spin = QSpinBox()
        self._interval_spin.setRange(1, 3600)
        self._interval_spin.setValue(getattr(self._controller, "watch_interval", 5))
        self._interval_spin.setFixedHeight(38)
        self._interval_spin.setSuffix("  sec")
        interval_col.addWidget(self._interval_spin)

        pref_row.addLayout(dir_col, 2)
        pref_row.addLayout(interval_col, 1)
        pref_layout.addLayout(pref_row)

        right_col.addWidget(pref_card)
        right_col.addStretch()

        body.addLayout(right_col, 1)
        layout.addLayout(body)
        layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def _save_profile(self):
        self._controller.output_dir = self._dir_inp.text().strip()
        QMessageBox.information(self, "Saved", "Profile saved successfully.")

    def _browse_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Output Directory", self._dir_inp.text())
        if path:
            self._dir_inp.setText(path)

    def _update_password(self):
        pwd = self._pwd_inp.text()
        confirm = self._pwd_confirm_inp.text()
        if not pwd:
            QMessageBox.warning(self, "Error", "Please enter a new password.")
            return
        if pwd != confirm:
            QMessageBox.warning(self, "Error", "Passwords do not match.")
            return
        self._pwd_inp.clear()
        self._pwd_confirm_inp.clear()
        QMessageBox.information(self, "Success", "Password updated successfully.")
