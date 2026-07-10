import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    return app


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    return config_store


def test_default_mode_is_light(qapp, isolated_store):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    assert tm.current_mode == "light"

def test_get_returns_light_accent(qapp, isolated_store):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    assert tm.get("accent") == "#1a7f37"

def test_toggle_switches_to_dark(qapp, isolated_store):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    assert tm.current_mode == "dark"
    assert tm.get("accent") == "#39d353"

def test_toggle_switches_back_to_light(qapp, isolated_store):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    tm.toggle()
    assert tm.current_mode == "light"

def test_get_unknown_token_raises(qapp, isolated_store):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    with pytest.raises(KeyError):
        tm.get("nonexistent_token")

def test_toggle_persists_selection(qapp, isolated_store):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    assert isolated_store.load_theme() == "dark"

def test_new_manager_loads_persisted_theme(qapp, isolated_store):
    from theme import ThemeManager
    isolated_store.save_theme("dark")
    tm = ThemeManager(qapp)
    assert tm.current_mode == "dark"
