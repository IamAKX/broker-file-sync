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

**Expected output:** `44 passed`

---

## Test Files

| File | What it tests |
|------|--------------|
| `test_login_signup.py` | Login and signup screens render correctly |
| `test_dashboard.py` | Dashboard widgets and metric cards |
| `test_data_import.py` | Broker import cards, watcher button state |
| `test_config_editor.py` | Config tabs, add/delete/reset rows |
| `test_strategy_builder.py` | Strategy CRUD, header sync, formula builder |
| `test_notifications.py` | Notification toggles and trigger rows |
| `test_profile.py` | Profile form, save changes button |
| `test_app_window.py` | Navigation, screen registration |
| `test_sidebar.py` | Nav items, broker file rows |
| `test_topbar.py` | Theme toggle button, menu bar |
| `test_theme.py` | Dark/light palette, token lookup |
| `test_integration.py` | Full user journey — login → navigate all screens |

---

## CI Pipeline

Tests run automatically on every push and pull request via GitHub Actions (`.github/workflows/ci.yml`).

**Pipeline steps:**
1. **Test** — runs on Ubuntu with headless Qt (`QT_QPA_PLATFORM=offscreen`)
2. **Build macOS** — PyInstaller `.app` bundle (runs after tests pass)
3. **Build Windows** — PyInstaller `.exe` with DPI manifest (runs after tests pass)
4. **Release** — creates a GitHub Release with both artifacts (push to `main` only)

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
