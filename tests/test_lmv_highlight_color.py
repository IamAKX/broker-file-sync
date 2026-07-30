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


# ── services.config_store persistence (LMV-wide default) ────────────────────

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


# ── services.config_store persistence (per-column overrides) ────────────────

def test_load_column_highlight_colors_defaults_to_empty():
    from services import config_store
    assert config_store.load_lmv_column_highlight_colors() == {}


def test_save_and_load_column_highlight_colors_round_trips():
    from services import config_store
    config_store.save_lmv_column_highlight_colors({"Open": "#ff0000", "Close": "#00ff00"})
    assert config_store.load_lmv_column_highlight_colors() == {
        "Open": "#ff0000", "Close": "#00ff00",
    }


# ── _contrasting_text ─────────────────────────────────────────────────────────

def test_contrasting_text_is_black_on_light_background():
    from screens.live_viewer import _contrasting_text
    assert _contrasting_text("#ffffff") == "#000000"


def test_contrasting_text_is_white_on_dark_background():
    from screens.live_viewer import _contrasting_text
    assert _contrasting_text("#000000") == "#ffffff"


# ── LiveViewerWindow: default color ──────────────────────────────────────────

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


def test_persisted_default_color_survives_new_window_instance(qapp):
    from services import config_store
    from screens.live_viewer import LiveViewerWindow
    config_store.save_lmv_highlight_color("#abcdef")
    w = LiveViewerWindow("", "", "", [])
    assert w._highlight_color == "#abcdef"
    assert w._effective_highlight_color() == "#abcdef"


# ── LiveViewerWindow: per-column overrides ───────────────────────────────────

def test_column_without_override_falls_back_to_default(lmv):
    lmv._set_highlight_color("#111111")
    assert lmv._effective_highlight_color("Open") == "#111111"


def test_column_override_wins_over_default(lmv):
    lmv._set_highlight_color("#111111")
    lmv._set_column_highlight_color("Open", "#222222")
    assert lmv._effective_highlight_color("Open") == "#222222"
    # Other columns are untouched.
    assert lmv._effective_highlight_color("Close") == "#111111"


def test_clearing_column_override_reverts_to_default(lmv):
    lmv._set_highlight_color("#111111")
    lmv._set_column_highlight_color("Open", "#222222")
    lmv._set_column_highlight_color("Open", None)
    assert lmv._effective_highlight_color("Open") == "#111111"


def test_set_column_highlight_color_persists(lmv):
    from services import config_store
    lmv._set_column_highlight_color("Open", "#333333")
    assert config_store.load_lmv_column_highlight_colors() == {"Open": "#333333"}


def test_persisted_column_colors_survive_new_window_instance(qapp):
    from services import config_store
    from screens.live_viewer import LiveViewerWindow
    config_store.save_lmv_column_highlight_colors({"Open": "#444444"})
    w = LiveViewerWindow("", "", "", [])
    assert w._column_highlight_colors == {"Open": "#444444"}
    assert w._effective_highlight_color("Open") == "#444444"


def test_populate_table_uses_per_column_brushes(lmv):
    lmv._set_highlight_color("#111111")
    lmv._set_column_highlight_color("Open", "#00ff00")
    lmv._populate_table(lmv._data, changed_keys=set())

    headers = lmv._current_column_labels()
    open_idx  = headers.index("Open")
    close_idx = headers.index("Close")

    assert lmv._amber_bg_by_col[open_idx].color().name() == "#00ff00"
    # #00ff00 is bright -> black text for contrast.
    assert lmv._amber_txt_by_col[open_idx].color().name() == "#000000"
    # Close has no override -> uses the default.
    assert lmv._amber_bg_by_col[close_idx].color().name() == "#111111"


# ── HighlightColorManagerDialog ───────────────────────────────────────────────

def test_manager_lists_default_plus_every_column(qapp, lmv):
    from screens.live_viewer import HighlightColorManagerDialog
    dlg = HighlightColorManagerDialog(
        columns=["Open", "Close"], default_color=None, column_colors={},
        theme=lmv._theme,
    )
    labels = [dlg._list.item(i).text() for i in range(dlg._list.count())]
    assert labels[0] == "Default (all other columns)"
    assert "Open" in labels
    assert "Close" in labels


def test_manager_marks_columns_with_override_as_custom(qapp, lmv):
    from screens.live_viewer import HighlightColorManagerDialog
    dlg = HighlightColorManagerDialog(
        columns=["Open", "Close"], default_color=None,
        column_colors={"Open": "#ff0000"}, theme=lmv._theme,
    )
    labels = [dlg._list.item(i).text() for i in range(dlg._list.count())]
    assert "Open  (custom)" in labels
    assert "Close" in labels  # untouched, no "(custom)" suffix


def test_manager_apply_to_default_row_emits_default_changed(qapp, lmv):
    from screens.live_viewer import HighlightColorManagerDialog
    dlg = HighlightColorManagerDialog(
        columns=["Open"], default_color=None, column_colors={}, theme=lmv._theme,
    )
    received = []
    dlg.default_changed.connect(lambda c: received.append(c))
    dlg._list.setCurrentRow(0)   # "Default" row
    dlg._apply("#ff0000")
    assert received == ["#ff0000"]


def test_manager_apply_to_column_row_emits_column_changed(qapp, lmv):
    from screens.live_viewer import HighlightColorManagerDialog
    dlg = HighlightColorManagerDialog(
        columns=["Open", "Close"], default_color=None, column_colors={}, theme=lmv._theme,
    )
    received = []
    dlg.column_changed.connect(lambda col, c: received.append((col, c)))
    # Row 0 is "Default", row 1 is "Open".
    dlg._list.setCurrentRow(1)
    dlg._apply("#00ff00")
    assert received == [("Open", "#00ff00")]


def test_manager_apply_none_to_column_clears_override(qapp, lmv):
    from screens.live_viewer import HighlightColorManagerDialog
    dlg = HighlightColorManagerDialog(
        columns=["Open"], default_color=None,
        column_colors={"Open": "#ff0000"}, theme=lmv._theme,
    )
    received = []
    dlg.column_changed.connect(lambda col, c: received.append((col, c)))
    dlg._list.setCurrentRow(1)   # "Open"
    dlg._apply(None)
    assert received == [("Open", None)]
    assert "Open" not in dlg._column_colors


def test_wiring_manager_signals_updates_lmv_state(qapp, lmv):
    """End-to-end: the signals HighlightColorManagerDialog emits are exactly
    what _show_highlight_color_manager wires up — verified here without
    calling that method directly, since it opens the dialog modally
    (dlg.exec()) and would block the test."""
    from screens.live_viewer import HighlightColorManagerDialog
    dlg = HighlightColorManagerDialog(
        columns=lmv._current_column_labels(),
        default_color=lmv._highlight_color,
        column_colors=lmv._column_highlight_colors,
        theme=lmv._theme,
    )
    dlg.default_changed.connect(lmv._set_highlight_color)
    dlg.column_changed.connect(lmv._set_column_highlight_color)

    dlg._list.setCurrentRow(0)
    dlg._apply("#101010")
    assert lmv._highlight_color == "#101010"

    # Find the row for "Open" by its stored UserRole data.
    from PySide6.QtCore import Qt
    idx = next(
        i for i in range(dlg._list.count())
        if dlg._list.item(i).data(Qt.ItemDataRole.UserRole) == "Open"
    )
    dlg._list.setCurrentRow(idx)
    dlg._apply("#202020")
    assert lmv._column_highlight_colors.get("Open") == "#202020"
