import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp):
    # tests/conftest.py's autouse _isolate_disk_stores fixture already
    # redirects config_store/strategy_store to a per-test tmp path.
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Open", "High", "Low", "Close"]
    w._data    = [["INFY", "100", "110", "95", "105"]]
    w._visible_cols = set(range(len(w._headers)))
    w._populate_table(w._data, changed_keys=set())
    return w


# ── services.config_store persistence ────────────────────────────────────────

def test_load_highlight_color_defaults_to_none():
    from services import config_store
    assert config_store.load_lmv_highlight_color() is None


def test_save_and_load_highlight_color_round_trips():
    from services import config_store
    config_store.save_lmv_highlight_color("#ff00aa")
    assert config_store.load_lmv_highlight_color() == "#ff00aa"


def test_save_none_clears_override():
    from services import config_store
    config_store.save_lmv_highlight_color("#ff00aa")
    config_store.save_lmv_highlight_color(None)
    assert config_store.load_lmv_highlight_color() is None


# ── _contrasting_text ─────────────────────────────────────────────────────────

def test_contrasting_text_is_black_on_light_background():
    from screens.live_viewer import _contrasting_text
    assert _contrasting_text("#ffffff") == "#000000"


def test_contrasting_text_is_white_on_dark_background():
    from screens.live_viewer import _contrasting_text
    assert _contrasting_text("#000000") == "#ffffff"


# ── LiveViewerWindow wiring ───────────────────────────────────────────────────

def test_default_highlight_uses_theme_amber(lmv):
    # No override saved — falls back to the theme's status_amber, same as
    # before this feature existed.
    t = lmv._theme
    expected = t.get("status_amber") if t else "#d29922"
    assert lmv._effective_highlight_color().lower() == expected.lower()


def test_set_highlight_color_updates_effective_color_and_persists(lmv):
    from services import config_store
    lmv._set_highlight_color("#123456")
    assert lmv._effective_highlight_color() == "#123456"
    assert config_store.load_lmv_highlight_color() == "#123456"


def test_set_highlight_color_none_reverts_to_theme_default(lmv):
    lmv._set_highlight_color("#123456")
    lmv._set_highlight_color(None)
    t = lmv._theme
    expected = t.get("status_amber") if t else "#d29922"
    assert lmv._effective_highlight_color().lower() == expected.lower()


def test_populate_table_amber_brush_reflects_configured_color(lmv):
    lmv._set_highlight_color("#00ff00")
    lmv._populate_table(lmv._data, changed_keys=set())
    assert lmv._amber_bg.color().name() == "#00ff00"
    # #00ff00 is bright -> black text for contrast.
    assert lmv._amber_txt.color().name() == "#000000"


def test_persisted_color_survives_new_window_instance(qapp):
    from services import config_store
    from screens.live_viewer import LiveViewerWindow
    config_store.save_lmv_highlight_color("#abcdef")
    w = LiveViewerWindow("", "", "", [])
    assert w._highlight_color == "#abcdef"
    assert w._effective_highlight_color() == "#abcdef"


# ── HighlightColorPopup ───────────────────────────────────────────────────────

def test_popup_emits_preset_color_on_swatch_click(qapp, lmv):
    from screens.live_viewer import HighlightColorPopup, _HIGHLIGHT_PRESETS
    popup = HighlightColorPopup(None, theme=lmv._theme)
    received = []
    popup.color_picked.connect(lambda c: received.append(c))
    # Second preset (index 0 is "Amber (default)" -> None); pick the first
    # concrete color instead so we can assert a real value came through.
    label, color = _HIGHLIGHT_PRESETS[1]
    assert color is not None
    popup._pick(color)
    assert received == [color]


def test_show_highlight_color_popup_opens_without_error(lmv):
    # Smoke test: constructing/positioning the popup from the toolbar button
    # must not raise (regression guard for the mapToGlobal/move wiring).
    lmv._show_highlight_color_popup()
