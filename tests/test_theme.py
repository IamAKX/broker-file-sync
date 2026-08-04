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


# ── QPalette (popup/dropdown backgrounds) ────────────────────────────────────
#
# QComboBox/QMenu/tooltip popups paint their surrounding frame from the
# ambient QPalette, not just the QSS stylesheet — see ThemeManager.apply's
# docstring on _build_palette. These check the palette actually gets set to
# the theme's colors (not left at Qt's light-native default) when apply()
# runs, since that's the part a purely-visual bug like a white dropdown on a
# dark theme would come from.

def test_apply_sets_dark_palette_base_and_window(qapp, isolated_store):
    from PySide6.QtGui import QPalette
    from theme import DARK, ThemeManager
    tm = ThemeManager(qapp)
    tm._mode = "dark"
    tm.apply()

    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Base).name() == DARK["input_bg"]
    assert palette.color(QPalette.ColorRole.Window).name() == DARK["background"]
    assert palette.color(QPalette.ColorRole.Text).name() == DARK["text_primary"]
    assert palette.color(QPalette.ColorRole.Highlight).name() == DARK["accent"]


def test_apply_sets_light_palette_base_and_window(qapp, isolated_store):
    from PySide6.QtGui import QPalette
    from theme import LIGHT, ThemeManager
    tm = ThemeManager(qapp)
    tm._mode = "light"
    tm.apply()

    palette = qapp.palette()
    assert palette.color(QPalette.ColorRole.Base).name() == LIGHT["input_bg"]
    assert palette.color(QPalette.ColorRole.Window).name() == LIGHT["background"]


# ── QComboBox popup frame (double-border fix) ────────────────────────────────

def test_combobox_popup_has_no_native_frame(qapp):
    # Regression guard: QComboBox's popup view draws its own native frame by
    # default, layered on top of the QSS border on the same selector, which
    # reads as a doubled/"extra" border around every dropdown — see theme.py's
    # _patch_combo_popup_frame. Importing theme (already done at module scope
    # via other fixtures) must have patched every QComboBox, not just ones
    # created after some manual opt-in call.
    from PySide6.QtWidgets import QComboBox, QFrame
    import theme  # noqa: F401 — ensures the patch has been applied

    combo = QComboBox()
    combo.addItems(["A", "B"])
    combo.show()
    combo.showPopup()
    try:
        assert combo.view().frameShape() == QFrame.Shape.NoFrame
    finally:
        combo.hidePopup()
        combo.close()


def test_toggle_updates_palette_to_match_new_mode(qapp, isolated_store):
    from PySide6.QtGui import QPalette
    from theme import DARK, LIGHT, ThemeManager
    tm = ThemeManager(qapp)
    tm._mode = "light"
    tm.apply()
    assert qapp.palette().color(QPalette.ColorRole.Base).name() == LIGHT["input_bg"]

    tm.toggle()
    assert tm.current_mode == "dark"
    assert qapp.palette().color(QPalette.ColorRole.Base).name() == DARK["input_bg"]
