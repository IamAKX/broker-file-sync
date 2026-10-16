"""
System tray icon: lets the app stay resident when the main window is hidden,
and is the surface the background scheduler's notifications are delivered
through (see services/notifications/).
"""

from PySide6.QtWidgets import QSystemTrayIcon, QMenu
from PySide6.QtGui import QIcon
from PySide6.QtCore import QObject
from branding import APP_NAME


class AppTray(QObject):
    def __init__(self, controller, icon_path: str, parent=None):
        super().__init__(parent)
        self._controller = controller
        self.icon = QSystemTrayIcon(QIcon(icon_path))
        self.icon.setToolTip(APP_NAME)

        menu = QMenu()
        menu.addAction(f"Open {APP_NAME}", self._show)
        menu.addSeparator()
        menu.addAction("Quit", self._controller.request_quit)
        self.icon.setContextMenu(menu)

        self.icon.activated.connect(self._on_activated)
        self.icon.show()

    def _show(self):
        self._controller.show_main_window()
        mw = self._controller._main_window
        if mw is not None:
            mw.showNormal()
            mw.raise_()
            mw.activateWindow()

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._show()
