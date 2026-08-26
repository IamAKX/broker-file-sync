"""
Persistence for Config Editor tab data — and the client's per-user settings
cache generally. load_json()/save_json() are server-backed (see
api/settings_api.py, backed by the backend's UserSetting table: one row per
(user, key)); config_data.json survives as a local read cache so the app
still has last-known data when offline. Every other function below (tabs,
column order, LMV highlight colors) is a thin wrapper over load_json/
save_json, so those two are the only functions that had to learn about the
server — see their docstrings for the offline-fallback and one-time-
migration behavior.

Theme is the one key handled separately (see load_theme/save_theme/
sync_theme_from_server) — it's synced via the dedicated /auth/me/theme
endpoint (a column on the central User row), not this generic per-tenant
settings store, since it's an identity-level preference with no tenant
dependency.

Tab keys (stable identifiers, independent of UI labels):
  "sector_stock"                 — (Sector, Stock)
  "script_name"                  — (Stock, Initial)
  "main_column_name"             — (Actual, Renamed)
  "main_column_order"            — flat list of column names (LMV) — see
                                    save_column_order/load_column_order
  "inception_hmv_column_order"   — same shape, shared by Inception HMV and
                                    View by Date (name kept from when it was
                                    HMV-only — see screens.inception_hmv/
                                    inception_view_by_date's own docstrings)
  "inception_highlight_color"/
  "inception_column_highlight_colors" — same shape/idea as the lmv_* pair
                                    below, shared by Inception HMV and View
                                    by Date (see services.
                                    inception_change_highlight)
  "theme"                        — "dark" | "light" (local-cache key only — see above)
"""

import json
import os

_STORE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "config_data.json")

MAIN_COLUMN_NAME  = "main_column_name"
MAIN_COLUMN_ORDER = "main_column_order"
INCEPTION_HMV_COLUMN_ORDER = "inception_hmv_column_order"
THEME             = "theme"
LMV_HIGHLIGHT_COLOR = "lmv_highlight_color"
LMV_COLUMN_HIGHLIGHT_COLORS = "lmv_column_highlight_colors"
INCEPTION_HIGHLIGHT_COLOR = "inception_highlight_color"
INCEPTION_COLUMN_HIGHLIGHT_COLORS = "inception_column_highlight_colors"


