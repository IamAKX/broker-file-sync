from datetime import time as dtime

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    return config_store


def test_load_defaults_when_unsaved(store):
    from services import trigger_config
    configs = trigger_config.load_trigger_configs()
    assert [c.id for c in configs] == ["availability_check", "lmv_check", "historic_save"]
    for c in configs:
        assert c.system_enabled is True
        assert c.telegram_enabled is False
        assert c.sms_enabled is False


def test_save_then_load_roundtrip(store):
    from services import trigger_config
    configs = trigger_config.load_trigger_configs()
    configs[0].time = dtime(9, 15)
    configs[0].telegram_enabled = True
    trigger_config.save_trigger_configs(configs)

    reloaded = trigger_config.load_trigger_configs()
    assert reloaded[0].time == dtime(9, 15)
    assert reloaded[0].telegram_enabled is True
    # Untouched triggers keep their defaults
    assert reloaded[1].system_enabled is True
    assert reloaded[1].telegram_enabled is False


def test_last_fired_roundtrip(store):
    from services import trigger_config
    assert trigger_config.load_last_fired() == {}
    trigger_config.save_last_fired({"historic_save": "2026-07-19"})
    assert trigger_config.load_last_fired() == {"historic_save": "2026-07-19"}
