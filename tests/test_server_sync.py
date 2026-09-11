"""
Tests for the actual server-sync behavior added to config_store.py,
strategy_store.py, and formula_variable_store.py — the conftest.py autouse
fixture already stubs the API layer to simulate "a reachable server with
nothing saved yet" for every other test in the suite (so they keep exercising
local-cache round-tripping exactly as before); these tests override those
stubs per-test to exercise the three states that fixture doesn't cover:
server already has data, offline (NetworkError), and a failed write.
"""
from api.exceptions import ApiError, NetworkError


# ── config_store.load_json / save_json ──────────────────────────────────────

def test_load_json_uses_and_caches_server_value(monkeypatch):
    from services import config_store
    from api import settings_api

    monkeypatch.setattr(settings_api, "get_setting", lambda key: {"key": key, "value": {"rows": [1, 2]}})

    result = config_store.load_json("some_key", "default")
    assert result == {"rows": [1, 2]}
    # cached locally too
    assert config_store._load_raw()["some_key"] == {"rows": [1, 2]}


def test_load_json_migrates_local_only_data_up_once(monkeypatch):
    from services import config_store
    from api import settings_api

    # Seed a local-only value, as if this install predates server sync.
    config_store._save_raw({"legacy_key": ["a", "b"]})

    pushed = []
    monkeypatch.setattr(settings_api, "get_setting", lambda key: {"key": key, "value": None})
    monkeypatch.setattr(settings_api, "put_setting", lambda key, value: pushed.append((key, value)))

    result = config_store.load_json("legacy_key", [])
    assert result == ["a", "b"]
    assert pushed == [("legacy_key", ["a", "b"])]


def test_load_json_falls_back_to_cache_when_offline(monkeypatch):
    from services import config_store
    from api import settings_api

    config_store._save_raw({"cached_key": "cached_value"})

    def _raise(key):
        raise NetworkError("offline")

    monkeypatch.setattr(settings_api, "get_setting", _raise)

    assert config_store.load_json("cached_key", "default") == "cached_value"
    assert config_store.load_json("never_cached_key", "default") == "default"


def test_save_json_raises_when_server_write_fails(monkeypatch):
    from services import config_store
    from api import settings_api

    def _raise(key, value):
        raise ApiError("boom", "unknown_error", 500)

    monkeypatch.setattr(settings_api, "put_setting", _raise)

    import pytest
    with pytest.raises(ApiError):
        config_store.save_json("some_key", "value")
    # Not silently cached locally either, since the server write failed.
    assert "some_key" not in config_store._load_raw()


# ── strategy_store.load_all / save_strategy / delete_strategy ──────────────

def test_strategy_load_all_uses_server_data(monkeypatch):
    from services import strategy_store as store
    from api import strategies_api

    server_strategy = {
        "id": "s1", "name": "From Server", "active": True,
        "category": "Daily", "columns": [], "row_filter": [],
    }
    monkeypatch.setattr(strategies_api, "list_strategies", lambda: {"strategies": [server_strategy]})

    result = store.load_all()
    assert result == [server_strategy]
    assert store._load_raw() == [server_strategy]


def test_strategy_load_all_migrates_local_only_strategies(monkeypatch):
    from services import strategy_store as store
    from api import strategies_api

    local_strategy = store.new_strategy("Local Only")
    store._save_raw([local_strategy])

    monkeypatch.setattr(strategies_api, "list_strategies", lambda: {"strategies": []})
    pushed = []
    monkeypatch.setattr(strategies_api, "import_strategies", lambda strategies: pushed.append(strategies) or {"overwritten": 0, "added": 1})

    result = store.load_all()
    assert result[0]["name"] == "Local Only"
    assert pushed == [[local_strategy]]


def test_strategy_load_all_falls_back_offline(monkeypatch):
    from services import strategy_store as store
    from api import strategies_api

    local_strategy = store.new_strategy("Cached")
    store._save_raw([local_strategy])

    def _raise():
        raise NetworkError("offline")

    monkeypatch.setattr(strategies_api, "list_strategies", _raise)

    result = store.load_all()
    assert result[0]["name"] == "Cached"


def test_save_strategy_raises_when_server_write_fails(monkeypatch):
    from services import strategy_store as store
    from api import strategies_api

    def _raise(*a, **kw):
        raise ApiError("boom", "unknown_error", 500)

    monkeypatch.setattr(strategies_api, "upsert_strategy", _raise)

    import pytest
    s = store.new_strategy("Will Fail")
    with pytest.raises(ApiError):
        store.save_strategy(s)
    assert store._load_raw() == []   # not saved locally either


def test_delete_strategy_raises_when_server_delete_fails(monkeypatch):
    from services import strategy_store as store
    from api import strategies_api

    s = store.new_strategy("Keep Me")
    store._save_raw([s])

    def _raise(strategy_id):
        raise NetworkError("offline")

    monkeypatch.setattr(strategies_api, "delete_strategy", _raise)

    import pytest
    with pytest.raises(NetworkError):
        store.delete_strategy(s["id"])
    assert store._load_raw() == [s]   # untouched — delete never applied locally


