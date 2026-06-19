import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    return app

def test_default_mode_is_dark(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    assert tm.current_mode == "dark"

def test_get_returns_dark_accent(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    assert tm.get("accent") == "#39d353"

def test_toggle_switches_to_light(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    assert tm.current_mode == "light"
    assert tm.get("accent") == "#1a7f37"

def test_toggle_switches_back_to_dark(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    tm.toggle()
    assert tm.current_mode == "dark"

def test_get_unknown_token_raises(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    with pytest.raises(KeyError):
        tm.get("nonexistent_token")
