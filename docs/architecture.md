# 🏗️ Architecture

## Overview

Broker Sync follows a lightweight **MVC-inspired** pattern built on PySide6 (Qt6).

```
┌─────────────────────────────────────────────────────┐
│                     main.py                         │
│         DPI setup → QApplication → AppController    │
└────────────────────┬────────────────────────────────┘
                     │
          ┌──────────▼──────────┐
          │    AppController    │  ← lifecycle, screen routing
          │      (app.py)       │
          └──────────┬──────────┘
                     │
          ┌──────────▼──────────┐
          │     MainWindow      │  ← QMainWindow shell
          │  (app_window.py)    │
          │  Sidebar + TopBar   │
          │  QStackedWidget     │
          └──────────┬──────────┘
                     │
        ┌────────────┴────────────┐
        │         Screens         │
        │  Login / Signup         │
        │  Dashboard              │
        │  Data Import            │
        │  Live Viewer (window)   │
        │  Config Editor          │
        │  Strategy Builder       │
        │  Notifications          │
        │  My Profile             │
        └────────────┬────────────┘
                     │
        ┌────────────▼────────────┐
        │        Services         │
        │  FileReader             │
        │  MasterGenerator        │
        │  FileWatcher            │
        │  StrategyEngine         │
        │  StrategyStore          │
        └─────────────────────────┘
```

---

## Key Files

### `main.py`
Entry point. Sets Windows DPI environment variables **before** `QApplication` is created, then hands off to `AppController`.

### `app.py` — `AppController`
Single controller object passed to every screen. Owns:
- `theme` — `ThemeManager` instance
- `watcher` — `FileWatcher` service
- Screen lifecycle (`show_login`, `show_signup`, `show_main_window`)

### `app_window.py` — `MainWindow`
The main shell. Holds:
- `TopBar` — theme toggle, menu bar
- `Sidebar` — navigation buttons
- `QStackedWidget` — one widget per screen, swapped on navigation

### `theme.py` — `ThemeManager`
Owns the global Qt stylesheet. Calling `toggle()` switches dark ↔ light and re-applies the stylesheet to `QApplication`. Every screen also implements `refresh_theme()` for widgets that can't be covered by CSS alone.

### `font_scale.py`
Single source of truth for font sizes. Change `SMALL`, `MEDIUM`, `LARGE` here and every widget updates.

```python
SMALL  = 14   # labels, secondary text
MEDIUM = 16   # body, inputs, buttons
LARGE  = 18   # primary action buttons
```

---

## Data Flow

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
LiveViewerWindow     ← real-time QTableWidget
      │
      ▼
StrategyEngine       ← applies formula columns + conditional formatting
      │
      ▼
strategies.json      ← persisted via StrategyStore
```

---

## Signal / Slot Connections

| Signal | Emitter | Receiver |
|--------|---------|----------|
| `lmv_headers_ready` | `DataImportScreen` | `app_window._on_lmv_ready` |
| `theme_toggled` | `TopBar` | `MainWindow._on_theme_toggled` |
| `navigate` | `Sidebar` | `MainWindow.navigate` |
| `watcher.started` | `FileWatcher` | `DataImportScreen._on_watcher_started` |
| `watcher.synced` | `FileWatcher` | `LiveViewerWindow._populate_table` |

---

← [Back to README](../README)
