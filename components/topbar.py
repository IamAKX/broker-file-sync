from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QSizePolicy
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QAction
from theme import ThemeManager

MENUS = {
    "File":          ["New Session", "Open Config", "---", "Exit"],
    "Edit":          ["Undo", "Redo", "---", "Preferences"],
    "View":          ["Zoom In", "Zoom Out", "---", "Full Screen"],
    "Notifications": ["Mark All Read", "Clear All"],
    "Profile":       ["My Profile", "---", "Logout"],
    "Help":          ["Documentation", "About Broker File Sync"],
}


class TopBar(QWidget):
    theme_toggled = Signal()
    restart_requested = Signal()

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

        app_label = QLabel("BROKER FILE SYNC")
        app_label.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        layout.addWidget(app_label)

        layout.addSpacing(16)

        for menu_name, items in MENUS.items():
            btn = QPushButton(menu_name)
            btn.setFlat(True)
            btn.setFont(QFont("Courier New", 11))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"color: {self._theme.get('text_secondary')};"
                "background: transparent; border: none; padding: 0 6px;"
            )
            menu = QMenu(self)
            for item in items:
                if item == "---":
                    menu.addSeparator()
                else:
                    menu.addAction(QAction(item, self))
            btn.setMenu(menu)
            layout.addWidget(btn)

        layout.addStretch()

        self._toggle_btn = QPushButton(self._theme_icon())
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFont(QFont("Courier New", 14))
        self._toggle_btn.setToolTip("Toggle dark/light mode")
        self._toggle_btn.setStyleSheet("background: transparent; border: none;")
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        restart_btn = QPushButton("⟳ Restart")
        restart_btn.setFont(QFont("Courier New", 11))
        restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restart_btn.setFixedHeight(26)
        restart_btn.clicked.connect(self._on_restart)
        layout.addWidget(restart_btn)

    def _theme_icon(self) -> str:
        return "☀" if self._theme.current_mode == "dark" else "\U0001f319"

    def _on_toggle(self):
        self._theme.toggle()
        self._toggle_btn.setText(self._theme_icon())
        self.theme_toggled.emit()

    def _on_restart(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Restart",
            "Reset the application to its initial state?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.restart_requested.emit()
