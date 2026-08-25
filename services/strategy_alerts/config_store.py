"""
Persistence for per-strategy notification config (see engine.py for how it's
evaluated). Stored as one JSON blob, keyed by strategy id, via the existing
services.config_store — backend-synced for free through the generic per-user
settings endpoint, the same mechanism services/trigger_config.py and
strategy_store.py's custom categories already use.

Deliberately separate from strategies.json / SavedStrategy: a notification
config never needs to be queried at the SQL level any more than a strategy's
own columns/row_filter do, and keeping it out of the strategies sync pipeline
means this feature never has to touch strategy_store.py's schema or the
backend's SavedStrategy model.
"""

from services import config_store

_CONFIGS_KEY = "strategy_notification_configs"

# In-memory cache: services/strategy_alerts/engine.py's evaluate_tick runs
# from the Live Master View's render loop (every ~200ms-1s), so load_configs()
# must not hit config_store.load_json's server round trip on every call —
# only lazily once, refreshed by save_config/delete_config (which already
# have the fresh data in hand) or reload_cache() (called on login/logout,
# see app_window.py's reload_per_user_data).
_cache: dict | None = None


def _ensure_cache_loaded() -> None:
    global _cache
    if _cache is None:
        loaded = config_store.load_json(_CONFIGS_KEY, {})
        _cache = dict(loaded) if isinstance(loaded, dict) else {}


def load_configs() -> dict:
    """Return {strategy_id: config_dict} for every strategy that has a
    notification config (enabled or not — disabled configs are kept so a
    user's setup survives toggling Enabled off and back on)."""
    _ensure_cache_loaded()
    return dict(_cache)


def peek_configs() -> dict:
    """Like load_configs(), but NEVER touches the network — {} if the cache
    hasn't been warmed yet (right after reload_cache(), before anything else
    has called load_configs()), the cached dict otherwise. For a caller on
    the GUI thread with no business blocking on a server round trip — see
    screens.live_viewer.LiveViewerWindow._run_strategy_alert_checks, called
    from every render pass (every live tick): before this existed it called
    load_configs() directly, which was safe on the (documented) assumption
    that the cache was already warm by the time any tick fires, but nothing
    actually guaranteed that — a strategy toggle/category change or the
    window's own initial render could be the very first load_configs() call
    after a reload_cache() (e.g. right after login), synchronously blocking
    the GUI thread on a live network fetch. Worst case here is just one
    render pass with no live-alert coverage while the cache is still cold
    (something else — e.g. that same window's own day-history refresh —
    warms it moments later off the GUI thread), not a frozen window."""
    return dict(_cache) if _cache is not None else {}


def load_config(strategy_id: str) -> dict | None:
    return load_configs().get(strategy_id)


def save_config(strategy_id: str, config: dict) -> None:
    _ensure_cache_loaded()
    _cache[strategy_id] = config
    config_store.save_json(_CONFIGS_KEY, _cache)


def delete_config(strategy_id: str) -> None:
    """No-op if *strategy_id* has no notification config — mirrors
    strategy_store.delete_strategy's own idempotent style."""
    _ensure_cache_loaded()
    if strategy_id in _cache:
        del _cache[strategy_id]
        config_store.save_json(_CONFIGS_KEY, _cache)


def reload_cache() -> None:
    """Drop the in-memory cache so the next load_configs() call re-fetches
    from the server — call on login/logout so a second user on the same
    running app instance doesn't see the first user's cached configs."""
    global _cache
    _cache = None
