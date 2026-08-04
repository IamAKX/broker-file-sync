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
