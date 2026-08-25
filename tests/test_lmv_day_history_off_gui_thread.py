"""Regression tests for the "LMV strategy apply/load is laggy, sometimes
Not Responding" report (2026-08-25).

Root cause: services.strategy_engine's Row-Filter Streak feature (shipped
2026-08-24) made a day_history recompute fire on nearly every active
strategy toggle (any strategy with a row filter, not just the rare "uses
AVG_DAYS" case a couple of these code paths were designed around). Two
real GUI-thread network calls this exposed:

1. LiveViewerWindow._refresh_day_history — the strategy-toggle/category-
   change path — used to run compute_day_history() (a real historic-
   snapshot fetch) SYNCHRONOUSLY on the GUI thread, on the documented
   assumption that it "only runs occasionally, not per tick". Now routes
   through the same worker-thread call _refresh_day_history_from_store
   already used (_LiveDataWorker.refresh_day_history), via the shared
   _request_day_history_refresh trigger.
2. LiveViewerWindow._run_strategy_alert_checks (called from EVERY render
   pass, i.e. every live tick, on the GUI thread) used to call
   services.strategy_alerts.config_store.load_configs(), which hits the
   network on its first call after a cache reset (e.g. right after login)
   — now uses peek_configs(), which never touches the network.

See services/strategy_alerts/config_store.py's peek_configs() docstring
and screens/live_viewer.py's _LiveDataWorker.refresh_day_history /
_request_day_history_refresh docstrings for the full "why".
"""
import sys

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store, config_store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Current"]
    w._data = [["INFY", "100"]]
    w._visible_cols = set(range(2))
    w._populate_table(w._data, changed_keys=set())
    # A placeholder "worker exists" marker — _request_day_history_refresh
    # only checks `self._worker is None`, never calls into it directly
    # (dispatch is via the _request_day_history Signal, captured below via
    # a direct .connect() spy instead of a real QThread/worker).
    w._worker = object()
    return w


def _row_filter_strategy(sid="s1"):
    return {
        "id": sid, "name": "Streaky", "active": True,
        "row_filter": [{"type": "col", "value": "Current"}, {"type": "op", "value": ">"},
                        {"type": "num", "value": "0"}],
        "columns": [],
    }


# ── _refresh_day_history / _refresh_day_history_from_store: no synchronous
# network calls, dispatch via the worker signal instead ─────────────────────

def test_refresh_day_history_never_calls_compute_day_history_directly(lmv, monkeypatch):
    from services import formula_stats_engine

    called = []
    monkeypatch.setattr(formula_stats_engine, "compute_day_history", lambda *a, **kw: called.append(1) or {})
    lmv.set_strategies([_row_filter_strategy()])

    emitted = []
    lmv._request_day_history.connect(lambda strategies, category, reload: emitted.append((strategies, category, reload)))

    lmv._refresh_day_history()

    assert called == []            # never computed on the calling thread
    assert len(emitted) == 1
    assert emitted[0][2] is False  # reload_from_store=False for the cheap/toggle path


