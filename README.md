# 📊 Broker Sync

> A desktop application for syncing, merging, and analyzing broker Excel exports in real time — with live strategy evaluation and smart notifications.

[![CI](https://github.com/IamAKX/broker-file-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/IamAKX/broker-file-sync/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![PySide6](https://img.shields.io/badge/PySide6-6.6%2B-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)

---

## ✨ Features

- 🔐 **Accounts & sync** — sign up / log in against the Broker Sync backend; strategies, formula variables, settings, and theme all sync to your account, not just this machine
- 📥 **Multi-broker import** — drag-and-drop Excel exports from Sharekhan, ReliableSoftware, and NiftyInvest
- 🔀 **Live Master View** — real-time merged table that auto-refreshes when files change on disk, with Sector filtering and Opening Range High/Low columns
- 🧮 **Strategy Builder** — visual formula builder with conditional formatting and color rules
- 🔔 **Strategy Notifications** — turn a strategy into a live trade-signal alert: debounced entry trigger, Stop Loss/Target/Trailing Exit lifecycle tracking, delivered via System tray or Email — see [docs/strategy-notifications.md](docs/strategy-notifications.md)
- 🗂 **Live Alerts** — a log of every open and resolved signal, filterable by recency
- 📅 **Historic data & LMV snapshots** — upload daily historic values and full LMV snapshots to the backend, browse them back, gated by a Market Holidays calendar so a holiday's data is never mistakenly saved
- 📊 **Formula Stats & historic aggregates** — the Data menu's Formula Stats screen aggregates a strategy's columns over N historic days; `AVG_DAYS`/`MIN_DAYS`/etc. bring that same aggregation into the formula language itself — usable in any column, condition, or notification metric — see [docs/strategy-builder.md](docs/strategy-builder.md#historic-n-days-aggregates). `VALUE_DAYS_AGO`/`VALUE_ON_DATE` look up a single historic value instead of aggregating, and `VALUE_AT_MAX_DAYS`/`VALUE_AT_MIN_DAYS` look up one column's value on whichever day a second (driver) column peaked/bottomed over the window — see [Historic Value (Point Lookup)](docs/strategy-builder.md#historic-value-point-lookup)
- ⚙️ **Config Editor** — manage sector mappings, script names, and column order
- 🌗 **Dark / Light theme** — toggle anytime, all screens update instantly
- 🖥️ **Cross-platform** — macOS and Windows, HiDPI aware

---

## 📚 Documentation

| Doc | Description |
|-----|-------------|
| [🚀 Setup & Installation](docs/setup.md) | Python setup, dependencies, running the app |
| [🏗️ Architecture](docs/architecture.md) | Project structure, MVC design, data flow |
| [🧮 Strategy Builder](docs/strategy-builder.md) | Formula syntax, functions, conditional formatting |
| [📐 Formula Builder Reference](docs/formula-builder.md) | Every function, every catalogue section, with examples |
| [🔔 Strategy Notifications](docs/strategy-notifications.md) | Trade-signal alerts: trigger, debounce, metrics, lifecycle, channels |
| [🔄 Live Master View](docs/live-master-view.md) | File watcher, merge logic, column filter |
| [🎨 Theming & Fonts](docs/theming.md) | Theme tokens, font scale constants, customisation |
| [🧪 Testing](docs/testing.md) | Running tests, CI pipeline, writing new tests |
| [📦 Building Executables](docs/building.md) | PyInstaller builds for macOS and Windows |

---

## 🖼️ Screenshots

| Dark Theme | Light Theme |
|------------|-------------|
| Dashboard, Data Import, Strategy Builder | Same screens in light mode |

---

## ⚡ Quick Start

```bash
# 1. Clone
git clone https://github.com/IamAKX/broker-file-sync.git
cd broker-file-sync

# 2. Create virtual environment
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

# 3. Install dependencies
pip install -r requirements.txt

# 4. Run
python main.py
```

→ Full setup guide: [docs/setup.md](docs/setup.md)

---

## 🗂️ Project Structure

```
broker-file-sync/
├── main.py               # Entry point, DPI + font setup
├── app.py                # AppController (lifecycle, scheduler, notifier)
├── app_window.py         # MainWindow, screen routing, per-user reload
├── theme.py              # ThemeManager, global stylesheet + QPalette
├── font_scale.py         # SMALL / MEDIUM / LARGE constants
├── config_defaults.py    # 216-row stock/column mappings
│
├── api/                  # Backend HTTP client (see broker-sync-api)
│   ├── client.py             # requests.Session wrapper, token refresh
│   ├── auth_api.py            # login/signup/theme
│   ├── token_store.py         # in-memory + persisted JWT
│   ├── strategies_api.py, holidays_api.py, settings_api.py,
│   │   formula_variables_api.py, historic_api.py, opening_range_api.py,
│   │   lmv_snapshot_api.py, notifications_api.py   # one module per resource
│   └── config.py, endpoints.py, exceptions.py, api_logger.py
│
├── screens/              # One file per screen
│   ├── login.py, signup.py, dashboard.py, data_import.py
│   ├── live_viewer.py                        # Live Master View window
│   ├── config_editor.py, strategy_builder.py
│   ├── notifications.py, live_alerts.py, profile.py
│   ├── historic_upload.py, historic_viewer.py
│   ├── lmv_upload.py, lmv_snapshot_viewer.py
│   ├── formula_builder.py, formula_editor.py, formula_field_editor.py,
│   │   formula_stats.py
│   └── holidays.py, jobs.py
│
├── components/           # Reusable widgets
│   ├── sidebar.py, topbar.py
│   └── column_filter_popup.py, error_popup.py, update_dialog.py
│
├── services/             # Business logic
│   ├── file_reader.py, master_generator.py, watcher.py   # import + merge
│   ├── strategy_engine.py, strategy_store.py             # Strategy Builder
│   ├── formula_engine.py, formula_stats_engine.py, formula_tokens.py,
│   │   formula_variable_store.py                          # Formula Builder
│   ├── strategy_alerts/       # Strategy Notifications engine
│   │   ├── engine.py              # trigger/debounce/lifecycle state machine
│   │   ├── config_store.py        # per-strategy notification config (backend-synced)
│   │   ├── state_store.py         # open signals + alert history (local)
│   │   └── models.py, messages.py
│   ├── notifications/         # Delivery channels
│   │   ├── manager.py             # NotificationService facade
│   │   └── channels/              # system.py, email.py, telegram.py (stub)
│   ├── notification_channels.py, trigger_config.py    # channel/schedule config
│   ├── scheduler.py, scheduled_jobs.py                # background jobs (tray-resident)
│   ├── config_store.py, historic_lmv_merge.py, live_formula.py, live_merge.py,
│   │   lmv_export.py, trading_calendar.py, update_checker.py, tray.py,
│   │   single_instance.py, autostart.py, error_logging.py
│   └── broker_db_source.py, com_reader.py, external_import_source.py
│
├── assets/icons/         # SVG icons
├── tests/                # pytest test suite (59 files, see docs/testing.md)
└── docs/                 # Extended documentation
```

---

## 🤝 Contributing

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/my-feature`
3. Run tests: `python -m pytest tests/`
4. Push and open a PR

---

## 📄 License

MIT