def test_import_all_raises_when_server_import_fails(monkeypatch):
    from services import strategy_store as store
    from api import strategies_api

    def _raise(strategies):
        raise NetworkError("offline")

    monkeypatch.setattr(strategies_api, "import_strategies", _raise)

    import pytest
    with pytest.raises(NetworkError):
        store.import_all([store.new_strategy("X")])
    assert store._load_raw() == []   # local merge never applied either


# ── formula_variable_store.load_all / save_variable / delete_variable ──────

def test_formula_variable_load_all_uses_server_data(monkeypatch):
    from services import formula_variable_store as store
    from api import formula_variables_api

    server_var = {"id": "v1", "name": "FromServer", "formula": []}
    monkeypatch.setattr(formula_variables_api, "list_variables", lambda: {"variables": [server_var]})

    assert store.load_all() == [server_var]
    assert store._load_raw() == [server_var]


def test_formula_variable_save_raises_when_server_write_fails(monkeypatch):
    from services import formula_variable_store as store
    from api import formula_variables_api

    def _raise(*a, **kw):
        raise ApiError("boom", "unknown_error", 500)

    monkeypatch.setattr(formula_variables_api, "upsert_variable", _raise)

    import pytest
    v = store.new_variable("Will Fail")
    with pytest.raises(ApiError):
        store.save_variable(v)


def test_formula_variable_import_all_merges_by_name_via_bulk_endpoint(monkeypatch):
    """import_all must go through the dedicated bulk endpoint, not a
    per-item save_variable loop — see the function's own docstring for why
    (an imported variable sharing an existing one's NAME but not its id
    would otherwise create a duplicate row server-side)."""
    from services import formula_variable_store as store
    from api import formula_variables_api

    existing = store.new_variable("Threshold")
    store._save_raw([existing])

    captured = {}

    def _fake_import(variables):
        captured["variables"] = variables
        return {"overwritten": 1, "added": 0}

    monkeypatch.setattr(formula_variables_api, "import_variables", _fake_import)

    imported = {"id": "brand-new-id", "name": "Threshold", "formula": [{"type": "num", "value": "2"}]}
    overwritten, added = store.import_all([imported])

    assert (overwritten, added) == (1, 0)
    assert captured["variables"] == [imported]
    # Local cache reflects the merge-by-name (imported data replaces the
    # old row entirely, same convention as strategy_store.import_all).
    assert store._load_raw() == [imported]


def test_formula_variable_import_all_raises_when_server_import_fails(monkeypatch):
    from services import formula_variable_store as store
    from api import formula_variables_api

    def _raise(variables):
        raise NetworkError("offline")

    monkeypatch.setattr(formula_variables_api, "import_variables", _raise)

    import pytest
    with pytest.raises(NetworkError):
        store.import_all([store.new_variable("X")])
    assert store._load_raw() == []


# ── inception_strategy_store.import_all / inception_formula_variable_ ──────
# store.import_all — same bulk-endpoint-not-a-loop shape as the LMV stores
# above, added for the combined Export/Import All Data feature (Inception
# previously had no bulk import for either).

def test_inception_strategy_import_all_merges_by_name_via_bulk_endpoint(monkeypatch):
    from services import inception_strategy_store as store
    from api import inception_api

    existing = store.new_strategy("52WH")
    store._save_raw([existing])

    captured = {}

    def _fake_import(strategies):
        captured["strategies"] = strategies
        return {"overwritten": 1, "added": 0}

    monkeypatch.setattr(inception_api, "import_strategies", _fake_import)

    imported = {"id": "brand-new-id", "name": "52WH", "active": True, "category": "Daily",
                "columns": [{"name": "c1"}], "row_filter": []}
    overwritten, added = store.import_all([imported])

    assert (overwritten, added) == (1, 0)
    assert captured["strategies"] == [imported]
    assert store._load_raw() == [imported]


def test_inception_strategy_import_all_raises_when_server_import_fails(monkeypatch):
    from services import inception_strategy_store as store
    from api import inception_api

    def _raise(strategies):
        raise NetworkError("offline")

    monkeypatch.setattr(inception_api, "import_strategies", _raise)

    import pytest
    with pytest.raises(NetworkError):
        store.import_all([store.new_strategy("X")])
    assert store._load_raw() == []


def test_inception_formula_variable_import_all_merges_by_name_via_bulk_endpoint(monkeypatch):
    from services import inception_formula_variable_store as store
    from api import inception_api

    existing = store.new_variable("Threshold")
    store._save_raw([existing])

    captured = {}

    def _fake_import(variables):
        captured["variables"] = variables
        return {"overwritten": 1, "added": 0}

    monkeypatch.setattr(inception_api, "import_variables", _fake_import)

    imported = {"id": "brand-new-id", "name": "Threshold", "formula": [{"type": "num", "value": "2"}]}
    overwritten, added = store.import_all([imported])

    assert (overwritten, added) == (1, 0)
    assert captured["variables"] == [imported]
    assert store._load_raw() == [imported]


