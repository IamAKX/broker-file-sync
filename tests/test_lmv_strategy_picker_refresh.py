"""
Regression tests for the "not all active strategies show up in LMV's
Strategies picker" bug: self._strategies used to only ever be set once
(LiveViewerWindow.set_strategies, at window construction) and otherwise
resynced with services.strategy_store only via the unrelated "↻ N-Day Data"
button. A strategy switched on in Strategy Builder after the LMV window was
already open silently never appeared in the "⚡ Strategies" picker until
that button was clicked. See LiveViewerWindow._show_strategy_picker /
_sync_strategies_from_store and LmvSnapshotViewer._show_strategy_picker.
"""
import sys

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Current"]
    w._data = [["INFY", "100"]]
    w._visible_cols = set(range(2))
    w._populate_table(w._data, changed_keys=set())
    return w


def test_merge_session_active_keeps_only_builder_active_strategies():
    from services.strategy_store import merge_session_active

    fresh = [
        {"id": "1", "name": "A", "active": True},
        {"id": "2", "name": "B", "active": False},
        {"id": "3", "name": "C", "active": True},
    ]
    session = [{"id": "1", "name": "A", "active": True}]

    merged = merge_session_active(fresh, session)

    assert [s["id"] for s in merged] == ["1", "3"]
    # "1" was already applied this session — that's preserved...
    assert next(s for s in merged if s["id"] == "1")["active"] is True
    # ...but "3" is new to this session (just switched on in Strategy
    # Builder) and starts unapplied, same as every strategy does on open.
    assert next(s for s in merged if s["id"] == "3")["active"] is False


def test_strategy_picker_shows_strategy_activated_after_window_opened(lmv, monkeypatch):
    """The exact reported bug: a strategy marked Active in Strategy Builder
    after LMV is already open must show up in the picker without requiring
    the "↻ N-Day Data" button first."""
    from services import strategy_store as store

    # Window opened with nothing active in Strategy Builder yet.
    lmv.set_strategies([])
    assert lmv._filtered_strategies() == []

    # User goes to Strategy Builder and switches a strategy on.
    monkeypatch.setattr(
        store, "load_all",
        lambda: [{"id": "new", "name": "New Strat", "active": True, "category": "Daily"}],
    )

    lmv._sync_strategies_from_store()

    names = [s["name"] for s in lmv._filtered_strategies()]
    assert names == ["New Strat"]


def test_strategy_picker_drops_strategy_deactivated_in_builder(lmv, monkeypatch):
    from services import strategy_store as store

    lmv.set_strategies([{"id": "x", "name": "X", "active": True}])
    assert [s["name"] for s in lmv._filtered_strategies()] == ["X"]

    monkeypatch.setattr(store, "load_all", lambda: [{"id": "x", "name": "X", "active": False}])
    lmv._sync_strategies_from_store()

    assert lmv._filtered_strategies() == []


def test_show_strategy_picker_calls_sync_first(lmv, monkeypatch):
    called = []
    monkeypatch.setattr(lmv, "_sync_strategies_from_store", lambda: called.append(True))
    lmv._show_strategy_picker()
    assert called == [True]
