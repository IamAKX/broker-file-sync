# 🧪 Testing

---

## Running Tests

```bash
# Activate your virtual environment first
source .venv/bin/activate       # Windows: .venv\Scripts\activate

# Run all tests
python -m pytest tests/ -v

# Run a specific test file
python -m pytest tests/test_strategy_builder.py -v

# Run with short output
python -m pytest tests/ -q
```

**Expected output:** ~820 tests passed, across 59 files (grows with every new feature — don't treat either number as exact).

---

## Test Files

59 files as of this writing — grouped by area rather than listed exhaustively (an
up-to-the-minute list is always `ls tests/`):

| Area | Representative files |
|------|--------------|
| Auth / shell | `test_login_signup.py`, `test_app_window.py`, `test_sidebar.py`, `test_topbar.py`, `test_theme.py`, `test_server_sync.py` |
| Dashboard / import | `test_dashboard.py`, `test_data_import.py`, `test_config_editor.py`, `test_config_store.py`, `test_file_reader.py`, `test_external_import.py`, `test_broker_db_source.py` |
| Strategy Builder | `test_strategy_builder.py`, `test_strategy_engine_functions.py`, `test_strategy_fmt_target.py` |
| Strategy Notifications | `test_strategy_alerts_engine.py`, `test_strategy_alerts_config_store.py`, `test_strategy_alerts_state_store.py`, `test_strategy_notification_section.py`, `test_live_viewer_strategy_alerts.py`, `test_live_alerts.py` |
| Delivery / scheduling | `test_notifications.py`, `test_notification_channels.py`, `test_notification_channel_toggles.py`, `test_trigger_config.py`, `test_scheduler.py`, `test_scheduled_jobs.py` |
| Formula Builder / Stats | `test_formula_builder.py`, `test_formula_editor.py`, `test_formula_field_editor.py`, `test_formula_engine.py`, `test_formula_tokens.py`, `test_formula_variables.py`, `test_formula_stats.py` |
| Live Master View | `test_lmv_export.py`, `test_lmv_export_ui.py`, `test_lmv_frozen_column.py`, `test_lmv_highlight_color.py`, `test_lmv_reset.py`, `test_lmv_snapshot_viewer.py`, `test_lmv_strategy_names_label.py`, `test_lmv_upload.py`, `test_live_formula.py`, `test_market_profile.py` |
| Historic data / holidays | `test_historic_upload.py`, `test_historic_lmv_merge.py`, `test_holidays.py`, `test_trading_calendar.py` |
| Other | `test_profile.py`, `test_jobs_screen.py`, `test_api_client.py`, `test_update_checker.py`, `test_update_dialog.py`, `test_column_filter_popup.py`, `test_reliable_rolling_suffix.py`, `test_integration.py` (full user journey — login → navigate all screens) |

---

## Test Isolation & Backend Stubbing

`tests/conftest.py` has an **autouse** fixture (`_isolate_disk_stores`) that runs
before every single test, with no per-test opt-in needed:

- Redirects every JSON-backed local store (`config_store`, `strategy_store`,
  `formula_variable_store`, `strategy_alerts.state_store`) to a per-test
  `tmp_path` — so no test can accidentally read/write the real
  `config_data.json`/`strategies.json`/etc. at the repo root.
- Stubs `api.auth_api`, `api.settings_api`, `api.strategies_api`,
  `api.formula_variables_api` to simulate "a reachable server with nothing saved
  yet" instead of making a real network call — a test that saves then loads
  within itself still round-trips correctly through the local tmp-path cache,
  exactly as before backend sync existed.

Since login/backend calls are now load-bearing for so much of the app (see
[setup.md](setup.md)'s Account & Backend section), most screen tests would
otherwise need to mock the backend by hand — this fixture means they don't have
to.

---

## CI Pipeline

Tests run automatically on every push and pull request via GitHub Actions (`.github/workflows/ci.yml`), which has 5 jobs:

1. **`test`** — runs on Ubuntu with headless Qt (`QT_QPA_PLATFORM=offscreen`)
2. **`compute-version`** — push to `main` only; computes the next patch semver
   off the highest existing `vX.Y.Z` git tag (`version.py`'s version string)
3. **`build-windows`** — PyInstaller `.exe` with DPI manifest (needs `test` + `compute-version`)
4. **`build-macos`** — PyInstaller `.app` bundle, zipped as `BrokerFileSync-macos.zip` (needs `test` + `compute-version`)
5. **`release`** — creates a GitHub Release with both artifacts (push to `main` only)

---

## Headless Qt on Linux

The test runner uses `QT_QPA_PLATFORM=offscreen` to run without a display. This requires some system libraries:

```bash
sudo apt-get install -y libgl1 libegl1 libglib2.0-0 libdbus-1-3 \
  libxcb-xinerama0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
  libxcb-randr0 libxcb-render-util0 libxkbcommon-x11-0 xvfb
```

---

## Writing New Tests

All tests follow the same pattern — a `screen` fixture creates the widget:

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.my_screen import MyScreen
    return MyScreen(AppController(qapp))

def test_my_screen_creates(screen):
    assert screen is not None

def test_has_save_button(screen):
    from PySide6.QtWidgets import QPushButton
    buttons = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Save" in t for t in buttons)
```

> **Note:** `ThemeManager.apply()` safely returns early if no screen is available, so tests don't need a display to construct widgets.

---

← [Back to README](../README)