# ── config_store.export_all_settings / import_all_settings ─────────────────

def test_export_all_settings_reads_from_the_server_not_the_local_cache(monkeypatch):
    """Must NOT just return _load_raw()'s local dict — that only ever
    holds whatever keys a screen has actually load_json()'d this session,
    not "every setting this user has" (see the function's own docstring)."""
    from services import config_store
    from api import settings_api

    config_store._save_raw({"stale_local_only_key": "should not appear"})
    monkeypatch.setattr(
        settings_api, "list_settings",
        lambda: {"settings": [{"key": "theme", "value": "dark"}, {"key": "main_column_order", "value": ["A", "B"]}]},
    )

    result = config_store.export_all_settings()

    assert result == {"theme": "dark", "main_column_order": ["A", "B"]}


def test_import_all_settings_pushes_every_key_to_the_server(monkeypatch):
    from services import config_store
    from api import settings_api

    pushed = {}

    def _fake_put(key, value):
        pushed[key] = value
        return {"key": key, "value": value}

    monkeypatch.setattr(settings_api, "put_setting", _fake_put)

    count = config_store.import_all_settings({"theme": "dark", "main_column_order": ["A", "B"]})

    assert count == 2
    assert pushed == {"theme": "dark", "main_column_order": ["A", "B"]}


def test_import_all_settings_raises_on_first_failed_key(monkeypatch):
    from services import config_store
    from api import settings_api

    def _raise(key, value):
        raise NetworkError("offline")

    monkeypatch.setattr(settings_api, "put_setting", _raise)

    import pytest
    with pytest.raises(NetworkError):
        config_store.import_all_settings({"theme": "dark"})


# ── theme: local-only at boot, best-effort push on toggle, explicit sync ───

def test_load_theme_never_touches_the_network(monkeypatch):
    """ThemeManager.__init__ runs before login (no token yet) — load_theme
    must stay local-only or every app boot would make a doomed, unauthenticated
    API call. Fails the test if get_theme is called at all."""
    from services import config_store
    from api import auth_api

    def _fail_if_called():
        raise AssertionError("load_theme must not call the server")

    monkeypatch.setattr(auth_api, "get_theme", _fail_if_called)

    config_store._save_raw({"theme": "dark"})
    assert config_store.load_theme() == "dark"
    assert config_store.load_theme(default="light") == "dark"


def test_save_theme_swallows_network_failure(monkeypatch):
    """Unlike strategies/settings, a failed theme push must not raise —
    see save_theme's docstring for why this one specific write is best-effort."""
    from services import config_store
    from api import auth_api

    def _raise(theme):
        raise NetworkError("offline")

    monkeypatch.setattr(auth_api, "update_theme", _raise)

    config_store.save_theme("dark")   # must not raise
    assert config_store._load_raw()["theme"] == "dark"   # still cached locally


def test_sync_theme_from_server_updates_cache_and_returns_mode(monkeypatch):
    from services import config_store
    from api import auth_api

    monkeypatch.setattr(auth_api, "get_theme", lambda: {"theme": "dark"})
    result = config_store.sync_theme_from_server()
    assert result == "dark"
    assert config_store._load_raw()["theme"] == "dark"


def test_sync_theme_from_server_returns_none_when_offline(monkeypatch):
    from services import config_store
    from api import auth_api

    def _raise():
        raise NetworkError("offline")

    monkeypatch.setattr(auth_api, "get_theme", _raise)
    assert config_store.sync_theme_from_server() is None


def test_theme_manager_sync_from_server_reapplies_on_change(monkeypatch):
    from theme import ThemeManager
    from services import config_store

    class _FakeApp:
        def setStyleSheet(self, *a, **kw):
            pass

        def setPalette(self, *a, **kw):
            pass

    config_store._save_raw({"theme": "light"})
    tm = ThemeManager(_FakeApp())
    assert tm.current_mode == "light"

    monkeypatch.setattr(config_store, "sync_theme_from_server", lambda: "dark")
    changed = tm.sync_from_server()
    assert changed is True
    assert tm.current_mode == "dark"


def test_theme_manager_sync_from_server_noop_when_unchanged(monkeypatch):
    from theme import ThemeManager
    from services import config_store

    class _FakeApp:
        def setStyleSheet(self, *a, **kw):
            pass

        def setPalette(self, *a, **kw):
            pass

    config_store._save_raw({"theme": "light"})
    tm = ThemeManager(_FakeApp())

    monkeypatch.setattr(config_store, "sync_theme_from_server", lambda: "light")
    assert tm.sync_from_server() is False
    assert tm.current_mode == "light"
