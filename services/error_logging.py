"""App-wide fallback exception logging.

Anything that reaches here is a bug the caller didn't anticipate, but it must
never be allowed to crash the app or vanish silently — see
main.install_excepthook and the per-tick render guards in
screens.live_viewer.LiveViewerWindow.

Writes to stdout (visible when running via python main.py / run.sh) AND to
error.log in the app root (same directory auth_session.json,
strategy_alert_state_*.json etc. already live in — confirmed writable by
existing local storage). The file handler exists specifically so a packaged
build (PyInstaller — see docs/building.md), which has no visible stdout at
all, still leaves a trail: without it, something failing silently in the
background — e.g. services/notifications/channels/email.py's send() running
on its own thread, with nothing else ever seeing what it raises — was
completely undiagnosable in a shipped build. Capped and rotated so it can't
grow unbounded over a long-running session.
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler

_LOG_DIR = os.path.dirname(os.path.dirname(__file__))
_LOG_FILE = os.path.join(_LOG_DIR, "error.log")


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("broker_sync.errors")
    logger.setLevel(logging.ERROR)
    if not logger.handlers:
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")

        stream_handler = logging.StreamHandler(sys.stdout)
        stream_handler.setFormatter(fmt)
        logger.addHandler(stream_handler)

        try:
            file_handler = RotatingFileHandler(
                _LOG_FILE, maxBytes=5_000_000, backupCount=5, encoding="utf-8",
            )
            file_handler.setFormatter(fmt)
            logger.addHandler(file_handler)
        except OSError:
            pass   # e.g. a read-only install location — stdout logging still works

        logger.propagate = False
    return logger


error_logger = _build_logger()


def install_excepthook() -> None:
    """Log otherwise-uncaught exceptions instead of relying on whatever the
    platform/Qt binding does by default (silently dropping the traceback, or
    aborting the process)."""
    def _hook(exc_type, exc_value, exc_tb):
        error_logger.error("Unhandled exception", exc_info=(exc_type, exc_value, exc_tb))
    sys.excepthook = _hook
