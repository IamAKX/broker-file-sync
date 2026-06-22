# 📊 Broker File Sync

> A desktop application for syncing, merging, and analyzing broker Excel exports in real time — with live strategy evaluation and smart notifications.

[![CI](https://github.com/IamAKX/broker-file-sync/actions/workflows/ci.yml/badge.svg)](https://github.com/IamAKX/broker-file-sync/actions/workflows/ci.yml)
![Python](https://img.shields.io/badge/python-3.11%2B-blue)
![PySide6](https://img.shields.io/badge/PySide6-6.6%2B-green)
![Platform](https://img.shields.io/badge/platform-macOS%20%7C%20Windows-lightgrey)

---

## ✨ Features

- 📥 **Multi-broker import** — drag-and-drop Excel exports from Sharekhan, ReliableSoftware, and NiftyInvest
- 🔀 **Live Master View** — real-time merged table that auto-refreshes when files change on disk
- 🧮 **Strategy Builder** — visual formula builder with conditional formatting and color rules
- ⚙️ **Config Editor** — manage sector mappings, script names, and column order
- 🔔 **Notifications** — SMS and Telegram alerts for trade triggers
- 🌗 **Dark / Light theme** — toggle anytime, all screens update instantly
- 🖥️ **Cross-platform** — macOS and Windows, HiDPI aware

---

## 📚 Documentation

| Doc | Description |
|-----|-------------|
| [🚀 Setup & Installation](docs/setup.md) | Python setup, dependencies, running the app |
| [🏗️ Architecture](docs/architecture.md) | Project structure, MVC design, data flow |
| [🧮 Strategy Builder](docs/strategy-builder.md) | Formula syntax, functions, conditional formatting |
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
├── app.py                # AppController (lifecycle)
├── app_window.py         # MainWindow, screen routing
├── theme.py              # ThemeManager, global stylesheet
├── font_scale.py         # SMALL / MEDIUM / LARGE constants
├── config_defaults.py    # 216-row stock/column mappings
│
├── screens/              # One file per screen
│   ├── login.py
│   ├── signup.py
│   ├── dashboard.py
│   ├── data_import.py
│   ├── live_viewer.py
│   ├── config_editor.py
│   ├── strategy_builder.py
│   ├── notifications.py
│   └── profile.py
│
├── components/           # Reusable widgets
│   ├── sidebar.py
│   └── topbar.py
│
├── services/             # Business logic
│   ├── file_reader.py
│   ├── master_generator.py
│   ├── watcher.py
│   ├── strategy_engine.py
│   └── strategy_store.py
│
├── assets/icons/         # SVG icons
├── tests/                # pytest test suite
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
