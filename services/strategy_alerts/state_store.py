"""
Local-only persistence for strategy-notification runtime state: pending/open
signals (updated every Live Master View tick — running high/low, trailing
exit) and resolved alert history. Deliberately bypasses
services/config_store.py's backend sync (unlike the notification CONFIG in
this package's config_store.py) — routing a per-tick running-high/low update
through the generic /settings/{key} endpoint would mean a network round trip
every poll cycle, which that store was never designed for.

Namespaced per logged-in user (by email, via api.token_store.token_manager)
so two users on the same machine don't leak open signals into each other —
mirrors why config_store-backed data needs app_window.py's
reload_per_user_data, except here there's no server copy to reload from, so
reset_for_user_switch() just drops the in-memory state and lets the next
access lazily reload whichever user's file is now current.

Writes are write-through for state *transitions* (a new pending signal, an
entry, a target hit, a resolve) but merely marked dirty for passive
running-high/low updates on every tick — callers doing per-tick updates
should call flush() periodically (see screens/live_viewer.py's wiring) rather
than relying on a transition to happen to save it.

Also tracks a small "cooldown" set — (strategy_id, symbol) keys that just
resolved and are waiting to see their trigger condition go false at least
once before a new signal can start (see engine.py's _evaluate_strategy).
Without it, a signal resolving while its trigger is STILL true (the common
case) would immediately re-arm into a brand new pending→open→resolved cycle
on the very next tick, for what is really one continuous price move.
"""

import json
import os
import re

_STORE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
_MAX_HISTORY = 500


def _slug(email: str | None) -> str:
    if not email:
        return "_default"
    slug = re.sub(r"[^a-z0-9]+", "_", email.strip().lower()).strip("_")
    return slug or "_default"


def _file_path() -> str:
    from api.token_store import token_manager

    return os.path.join(_STORE_DIR, f"strategy_alert_state_{_slug(token_manager.get_user_email())}.json")


def signal_key(strategy_id: str, symbol: str) -> str:
    return f"{strategy_id}::{str(symbol).strip().upper()}"


class _Store:
    def __init__(self):
        self._loaded_for: str | None = None
        self._open_signals: dict = {}
        self._alert_history: list = []
        # (strategy_id, symbol) keys that just resolved (target achieved or
        # stopped out) and are waiting to see their trigger condition go
        # false at least once before a new signal is allowed to start — see
        # engine.py's _evaluate_strategy. Without this, a signal that
        # resolves while its trigger is STILL true (the common case — e.g.
        # price is still above the breakout level that got you in) would
        # immediately start a brand new pending→open→resolved cycle on the
        # very next tick, for what is really the same one continuous move.
        self._cooldown: set = set()
        self._dirty = False

    def _ensure_loaded(self) -> None:
        path = _file_path()
        if self._loaded_for == path:
            return
        self._flush_if_dirty()
        self._open_signals = {}
        self._alert_history = []
        self._cooldown = set()
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict):
                    self._open_signals = data.get("open_signals") or {}
                    self._alert_history = data.get("alert_history") or []
                    self._cooldown = set(data.get("cooldown") or [])
            except Exception:
                pass
        self._loaded_for = path

    def _flush_if_dirty(self) -> None:
        if not self._dirty or self._loaded_for is None:
            return
        try:
            with open(self._loaded_for, "w", encoding="utf-8") as f:
                json.dump(
                    {
                        "open_signals": self._open_signals,
                        "alert_history": self._alert_history,
                        "cooldown": sorted(self._cooldown),
                    },
                    f, indent=2, ensure_ascii=False,
                )
        except OSError:
            pass
        self._dirty = False

    def get_open_signals(self) -> dict:
        self._ensure_loaded()
        return self._open_signals

    def get_alert_history(self) -> list:
        self._ensure_loaded()
        return self._alert_history

    def set_open_signal(self, key: str, signal: dict, force_flush: bool = False) -> None:
        self._ensure_loaded()
        self._open_signals[key] = signal
        self._dirty = True
        if force_flush:
            self._flush_if_dirty()

    def clear_open_signal(self, key: str, force_flush: bool = True) -> None:
        self._ensure_loaded()
        if self._open_signals.pop(key, None) is not None:
            self._dirty = True
        if force_flush:
            self._flush_if_dirty()

    def append_alert_history(self, record: dict) -> None:
        self._ensure_loaded()
        self._alert_history.append(record)
        if len(self._alert_history) > _MAX_HISTORY:
            self._alert_history = self._alert_history[-_MAX_HISTORY:]
        self._dirty = True
        self._flush_if_dirty()

    def is_cooling_down(self, key: str) -> bool:
        self._ensure_loaded()
        return key in self._cooldown

    def set_cooldown(self, key: str) -> None:
        self._ensure_loaded()
        if key not in self._cooldown:
            self._cooldown.add(key)
            self._dirty = True

    def clear_cooldown(self, key: str) -> None:
        self._ensure_loaded()
        if key in self._cooldown:
            self._cooldown.discard(key)
            self._dirty = True

    def clear_all(self) -> None:
        self._ensure_loaded()
        self._open_signals = {}
        self._alert_history = []
        self._cooldown = set()
        self._dirty = True
        self._flush_if_dirty()

    def clear_strategy(self, strategy_id: str) -> None:
        """Drop every pending/open signal for *strategy_id* — called when a
        strategy is deleted, so it isn't tracked anymore. Alert history is
        left untouched: it's a record of what already happened, not a live
        subscription, so deleting the strategy shouldn't erase it."""
        self._ensure_loaded()
        prefix = f"{strategy_id}::"
        remaining = {k: v for k, v in self._open_signals.items() if not k.startswith(prefix)}
        remaining_cooldown = {k for k in self._cooldown if not k.startswith(prefix)}
        if len(remaining) != len(self._open_signals) or len(remaining_cooldown) != len(self._cooldown):
            self._open_signals = remaining
            self._cooldown = remaining_cooldown
            self._dirty = True
            self._flush_if_dirty()

    def flush(self) -> None:
        self._flush_if_dirty()

    def reset_for_user_switch(self) -> None:
        self._flush_if_dirty()
        self._loaded_for = None


_store = _Store()


def get_open_signals() -> dict:
    return _store.get_open_signals()


def get_alert_history() -> list:
    return _store.get_alert_history()


def set_open_signal(key: str, signal: dict, force_flush: bool = False) -> None:
    _store.set_open_signal(key, signal, force_flush)


def clear_open_signal(key: str, force_flush: bool = True) -> None:
    _store.clear_open_signal(key, force_flush)


def append_alert_history(record: dict) -> None:
    _store.append_alert_history(record)


def is_cooling_down(key: str) -> bool:
    return _store.is_cooling_down(key)


def set_cooldown(key: str) -> None:
    _store.set_cooldown(key)


def clear_cooldown(key: str) -> None:
    _store.clear_cooldown(key)


def clear_all() -> None:
    _store.clear_all()


def clear_strategy(strategy_id: str) -> None:
    _store.clear_strategy(strategy_id)


def flush() -> None:
    _store.flush()


def reset_for_user_switch() -> None:
    _store.reset_for_user_switch()
