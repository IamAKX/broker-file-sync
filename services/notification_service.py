"""
Delivers "System" channel notifications from the background scheduler via
the tray icon. Telegram/SMS remain dummy channels (no backend exists) — this
module only handles System.
"""

from PySide6.QtWidgets import QSystemTrayIcon


class NotificationService:
    def __init__(self, tray_icon: QSystemTrayIcon):
        self._tray = tray_icon
        self._pending_action = None
        self._tray.messageClicked.connect(self._on_message_clicked)

    def notify(self, title: str, message: str, action=None,
               icon=QSystemTrayIcon.MessageIcon.Information, timeout_ms: int = 10_000):
        self._pending_action = action
        self._tray.showMessage(title, message, icon, timeout_ms)

    def _on_message_clicked(self):
        if self._pending_action is not None:
            action, self._pending_action = self._pending_action, None
            action()
