"""Opt-in, app-wide debug log capture (File > Enable Debug Logging).

When enabled, everything the process emits that could explain a failure is
written to one file in a user-chosen folder:

  * every ``logging`` record from any module/screen/thread (root logger, plus
    the app's own non-propagating ``broker_sync.errors`` / ``broker_sync.api``
    loggers) at DEBUG — API request/response lines, handled-and-logged
    errors, library warnings;
  * uncaught exceptions on the main thread (sys.excepthook → error_logger)
    and on worker threads (threading.excepthook), with full tracebacks;
  * Qt's own warnings/critical messages (qInstallMessageHandler);
  * Python ``warnings``;
  * anything printed to stdout/stderr (print() calls on any screen);
  * hard crashes (faulthandler dumps the native/Python stack of every thread).

Settings (enabled flag + folder) are per-machine and stored locally in
debug_log_settings.json beside config_data.json — deliberately NOT in the
server-backed config_store, since a folder path is meaningless on another
machine. If enabled, capture restarts automatically on the next launch.

Meant for debugging only: nothing is written while disabled. Credentials the
api layer already redacts stay redacted; a final filter also masks bearer
tokens and password-looking fields in any message.
"""

import faulthandler
import json
import logging
import os
import platform
import re
import sys
import threading
from datetime import datetime
from logging.handlers import RotatingFileHandler

_SETTINGS_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "debug_log_settings.json"
)
_MAX_BYTES = 20_000_000
_BACKUPS = 5
_APP_LOGGERS = ("broker_sync.errors", "broker_sync.api")

_lock = threading.Lock()
_state: dict = {
    "handler": None, "path": None, "root_level": None, "crash_file": None,
    "orig_stdout": None, "orig_stderr": None, "orig_thread_hook": None,
    "qt_prev_handler": None,
}

_SECRET_RE = re.compile(
    r"(?i)(bearer\s+)[A-Za-z0-9._\-]+|((?:password|access_token|refresh_token)['\"]?\s*[:=]\s*['\"]?)[^'\",\s}]+"
)


class _RedactFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
            red = _SECRET_RE.sub(lambda m: (m.group(1) or m.group(2)) + "***", msg)
            if red != msg:
                record.msg, record.args = red, None
        except Exception:
            pass
        return True


# ── settings ────────────────────────────────────────────────────────────────

def load_settings() -> dict:
    try:
        with open(_SETTINGS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {"enabled": bool(data.get("enabled")), "folder": str(data.get("folder") or "")}
    except (OSError, ValueError):
        return {"enabled": False, "folder": ""}


def save_settings(enabled: bool, folder: str) -> None:
    try:
        with open(_SETTINGS_FILE, "w", encoding="utf-8") as f:
            json.dump({"enabled": bool(enabled), "folder": folder}, f)
    except OSError:
        pass


def is_active() -> bool:
    return _state["handler"] is not None


def current_log_path() -> str | None:
    return _state["path"]


# ── capture plumbing ────────────────────────────────────────────────────────

class _StreamTee:
    """File-like wrapper that forwards writes to the real stream AND logs each
    complete line. Tolerates a None original (windowed PyInstaller builds)."""

    def __init__(self, original, logger: logging.Logger, level: int):
        self._orig, self._logger, self._level, self._buf = original, logger, level, ""

    def write(self, text):
        try:
            if self._orig is not None:
                self._orig.write(text)
        except Exception:
            pass
        try:
            self._buf += text
            while "\n" in self._buf:
                line, self._buf = self._buf.split("\n", 1)
                if line.strip():
                    self._logger.log(self._level, line)
        except Exception:
            pass
        return len(text)

    def flush(self):
        try:
            if self._orig is not None:
                self._orig.flush()
        except Exception:
            pass

    def __getattr__(self, name):
        return getattr(self._orig, name)


def _qt_message_handler(mode, context, message):
    try:
        name = getattr(mode, "name", str(mode))
        level = {"QtDebugMsg": logging.DEBUG, "QtInfoMsg": logging.INFO,
                 "QtWarningMsg": logging.WARNING}.get(name, logging.ERROR)
        where = f" ({context.file}:{context.line})" if getattr(context, "file", None) else ""
        logging.getLogger("qt").log(level, "%s%s", message, where)
    except Exception:
        pass


def _thread_excepthook(args):
    try:
        logging.getLogger("threading").error(
            "Unhandled exception in thread %s", getattr(args.thread, "name", "?"),
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback),
        )
    except Exception:
        pass
    prev = _state["orig_thread_hook"]
    if prev is not None:
        prev(args)


