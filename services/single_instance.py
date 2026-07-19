"""
Prevents launching a second copy of the app once one is already tray-resident
(easy to trigger accidentally now that closing the window no longer quits).
Uses QLocalServer/QLocalSocket, which ships with PySide6 — no new dependency.
"""

from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstanceGuard:
    _KEY = "BrokerSyncSingleInstance"

    def __init__(self):
        self._server: QLocalServer | None = None
        self._on_second_instance = None

    def try_acquire(self, on_second_instance) -> bool:
        """Return True if this process should proceed as the one true
        instance. Return False if another instance is already running (it
        has been pinged to activate itself; the caller should exit
        immediately without building any UI)."""
        probe = QLocalSocket()
        probe.connectToServer(self._KEY)
        if probe.waitForConnected(200):
            probe.write(b"activate")
            probe.waitForBytesWritten(200)
            probe.disconnectFromServer()
            return False

        # No live server responded — remove any stale socket left behind by
        # a prior crash before claiming the name ourselves.
        QLocalServer.removeServer(self._KEY)
        self._on_second_instance = on_second_instance
        self._server = QLocalServer()
        self._server.newConnection.connect(self._drain)
        self._server.listen(self._KEY)
        return True

    def _drain(self):
        sock = self._server.nextPendingConnection()
        if sock is not None:
            sock.waitForReadyRead(200)
            sock.disconnectFromServer()
        if self._on_second_instance is not None:
            self._on_second_instance()
