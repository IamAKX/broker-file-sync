import font_scale
import re
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame
)
from PySide6.QtCore import Signal, Qt, QByteArray, QSize
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from theme import ThemeManager

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")

NAV_ITEMS = [
    ("dashboard",        "Dashboard",       "dashboard.svg"),
    ("data_import",      "Data Import",     "import.svg"),
    ("config_editor",    "Config Editor",   "config_editor.svg"),
    ("strategy_builder", "Strategy Builder","strategy_builder.svg"),
    ("notifications",    "Notifications",   "notification.svg"),
    ("profile",          "My Profile",      "profile.svg"),
]

BROKERS = [
    ("Sharekhan",       "status_red"),
    ("ReliableSoftware","status_blue"),
    ("NiftyInvest",     "status_orange"),
    ("ExternalImport",  "status_purple"),
    ("MarketProfile",   "status_pink"),
]


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()

    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^>]*></rect>', '', svg)
    # Rewrite fill on root <svg> element (covers inherited fills on child rects)
    svg = re.sub(r'(<svg\b[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)

    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class Sidebar(QWidget):
    navigate = Signal(str)

    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._buttons: dict[str, QPushButton] = {}
        self._nav_meta: list[tuple[str, str, str]] = []
        self._active = "dashboard"
        # broker row state: name -> (dot_label, name_label, selected)
        self._broker_rows: list[tuple[str, QLabel, QLabel, str]] = []
        self._selected_brokers: set[str] = set()
        self.setMinimumWidth(180)
        self.setMaximumWidth(180)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Nav items
        for key, label, icon_file in NAV_ITEMS:
            self._nav_meta.append((key, label, icon_file))
            btn = QPushButton(f"  {label}")
            btn.setFlat(True)
            btn.setFixedHeight(42)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setIconSize(QSize(18, 18))
            btn.clicked.connect(lambda _, k=key: self._on_nav(k))
            btn.setStyleSheet(self._nav_style(key == self._active))
            self._set_btn_icon(btn, icon_file, key == self._active)
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addStretch()

        # Broker Files section — above user widget
        broker_label = QLabel("BROKER FILES")
        broker_label.setFont(font_scale.font(font_scale.SMALL, False))
        broker_label.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        broker_label.setContentsMargins(14, 8, 0, 4)
        layout.addWidget(broker_label)

        for name, color_token in BROKERS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 4, 8, 4)
            row_layout.setSpacing(8)

            dot = QLabel("○")
            dot.setFont(font_scale.font(font_scale.SMALL, False))
            dot.setFixedWidth(14)
            dot.setStyleSheet(f"color: {self._theme.get('text_secondary')};")

            name_lbl = QLabel(name)
            name_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            name_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")

            row_layout.addWidget(dot)
            row_layout.addWidget(name_lbl)
            row_layout.addStretch()
            layout.addWidget(row)

            self._broker_rows.append((name, dot, name_lbl, color_token))

        layout.addSpacing(8)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {self._theme.get('border')}; max-height: 1px;")
        layout.addWidget(sep)

        # User widget
        user_widget = QWidget()
        user_layout = QHBoxLayout(user_widget)
        user_layout.setContentsMargins(10, 6, 10, 6)
        user_layout.setSpacing(8)

        avatar = QLabel("SP")
        avatar.setFixedSize(28, 28)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(font_scale.font(font_scale.SMALL, True))
        avatar.setStyleSheet(
            f"background: {self._theme.get('accent')}; color: {self._theme.get('background')};"
            "border-radius: 14px;"
        )
        self._avatar_label = avatar

        user_info = QVBoxLayout()
        user_info.setSpacing(0)
        name_lbl2 = QLabel("Sunder P.")
        name_lbl2.setFont(font_scale.font(font_scale.SMALL, False))
        name_lbl2.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        email_lbl = QLabel("sunder@gmail.com")
        email_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        email_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        self._user_name_lbl = name_lbl2
        self._user_email_lbl = email_lbl
        user_info.addWidget(name_lbl2)
        user_info.addWidget(email_lbl)

        user_layout.addWidget(avatar)
        user_layout.addLayout(user_info)
        layout.addWidget(user_widget)

    def set_broker_active(self, name: str, active: bool):
        if active:
            self._selected_brokers.add(name)
        else:
            self._selected_brokers.discard(name)
        self._refresh_broker_rows()

    def _refresh_broker_rows(self):
        for name, dot, name_lbl, color_token in self._broker_rows:
            selected = name in self._selected_brokers
            if selected:
                dot.setText("●")
                dot.setStyleSheet(f"color: {self._theme.get(color_token)};")
                name_lbl.setFont(font_scale.font(font_scale.SMALL, True))
                name_lbl.setStyleSheet(f"color: {self._theme.get('text_primary')};")
            else:
                dot.setText("○")
                dot.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
                name_lbl.setFont(font_scale.font(font_scale.SMALL, False))
                name_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")

    def _set_btn_icon(self, btn: QPushButton, icon_file: str, active: bool):
        color = self._theme.get("background") if active else self._theme.get("text_secondary")
        btn.setIcon(_svg_icon(icon_file, color))

    def _nav_style(self, active: bool) -> str:
        if active:
            return (
                f"background: {self._theme.get('accent')};"
                f"color: {self._theme.get('background')};"
                f"text-align: left; padding-left: 14px; border: none;"
                f"font-size: {font_scale.MEDIUM}pt;"
            )
        return (
            f"color: {self._theme.get('text_secondary')};"
            f"background: transparent; text-align: left; padding-left: 14px;"
            f"border: none; font-size: {font_scale.MEDIUM}pt;"
        )

    def _on_nav(self, key: str):
        self.set_active(key)
        self.navigate.emit(key)

    def set_active(self, screen_name: str):
        self._active = screen_name
        for key, btn in self._buttons.items():
            active = key == screen_name
            btn.setStyleSheet(self._nav_style(active))
            btn.setChecked(active)
            for k, _, icon_file in self._nav_meta:
                if k == key:
                    self._set_btn_icon(btn, icon_file, active)
                    break

    def refresh_theme(self):
        self._avatar_label.setStyleSheet(
            f"background: {self._theme.get('accent')}; color: {self._theme.get('background')};"
            "border-radius: 14px;"
        )
        self._user_name_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        self._user_email_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        self._refresh_broker_rows()
        for key, btn in self._buttons.items():
            active = key == self._active
            for k, _, icon_file in self._nav_meta:
                if k == key:
                    self._set_btn_icon(btn, icon_file, active)
                    break
