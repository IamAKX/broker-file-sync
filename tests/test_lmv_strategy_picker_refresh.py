"""
Regression tests for two related "Strategies picker" bugs:

1. self._strategies used to only ever be set once (LiveViewerWindow.
   set_strategies, at window construction) and otherwise resynced with
   services.strategy_store only via the unrelated "↻ N-Day Data" button. A
   strategy switched on in Strategy Builder after the LMV window was already
   open silently never appeared in the "⚡ Strategies" picker until that
   button was clicked.

2. The fix for #1 (LiveViewerWindow._sync_strategies_from_store) called
   services.strategy_store.load_all() SYNCHRONOUSLY on the GUI thread every
   time the "⚡ Strategies" button was clicked, on the theory that "a
   discrete click, not a per-tick path" made that acceptable. It wasn't: a
   slow/unreachable server froze the whole window (Windows' "Not
   Responding" title included) for the request's full timeout on every
   click — the same class of GUI-thread-network-call freeze do_read/
   recompute/refresh_day_history were already routed off the GUI thread to
   avoid (see test_lmv_day_history_off_gui_thread.py). Fixed by routing the
   reload through the worker thread too
   (_LiveDataWorker.sync_strategies_from_store), the same "request Signal
   out, result Signal back" pattern as everything else in this file.

See screens.live_viewer.LiveViewerWindow._show_strategy_picker /
_LiveDataWorker.sync_strategies_from_store and
LmvSnapshotViewer._show_strategy_picker.
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


# ── _LiveDataWorker.sync_strategies_from_store: the reload itself, off the
# GUI thread — same merge semantics as the old synchronous version ─────────

def test_worker_sync_strategies_shows_strategy_activated_after_window_opened(qapp, tmp_path, monkeypatch):
    """The original reported bug: a strategy marked Active in Strategy
    Builder after LMV is already open must show up in the picker without
    requiring the "↻ N-Day Data" button first."""
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import _LiveDataWorker

    monkeypatch.setattr(
        store, "load_all",
        lambda: [{"id": "new", "name": "New Strat", "active": True, "category": "Daily"}],
    )

    worker = _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})
    results = []
    worker.strategies_synced.connect(lambda merged: results.append(merged))

    worker.sync_strategies_from_store([])   # window opened with nothing active yet

    assert len(results) == 1
    assert [s["name"] for s in results[0]] == ["New Strat"]


def test_worker_sync_strategies_drops_strategy_deactivated_in_builder(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import _LiveDataWorker

    monkeypatch.setattr(store, "load_all", lambda: [{"id": "x", "name": "X", "active": False}])

    worker = _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})
    results = []
    worker.strategies_synced.connect(lambda merged: results.append(merged))

    worker.sync_strategies_from_store([{"id": "x", "name": "X", "active": True}])

    assert results == [[]]


def test_worker_sync_strategies_emits_failed_signal_on_network_error(qapp, tmp_path, monkeypatch):
    """The exact freeze trigger: server unreachable/slow. Must reach the
    caller as a Signal, same best-effort "keep whatever was already there"
    behavior as every other store reload in this window — never raise
    across the thread boundary, and never silently hang."""
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import _LiveDataWorker
    from api.exceptions import NetworkError

    def _boom():
        raise NetworkError("Could not reach server: timed out")
    monkeypatch.setattr(store, "load_all", _boom)

    worker = _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})
    synced, failed = [], []
    worker.strategies_synced.connect(lambda merged: synced.append(merged))
    worker.strategies_sync_failed.connect(lambda: failed.append(True))

    worker.sync_strategies_from_store([{"id": "x", "name": "X", "active": True}])

    assert synced == []
    assert failed == [True]


# ── LiveViewerWindow._show_strategy_picker: dispatches via the worker
# Signal, never calls strategy_store directly on the GUI thread ───────────

def test_show_strategy_picker_never_calls_load_all_on_gui_thread(lmv, monkeypatch):
    from services import strategy_store as store

    called = []
    monkeypatch.setattr(store, "load_all", lambda: called.append(1) or [])
    lmv._worker = object()   # placeholder — just needs to be non-None
    lmv._request_strategies_sync.connect(lambda *a: None)   # swallow — no real worker

    lmv._show_strategy_picker()

    assert called == []   # never touched directly on the calling (GUI) thread


def test_show_strategy_picker_dispatches_current_strategies_via_signal(lmv):
    lmv.set_strategies([{"id": "x", "name": "X", "active": True, "category": "Daily"}])
    lmv._worker = object()
    emitted = []
    lmv._request_strategies_sync.connect(lambda strategies: emitted.append(strategies))

    lmv._show_strategy_picker()

    assert len(emitted) == 1
    assert [s["name"] for s in emitted[0]] == ["X"]
    assert lmv._strategy_picker_pending is True
    assert lmv._strat_btn.isEnabled() is False


def test_show_strategy_picker_ignores_second_click_while_in_flight(lmv):
    lmv._worker = object()
    emitted = []
    lmv._request_strategies_sync.connect(lambda *a: emitted.append(1))

    lmv._show_strategy_picker()
    lmv._show_strategy_picker()   # second click before the first reply lands

    assert len(emitted) == 1


def test_strategies_synced_re_enables_button_and_updates_strategies(lmv):
    lmv._worker = object()
    lmv._request_strategies_sync.connect(lambda *a: None)
    lmv._show_strategy_picker()
    assert lmv._strat_btn.isEnabled() is False

    lmv._on_strategies_synced([{"id": "new", "name": "New", "active": True, "category": "Daily"}])

    assert lmv._strat_btn.isEnabled() is True
    assert lmv._strategy_picker_pending is False
    assert [s["name"] for s in lmv._filtered_strategies()] == ["New"]


def test_strategies_sync_failed_re_enables_button_keeps_existing_strategies(lmv):
    lmv.set_strategies([{"id": "x", "name": "X", "active": True, "category": "Daily"}])
    lmv._worker = object()
    lmv._request_strategies_sync.connect(lambda *a: None)
    lmv._show_strategy_picker()
    assert lmv._strat_btn.isEnabled() is False

    lmv._on_strategies_sync_failed()

    assert lmv._strat_btn.isEnabled() is True
    assert lmv._strategy_picker_pending is False
    assert [s["name"] for s in lmv._filtered_strategies()] == ["X"]   # untouched


def test_show_strategy_picker_falls_back_to_sync_open_when_worker_not_up(lmv, monkeypatch):
    """Shouldn't happen once the window is visible, but must degrade
    gracefully (open with whatever's already known) rather than silently
    doing nothing if it ever does."""
    from services import strategy_store as store

    lmv.set_strategies([{"id": "x", "name": "X", "active": True, "category": "Daily"}])
    lmv._worker = None
    opened = []
    monkeypatch.setattr(lmv, "_open_strategy_picker", lambda: opened.append(1))

    lmv._show_strategy_picker()

    assert opened == [1]
