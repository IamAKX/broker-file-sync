# 🏗️ Architecture

## Overview

Broker Sync follows a lightweight **MVC-inspired** pattern built on PySide6 (Qt6),
backed by a FastAPI service (`broker-sync-api`, a sibling repo) reached through a
thin HTTP client layer (`api/`). The app is no longer a purely local tool — an
account (login/signup) is required before `MainWindow` ever appears.

```
┌─────────────────────────────────────────────────────┐
│                     main.py                         │
│         DPI setup → QApplication → AppController    │
└────────────────────┬────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │    AppController    │  ← lifecycle, scheduler, tray, notifier
          │      (app.py)       │
          └──────────┬──────────┘
                     │
     token_manager.load_persisted()?
       │no                    │yes
       ▼                      ▼
 ┌───────────┐      ┌──────────────────────┐
 │  Login /  │      │      MainWindow      │  ← QMainWindow shell
 │  Signup   │─────▶│    (app_window.py)   │
 │ (api/*)   │      │   Sidebar + TopBar   │
 └───────────┘      │   QStackedWidget     │
                     └──────────┬───────────┘
                                │
        ┌───────────────────────┴────────────────────────┐
        │                     Screens                     │
        │  Dashboard · Data Import · Live Viewer (window) │
        │  Config Editor · Strategy Builder                │
        │  Notifications · Live Alerts · My Profile        │
        │  Historic Upload/Viewer · LMV Upload/Viewer      │
        │  Formula Builder/Stats · Holidays · Jobs         │
        └───────────────────────┬────────────────────────┘
                                │
        ┌───────────────────────▼────────────────────────┐
        │                     Services                     │
        │  FileReader · MasterGenerator · FileWatcher       │
        │  StrategyEngine · StrategyStore                   │
        │  strategy_alerts/ (trigger/debounce/lifecycle)    │
        │  notifications/ (System/Email/Slack delivery)     │
        │  Scheduler + scheduled_jobs (tray-resident)        │
        │  formula_engine, formula_variable_store, ...       │
        └───────────────────────┬────────────────────────┘
                                │
                     ┌──────────▼──────────┐
                     │   api/ (HTTP layer) │  ← auth, strategies, settings,
                     │   api_client + JWT   │    holidays, historic, LMV
                     └──────────┬───────────┘    snapshots, opening range,
                                │                 notifications, formula vars
                                ▼
                     broker-sync-api (FastAPI, separate repo)
```

---

## Key Files

### `main.py`
Entry point. Sets Windows DPI environment variables **before** `QApplication` is created, then hands off to `AppController`.

### `app.py` — `AppController`
Single controller object passed to every screen. Owns:
- `theme` — `ThemeManager` instance
- `watcher` — `FileWatcher` service
- `_tray`, `_scheduler`, `_notifier` — tray icon, background job scheduler, and
  `NotificationService`, all built lazily on first successful login
  (`_ensure_scheduler`) and preserved across a logout/login cycle within the
  same process
- Screen lifecycle (`start`, `show_login`, `show_main_window`)

`start()` checks `token_manager.load_persisted()` first — a valid persisted
session skips straight to `show_main_window()`; otherwise `LoginScreen` is shown
and the app is unusable until login/signup succeeds against the backend.
`api_client.set_session_expired_callback(self.show_login)` means an expired
token at any point later bounces the user back to the login screen automatically.

### `app_window.py` — `MainWindow`
The main shell. Holds:
- `TopBar` — theme toggle, menu bar, and menu actions (restart, quit, logout,
  fullscreen, check-for-update, export/import strategies, manage categories)
