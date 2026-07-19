"""
Persistence for the background scheduler's trigger configuration
(times + per-channel notification checkboxes) and per-trigger last-fired
dates, backed by services.config_store's generic JSON store.
"""

from dataclasses import dataclass
from datetime import time as dtime

from config_defaults import SCHEDULER_TRIGGER_DEFAULTS
from services import config_store

_TRIGGERS_KEY = "scheduler_triggers"
_LAST_FIRED_KEY = "scheduler_last_fired"


@dataclass
class TriggerConfig:
    id: str
    name: str
    subtitle: str
    time: dtime
    system_enabled: bool
    telegram_enabled: bool
    sms_enabled: bool


def load_trigger_configs() -> list:
    saved = config_store.load_json(_TRIGGERS_KEY, {})
    out = []
    for tid, name, subtitle, default_hhmm in SCHEDULER_TRIGGER_DEFAULTS:
        s = saved.get(tid, {})
        hh, mm = s.get("time", default_hhmm).split(":")
        out.append(TriggerConfig(
            id=tid,
            name=name,
            subtitle=subtitle,
            time=dtime(int(hh), int(mm)),
            system_enabled=bool(s.get("system", True)),
            telegram_enabled=bool(s.get("telegram", False)),
            sms_enabled=bool(s.get("sms", False)),
        ))
    return out


def save_trigger_configs(configs: list) -> None:
    config_store.save_json(_TRIGGERS_KEY, {
        c.id: {
            "time": c.time.strftime("%H:%M"),
            "system": c.system_enabled,
            "telegram": c.telegram_enabled,
            "sms": c.sms_enabled,
        }
        for c in configs
    })


def load_last_fired() -> dict:
    """Return {trigger_id: "YYYY-MM-DD"} of the last date each trigger fired."""
    return config_store.load_json(_LAST_FIRED_KEY, {})


def save_last_fired(last_fired: dict) -> None:
    config_store.save_json(_LAST_FIRED_KEY, last_fired)
