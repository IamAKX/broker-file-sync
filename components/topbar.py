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
from api.token_store import token_manager

# The one account Admin Controls > Inception Sync is shown for — matches
# the backend's own app.core.deps._ADMIN_EMAIL (broker-sync-api repo)
# exactly; that server-side check is what actually enforces this, not
# this menu's visibility — hiding the menu here is just so nobody else
# sees an entry that would 403 if they clicked it. Case-insensitive, same
# as the backend's own comparison.
_ADMIN_EMAIL = "sundarhari10@gmail.com"


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
    export_strategies_requested = Signal()
    import_strategies_requested = Signal()
    manage_categories_requested = Signal()
    clear_cache_requested = Signal()

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
                ("Clear Cache",  lambda: self.clear_cache_requested.emit()),
                ("---",          None),
                ("Export All Strategies", lambda: self.export_strategies_requested.emit()),
                ("Import All Strategies", lambda: self.import_strategies_requested.emit()),
                ("---",          None),
                ("Restart",      lambda: _restart_app()),
                ("---",          None),
                ("Quit",         lambda: self.quit_requested.emit()),
            ]),
            ("Edit", [
                ("Configs",         lambda: self.navigate.emit("config_editor")),
                ("Formula Builder", lambda: self.navigate.emit("formula_builder")),
                ("Market Holidays", lambda: self.navigate.emit("holidays")),
                ("---",             None),
                ("Manage Categories…", lambda: self.manage_categories_requested.emit()),
            ]),
            ("Data", [
                ("Data Import",     lambda: self.navigate.emit("data_import")),
                ("Historic Upload", lambda: self.navigate.emit("historic_upload")),
                ("LMV Upload",      lambda: self.navigate.emit("lmv_upload")),
                ("High/Low",        lambda: self.navigate.emit("jobs")),
                ("Formula Stats",   lambda: self.navigate.emit("formula_stats")),
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
            ("Inception", [
                ("View by Date",      lambda: self.navigate.emit("inception_view_by_date")),
                ("Strategy Builder",  lambda: self.navigate.emit("inception_strategy_builder")),
                ("HMV",               lambda: self.navigate.emit("inception_hmv")),
                ("Formula Stats",     lambda: self.navigate.emit("inception_formula_stats")),
                ("---",               None),
                ("Data & Settings",   lambda: self.navigate.emit("inception_settings")),
            ]),
            # Hidden for everyone except _ADMIN_EMAIL — see refresh_user's
            # own docstring. Always built (never conditionally skipped
            # here) so there's one stable button instance to toggle
            # setVisible() on rather than rebuilding the whole menu bar on
            # every login.
            ("Admin Controls", [
                ("Inception Sync", lambda: self.navigate.emit("inception_admin_sync")),
            ]),
            ("Help", [
                ("About",              lambda: self._show_about()),
                ("Terms & Conditions", lambda: None),
                ("Check for Update",   lambda: self.check_for_update_requested.emit()),
            ]),
        ]

        self._menu_buttons = {}
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
            self._menu_buttons[menu_name] = btn

        layout.addStretch()

        # Admin Controls is gated to one specific account — must run after
        # every button above exists (needs self._menu_buttons populated)
        # but before the theme toggle so an early return / exception here
        # can't skip building the rest of the bar.
        self.refresh_user()

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

    def refresh_user(self):
        """Shows/hides the "Admin Controls" menu for the CURRENT user —
        called once at construction (self._menu_buttons is already
        populated by the time _build() reaches this) and again on every
        re-login (app_window.MainWindow.refresh_user), since MainWindow/
        TopBar are reused across a logout/login cycle within the same
        running process (see app.AppController.show_main_window's own
        comment on that) — without this, a different user logging in on
        the same device would keep seeing whatever the PREVIOUS user's
        admin status left the menu showing."""
        email = (token_manager.get_user_email() or "").strip().lower()
        btn = self._menu_buttons.get("Admin Controls")
        if btn is not None:
            btn.setVisible(email == _ADMIN_EMAIL)

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
