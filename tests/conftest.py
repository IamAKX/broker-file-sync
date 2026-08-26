import gc

import pytest


def pytest_configure(config):
    """Disable Python's cyclic garbage collector for the whole test session.

    A full `pytest tests/` run accumulates a large live graph of PySide6
    QWidget-derived objects (every screen/dialog/popup any test ever
    constructed, plus their QThread children — several of these screens
    launch a background QThread worker and keep it as a permanent child
    even after the load it did is done, e.g. screens.inception_hmv/
    inception_view_by_date's own workers). With gc enabled, Python's cyclic
    collector can trigger at essentially any bytecode boundary — including
    from inside a QThread's own run() method, mid-computation on a
    worker thread. If that collection pass finalizes a Qt widget object
    (as opposed to a plain Python one), Qt aborts/segfaults: widgets may
    only ever be destroyed on the GUI/main thread. Confirmed via
    `python -m pytest tests/ -v`: a Fatal Python error: Segmentation fault,
    with `gc_collect_main` on the crashing thread's own C stack, nested
    inside `QThreadWrapper::run`, deleting a QCalendarWidget/QTabWidget/
    QStackedWidget subtree — every single time, always shortly after a test
    that runs two Loads/Views on the same screen instance (twice as many
    live QThread children on that one screen to eventually collect).
    Reference counting alone (never disabled) still frees the vast
    majority of objects immediately as each test's local variables go out
    of scope; disabling only the cyclic collector means genuine reference
    cycles pile up uncollected for the rest of the session instead of
    being swept at an unpredictable, possibly-unsafe moment — an
    acceptable trade for a process that exits shortly after the suite
    finishes anyway. Not narrowed to a subset of tests: this fixes a
    property of the WHOLE session's accumulated object graph, and the
    thread-timing bug it's dodging is exactly as invisible in a small
    per-file run as it is common in the full-suite one.
    """
    gc.disable()


@pytest.fixture(autouse=True)
def _isolate_disk_stores(tmp_path, monkeypatch):
    """Redirect every JSON-backed store to a per-test tmp path, and stub out
    the backend calls those stores now make (see services/config_store.py,
    strategy_store.py, formula_variable_store.py — each syncs through the
    backend, with the local JSON file surviving as a read cache).

    Without the tmp-path redirect, a test that doesn't remember to patch
    these itself can read/write the real config_data.json / strategies.json
    at the repo root — which has actually happened (a header-reorder code
    path wrote a stray "main_column_order" entry into a real, in-use config
    file during a full-suite run). Applying it globally means no individual
    test can forget it.

    Without the API stubs, any test that touches these stores would make a
    REAL network call to the live backend. The stubs simulate "a reachable
    server with nothing saved yet" rather than "offline" (NetworkError) —
    every load function already prefers already-written local data over an
    empty server response (that's the one-time-migration path), so a save
    followed by a load within the same test still round-trips correctly
    through the local tmp-path cache, exactly as it did before server sync
    existed. Tests that specifically want to exercise real offline/error
    handling override these within their own test function.
    """
    from services import config_store, strategy_store, formula_variable_store
    from services.strategy_alerts import config_store as alerts_config_store
    from services.strategy_alerts import state_store as alerts_state_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    monkeypatch.setattr(strategy_store, "_STORE_FILE", str(tmp_path / "strategies.json"))
    monkeypatch.setattr(formula_variable_store, "_STORE_FILE", str(tmp_path / "formula_variables.json"))
    monkeypatch.setattr(alerts_state_store, "_STORE_DIR", str(tmp_path))
    alerts_state_store.reset_for_user_switch()
    alerts_config_store.reload_cache()

    from api import auth_api, formula_variables_api, settings_api, strategies_api, strategy_signals_api

    monkeypatch.setattr(settings_api, "get_setting", lambda key: {"key": key, "value": None})
    monkeypatch.setattr(settings_api, "put_setting", lambda key, value: {"key": key, "value": value})

    monkeypatch.setattr(strategies_api, "list_strategies", lambda: {"strategies": []})
    monkeypatch.setattr(
        strategies_api, "upsert_strategy",
        lambda strategy_id, name, active, category, columns, row_filter: {
            "id": strategy_id, "name": name, "active": active,
            "category": category, "columns": columns, "row_filter": row_filter,
        },
    )
    monkeypatch.setattr(strategies_api, "delete_strategy", lambda strategy_id: None)
    monkeypatch.setattr(
        strategies_api, "import_strategies",
        lambda strategies: {"overwritten": 0, "added": len(strategies)},
    )

    monkeypatch.setattr(formula_variables_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(
        formula_variables_api, "upsert_variable",
        lambda variable_id, name, formula: {"id": variable_id, "name": name, "formula": formula},
    )
    monkeypatch.setattr(formula_variables_api, "delete_variable", lambda variable_id: None)

    monkeypatch.setattr(auth_api, "get_theme", lambda: {"theme": "light"})
    monkeypatch.setattr(auth_api, "update_theme", lambda theme: {"theme": theme})

    # services/strategy_alerts/backend_sync.py fires a real HTTP call
    # (dispatched to a background thread, so it wouldn't block a test either
    # way, but a live_viewer test that produces an entry/target/stop-out
    # event would otherwise make a genuine network attempt from every test
    # run — see this fixture's own docstring for why that's unacceptable).
    monkeypatch.setattr(
        strategy_signals_api, "upsert_signal",
        lambda signal_id, payload: {"id": signal_id, **payload},
    )
    monkeypatch.setattr(
        strategy_signals_api, "list_signals",
        lambda **kwargs: {"items": [], "total": 0, "page": kwargs.get("page", 1),
                          "page_size": kwargs.get("page_size", 25), "total_pages": 0},
    )
    monkeypatch.setattr(strategy_signals_api, "clear_signals", lambda: None)
