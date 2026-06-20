# Broker File Sync — PySide6 Desktop App Design Spec
**Date:** 2026-06-19  
**Status:** Approved

---

## Overview

A PySide6 desktop prototype that replicates the Broker File Sync Figma wireframe
(https://fresh-power-43691787.figma.site). The app demonstrates a complete user journey
across 7 screens with dummy data, dark/light mode, and clickable navigation throughout.

---

## File Structure

```
broker-file-sync/
├── main.py
├── app.py
├── theme.py
├── screens/
│   ├── __init__.py
│   ├── login.py
│   ├── signup.py
│   ├── dashboard.py
│   ├── data_import.py
│   ├── config_editor.py
│   ├── notifications.py
│   └── profile.py
├── components/
│   ├── __init__.py
│   ├── sidebar.py
│   └── topbar.py
└── assets/
    └── (no external assets — icons via Unicode/Qt built-ins)
```

---

## Navigation Flow

```
Login ──────────────────────────────── Signup
  │  (click "Sign Up" link)               │
  │                       (click "Create Account")
  └──── (click "Login") ──────────────────┘
                │
           MainWindow
         (sidebar + topbar)
                │
    ┌───────────┼───────────────────┐
 Dashboard  Data Import  Config Editor  Notifications  My Profile
                                                           │
                                                        Logout
                                                           │
                                                        Login
```

- `main.py` launches the Login screen directly (no sidebar/topbar).
- Login and Signup are standalone `QWidget` windows (no `MainWindow` chrome).
- Clicking Login or Signup (any non-empty or even empty input) immediately enters `MainWindow`.
- `MainWindow` is a `QMainWindow` with `QStackedWidget` holding all 5 main screens.
- Sidebar buttons call `MainWindow.navigate(screen_name)` to switch the stacked widget index.

---

## Architecture

### `main.py`
- Creates `QApplication`.
- Instantiates `ThemeManager` (dark by default).
- Shows `LoginScreen` as the entry point.
- Passes `app` reference so screens can call `app.show_main_window()` / `app.show_login()`.

### `app.py` — `AppController`
- Owns `LoginScreen`, `SignupScreen`, and `MainWindow`.
- `show_main_window()`: hides login/signup, shows `MainWindow`, navigates to Dashboard.
- `show_login()`: hides `MainWindow`, shows `LoginScreen`.
- `show_signup()`: hides `LoginScreen`, shows `SignupScreen`.

### `theme.py` — `ThemeManager`
- Holds two palette dicts: `DARK` and `LIGHT`.
- `apply(app, mode)`: builds a `QPalette` and calls `app.setPalette()` + `app.setStyleSheet()`.
- Exposes `toggle()` and `current_mode` property.
- All screens/components read colors from `ThemeManager` — no hardcoded hex values in screen files.

### `components/sidebar.py` — `Sidebar(QWidget)`
- Fixed width: 180px.
- Logo/app name at top.
- Nav items: Dashboard, Data Import, Config Editor, Notifications, My Profile.
- Active item highlighted with accent color background.
- "BROKER FILES" label + 3 broker items (Sharekhan/red, ReliableSoftware/blue, NiftyInvest/orange) with colored dots.
- User avatar widget at bottom (initials "RJ", name "Rajesh", truncated email).
- Emits `navigate(screen_name: str)` signal on item click.

### `components/topbar.py` — `TopBar(QWidget)`
- Fixed height: 40px.
- Left: App name label.
- Center: clickable menu labels — File, Edit, View, Notifications, Profile, Help.
  - Each shows a small `QMenu` popup with 2–3 dummy items on click.
- Right: sun/moon toggle button (switches theme) + Restart button (shows confirmation dialog, resets to Dashboard).
- Emits `theme_toggled()` signal.

---

## Screens

### `screens/login.py` — `LoginScreen`
- Centered card (480×400px) on a full-screen background.
- App logo/title at top: "BROKER FILE SYNC" (monospace, large).
- Subtitle: "Excel Processing Software".
- Email input field.
- Password input field (masked).
- "Login" primary button → calls `app_controller.show_main_window()`.
- "Don't have an account? Sign Up" link → calls `app_controller.show_signup()`.

### `screens/signup.py` — `SignupScreen`
- Same centered card layout as Login.
- Fields: Full Name, Email, Password, Confirm Password.
- "Create Account" button → calls `app_controller.show_main_window()`.
- "Already have an account? Login" link → calls `app_controller.show_login()`.

### `screens/dashboard.py` — `DashboardScreen`
- Page title: "Dashboard", subtitle: "File import overview and processing activity".
- **Stats row:** 4 `StatCard` widgets side by side.
  - Total Files Imported: 0
  - Total Rows Processed: 0
  - Import Errors: 0
  - Broker Sources Active: 0/3
- **Two-column section:**
  - Left — "BROKER SOURCES": list of 3 brokers with colored dot, name, stats ("0 files – 0 imported"), status "Awaiting".
  - Right — "RECENT FILE ACTIVITY": empty state with folder icon, "No files imported yet." message, "Go to Data Import" link-style button that navigates to Data Import screen.
- **Info banner** at bottom: green-tinted background, info icon, instructional text about Config Editor setup.

### `screens/data_import.py` — `DataImportScreen`
- Page title: "Data Import".
- **Broker selector:** `QComboBox` with options: Sharekhan, ReliableSoftware, NiftyInvest.
- **File drop area:** styled `QLabel` box ("Drop Excel files here or click to browse"), clicking opens `QFileDialog` (filter: `*.xlsx *.xls`). Selected filename shown below.
- **Import button:** "Import Files" — clicking shows a `QProgressBar` that animates to 100% over 2 seconds, then shows "Import complete! 0 rows processed." in the log area.
- **Log area:** `QPlainTextEdit` (read-only), shows timestamped dummy log lines after import.

### `screens/config_editor.py` — `ConfigEditorScreen`
- Page title: "Config Editor".
- **Two tabs** via `QTabWidget`:
  - "Column Name Mapping": `QTableWidget` with columns Source Column / Target Column, pre-populated with 5 dummy rows. Cells are editable.
  - "Script Name Mapping": `QTableWidget` with columns Script ID / Script Name / Broker, pre-populated with 4 dummy rows. Cells are editable.
- **Save button** at bottom: shows a `QMessageBox` "Configuration saved successfully."

### `screens/notifications.py` — `NotificationsScreen`
- Page title: "Notifications".
- List of 5 dummy notification items in a `QScrollArea`.
- Each item: colored icon (info/warning/error/success), title, body text, timestamp.
- "Mark all as read" button at top-right: grays out all notification icons.

### `screens/profile.py` — `ProfileScreen`
- Page title: "My Profile".
- **User info section:** read-only fields — Full Name, Email, Role ("Administrator").
- **Theme toggle:** label "Dark Mode" + `QCheckBox` (checked = dark, unchecked = light). Toggling calls `theme_manager.toggle()` and immediately applies the new palette.
- **Change Password button:** opens a `QDialog` with Old Password / New Password / Confirm fields and an "Update" button (shows success message, no real logic).
- **Logout button** (destructive style, red): calls `app_controller.show_login()`.

---

## Theme System

### Dark Palette (`DARK`)
| Token | Hex |
|-------|-----|
| background | `#0d1117` |
| sidebar_bg | `#161b22` |
| card_bg | `#1c2128` |
| border | `#30363d` |
| accent | `#39d353` |
| text_primary | `#e6edf3` |
| text_secondary | `#8b949e` |
| status_red | `#f85149` |
| status_blue | `#58a6ff` |
| status_orange | `#e3b341` |
| info_banner_bg | `#0d4429` |

### Light Palette (`LIGHT`)
| Token | Hex |
|-------|-----|
| background | `#ffffff` |
| sidebar_bg | `#f6f8fa` |
| card_bg | `#ffffff` |
| border | `#d0d7de` |
| accent | `#1a7f37` |
| text_primary | `#1f2328` |
| text_secondary | `#656d76` |
| status_red | `#cf222e` |
| status_blue | `#0969da` |
| status_orange | `#9a6700` |
| info_banner_bg | `#dafbe1` |

---

## Component: StatCard
- Reusable `QFrame` used in Dashboard.
- Properties: `label` (all-caps string), `value` (string), `icon` (Unicode char).
- Icon shown top-right, label below, large bold value below label.
- Styled via `ThemeManager` tokens.

---

## Dependencies
- Python 3.10+
- PySide6 (`pip install PySide6`)
- No other external dependencies.

---

## Out of Scope (prototype)
- Real file parsing or database.
- Authentication logic.
- Actual broker API connections.
- Persistent settings between sessions.
