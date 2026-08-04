from services import notification_channels


def test_defaults_when_unsaved():
    enabled = notification_channels.load_enabled_channels()
    assert enabled == {"system": True, "email": True, "telegram": False}
    assert notification_channels.enabled_channel_ids() == {"system", "email"}


def test_save_then_load_roundtrip():
    notification_channels.save_enabled_channels({"system": False, "email": True, "telegram": True})

    reloaded = notification_channels.load_enabled_channels()
    assert reloaded == {"system": False, "email": True, "telegram": True}
    assert notification_channels.enabled_channel_ids() == {"email", "telegram"}


def test_missing_key_falls_back_to_default():
    # Simulates a value saved before "telegram" existed in the schema.
    from services import config_store
    config_store.save_json(notification_channels._CHANNELS_KEY, {"system": False, "email": False})

    reloaded = notification_channels.load_enabled_channels()
    assert reloaded == {"system": False, "email": False, "telegram": False}
