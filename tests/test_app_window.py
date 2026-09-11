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
    for name in ["dashboard", "data_import", "config_editor", "notifications", "profile",
                 "formula_builder", "formula_stats",
                 "inception_view_by_date", "inception_strategy_builder", "inception_hmv"]:
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
    w._screens["formula_stats"].reload_strategies = MagicMock()

    w.reload_per_user_data()

    w._screens["strategy_builder"].reload_strategies.assert_called_once()
    w._screens["notifications"].reload_configs.assert_called_once()
    w._screens["formula_builder"].reload_formulas.assert_called_once()
    w._screens["formula_stats"].reload_strategies.assert_called_once()


def test_lmv_ready_only_pushes_strategies_active_in_strategy_builder(controller):
    """A strategy switched off in Strategy Builder shouldn't even appear in
    LMV's Strategies picker — see app_window.py::_on_lmv_ready, which now
    sources from get_active_strategies() instead of get_all_strategies()."""
    from app_window import MainWindow
    from unittest.mock import MagicMock

    w = MainWindow(controller)
    data_import = w._screens["data_import"]
    strategy_builder = w._screens["strategy_builder"]
    strategy_builder._strategies = [
        {"id": "1", "name": "Active One", "active": True},
        {"id": "2", "name": "Inactive One", "active": False},
    ]

    fake_viewer = MagicMock()
    data_import._live_viewer = fake_viewer

    data_import.lmv_headers_ready.emit(["Scrip Name", "High", "Low"])

    pushed = fake_viewer.set_strategies.call_args[0][0]
    assert [s["name"] for s in pushed] == ["Active One"]
    # None auto-applied even though it's active in Strategy Builder — the
    # user still opts it in per LMV session (see the closure's comment).
    assert pushed[0]["active"] is False


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


def test_data_menu_manage_variables_opens_dialog(controller, monkeypatch):
    """Data > Manage Variables… fires the topbar signal, which MainWindow
    routes to a VariablesManagerDialog (see app_window._open_manage_variables /
    the formula-variable sync bug it addresses)."""
    from app_window import MainWindow
    import screens.formula_editor as fe

    opened = []

    class _FakeDlg:
        def __init__(self, *a, **k):
            opened.append((a, k))

        def exec(self):
            return 0

    monkeypatch.setattr(fe, "VariablesManagerDialog", _FakeDlg)

    w = MainWindow(controller)
    data_menu = w._topbar._menu_buttons["Data"].menu()
    action = next(a for a in data_menu.actions() if a.text() == "Manage Variables…")
    action.trigger()

    assert len(opened) == 1


def test_clear_cache_also_clears_formula_variables_and_compile_cache(controller, monkeypatch):
    """File > Clear Cache must drop the formula-variable local cache and
    strategy_engine's compile cache too — otherwise a stale "{Name}"
    expansion survives the "re-fetch everything" the user just asked for
    (see app_window._clear_cache)."""
    from app_window import MainWindow
    from PySide6.QtWidgets import QMessageBox
    from services import formula_variable_store, strategy_engine, config_store, strategy_store

    calls = []
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    # _clear_cache ends with a real QMessageBox.information("Cache cleared...")
    # on success — unmocked, that's a genuine modal that renders on screen and
    # blocks on .exec() waiting for a click (this is what happened the first
    # time this test was written without this line: a real "Cache cleared —
    # data refreshed from the server." dialog popped up and hung the run).
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(config_store, "clear_local_cache", lambda: calls.append("config"))
    monkeypatch.setattr(strategy_store, "clear_local_cache", lambda: calls.append("strategy"))
    monkeypatch.setattr(formula_variable_store, "clear_local_cache",
                        lambda: calls.append("variables"))
    monkeypatch.setattr(strategy_engine, "clear_compile_cache",
                        lambda: calls.append("compile"))

    w = MainWindow(controller)
    w._clear_cache()

    assert "variables" in calls
    assert "compile" in calls


# ── Export/Import All Data — superset of the old Export/Import All ─────────
# Strategies: LMV + Inception strategies, both apps' formula variables, and
# every settings key, all in one bundle (see app_window._export_all_data /
# _import_all_data).

def _mock_all_message_boxes(monkeypatch):
    """Every _export_all_data/_import_all_data path ends in a real
    QMessageBox.information/warning — unmocked, that's a genuine modal that
    renders on screen and blocks on .exec() (see
    test_clear_cache_also_clears_formula_variables_and_compile_cache's own
    note on exactly this happening once already). Mock all three so a test
    that doesn't care about the dialog text can't accidentally hang."""
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)