def _load_raw() -> dict:
    if not os.path.exists(_STORE_FILE):
        return {}
    try:
        with open(_STORE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_raw(data: dict):
    with open(_STORE_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def clear_local_cache() -> None:
    """Deletes config_data.json, the local read-cache behind every
    save_json/load_json key here (Formula Builder formulas, Config Editor
    tabs, LMV highlight colors, theme, ...) — used by File > Clear Cache
    (see app_window.py._clear_cache). Safe to call any time: load_json()
    always tries the server first regardless of whether this file exists,
    so removing it only matters for whatever a stale/corrupted local copy
    would otherwise serve the next time the app is offline. A no-op if the
    file isn't there.
    """
    if os.path.exists(_STORE_FILE):
        os.remove(_STORE_FILE)


def save_json(key: str, value) -> None:
    """Persist any JSON-serializable value under *key*. The server is the
    source of truth; config_data.json is only a local read cache, updated
    here on every successful server write so the next load_json() call has
    something to fall back to if offline. A failed server write propagates
    to the caller (ApiError/NetworkError) rather than silently degrading to
    a local-only save — losing sync silently would defeat the point of
    this store.
    """
    from api import settings_api

    settings_api.put_setting(key, value)

    data = _load_raw()
    data[key] = value
    _save_raw(data)


def load_json(key: str, default):
    """Return the saved value for *key*. Tries the server first; on
    success, refreshes the local cache and returns the server's value. On
    NetworkError/ApiError (offline, or session not ready), falls back to
    the last-cached local value, or *default* if nothing's ever been
    cached.

    One-time migration: if the server has never seen this key but the local
    cache already has a value (e.g. this install predates server sync), that
    local value is pushed up to the server once here rather than silently
    orphaned — idempotent, since after the push the server is no longer
    empty for this key and this branch doesn't fire again.
    """
    from api import settings_api
    from api.exceptions import ApiError, NetworkError

    data = _load_raw()
    has_local = key in data
    local_value = data.get(key)

    try:
        result = settings_api.get_setting(key)
    except (ApiError, NetworkError):
        return local_value if has_local else default

    server_value = result.get("value")
    if server_value is not None:
        if data.get(key) != server_value:
            data[key] = server_value
            _save_raw(data)
        return server_value

    if has_local:
        try:
            settings_api.put_setting(key, local_value)
        except (ApiError, NetworkError):
            pass
        return local_value

    return default


def load_tab(key: str, default: list) -> list:
    """Return saved rows for *key*, or *default* (as lists) when none saved."""
    rows = load_json(key, None)
    if rows is None:
        return [list(r) for r in default]
    return [list(r) for r in rows]


def save_tab(key: str, rows: list):
    """Persist *rows* (iterable of cell sequences) under *key*."""
    save_json(key, [list(r) for r in rows])


def save_column_order(ordered_names: list, key: str = MAIN_COLUMN_ORDER):
    """Persist the user's column order as a FLAT list of column names —
    deliberately not save_tab's list-of-row-tuples shape (screens.
    config_editor.ConfigTabWidget's reorderable tabs are single-column, so
    a "row" there and a "name" here are the same thing; using save_tab for
    them used to save [["OPEN"], ["HIGH"], ...] instead of ["OPEN", "HIGH",
    ...] — silently breaking every reader of this key, since
    screens.live_viewer._restore_column_order (the only real consumer)
    expects and iterates a flat list of strings; a list of 1-element lists
    made every "in saved" lookup an unhashable-list dict-key crash the next
    time LMV rendered. ConfigTabWidget now saves/loads reorderable tabs
    through this pair specifically to keep that shape correct — see its
    _save/__init__.

    *key* defaults to MAIN_COLUMN_ORDER (LMV's own column order) but takes
    any settings key — screens.inception_hmv reuses this same pair under
    INCEPTION_HMV_COLUMN_ORDER for its own, separate reorder list.
    """
    save_json(key, list(ordered_names))


def load_column_order(key: str = MAIN_COLUMN_ORDER) -> list:
    """Return saved column order (list of names) for *key*, or [] if none
    saved — silently drops any non-string entry (defends against the
    legacy list-of-1-element-lists shape a pre-fix save_tab call could have
    written under this same key; see save_column_order's docstring)."""
    order = load_json(key, None)
    if not isinstance(order, list):
        return []
    return [name for name in order if isinstance(name, str)]


def save_theme(mode: str):
    """Persist the selected theme mode ("dark" or "light"). Always called
    post-login (from the theme-toggle button in the main window's topbar,
    never visible before login), so a valid session always exists here —
    pushed via the dedicated /auth/me/theme endpoint (api/auth_api.py), not
    the generic settings store. A failed server push is swallowed rather
    than surfaced: unlike a strategy or config-table edit, a cosmetic
    dark/light toggle failing loudly over a flaky connection would be poor
    UX for something this low-stakes — the choice still applies locally and
    re-syncs whenever the server is next reachable.
    """
    from api import auth_api
    from api.exceptions import ApiError, NetworkError

    try:
        auth_api.update_theme(mode)
    except (ApiError, NetworkError):
        pass

    data = _load_raw()
    data[THEME] = mode
    _save_raw(data)


def load_theme(default: str = "light") -> str:
    """Return the LOCALLY cached theme mode only. Called once, from
    ThemeManager.__init__ before login even happens (so the window can
    paint immediately without a token to authenticate a server call yet) —
    see sync_theme_from_server for the server-authoritative pull that runs
    once a session actually exists."""
    data = _load_raw()
    mode = data.get(THEME)
    return mode if mode in ("dark", "light") else default


def sync_theme_from_server() -> str | None:
    """Pulls the logged-in user's theme from the server and updates the
    local cache. Called once, right after a successful login (fresh or via
    a persisted "keep me logged in" token) — see
    app.py::AppController.show_main_window / theme.py::ThemeManager.
    sync_from_server. Returns the server's theme, or None if it couldn't be
    reached (caller keeps showing whatever load_theme() already applied at
    boot)."""
    from api import auth_api
    from api.exceptions import ApiError, NetworkError

    try:
        result = auth_api.get_theme()
    except (ApiError, NetworkError):
        return None
    mode = result.get("theme")
    if mode not in ("dark", "light"):
        return None
    data = _load_raw()
    data[THEME] = mode
    _save_raw(data)
    return mode


def save_lmv_highlight_color(hex_color: str | None):
    """Persist the LMV's value-changed highlight color ("#rrggbb"), or None
    to clear the override and fall back to the theme's own amber."""
    save_json(LMV_HIGHLIGHT_COLOR, hex_color)


def load_lmv_highlight_color() -> str | None:
    """Return the saved override color, or None if the user hasn't picked
    one (callers fall back to the theme's status_amber in that case)."""
    color = load_json(LMV_HIGHLIGHT_COLOR, None)
    return color if isinstance(color, str) else None


def save_lmv_column_highlight_colors(colors: dict):
    """Persist the per-column value-changed highlight overrides
    ({column_name: "#rrggbb"}) — a column absent from this dict falls back
    to the LMV-wide default (see save_lmv_highlight_color)."""
    save_json(LMV_COLUMN_HIGHLIGHT_COLORS, dict(colors))


def load_lmv_column_highlight_colors() -> dict:
    """Return the saved {column_name: "#rrggbb"} overrides, or {} if none
    saved."""
    colors = load_json(LMV_COLUMN_HIGHLIGHT_COLORS, None)
    return dict(colors) if isinstance(colors, dict) else {}


def save_inception_highlight_color(hex_color: str | None):
    """Same idea as save_lmv_highlight_color, for Inception's HMV/View by
    Date "changed since last Load" highlight (services.
    inception_change_highlight) — one shared color, same key for both
    screens (see INCEPTION_HIGHLIGHT_COLOR's own docstring)."""
    save_json(INCEPTION_HIGHLIGHT_COLOR, hex_color)


def load_inception_highlight_color() -> str | None:
    color = load_json(INCEPTION_HIGHLIGHT_COLOR, None)
    return color if isinstance(color, str) else None


def save_inception_column_highlight_colors(colors: dict):
    """Same idea as save_lmv_column_highlight_colors, for Inception."""
    save_json(INCEPTION_COLUMN_HIGHLIGHT_COLORS, dict(colors))


def load_inception_column_highlight_colors() -> dict:
    colors = load_json(INCEPTION_COLUMN_HIGHLIGHT_COLORS, None)
    return dict(colors) if isinstance(colors, dict) else {}


def get_rename_map() -> dict:
    """
    Mapping of {actual_column_name -> renamed_column_name} from the
    'Main Column Name' tab. Only entries with a non-empty renamed value that
    differs from the actual name are included.
    """
    from config_defaults import MAIN_COLUMN_NAME_DATA
    rows = load_tab(MAIN_COLUMN_NAME, MAIN_COLUMN_NAME_DATA)
    mapping = {}
    for row in rows:
        if len(row) < 2:
            continue
        actual, renamed = (row[0] or "").strip(), (row[1] or "").strip()
        if actual and renamed and actual != renamed:
            mapping[actual] = renamed
    return mapping