- `Sidebar` — navigation buttons (see `components/sidebar.py`'s `NAV_ITEMS`)
- `QStackedWidget` — one widget per registered screen, swapped on navigation

`_register_screens()` registers 13 screens total; only 7 have a permanent
sidebar entry (`dashboard`, `data_import`, `config_editor`, `strategy_builder`,
`notifications`, `live_alerts`, `profile`) — the rest (`historic_upload`,
`formula_builder`, `holidays`, `lmv_upload`, `jobs`, `formula_stats`) are reached
via `TopBar`'s Edit/Data menus instead of the sidebar.

`reload_per_user_data()` re-pulls every eagerly-loaded, now-per-user store
(strategies, notification configs/state, trigger config, formula variables,
config editor tables) on every login, not just the first — `MainWindow` and its
screens are reused across a logout/login cycle in the same process, so a second
user logging in on the same device must not keep seeing the first user's data.

`check_holiday_gate()` can block the whole app behind a modal until the current
year's Market Holidays are on file (see `screens/holidays.py`) — historic
uploads need to know which dates to reject.

### `theme.py` — `ThemeManager`
Owns the global Qt stylesheet **and** an explicit `QPalette` (`_build_palette`).
Calling `toggle()` switches dark ↔ light and re-applies both to `QApplication`.
The palette exists specifically because Fusion-style popups that spawn their own
top-level window (a `QComboBox` dropdown, a `QMenu`, a tooltip) paint their frame
from the ambient palette before any QSS on the inner view applies — without it,
popups fall back to native white regardless of the app's theme. A module-level
patch on `QComboBox.showPopup` (`_patch_combo_popup_frame`) additionally strips
the popup list's own native frame to avoid a doubled-border look. Every screen
also implements `refresh_theme()` for widgets that can't be covered by CSS alone.

### `font_scale.py`
Single source of truth for font sizes. Change `SMALL`, `MEDIUM`, `LARGE` here and every widget updates.

```python
SMALL  = 14   # labels, secondary text
MEDIUM = 16   # body, inputs, buttons
LARGE  = 18   # primary action buttons
```

### `api/` — Backend HTTP layer
One module per backend resource (`auth_api.py`, `strategies_api.py`,
`holidays_api.py`, `historic_api.py`, `opening_range_api.py`,
`lmv_snapshot_api.py`, `notifications_api.py`, `formula_variables_api.py`,
`settings_api.py`), all routed through `api/client.py`'s `api_client` — a
`requests.Session` wrapper that attaches the bearer token, retries once on 401
after a token refresh, and normalizes FastAPI's error shapes. `api/token_store.py`
holds the JWT in memory plus optional disk persistence for "keep me logged in".
`BASE_URL` (`api/config.py`) defaults to a specific remote host, overridable via
the `BROKER_SYNC_API_URL` environment variable.

### `services/strategy_alerts/` and `services/notifications/`
The Strategy Notifications feature (see
[docs/strategy-notifications.md](strategy-notifications.md)): `strategy_alerts/`
holds the trigger/debounce/lifecycle state machine (`engine.py`) and its config/
state persistence; `notifications/` is the channel-agnostic delivery layer
(`manager.py`'s `NotificationService`, plus `channels/system.py`, `email.py`,
`slack.py`). `services/scheduler.py` + `services/scheduled_jobs.py` are a
separate, tray-resident background job runner (historic save, LMV check,
availability check, opening-range capture) that also delivers through
`NotificationService`.

---

## Data Flow

### File import → Live Master View

```
Broker Excel files
      │
      ▼
 FileReader          ← reads each broker format (header offsets differ)
      │
      ▼
MasterGenerator      ← 3-way merge → master.xlsx (BytesIO, preserves inode)
      │
      ▼
FileWatcher          ← QFileSystemWatcher, 300ms debounce, 3x retry
      │
      ▼
LiveViewerWindow     ← real-time QTableWidget (worker thread computes
      │                 formula columns; GUI thread renders + runs
      │                 strategy_alerts.engine.evaluate_tick)
      ▼
StrategyEngine       ← applies formula columns + conditional formatting
      │
      ▼
strategies.json      ← persisted via StrategyStore, synced to the backend
```

### Account & sync

Login/signup issue a JWT (`api/auth_api.py`) held by `token_manager`. Once
authenticated, `strategy_store.py`, `config_store.py`,
`formula_variable_store.py`, and `strategy_alerts/config_store.py` all read/write
through the backend via `api/`, with a local JSON file as an offline-read cache —
so strategies, settings, formula variables, and notification configs follow the
account, not the machine. Strategy-alert **runtime state** (open signals, alert
history) is the one exception: it stays local-only, per logged-in user on that
machine (see `services/strategy_alerts/state_store.py`).

---

## Signal / Slot Connections

| Signal | Emitter | Receiver |
|--------|---------|----------|
| `navigate` | `Sidebar` | `MainWindow.navigate` |
| `navigate` | `TopBar` | `MainWindow.navigate` |
| `theme_toggled` | `TopBar` | `MainWindow._on_theme_toggled` |
| `restart_requested` | `TopBar` | `MainWindow.navigate("dashboard")` |
| `quit_requested` | `TopBar` | `AppController.request_quit` |
| `logout_requested` | `TopBar` | `AppController.show_login` |
| `fullscreen_requested` | `TopBar` | `MainWindow._toggle_fullscreen` |
| `check_for_update_requested` | `TopBar` | `MainWindow._open_update_dialog` |
| `export_strategies_requested` / `import_strategies_requested` | `TopBar` | `MainWindow._export_all_strategies` / `_import_all_strategies` |
| `manage_categories_requested` | `TopBar` | `MainWindow._open_manage_categories` |
| `broker_imported` / `broker_reset` | `DataImportScreen` | `Sidebar.set_broker_active`, `DashboardScreen.on_broker_imported`/`on_broker_reset` |
| `broker_source_active` | `DataImportScreen` | `Sidebar.set_broker_active`, `DashboardScreen.on_broker_source_active` |
| `lmv_headers_ready` | `DataImportScreen` | a closure in `app_window._register_screens` that pushes headers into `StrategyBuilderScreen` and active-only strategies into the open `LiveViewerWindow` |
| `lmv_data_ready` | `DataImportScreen` | `StrategyBuilderScreen.set_lmv_data` |
| `watcher.started` | `FileWatcher` | `DataImportScreen._on_watcher_started` |
| `watcher.synced` | `FileWatcher` | `DashboardScreen._on_watcher_synced` |

---

← [Back to README](../README)
