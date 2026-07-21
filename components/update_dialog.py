"""Help > Check for Update.

Checks GitHub for a newer release and, once the user confirms, downloads,
verifies, and applies it (services.update_checker). Network/download/
extraction all run on a worker QThread so the modal dialog never freezes
the UI — mirrors the _LiveDataWorker pattern in screens/live_viewer.py.

State machine (all driven by the slot methods below, which is also what
tests call directly rather than spinning up real threads — the same
convention screens/live_viewer.py's tests use for LiveDataReader):
  checking -> error | up_to_date | available
  available -> downloading -> applying -> restarting
                            -> failed (back to available, try again)
"""
import font_scale
from PySide6.QtCore import Qt, QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QProgressBar,
    QTextEdit, QMessageBox,
)

from services import update_checker as uc


def _t(theme, key: str) -> str:
    _FALLBACK = {
        "background": "#0d1117", "card_bg": "#1c2128", "border": "#30363d",
        "accent": "#39d353", "text_primary": "#e6edf3", "text_secondary": "#8b949e",
        "button_bg": "#21262d", "destructive": "#da3633",
    }
    if theme:
        try:
            return theme.get(key)
        except Exception:
            pass
    return _FALLBACK.get(key, "#888")


class _CheckWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def run(self):
        try:
            release = uc.fetch_latest_release()
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(release)


class _ApplyWorker(QThread):
    progress = Signal(int, int)   # written, total
    status = Signal(str)
    succeeded = Signal()
    failed = Signal(str)

    def __init__(self, release: dict, parent=None):
        super().__init__(parent)
        self._release = release

    def run(self):
        import tempfile
        from pathlib import Path
        try:
            self.status.emit("Downloading update…")
            with tempfile.TemporaryDirectory() as tmp:
                dest = uc.download_asset(
                    self._release, Path(tmp),
                    progress_cb=lambda w, t: self.progress.emit(w, t),
                )
                self.status.emit("Verifying download…")
                if not uc.verify_checksum(self._release, dest):
                    self.failed.emit("Downloaded file failed checksum verification — not applying.")
                    return
                self.status.emit("Applying update…")
                uc.stage_and_apply(dest)
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit()


class UpdateDialog(QDialog):
    def __init__(self, controller, theme=None, parent=None):
        super().__init__(parent)
        self._controller = controller
        self._theme = theme
        self._release = None
        self._check_worker = None
        self._apply_worker = None
        self.setWindowTitle("Check for Update")
        self.setFixedWidth(440)
        self._build()
        self.start_check()

    def _build(self):
        t = self._theme
        bg, txt = _t(t, "background"), _t(t, "text_primary")
        self.setStyleSheet(
            f"QDialog{{background:{bg};color:{txt};}}QWidget{{background:{bg};color:{txt};}}"
            f"QLabel{{background:transparent;}}"
            f"QPushButton{{background:{_t(t,'button_bg')};color:{txt};"
            f"border:1px solid {_t(t,'border')};border-radius:4px;padding:6px 14px;}}"
            f"QPushButton:hover{{border-color:{_t(t,'accent')};color:{_t(t,'accent')};}}"
            f"QPushButton:disabled{{color:{_t(t,'text_secondary')};}}"
        )
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        self._status_lbl = QLabel("Checking for updates…")
        self._status_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
        self._status_lbl.setWordWrap(True)
        root.addWidget(self._status_lbl)

        self._hint_lbl = QLabel("")
        self._hint_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._hint_lbl.setStyleSheet(f"color:{_t(t,'text_secondary')};")
        self._hint_lbl.setWordWrap(True)
        self._hint_lbl.setVisible(False)
        root.addWidget(self._hint_lbl)

        self._notes = QTextEdit()
        self._notes.setReadOnly(True)
        self._notes.setFixedHeight(140)
        self._notes.setVisible(False)
        root.addWidget(self._notes)

        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setVisible(False)
        root.addWidget(self._progress)

        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self._close_btn = QPushButton("Close")
        self._close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._close_btn.clicked.connect(self.close)
        self._update_btn = QPushButton("Update Now")
        self._update_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._update_btn.setStyleSheet(
            f"QPushButton{{background:{_t(t,'accent')};color:{_t(t,'background')};"
            "border:none;border-radius:4px;padding:6px 16px;}"
        )
        self._update_btn.setVisible(False)
        self._update_btn.clicked.connect(self._on_update_clicked)
        btn_row.addWidget(self._close_btn)
        btn_row.addWidget(self._update_btn)
        root.addLayout(btn_row)

    # ── Check ────────────────────────────────────────────────────────────────

    def start_check(self):
        self._status_lbl.setText("Checking for updates…")
        self._check_worker = _CheckWorker(self)
        self._check_worker.succeeded.connect(self.on_check_succeeded)
        self._check_worker.failed.connect(self.on_check_failed)
        self._check_worker.start()

    def on_check_succeeded(self, release: dict):
        self._release = release
        if not uc.has_update(release):
            self._status_lbl.setText(f"You're on the latest version (v{release['version']}).")
            return

        self._status_lbl.setText(f"v{release['version']} is available (you have v{uc.APP_VERSION}).")
        if release.get("notes"):
            self._notes.setPlainText(release["notes"])
            self._notes.setVisible(True)

        if uc.is_frozen():
            self._update_btn.setVisible(True)
        else:
            self._hint_lbl.setText(
                "Running from source — download the packaged build from "
                f"GitHub to update: {release.get('html_url', '')}"
            )
            self._hint_lbl.setVisible(True)

    def on_check_failed(self, message: str):
        self._status_lbl.setText(f"Could not check for updates: {message}")

    # ── Apply ────────────────────────────────────────────────────────────────

    def _on_update_clicked(self):
        self._update_btn.setEnabled(False)
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._apply_worker = _ApplyWorker(self._release, self)
        self._apply_worker.progress.connect(self.on_apply_progress)
        self._apply_worker.status.connect(self._status_lbl.setText)
        self._apply_worker.succeeded.connect(self.on_apply_succeeded)
        self._apply_worker.failed.connect(self.on_apply_failed)
        self._apply_worker.start()

    def on_apply_progress(self, written: int, total: int):
        if total:
            self._progress.setValue(int(written / total * 100))

    def on_apply_succeeded(self):
        self._progress.setVisible(False)
        self._status_lbl.setText("Restarting to apply the update…")
        self._update_btn.setVisible(False)
        self._close_btn.setEnabled(False)
        QTimer.singleShot(600, self._controller.request_quit)

    def on_apply_failed(self, message: str):
        self._progress.setVisible(False)
        self._update_btn.setEnabled(True)
        QMessageBox.critical(self, "Update Failed", message)
        self._status_lbl.setText("Update failed — you're still on the current version.")

    def closeEvent(self, event):
        for worker in (self._check_worker, self._apply_worker):
            if worker is not None and worker.isRunning():
                worker.wait(200)
        super().closeEvent(event)