def test_export_all_data_bundles_every_section(controller, monkeypatch, tmp_path):
    from app_window import MainWindow
    from PySide6.QtWidgets import QFileDialog
    from services import config_store, formula_variable_store, inception_formula_variable_store, inception_strategy_store, strategy_store

    _mock_all_message_boxes(monkeypatch)
    monkeypatch.setattr(strategy_store, "load_all", lambda: [{"id": "1", "name": "S1"}])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{"id": "2", "name": "IS1"}])
    monkeypatch.setattr(formula_variable_store, "load_all", lambda: [{"id": "3", "name": "V1"}])
    monkeypatch.setattr(inception_formula_variable_store, "load_all", lambda: [{"id": "4", "name": "IV1"}])
    monkeypatch.setattr(config_store, "export_all_settings", lambda: {"theme": "dark"})

    out_path = str(tmp_path / "export.json")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out_path, "")))

    w = MainWindow(controller)
    w._export_all_data()

    import json
    with open(out_path) as f:
        bundle = json.load(f)
    assert bundle["strategies"] == [{"id": "1", "name": "S1"}]
    assert bundle["inception_strategies"] == [{"id": "2", "name": "IS1"}]
    assert bundle["formula_variables"] == [{"id": "3", "name": "V1"}]
    assert bundle["inception_formula_variables"] == [{"id": "4", "name": "IV1"}]
    assert bundle["settings"] == {"theme": "dark"}


def test_export_all_data_nothing_to_export(controller, monkeypatch):
    from app_window import MainWindow
    from services import config_store, formula_variable_store, inception_formula_variable_store, inception_strategy_store, strategy_store

    shown = []
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "information", lambda self_, title, msg: shown.append(msg))
    monkeypatch.setattr(strategy_store, "load_all", lambda: [])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [])
    monkeypatch.setattr(formula_variable_store, "load_all", lambda: [])
    monkeypatch.setattr(inception_formula_variable_store, "load_all", lambda: [])
    monkeypatch.setattr(config_store, "export_all_settings", lambda: {})

    w = MainWindow(controller)
    w._export_all_data()

    assert shown and "Nothing to export" in shown[0]


def test_import_all_data_pushes_every_present_section_to_the_server(controller, monkeypatch, tmp_path):
    from app_window import MainWindow
    from PySide6.QtWidgets import QFileDialog
    from services import config_store, formula_variable_store, inception_formula_variable_store, inception_strategy_store, strategy_store

    _mock_all_message_boxes(monkeypatch)
    calls = {}

    def _fake_import(section, result):
        def _importer(items):
            calls[section] = items
            return result
        return _importer

    monkeypatch.setattr(strategy_store, "import_all", _fake_import("strategies", (1, 0)))
    monkeypatch.setattr(inception_strategy_store, "import_all", _fake_import("inception_strategies", (0, 1)))
    monkeypatch.setattr(formula_variable_store, "import_all", _fake_import("formula_variables", (2, 0)))
    monkeypatch.setattr(inception_formula_variable_store, "import_all", _fake_import("inception_formula_variables", (0, 2)))

    def _fake_import_settings(settings):
        calls["settings"] = settings
        return len(settings)

    monkeypatch.setattr(config_store, "import_all_settings", _fake_import_settings)
    monkeypatch.setattr(strategy_store, "load_all", lambda: [])

    import json
    bundle = {
        "strategies": [{"id": "1", "name": "S1"}],
        "inception_strategies": [{"id": "2", "name": "IS1"}],
        "formula_variables": [{"id": "3", "name": "V1"}],
        "inception_formula_variables": [{"id": "4", "name": "IV1"}],
        "settings": {"theme": "dark"},
    }
    in_path = tmp_path / "import.json"
    in_path.write_text(json.dumps(bundle))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(in_path), "")))

    w = MainWindow(controller)
    w._import_all_data()

    assert calls["strategies"] == bundle["strategies"]
    assert calls["inception_strategies"] == bundle["inception_strategies"]
    assert calls["formula_variables"] == bundle["formula_variables"]
    assert calls["inception_formula_variables"] == bundle["inception_formula_variables"]
    assert calls["settings"] == bundle["settings"]


def test_import_all_data_accepts_the_old_bare_list_strategies_only_format(controller, monkeypatch, tmp_path):
    """Backward compatibility: a file exported by the old "Export All
    Strategies" feature (a bare JSON list, no wrapping dict) must still
    import correctly as strategies-only."""
    from app_window import MainWindow
    from PySide6.QtWidgets import QFileDialog
    from services import strategy_store

    _mock_all_message_boxes(monkeypatch)
    calls = []

    def _fake_import(items):
        calls.append(items)
        return (1, 0)

    monkeypatch.setattr(strategy_store, "import_all", _fake_import)
    monkeypatch.setattr(strategy_store, "load_all", lambda: [])

    import json
    old_format = [{"id": "1", "name": "S1"}]
    in_path = tmp_path / "old_export.json"
    in_path.write_text(json.dumps(old_format))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(in_path), "")))

    w = MainWindow(controller)
    w._import_all_data()

    assert calls == [old_format]


def test_import_all_data_rejects_a_malformed_file(controller, monkeypatch, tmp_path):
    from app_window import MainWindow
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    warned = {}
    monkeypatch.setattr(QMessageBox, "warning",
                        lambda self_, title, msg: warned.setdefault("shown", msg))

    in_path = tmp_path / "bad.json"
    in_path.write_text('{"strategies": "not a list"}')
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(in_path), "")))

    w = MainWindow(controller)
    w._import_all_data()

    assert "shown" in warned
