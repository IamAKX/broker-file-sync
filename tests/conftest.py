import pytest


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
