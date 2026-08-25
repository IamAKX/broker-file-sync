from services.strategy_alerts import config_store as alerts_config_store
from services.strategy_alerts.models import new_metric, new_notification_config


def test_load_configs_empty_by_default():
    assert alerts_config_store.load_configs() == {}
    assert alerts_config_store.load_config("missing") is None


def test_save_then_load_roundtrip():
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["metrics"].append(new_metric("Stop Loss", "stop_loss", [{"type": "col", "value": "Open"}]))

    alerts_config_store.save_config("strat-1", cfg)

    reloaded = alerts_config_store.load_config("strat-1")
    assert reloaded["enabled"] is True
    assert reloaded["metrics"][0]["name"] == "Stop Loss"
    assert reloaded["metrics"][0]["role"] == "stop_loss"


def test_multiple_configs_keyed_independently():
    alerts_config_store.save_config("strat-1", new_notification_config())
    alerts_config_store.save_config("strat-2", new_notification_config())

    configs = alerts_config_store.load_configs()
    assert set(configs.keys()) == {"strat-1", "strat-2"}


def test_delete_config():
    alerts_config_store.save_config("strat-1", new_notification_config())
    alerts_config_store.delete_config("strat-1")
    assert alerts_config_store.load_config("strat-1") is None


def test_delete_missing_config_is_noop():
    alerts_config_store.delete_config("does-not-exist")
    assert alerts_config_store.load_configs() == {}


def test_load_configs_only_hits_backend_once_then_uses_cache(monkeypatch):
    from api import settings_api

    calls = []
    real_get = settings_api.get_setting

    def _counting_get(key):
        calls.append(key)
        return real_get(key)

    monkeypatch.setattr(settings_api, "get_setting", _counting_get)

    alerts_config_store.load_configs()
    alerts_config_store.load_configs()
    alerts_config_store.load_configs()

    assert len(calls) == 1  # not one network round trip per call


def test_reload_cache_forces_a_fresh_fetch(monkeypatch):
    from api import settings_api

    calls = []
    real_get = settings_api.get_setting

    def _counting_get(key):
        calls.append(key)
        return real_get(key)

    monkeypatch.setattr(settings_api, "get_setting", _counting_get)

    alerts_config_store.load_configs()
    alerts_config_store.reload_cache()
    alerts_config_store.load_configs()

    assert len(calls) == 2


def test_peek_configs_returns_empty_without_touching_network_when_cold(monkeypatch):
    from api import settings_api

    calls = []
    monkeypatch.setattr(settings_api, "get_setting", lambda key: calls.append(key) or {})
    alerts_config_store.reload_cache()   # force cold state

    assert alerts_config_store.peek_configs() == {}
    assert calls == []   # never hit the network


def test_peek_configs_returns_cache_once_warm(monkeypatch):
    alerts_config_store.save_config("strat-1", new_notification_config())   # warms the cache

    from api import settings_api
    calls = []
    monkeypatch.setattr(settings_api, "get_setting", lambda key: calls.append(key) or {})

    assert set(alerts_config_store.peek_configs().keys()) == {"strat-1"}
    assert calls == []   # already warm — still no network hit


def test_save_config_updates_cache_without_extra_fetch(monkeypatch):
    from api import settings_api

    calls = []
    real_get = settings_api.get_setting
    monkeypatch.setattr(settings_api, "get_setting", lambda key: calls.append(key) or real_get(key))

    alerts_config_store.load_configs()  # warms the cache (1 fetch)
    alerts_config_store.save_config("strat-1", new_notification_config())
    assert alerts_config_store.load_config("strat-1") is not None
    assert len(calls) == 1  # save + subsequent load_config didn't re-fetch