# ── enable / disable ────────────────────────────────────────────────────────

def enable(folder: str) -> str:
    """Start capturing into *folder* (created if needed). Returns the log file
    path. Raises OSError if the folder/file can't be written. Idempotent:
    re-enabling with a different folder switches files."""
    with _lock:
        _disable_locked()
        os.makedirs(folder, exist_ok=True)
        path = os.path.join(folder, f"broker_sync_debug_{datetime.now():%Y%m%d_%H%M%S}.log")
        handler = RotatingFileHandler(path, maxBytes=_MAX_BYTES, backupCount=_BACKUPS, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)-8s [%(threadName)s] %(name)s: %(message)s"))
        handler.addFilter(_RedactFilter())

        root = logging.getLogger()
        _state["root_level"] = root.level
        root.setLevel(logging.DEBUG)
        root.addHandler(handler)
        for name in _APP_LOGGERS:       # propagate=False loggers need it directly
            logging.getLogger(name).addHandler(handler)
        logging.captureWarnings(True)

        _state["handler"], _state["path"] = handler, path

        try:
            crash = open(os.path.join(folder, "broker_sync_crash.log"), "a", encoding="utf-8")
            crash.write(f"\n--- session {datetime.now().isoformat()} ---\n")
            crash.flush()
            faulthandler.enable(file=crash, all_threads=True)
            _state["crash_file"] = crash
        except Exception:
            _state["crash_file"] = None

        _state["orig_stdout"], _state["orig_stderr"] = sys.stdout, sys.stderr
        sys.stdout = _StreamTee(sys.stdout, logging.getLogger("stdout"), logging.INFO)
        sys.stderr = _StreamTee(sys.stderr, logging.getLogger("stderr"), logging.ERROR)

        _state["orig_thread_hook"] = threading.excepthook
        threading.excepthook = _thread_excepthook

        try:
            from PySide6.QtCore import qInstallMessageHandler
            _state["qt_prev_handler"] = qInstallMessageHandler(_qt_message_handler)
        except Exception:
            pass

        log = logging.getLogger("debug_log")
        try:
            from version import APP_VERSION as app_version
        except Exception:
            app_version = "?"
        log.info("Debug logging started — app %s, Python %s, %s %s, pid %s",
                 app_version, platform.python_version(), platform.system(),
                 platform.release(), os.getpid())
        return path


def _disable_locked() -> None:
    handler = _state["handler"]
    if handler is None:
        return
    logging.getLogger("debug_log").info("Debug logging stopped")
    root = logging.getLogger()
    root.removeHandler(handler)
    for name in _APP_LOGGERS:
        logging.getLogger(name).removeHandler(handler)
    if _state["root_level"] is not None:
        root.setLevel(_state["root_level"])
    logging.captureWarnings(False)
    handler.close()

    if isinstance(sys.stdout, _StreamTee):
        sys.stdout = _state["orig_stdout"]
    if isinstance(sys.stderr, _StreamTee):
        sys.stderr = _state["orig_stderr"]
    if _state["orig_thread_hook"] is not None:
        threading.excepthook = _state["orig_thread_hook"]
    try:
        from PySide6.QtCore import qInstallMessageHandler
        qInstallMessageHandler(_state["qt_prev_handler"])
    except Exception:
        pass
    try:
        faulthandler.disable()
        if _state["crash_file"] is not None:
            _state["crash_file"].close()
    except Exception:
        pass
    for k in ("handler", "path", "root_level", "crash_file", "orig_stdout",
              "orig_stderr", "orig_thread_hook", "qt_prev_handler"):
        _state[k] = None


def disable() -> None:
    with _lock:
        _disable_locked()


def start_from_saved() -> str | None:
    """Called once at launch: resume capture if it was left enabled. Never
    raises — a bad/missing folder just leaves logging off."""
    s = load_settings()
    if not (s["enabled"] and s["folder"]):
        return None
    try:
        return enable(s["folder"])
    except Exception:
        return None
