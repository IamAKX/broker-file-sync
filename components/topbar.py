import font_scale
import re
import os
import sys
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QMessageBox
)
from PySide6.QtCore import Signal, Qt, QByteArray, QSize
from PySide6.QtGui import QFont, QAction, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from theme import ThemeManager
from version import APP_VERSION


def _restart_app():
    os.execv(sys.executable, [sys.executable] + sys.argv)

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")

def _load_svg_icon(filename: str, color: str = None, size: int = 20) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    if color:
        svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
        svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
        svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class TopBar(QWidget):
    theme_toggled   = Signal()
    restart_requested = Signal()
    navigate        = Signal(str)   # screen key
    quit_requested  = Signal()
    logout_requested = Signal()
    fullscreen_requested = Signal()
    check_for_update_requested = Signal()

    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setMinimumHeight(40)
        self.setMaximumHeight(40)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(4)

        menus = [
            ("File", [
                ("Clear Cache",  lambda: None),
                ("---",          None),
                ("Restart",      lambda: _restart_app()),
                ("---",          None),
                ("Quit",         lambda: self.quit_requested.emit()),
            ]),
            ("Edit", [
                ("Configs",         lambda: self.navigate.emit("config_editor")),
            ]),
            ("Data", [
                ("Data Import",     lambda: self.navigate.emit("data_import")),
                ("Historic Upload", lambda: self.navigate.emit("historic_upload")),
                ("Formula Builder", lambda: self.navigate.emit("formula_builder")),
                ("Market Holidays", lambda: self.navigate.emit("holidays")),
            ]),
            ("View", [
                ("Full Screen",  lambda: self.fullscreen_requested.emit()),
                ("Toggle Theme", lambda: self._on_toggle()),
            ]),
            ("Profile", [
                ("My Profile",   lambda: self.navigate.emit("profile")),
                ("---",          None),
                ("Logout",       lambda: self.logout_requested.emit()),
            ]),
            ("Help", [
                ("About",              lambda: self._show_about()),
                ("Terms & Conditions", lambda: None),
                ("Check for Update",   lambda: self.check_for_update_requested.emit()),
            ]),
        ]

        for menu_name, items in menus:
            btn = QPushButton(menu_name)
            btn.setFlat(True)
            btn.setFont(font_scale.font(font_scale.SMALL, False))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"color: {self._theme.get('text_secondary')};"
                "background: transparent; border: none; padding: 0 6px;"
            )
            menu = QMenu(self)
            menu.setFont(font_scale.font(font_scale.SMALL, False))
            for item in items:
                if item[0] == "---":
                    menu.addSeparator()
                else:
                    label, callback = item
                    action = QAction(label, self)
                    if callback:
                        action.triggered.connect(callback)
                    menu.addAction(action)
            btn.setMenu(menu)
            # hide the default dropdown arrow indicator
            btn.setStyleSheet(
                "QPushButton { color: " + self._theme.get('text_secondary') + ";"
                " background: transparent; border: none; padding: 0 6px; }"
                "QPushButton::menu-indicator { width: 0; image: none; }"
            )
            layout.addWidget(btn)

        layout.addStretch()

        # Theme toggle pill with SVG icon
        self._toggle_btn = QPushButton()
        self._toggle_btn.setFixedHeight(30)
        self._toggle_btn.setFixedWidth(52)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setIconSize(QSize(20, 20))
        self._toggle_btn.setStyleSheet(self._toggle_style())
        self._toggle_btn.setIcon(self._toggle_icon())
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

    def _toggle_icon(self) -> QIcon:
        if self._theme.current_mode == "dark":
            # show sun (switch to light) — keep original colors
            return _load_svg_icon("sun.svg")
        else:
            # show moon (switch to dark) — tint to theme color
            return _load_svg_icon("moon.svg", self._theme.get("text_primary"))

    def _toggle_style(self) -> str:
        t = self._theme
        return (
            f"background: {t.get('button_bg')}; color: {t.get('text_primary')};"
            f"border: 1px solid {t.get('border')}; border-radius: 15px;"
            "padding: 0 6px;"
        )

    def _on_toggle(self):
        self._theme.toggle()
        self._toggle_btn.setIcon(self._toggle_icon())
        self._toggle_btn.setStyleSheet(self._toggle_style())
        self.theme_toggled.emit()

    def _show_about(self):
        box = QMessageBox(self)
        box.setWindowTitle("About Broker Sync")
        box.setText(f"Broker Sync\nVersion {APP_VERSION}")
        box.setStyleSheet(
            f"QMessageBox{{background:{self._theme.get('background')};"
            f"color:{self._theme.get('text_primary')};}}"
            f"QMessageBox QLabel{{color:{self._theme.get('text_primary')};background:transparent;}}"
            f"QMessageBox QPushButton{{background:{self._theme.get('button_bg')};"
            f"color:{self._theme.get('text_primary')};border:1px solid {self._theme.get('border')};"
            "border-radius:4px;padding:6px 14px;}"
        )
        box.exec()
