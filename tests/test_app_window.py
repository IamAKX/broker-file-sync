import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)

def test_main_window_creates(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    assert w is not None

def test_navigate_does_not_raise(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    for name in ["dashboard", "data_import", "config_editor", "notifications", "profile", "formula_builder"]:
        w.navigate(name)

def test_close_event_hides_instead_of_quitting_by_default(controller):
    """Tray-resident: the X button hides the window rather than tearing it
    down, so the background scheduler keeps running."""
    from app_window import MainWindow
    from PySide6.QtGui import QCloseEvent
    from unittest.mock import MagicMock

    w = MainWindow(controller)
    live_viewer = MagicMock()
    w._screens["data_import"]._live_viewer = live_viewer

    assert controller.is_quitting is False
    w.closeEvent(QCloseEvent())

    live_viewer.close.assert_not_called()


def test_reload_per_user_data_refreshes_strategy_notifications_and_formula_screens(controller):
    from app_window import MainWindow
    from unittest.mock import MagicMock

    w = MainWindow(controller)
    w._screens["strategy_builder"].reload_strategies = MagicMock()
    w._screens["notifications"].reload_configs = MagicMock()
    w._screens["formula_builder"].reload_formulas = MagicMock()

    w.reload_per_user_data()

    w._screens["strategy_builder"].reload_strategies.assert_called_once()
    w._screens["notifications"].reload_configs.assert_called_once()
    w._screens["formula_builder"].reload_formulas.assert_called_once()


def test_reload_per_user_data_rebuilds_config_editor_screen(controller):
    """ConfigEditorScreen has no in-place reload method (see
    app_window.py::_reload_config_editor's docstring) — reload_per_user_data
    must swap in a fresh instance so a second user's config-editor data
    doesn't keep showing the first user's."""
    from app_window import MainWindow

    w = MainWindow(controller)
    old_config_editor = w._screens["config_editor"]

    w.reload_per_user_data()

    new_config_editor = w._screens["config_editor"]
    assert new_config_editor is not old_config_editor
    assert w._stack.indexOf(new_config_editor) != -1
    assert w._stack.indexOf(old_config_editor) == -1


def test_reload_per_user_data_preserves_current_config_editor_selection(controller):
    from app_window import MainWindow

    w = MainWindow(controller)
    w.navigate("config_editor")
    assert w._stack.currentWidget() is w._screens["config_editor"]

    w.reload_per_user_data()

    assert w._stack.currentWidget() is w._screens["config_editor"]


def test_second_login_on_same_process_reloads_per_user_data(controller, monkeypatch):
    """AppController.show_main_window only calls reload_per_user_data when
    _main_window already exists (a second+ login within the same process) —
    the first construction already loads fresh per-user data via each
    screen's own __init__, so reloading immediately after would just be
    redundant. Uses a fake already-built window rather than a real
    MainWindow so this doesn't also exercise check_holiday_gate's real
    network call / the background scheduler's startup, neither of which
    this test is about."""
    from unittest.mock import MagicMock

    monkeypatch.setattr(controller.theme, "sync_from_server", lambda: False)
    controller._tray = None   # keeps _ensure_scheduler a no-op (its own guard)
    fake_window = MagicMock()
    controller._main_window = fake_window

    controller.show_main_window()

    fake_window.reload_per_user_data.assert_called_once()
    fake_window.refresh_user.assert_called_once()


def test_close_event_closes_child_windows_when_really_quitting(controller):
    from app_window import MainWindow
    from PySide6.QtGui import QCloseEvent
    from unittest.mock import MagicMock

    w = MainWindow(controller)

    live_viewer = MagicMock()
    w._screens["data_import"]._live_viewer = live_viewer

    historic_viewer_1 = MagicMock()
    historic_viewer_2 = MagicMock()
    w._screens["historic_upload"]._viewers = [historic_viewer_1, historic_viewer_2]

    controller.is_quitting = True
    w.closeEvent(QCloseEvent())

    live_viewer.close.assert_called_once()
    historic_viewer_1.close.assert_called_once()
    historic_viewer_2.close.assert_called_once()
