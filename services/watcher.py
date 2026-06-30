import os
import time
from datetime import datetime
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtCore import QFileSystemWatcher


class FileWatcher(QObject):
    """
    Uses QFileSystemWatcher for real-time OS-level file change events.
    A 300ms debounce timer prevents double-fires while the file is still
    being written (Sharekhan flushes in chunks).
    """

    started     = Signal()
    stopped     = Signal()
    synced      = Signal(str)   # "HH:MM:SS" timestamp
    sync_failed = Signal(str)   # error message

    _DEBOUNCE_MS       = 300
    _MAX_READ_ATTEMPTS = 3
    _RETRY_DELAY_S     = 0.4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._fs_watcher       = QFileSystemWatcher(self)
        self._debounce         = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(self._DEBOUNCE_MS)
        self._debounce.timeout.connect(self._regenerate)
        self._fs_watcher.fileChanged.connect(self._on_file_changed)

        self._sharekhan_path   = None
        self._reliable_path    = None
        self._nifty_path       = None
        self._external_path    = None
        self._market_profile_path = None
        self._output_path      = None
        self._script_name_data = None

    # ── Configuration ─────────────────────────────────────────────────────────

    def configure(self, sharekhan_path: str, reliable_path: str,
                  nifty_path: str, output_path: str,
                  script_name_data: list, external_path: str = None,
                  market_profile_path: str = None) -> None:
        # Remove any previously watched file
        if self._fs_watcher.files():
            self._fs_watcher.removePaths(self._fs_watcher.files())

        self._sharekhan_path   = sharekhan_path
        self._reliable_path    = reliable_path
        self._nifty_path       = nifty_path
        self._external_path    = external_path
        self._market_profile_path = market_profile_path
        self._output_path      = output_path
        self._script_name_data = script_name_data

    # ── Control ───────────────────────────────────────────────────────────────

    def start(self) -> None:
        if not self._sharekhan_path:
            return
        self._fs_watcher.addPath(self._sharekhan_path)
        self.started.emit()

    def stop(self) -> None:
        if self._fs_watcher.files():
            self._fs_watcher.removePaths(self._fs_watcher.files())
        self._debounce.stop()
        self.stopped.emit()

    # ── Properties ────────────────────────────────────────────────────────────

    @property
    def is_active(self) -> bool:
        return bool(self._fs_watcher.files())

    @property
    def watched_filename(self) -> str:
        return os.path.basename(self._sharekhan_path) if self._sharekhan_path else ""

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_file_changed(self, path: str) -> None:
        # Some apps (incl. Excel) briefly remove+recreate the file on save.
        # Re-add the watch if it was lost.
        if path not in self._fs_watcher.files():
            if os.path.exists(path):
                self._fs_watcher.addPath(path)
        # Debounce: restart the 300ms timer so rapid successive events
        # collapse into one regeneration.
        self._debounce.start()

    def _regenerate(self) -> None:
        from services.master_generator import generate_master
        last_err = None
        for attempt in range(self._MAX_READ_ATTEMPTS):
            try:
                generate_master(
                    self._sharekhan_path,
                    self._reliable_path,
                    self._nifty_path,
                    self._output_path,
                    self._script_name_data,
                    external_path=self._external_path,
                    market_profile_path=self._market_profile_path,
                )
                self.synced.emit(datetime.now().strftime("%H:%M:%S"))
                return
            except Exception as exc:
                last_err = exc
                if attempt < self._MAX_READ_ATTEMPTS - 1:
                    time.sleep(self._RETRY_DELAY_S)
        self.sync_failed.emit(str(last_err))
