"""Tests for components.update_dialog.UpdateDialog's state transitions.

Calls the slot methods directly (on_check_succeeded/on_check_failed/
on_apply_progress/on_apply_succeeded/on_apply_failed) rather than spinning
up the real _CheckWorker/_ApplyWorker QThreads — the same convention this
repo already uses for LiveDataReader (tested directly, not through its
QThread wrapper). The worker classes themselves just call
services.update_checker, which is already covered by test_update_checker.py.
"""
import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class _FakeController:
    def __init__(self):
        self.quit_called = False

    def request_quit(self):
        self.quit_called = True


@pytest.fixture
def dialog(qapp, monkeypatch):
    # Prevent the real network check from firing during construction —
    # each test drives the state machine explicitly via the slot methods.
    from components.update_dialog import _CheckWorker
    monkeypatch.setattr(_CheckWorker, "start", lambda self: None)
    from components.update_dialog import UpdateDialog
    dlg = UpdateDialog(_FakeController(), theme=None)
    # isVisible() on a child widget reflects the whole ancestor chain's
    # shown state, not just its own setVisible() call — show() (non-modal,
    # non-blocking, safe under QT_QPA_PLATFORM=offscreen) so the visibility
    # assertions below test what they mean to.
    dlg.show()
    return dlg


def test_dialog_starts_in_checking_state(dialog):
    assert "Checking" in dialog._status_lbl.text()


def test_check_failed_shows_error(dialog):
    dialog.on_check_failed("connection refused")
    assert "Could not check" in dialog._status_lbl.text()
    assert "connection refused" in dialog._status_lbl.text()
    assert not dialog._update_btn.isVisible()


def test_check_succeeded_up_to_date(dialog, monkeypatch):
    from services import update_checker as uc
    monkeypatch.setattr(uc, "APP_VERSION", "1.2.0")
    release = {"version": "1.2.0", "version_tuple": (1, 2, 0), "notes": "", "html_url": ""}
    dialog.on_check_succeeded(release)
    assert "latest version" in dialog._status_lbl.text()
    assert not dialog._update_btn.isVisible()
    assert not dialog._notes.isVisible()


def test_check_succeeded_update_available_when_frozen(dialog, monkeypatch):
    from services import update_checker as uc
    monkeypatch.setattr(uc, "APP_VERSION", "1.2.0")
    monkeypatch.setattr(uc, "is_frozen", lambda: True)
    release = {
        "version": "1.5.0", "version_tuple": (1, 5, 0),
        "notes": "- fixed things", "html_url": "https://github.com/x/y/releases/tag/v1.5.0",
    }
    dialog.on_check_succeeded(release)
    assert "1.5.0" in dialog._status_lbl.text()
    assert "1.2.0" in dialog._status_lbl.text()
    assert dialog._update_btn.isVisible()
    assert dialog._notes.isVisible()
    assert dialog._notes.toPlainText() == "- fixed things"
    assert not dialog._hint_lbl.isVisible()


def test_check_succeeded_update_available_but_not_frozen(dialog, monkeypatch):
    from services import update_checker as uc
    monkeypatch.setattr(uc, "APP_VERSION", "1.2.0")
    monkeypatch.setattr(uc, "is_frozen", lambda: False)
    release = {
        "version": "1.5.0", "version_tuple": (1, 5, 0),
        "notes": "", "html_url": "https://github.com/x/y/releases/tag/v1.5.0",
    }
    dialog.on_check_succeeded(release)
    assert not dialog._update_btn.isVisible()
    assert dialog._hint_lbl.isVisible()
    assert "source" in dialog._hint_lbl.text()


def test_apply_progress_updates_bar(dialog):
    dialog.on_apply_progress(50, 200)
    assert dialog._progress.value() == 25


def test_apply_progress_ignores_zero_total(dialog):
    dialog._progress.setValue(10)
    dialog.on_apply_progress(50, 0)
    assert dialog._progress.value() == 10   # unchanged, no divide-by-zero


def test_apply_succeeded_schedules_quit(dialog, monkeypatch, qapp):
    from PySide6.QtCore import QTimer
    scheduled = []
    monkeypatch.setattr(QTimer, "singleShot", staticmethod(lambda ms, cb: scheduled.append((ms, cb))))
    dialog.on_apply_succeeded()
    assert "Restarting" in dialog._status_lbl.text()
    assert len(scheduled) == 1
    delay, callback = scheduled[0]
    callback()
    assert dialog._controller.quit_called is True


def test_apply_failed_shows_error_and_reenables_button(dialog, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    dialog._update_btn.setEnabled(False)
    dialog.on_apply_failed("checksum mismatch")
    assert dialog._update_btn.isEnabled()
    assert "failed" in dialog._status_lbl.text().lower()


def test_update_button_click_starts_apply_worker(dialog, monkeypatch):
    from components.update_dialog import _ApplyWorker
    started = []
    monkeypatch.setattr(_ApplyWorker, "start", lambda self: started.append(self))
    dialog._release = {"version": "1.5.0", "asset_url": "https://dl/x.zip", "asset_name": "x.zip"}
    dialog._on_update_clicked()
    assert len(started) == 1
    assert dialog._progress.isVisible()
    assert not dialog._update_btn.isEnabled()
