from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QCheckBox, QDialog, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class ProfileScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("My Profile")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Account settings and preferences")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # User info card
        info_card = QFrame()
        info_card.setObjectName("infoCard")
        info_card.setStyleSheet(
            f"QFrame#infoCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(24, 20, 24, 20)
        info_layout.setSpacing(14)

        section_lbl = QLabel("USER INFORMATION")
        section_lbl.setFont(QFont("Courier New", 10))
        section_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        info_layout.addWidget(section_lbl)

        for field_label, value in [
            ("FULL NAME", "Rajesh Kumar"),
            ("EMAIL",     "rajesh.kumar@example.com"),
            ("ROLE",      "Administrator"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(field_label)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setFixedWidth(120)
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            val = QLineEdit(value)
            val.setReadOnly(True)
            val.setFixedHeight(34)
            val.setStyleSheet(
                f"background: {t.get('input_bg')}; color: {t.get('text_primary')};"
                f"border: 1px solid {t.get('border')}; border-radius: 4px; padding: 0 10px;"
            )
            row.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(val, 1)
            info_layout.addLayout(row)

        layout.addWidget(info_card)

        # Preferences card
        pref_card = QFrame()
        pref_card.setObjectName("prefCard")
        pref_card.setStyleSheet(
            f"QFrame#prefCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        pref_layout = QVBoxLayout(pref_card)
        pref_layout.setContentsMargins(24, 20, 24, 20)
        pref_layout.setSpacing(14)

        pref_lbl = QLabel("PREFERENCES")
        pref_lbl.setFont(QFont("Courier New", 10))
        pref_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        pref_layout.addWidget(pref_lbl)

        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Dark Mode")
        theme_lbl.setFont(QFont("Courier New", 13))
        self._theme_check = QCheckBox()
        self._theme_check.setChecked(t.current_mode == "dark")
        self._theme_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_check.stateChanged.connect(self._on_theme_toggle)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_check)
        theme_row.addStretch()
        pref_layout.addLayout(theme_row)

        layout.addWidget(pref_card)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        pwd_btn = QPushButton("\U0001f511  Change Password")
        pwd_btn.setFixedHeight(40)
        pwd_btn.setFont(QFont("Courier New", 12))
        pwd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pwd_btn.clicked.connect(self._open_change_password)
        btn_row.addWidget(pwd_btn)

        logout_btn = QPushButton("⏻  Logout")
        logout_btn.setFixedHeight(40)
        logout_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.setStyleSheet(
            f"background: {t.get('destructive')}; color: white;"
            "border: none; border-radius: 4px; padding: 0 20px;"
        )
        logout_btn.clicked.connect(self._controller.show_login)
        btn_row.addWidget(logout_btn)
        btn_row.addStretch()

        layout.addLayout(btn_row)
        layout.addStretch()

    def _on_theme_toggle(self, state):
        t = self._controller.theme
        wants_dark = bool(state)
        if (wants_dark and t.current_mode != "dark") or \
           (not wants_dark and t.current_mode != "light"):
            t.toggle()

    def _open_change_password(self):
        t = self._controller.theme
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Password")
        dialog.setFixedWidth(360)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(24, 24, 24, 24)
        dlg_layout.setSpacing(12)

        for lbl_text, placeholder, echo in [
            ("CURRENT PASSWORD", "Enter current password", True),
            ("NEW PASSWORD",     "Enter new password",     True),
            ("CONFIRM PASSWORD", "Confirm new password",   True),
        ]:
            lbl = QLabel(lbl_text)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFixedHeight(34)
            if echo:
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            dlg_layout.addWidget(lbl)
            dlg_layout.addWidget(inp)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(lambda: (
            QMessageBox.information(dialog, "Success", "Password updated successfully."),
            dialog.accept()
        ))
        btns.rejected.connect(dialog.reject)
        dlg_layout.addWidget(btns)
        dialog.exec()