def test_refresh_day_history_from_store_dispatches_with_reload_true(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    emitted = []
    lmv._request_day_history.connect(lambda strategies, category, reload: emitted.append(reload))

    lmv._refresh_day_history_from_store()

    assert emitted == [True]


def test_refresh_day_history_never_calls_load_configs_directly(lmv, monkeypatch):
    """Same bug, the other input: notif_configs used to be fetched via
    alerts_config_store.load_configs() on the GUI thread before dispatch —
    now fetched inside the worker method itself."""
    from services.strategy_alerts import config_store as alerts_config_store

    called = []
    monkeypatch.setattr(alerts_config_store, "load_configs", lambda: called.append(1) or {})
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_day_history.connect(lambda *a: None)

    lmv._refresh_day_history()
    lmv._day_history_refreshing = False   # second call, still shouldn't touch it
    lmv._refresh_day_history_from_store()

    assert called == []


# ── in-flight coalescing ─────────────────────────────────────────────────

def test_second_request_while_one_in_flight_is_coalesced_not_dropped(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    emitted = []
    lmv._request_day_history.connect(lambda strategies, category, reload: emitted.append(reload))

    lmv._refresh_day_history()                        # in flight now (reload=False)
    lmv._refresh_day_history_from_store()              # arrives while busy -> coalesced

    assert len(emitted) == 1                           # NOT re-emitted immediately
    assert lmv._day_history_pending is True
    assert lmv._day_history_pending_reload is True      # True "wins" over the first False

    # Simulate the in-flight one landing — the coalesced request must fire.
    lmv._on_day_history_from_store_ready({}, lmv._strategies)

    assert len(emitted) == 2
    assert emitted[1] is True
    assert lmv._day_history_pending is False


def test_pending_request_also_reissued_after_a_failure(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    emitted = []
    lmv._request_day_history.connect(lambda strategies, category, reload: emitted.append(reload))

    lmv._refresh_day_history()
    lmv._refresh_day_history()   # coalesced (reload stays False)

    lmv._on_day_history_from_store_failed("boom", lmv._strategies)

    assert len(emitted) == 2
    assert emitted == [False, False]


# ── _run_strategy_alert_checks: peek, never a blocking load ──────────────

def test_run_strategy_alert_checks_never_calls_load_configs(lmv, monkeypatch):
    from services.strategy_alerts import config_store as alerts_config_store

    called = []
    monkeypatch.setattr(alerts_config_store, "load_configs", lambda: called.append(1) or {})
    alerts_config_store.reload_cache()   # force a cold cache

    lmv._run_strategy_alert_checks([], [], {}, {})

    assert called == []   # peek_configs() used instead — never hits load_configs


def test_run_strategy_alert_checks_returns_quietly_with_cold_cache(lmv):
    from services.strategy_alerts import config_store as alerts_config_store
    alerts_config_store.reload_cache()
    # Must not raise even with an empty active_strategies/all_dicts and a
    # cold (never-loaded) notification-config cache.
    lmv._run_strategy_alert_checks([], [], {}, {})


# ── _LiveDataWorker.refresh_day_history: reload_from_store gate + internal
# notif_configs fetch ─────────────────────────────────────────────────────

def test_worker_refresh_day_history_skips_store_reload_when_false(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import _LiveDataWorker

    called = []
    monkeypatch.setattr(store, "load_all", lambda: called.append(1) or [])

    worker = _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})
    results = []
    worker.day_history_result.connect(lambda dh, strategies: results.append((dh, strategies)))

    # No row filter/AVG_DAYS etc. -> collect_day_requests is empty -> the
    # worker's own "nothing to fetch" fast path fires with no network call
    # at all, letting this test stay offline-safe.
    no_filter_strategy = {"id": "s1", "name": "Plain", "active": True, "row_filter": [], "columns": []}
    worker.refresh_day_history([no_filter_strategy], "All", False)

    assert called == []   # strategy_store never touched
    assert len(results) == 1
    assert results[0][0] == {}


def test_worker_refresh_day_history_reloads_store_when_true(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import _LiveDataWorker

    called = []
    monkeypatch.setattr(store, "load_all", lambda: called.append(1) or [_row_filter_strategy()])

    worker = _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})
    worker.refresh_day_history([_row_filter_strategy()], "All", True)

    assert called == [1]


# ── busy indicator (thin progress bar at the bottom of the window) ───────
# Both background paths now run off the GUI thread (that's the whole
# point) — without some visible cue, a strategy toggle/category change on
# a large sheet would look like nothing is happening for however long the
# worker takes. See LiveViewerWindow._update_busy_indicator.

def test_busy_bar_hidden_by_default(lmv):
    assert lmv._busy_bar.isHidden() is True


def test_busy_bar_shows_while_day_history_refresh_in_flight(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_day_history.connect(lambda *a: None)   # swallow — no real worker

    lmv._refresh_day_history()

    assert lmv._busy_bar.isHidden() is False


def test_busy_bar_hides_once_day_history_refresh_completes(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_day_history.connect(lambda *a: None)
    # _on_day_history_from_store_ready also triggers a recompute — swallow
    # that dispatch too so the recompute side reaches a genuinely idle
    # state once its own completion signal fires below, same as it would
    # for a real worker.
    lmv._request_recompute.connect(lambda *a: None)
    lmv._refresh_day_history()
    assert lmv._busy_bar.isHidden() is False

    lmv._on_day_history_from_store_ready({}, lmv._strategies)
    lmv._on_recompute_ready(lmv._headers, lmv._data)

    assert lmv._busy_bar.isHidden() is True


def test_busy_bar_stays_visible_if_a_request_was_coalesced(lmv):
    """A second request arrived while the first was in flight — the bar
    must stay up until the coalesced (re-issued) one also lands, not drop
    the instant the FIRST one finishes."""
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_day_history.connect(lambda *a: None)
    lmv._request_recompute.connect(lambda *a: None)
    lmv._refresh_day_history()
    lmv._refresh_day_history_from_store()   # coalesced while busy

    lmv._on_day_history_from_store_ready({}, lmv._strategies)   # first one lands
    lmv._on_recompute_ready(lmv._headers, lmv._data)            # its recompute lands too

    # The coalesced day-history request was just re-issued
    # (_run_pending_day_history_refresh) — still busy, not done.
    assert lmv._busy_bar.isHidden() is False

    lmv._on_day_history_from_store_ready({}, lmv._strategies)   # second one lands
    lmv._on_recompute_ready(lmv._headers, lmv._data)
    assert lmv._busy_bar.isHidden() is True


def test_busy_bar_shows_while_recompute_in_flight(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_recompute.connect(lambda *a: None)   # swallow — no real worker

    lmv._recompute_display()

    assert lmv._busy_bar.isHidden() is False


def test_busy_bar_hides_once_recompute_completes(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_recompute.connect(lambda *a: None)
    lmv._recompute_display()
    assert lmv._busy_bar.isHidden() is False

    lmv._on_recompute_ready(lmv._headers, lmv._data)

    assert lmv._busy_bar.isHidden() is True


def test_busy_bar_hides_after_a_recompute_failure_too(lmv):
    lmv.set_strategies([_row_filter_strategy()])
    lmv._request_recompute.connect(lambda *a: None)
    lmv._recompute_display()

    lmv._on_recompute_failed("boom")

    assert lmv._busy_bar.isHidden() is True


def test_worker_refresh_day_history_fetches_notif_configs_itself(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store, config_store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config.json"))
    from screens.live_viewer import _LiveDataWorker
    from services.strategy_alerts import config_store as alerts_config_store

    called = []
    real = alerts_config_store.load_configs
    monkeypatch.setattr(alerts_config_store, "load_configs", lambda: called.append(1) or real())

    worker = _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})
    worker.refresh_day_history([_row_filter_strategy()], "All", False)

    assert called == [1]
