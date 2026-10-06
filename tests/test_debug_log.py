"""services.debug_log — opt-in app-wide capture."""
import logging
import sys
import threading

import pytest

from services import debug_log


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(debug_log, "_SETTINGS_FILE", str(tmp_path / "debug_log_settings.json"))
    yield
    debug_log.disable()


def _read(path):
    for h in logging.getLogger().handlers:
        h.flush()
    return open(path, encoding="utf-8").read()


def test_captures_logs_prints_thread_errors_and_app_loggers(tmp_path):
    path = debug_log.enable(str(tmp_path / "logs"))
    logging.getLogger("some.screen").debug("hello-debug")
    logging.getLogger("broker_sync.api").warning("api-warn")
    logging.getLogger("broker_sync.errors").error("app-error")
    print("printed-line")

    def boom():
        raise RuntimeError("thread-boom")
    t = threading.Thread(target=boom); t.start(); t.join()

    text = _read(path)
    for needle in ("hello-debug", "api-warn", "app-error", "printed-line", "thread-boom", "Debug logging started"):
        assert needle in text


def test_redacts_bearer_tokens_and_passwords(tmp_path):
    path = debug_log.enable(str(tmp_path))
    logging.getLogger("x").info("Authorization: Bearer abc.def.ghi password=hunter2")
    text = _read(path)
    assert "abc.def.ghi" not in text and "hunter2" not in text


def test_disable_stops_capture_and_restores_streams(tmp_path):
    out = sys.stdout
    path = debug_log.enable(str(tmp_path))
    debug_log.disable()
    assert sys.stdout is out and not debug_log.is_active()
    logging.getLogger("x").error("after-disable")
    assert "after-disable" not in open(path, encoding="utf-8").read()


def test_settings_roundtrip_and_resume(tmp_path):
    assert debug_log.load_settings() == {"enabled": False, "folder": ""}
    assert debug_log.start_from_saved() is None
    debug_log.save_settings(True, str(tmp_path))
    assert debug_log.start_from_saved() is not None and debug_log.is_active()


def test_start_from_saved_never_raises_on_bad_folder(tmp_path):
    f = tmp_path / "file"; f.write_text("x")
    debug_log.save_settings(True, str(f / "sub"))   # parent is a file → can't mkdir
    assert debug_log.start_from_saved() is None
