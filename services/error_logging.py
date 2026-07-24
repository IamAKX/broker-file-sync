"""App-wide fallback exception logging.

Anything that reaches here is a bug the caller didn't anticipate, but it must
never be allowed to crash the app or vanish silently — see
main.install_excepthook and the per-tick render guards in
screens.live_viewer.LiveViewerWindow.
"""

import logging
import sys


def _build_logger() -> logging.Logger:
    logger = logging.getLogger("broker_sync.errors")
    logger.setLevel(logging.ERROR)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
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
