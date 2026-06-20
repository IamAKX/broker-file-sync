# Broker File Sync Desktop App Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a PySide6 desktop prototype of the Broker File Sync app with 7 screens, dark/light theme, full user journey, and all buttons clickable with dummy functionality.

**Architecture:** Multi-file MVC — `AppController` owns all screens and handles navigation, `ThemeManager` owns palette state and applies it app-wide, each screen is a self-contained `QWidget` that emits signals or calls controller methods to navigate. Sidebar and TopBar are shared components mounted inside `MainWindow`.

**Tech Stack:** Python 3.10+, PySide6 (`pip install PySide6`), no other external dependencies.

## Global Constraints

- Font: `Courier New` or `Consolas` (monospace) for all UI text — set via `QFont` globally.
- No hardcoded hex values in screen/component files — all colors come from `ThemeManager.get(token)`.
- All navigation calls go through `AppController` — screens never directly show/hide other screens.
- Window size: minimum 1100×700px, default 1280×800px.
- Dark mode is the default on launch.
- PySide6 only — no PyQt5/PyQt6/tkinter.
- Python 3.10+ syntax allowed.

---

### Task 1: Project scaffold + ThemeManager

**Files:**
- Create: `main.py`
- Create: `theme.py`
- Create: `app.py` (stub)
- Create: `screens/__init__.py`
- Create: `components/__init__.py`
- Create: `requirements.txt`
- Test: `tests/test_theme.py`

**Interfaces:**
- Produces:
  - `ThemeManager(app: QApplication)` — constructor stores app ref, sets mode to `"dark"`.
  - `ThemeManager.get(token: str) -> str` — returns hex color for current mode.
  - `ThemeManager.toggle()` — switches mode between `"dark"` and `"light"`, reapplies palette.
  - `ThemeManager.current_mode: str` — property, `"dark"` or `"light"`.
  - `ThemeManager.apply()` — builds `QStyleSheet` from current palette and calls `app.setStyleSheet()`.

- [ ] **Step 1: Create requirements.txt**

```
PySide6>=6.6.0
```

- [ ] **Step 2: Create `tests/test_theme.py` — write failing tests**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication(sys.argv)
    return app

def test_default_mode_is_dark(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    assert tm.current_mode == "dark"

def test_get_returns_dark_accent(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    assert tm.get("accent") == "#39d353"

def test_toggle_switches_to_light(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    assert tm.current_mode == "light"
    assert tm.get("accent") == "#1a7f37"

def test_toggle_switches_back_to_dark(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    tm.toggle()
    tm.toggle()
    assert tm.current_mode == "dark"

def test_get_unknown_token_raises(qapp):
    from theme import ThemeManager
    tm = ThemeManager(qapp)
    with pytest.raises(KeyError):
        tm.get("nonexistent_token")
```

- [ ] **Step 3: Run tests — verify they fail**

```bash
cd /Users/akash/Desktop/broker-file-sync
python -m pytest tests/test_theme.py -v
```
Expected: `ModuleNotFoundError: No module named 'theme'`

- [ ] **Step 4: Create `theme.py`**

```python
from PySide6.QtWidgets import QApplication

DARK = {
    "background":    "#0d1117",
    "sidebar_bg":    "#161b22",
    "card_bg":       "#1c2128",
    "border":        "#30363d",
    "accent":        "#39d353",
    "accent_hover":  "#2ea043",
    "text_primary":  "#e6edf3",
    "text_secondary":"#8b949e",
    "status_red":    "#f85149",
    "status_blue":   "#58a6ff",
    "status_orange": "#e3b341",
    "info_banner_bg":"#0d4429",
    "input_bg":      "#0d1117",
    "button_bg":     "#21262d",
    "destructive":   "#da3633",
}

LIGHT = {
    "background":    "#ffffff",
    "sidebar_bg":    "#f6f8fa",
    "card_bg":       "#ffffff",
    "border":        "#d0d7de",
    "accent":        "#1a7f37",
    "accent_hover":  "#116329",
    "text_primary":  "#1f2328",
    "text_secondary":"#656d76",
    "status_red":    "#cf222e",
    "status_blue":   "#0969da",
    "status_orange": "#9a6700",
    "info_banner_bg":"#dafbe1",
    "input_bg":      "#ffffff",
    "button_bg":     "#f6f8fa",
    "destructive":   "#cf222e",
}

PALETTES = {"dark": DARK, "light": LIGHT}


class ThemeManager:
    def __init__(self, app: QApplication):
        self._app = app
        self._mode = "dark"
        self.apply()

    @property
    def current_mode(self) -> str:
        return self._mode

    def get(self, token: str) -> str:
        return PALETTES[self._mode][token]

    def toggle(self):
        self._mode = "light" if self._mode == "dark" else "dark"
        self.apply()

    def apply(self):
        p = PALETTES[self._mode]
        self._app.setStyleSheet(f"""
            QWidget {{
                background-color: {p['background']};
                color: {p['text_primary']};
                font-family: 'Courier New', Consolas, monospace;
                font-size: 13px;
            }}
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox {{
                background-color: {p['input_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 4px;
                padding: 6px 10px;
                font-family: 'Courier New', Consolas, monospace;
            }}
            QLineEdit:focus, QPlainTextEdit:focus {{
                border: 1px solid {p['accent']};
            }}
            QPushButton {{
                background-color: {p['button_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 4px;
                padding: 6px 14px;
                font-family: 'Courier New', Consolas, monospace;
            }}
            QPushButton:hover {{
                border-color: {p['accent']};
                color: {p['accent']};
            }}
            QTabWidget::pane {{
                border: 1px solid {p['border']};
                background: {p['card_bg']};
            }}
            QTabBar::tab {{
                background: {p['button_bg']};
                color: {p['text_secondary']};
                padding: 6px 16px;
                border: 1px solid {p['border']};
                font-family: 'Courier New', Consolas, monospace;
            }}
            QTabBar::tab:selected {{
                background: {p['card_bg']};
                color: {p['accent']};
                border-bottom: 2px solid {p['accent']};
            }}
            QScrollBar:vertical {{
                background: {p['sidebar_bg']};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {p['border']};
                border-radius: 4px;
            }}
            QTableWidget {{
                background: {p['card_bg']};
                color: {p['text_primary']};
                gridline-color: {p['border']};
                border: 1px solid {p['border']};
            }}
            QHeaderView::section {{
                background: {p['button_bg']};
                color: {p['text_secondary']};
                border: 1px solid {p['border']};
                padding: 4px 8px;
                font-family: 'Courier New', Consolas, monospace;
                font-size: 11px;
                text-transform: uppercase;
            }}
            QMenuBar {{
                background-color: {p['sidebar_bg']};
                color: {p['text_primary']};
                font-family: 'Courier New', Consolas, monospace;
                font-size: 12px;
            }}
            QMenuBar::item:selected {{
                background: {p['button_bg']};
            }}
            QMenu {{
                background-color: {p['card_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                font-family: 'Courier New', Consolas, monospace;
            }}
            QMenu::item:selected {{
                background: {p['accent']};
                color: {p['background']};
            }}
            QProgressBar {{
                border: 1px solid {p['border']};
                border-radius: 4px;
                background: {p['card_bg']};
                text-align: center;
                color: {p['text_primary']};
            }}
            QProgressBar::chunk {{
                background: {p['accent']};
                border-radius: 3px;
            }}
            QCheckBox {{
                color: {p['text_primary']};
                font-family: 'Courier New', Consolas, monospace;
            }}
            QCheckBox::indicator:checked {{
                background: {p['accent']};
                border: 1px solid {p['accent']};
            }}
            QDialog {{
                background: {p['background']};
            }}
            QMessageBox {{
                background: {p['background']};
                color: {p['text_primary']};
            }}
        """)
```

- [ ] **Step 5: Create `app.py` stub**

```python
from PySide6.QtWidgets import QApplication
from theme import ThemeManager


class AppController:
    def __init__(self, app: QApplication):
        self.app = app
        self.theme = ThemeManager(app)
        self._login = None
        self._signup = None
        self._main_window = None

    def start(self):
        from screens.login import LoginScreen
        self._login = LoginScreen(self)
        self._login.show()

    def show_main_window(self):
        from app_window import MainWindow
        if self._login:
            self._login.hide()
        if self._signup:
            self._signup.hide()
        if self._main_window is None:
            self._main_window = MainWindow(self)
        self._main_window.show()
        self._main_window.navigate("dashboard")

    def show_login(self):
        from screens.login import LoginScreen
        if self._main_window:
            self._main_window.hide()
        if self._signup:
            self._signup.hide()
        if self._login is None:
            self._login = LoginScreen(self)
        self._login.show()

    def show_signup(self):
        from screens.signup import SignupScreen
        if self._login:
            self._login.hide()
        if self._signup is None:
            self._signup = SignupScreen(self)
        self._signup.show()
```

- [ ] **Step 6: Create `main.py`**

```python
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from app import AppController


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Courier New", 13))
    controller = AppController(app)
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 7: Create `screens/__init__.py` and `components/__init__.py`**

Both files are empty:
```python
```

- [ ] **Step 8: Run tests — verify they pass**

```bash
python -m pytest tests/test_theme.py -v
```
Expected: 5 PASSED

- [ ] **Step 9: Commit**

```bash
git init
git add .
git commit -m "feat: scaffold project with ThemeManager"
```

---

### Task 2: Sidebar component

**Files:**
- Create: `components/sidebar.py`
- Test: `tests/test_sidebar.py`

**Interfaces:**
- Consumes: `ThemeManager.get(token)` from Task 1.
- Produces:
  - `Sidebar(theme: ThemeManager, parent=None)` — `QWidget`, fixed width 180px.
  - `Sidebar.navigate` — `Signal(str)` emitted with screen name when nav item clicked.
  - `Sidebar.set_active(screen_name: str)` — highlights the matching nav item.
  - Screen name strings: `"dashboard"`, `"data_import"`, `"config_editor"`, `"notifications"`, `"profile"`.

- [ ] **Step 1: Write failing test**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def sidebar(qapp):
    from theme import ThemeManager
    from components.sidebar import Sidebar
    tm = ThemeManager(qapp)
    return Sidebar(tm)

def test_sidebar_fixed_width(sidebar):
    assert sidebar.minimumWidth() == 180
    assert sidebar.maximumWidth() == 180

def test_set_active_does_not_raise(sidebar):
    sidebar.set_active("dashboard")
    sidebar.set_active("profile")

def test_navigate_signal_exists(sidebar):
    from PySide6.QtCore import Signal
    assert hasattr(sidebar, "navigate")
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_sidebar.py -v
```
Expected: `ModuleNotFoundError: No module named 'components.sidebar'`

- [ ] **Step 3: Create `components/sidebar.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont
from theme import ThemeManager

NAV_ITEMS = [
    ("dashboard",     "⊞  Dashboard"),
    ("data_import",   "⬆  Data Import"),
    ("config_editor", "⚙  Config Editor"),
    ("notifications", "🔔  Notifications"),
    ("profile",       "👤  My Profile"),
]

BROKERS = [
    ("Sharekhan",       "status_red"),
    ("ReliableSoftware","status_blue"),
    ("NiftyInvest",     "status_orange"),
]


class Sidebar(QWidget):
    navigate = Signal(str)

    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._buttons: dict[str, QPushButton] = {}
        self._active = "dashboard"
        self.setMinimumWidth(180)
        self.setMaximumWidth(180)
        self._build()

    def _build(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # Logo
        logo = QLabel("BROKER\nFILE SYNC")
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        logo.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        logo.setContentsMargins(0, 20, 0, 20)
        layout.addWidget(logo)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep)

        # Nav items
        for key, label in NAV_ITEMS:
            btn = QPushButton(label)
            btn.setFlat(True)
            btn.setFixedHeight(40)
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._on_nav(k))
            btn.setStyleSheet(self._nav_style(key == self._active))
            self._buttons[key] = btn
            layout.addWidget(btn)

        layout.addSpacing(16)

        # Broker Files section
        broker_label = QLabel("BROKER FILES")
        broker_label.setFont(QFont("Courier New", 9))
        broker_label.setContentsMargins(14, 4, 0, 4)
        layout.addWidget(broker_label)

        for name, color_token in BROKERS:
            row = QWidget()
            row_layout = QHBoxLayout(row)
            row_layout.setContentsMargins(14, 4, 8, 4)
            row_layout.setSpacing(8)

            dot = QLabel("●")
            dot.setFont(QFont("Courier New", 10))
            dot.setStyleSheet(f"color: {self._theme.get(color_token)};")
            dot.setFixedWidth(14)

            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Courier New", 11))

            row_layout.addWidget(dot)
            row_layout.addWidget(name_lbl)
            row_layout.addStretch()
            layout.addWidget(row)

        layout.addStretch()

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        layout.addWidget(sep2)

        # User widget
        user_widget = QWidget()
        user_widget.setObjectName("userWidget")
        user_layout = QHBoxLayout(user_widget)
        user_layout.setContentsMargins(10, 8, 10, 8)
        user_layout.setSpacing(8)

        avatar = QLabel("RJ")
        avatar.setFixedSize(32, 32)
        avatar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        avatar.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        avatar.setStyleSheet(
            f"background: {self._theme.get('accent')}; color: {self._theme.get('background')};"
            "border-radius: 16px;"
        )

        user_info = QVBoxLayout()
        user_info.setSpacing(0)
        name_lbl2 = QLabel("Rajesh")
        name_lbl2.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        email_lbl = QLabel("rajesh.kumar@exa...")
        email_lbl.setFont(QFont("Courier New", 9))
        user_info.addWidget(name_lbl2)
        user_info.addWidget(email_lbl)

        user_layout.addWidget(avatar)
        user_layout.addLayout(user_info)
        layout.addWidget(user_widget)

    def _nav_style(self, active: bool) -> str:
        if active:
            return (
                f"background: {self._theme.get('accent')};"
                f"color: {self._theme.get('background')};"
                "text-align: left; padding-left: 14px; border: none;"
                "font-family: 'Courier New', monospace; font-size: 13px;"
            )
        return (
            f"color: {self._theme.get('text_secondary')};"
            "background: transparent; text-align: left; padding-left: 14px;"
            "border: none; font-family: 'Courier New', monospace; font-size: 13px;"
        )

    def _on_nav(self, key: str):
        self.set_active(key)
        self.navigate.emit(key)

    def set_active(self, screen_name: str):
        self._active = screen_name
        for key, btn in self._buttons.items():
            btn.setStyleSheet(self._nav_style(key == screen_name))
            btn.setChecked(key == screen_name)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_sidebar.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add components/sidebar.py tests/test_sidebar.py
git commit -m "feat: add Sidebar component"
```

---

### Task 3: TopBar component

**Files:**
- Create: `components/topbar.py`
- Test: `tests/test_topbar.py`

**Interfaces:**
- Consumes: `ThemeManager.get(token)`, `ThemeManager.toggle()`, `ThemeManager.current_mode`.
- Produces:
  - `TopBar(theme: ThemeManager, parent=None)` — `QWidget`, fixed height 40px.
  - `TopBar.theme_toggled` — `Signal()` emitted after theme toggle (so parent can repaint).

- [ ] **Step 1: Write failing test**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def topbar(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    tm = ThemeManager(qapp)
    return TopBar(tm)

def test_topbar_fixed_height(topbar):
    assert topbar.minimumHeight() == 40
    assert topbar.maximumHeight() == 40

def test_theme_toggled_signal_exists(topbar):
    assert hasattr(topbar, "theme_toggled")
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_topbar.py -v
```
Expected: `ModuleNotFoundError: No module named 'components.topbar'`

- [ ] **Step 3: Create `components/topbar.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QHBoxLayout, QLabel, QPushButton, QMenu, QSizePolicy
)
from PySide6.QtCore import Signal, Qt
from PySide6.QtGui import QFont, QAction
from theme import ThemeManager

MENUS = {
    "File":          ["New Session", "Open Config", "---", "Exit"],
    "Edit":          ["Undo", "Redo", "---", "Preferences"],
    "View":          ["Zoom In", "Zoom Out", "---", "Full Screen"],
    "Notifications": ["Mark All Read", "Clear All"],
    "Profile":       ["My Profile", "---", "Logout"],
    "Help":          ["Documentation", "About Broker File Sync"],
}


class TopBar(QWidget):
    theme_toggled = Signal()

    def __init__(self, theme: ThemeManager, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setMinimumHeight(40)
        self.setMaximumHeight(40)
        self._build()

    def _build(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 0, 12, 0)
        layout.setSpacing(4)

        app_label = QLabel("BROKER FILE SYNC")
        app_label.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        layout.addWidget(app_label)

        layout.addSpacing(16)

        for menu_name, items in MENUS.items():
            btn = QPushButton(menu_name)
            btn.setFlat(True)
            btn.setFont(QFont("Courier New", 11))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"color: {self._theme.get('text_secondary')};"
                "background: transparent; border: none; padding: 0 6px;"
            )
            menu = QMenu(self)
            for item in items:
                if item == "---":
                    menu.addSeparator()
                else:
                    menu.addAction(QAction(item, self))
            btn.setMenu(menu)
            layout.addWidget(btn)

        layout.addStretch()

        self._toggle_btn = QPushButton(self._theme_icon())
        self._toggle_btn.setFlat(True)
        self._toggle_btn.setFixedSize(32, 32)
        self._toggle_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._toggle_btn.setFont(QFont("Courier New", 14))
        self._toggle_btn.setToolTip("Toggle dark/light mode")
        self._toggle_btn.setStyleSheet("background: transparent; border: none;")
        self._toggle_btn.clicked.connect(self._on_toggle)
        layout.addWidget(self._toggle_btn)

        restart_btn = QPushButton("⟳ Restart")
        restart_btn.setFont(QFont("Courier New", 11))
        restart_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        restart_btn.setFixedHeight(26)
        restart_btn.clicked.connect(self._on_restart)
        layout.addWidget(restart_btn)

    def _theme_icon(self) -> str:
        return "☀" if self._theme.current_mode == "dark" else "🌙"

    def _on_toggle(self):
        self._theme.toggle()
        self._toggle_btn.setText(self._theme_icon())
        self.theme_toggled.emit()

    def _on_restart(self):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Restart",
            "Reset the application to its initial state?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.theme_toggled.emit()
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_topbar.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add components/topbar.py tests/test_topbar.py
git commit -m "feat: add TopBar component with theme toggle and menus"
```

---

### Task 4: MainWindow (shell + navigation)

**Files:**
- Create: `app_window.py`
- Test: `tests/test_app_window.py`

**Interfaces:**
- Consumes: `Sidebar.navigate Signal`, `Sidebar.set_active(str)`, `TopBar.theme_toggled Signal`, `ThemeManager`.
- Produces:
  - `MainWindow(controller: AppController)` — `QMainWindow`, 1280×800, min 1100×700.
  - `MainWindow.navigate(screen_name: str)` — switches `QStackedWidget` to named screen, updates sidebar active state.
  - Screen names: `"dashboard"`, `"data_import"`, `"config_editor"`, `"notifications"`, `"profile"`.

- [ ] **Step 1: Write failing test**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)

def test_main_window_creates(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    assert w is not None

def test_navigate_does_not_raise(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    for name in ["dashboard", "data_import", "config_editor", "notifications", "profile"]:
        w.navigate(name)
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_app_window.py -v
```
Expected: `ModuleNotFoundError: No module named 'app_window'`

- [ ] **Step 3: Create `app_window.py`**

```python
from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget
from PySide6.QtCore import Qt
from components.sidebar import Sidebar
from components.topbar import TopBar


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker File Sync")
        self.resize(1280, 800)
        self.setMinimumSize(1100, 700)
        self._build()

    def _build(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self._topbar = TopBar(self._controller.theme)
        self._topbar.theme_toggled.connect(self._on_theme_toggled)
        root.addWidget(self._topbar)

        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)
        body.setSpacing(0)

        self._sidebar = Sidebar(self._controller.theme)
        self._sidebar.navigate.connect(self.navigate)
        body.addWidget(self._sidebar)

        self._stack = QStackedWidget()
        body.addWidget(self._stack, 1)

        root.addLayout(body)

        self._screens: dict = {}
        self._register_screens()

    def _register_screens(self):
        from screens.dashboard import DashboardScreen
        from screens.data_import import DataImportScreen
        from screens.config_editor import ConfigEditorScreen
        from screens.notifications import NotificationsScreen
        from screens.profile import ProfileScreen

        screens = [
            ("dashboard",     DashboardScreen(self._controller)),
            ("data_import",   DataImportScreen(self._controller)),
            ("config_editor", ConfigEditorScreen(self._controller)),
            ("notifications", NotificationsScreen(self._controller)),
            ("profile",       ProfileScreen(self._controller)),
        ]
        for name, widget in screens:
            self._screens[name] = widget
            self._stack.addWidget(widget)

    def navigate(self, screen_name: str):
        if screen_name in self._screens:
            self._stack.setCurrentWidget(self._screens[screen_name])
            self._sidebar.set_active(screen_name)

    def _on_theme_toggled(self):
        self._controller.theme.apply()
        self._sidebar.repaint()
        self._topbar.repaint()
        for w in self._screens.values():
            w.repaint()
```

- [ ] **Step 4: Create screen stubs** (so `_register_screens` doesn't fail in tests)

Create `screens/dashboard.py`:
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import Qt

class DashboardScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Dashboard — coming in next task"))
```

Create `screens/data_import.py`:
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class DataImportScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Data Import — coming in next task"))
```

Create `screens/config_editor.py`:
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class ConfigEditorScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Config Editor — coming in next task"))
```

Create `screens/notifications.py`:
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class NotificationsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Notifications — coming in next task"))
```

Create `screens/profile.py`:
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel

class ProfileScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("My Profile — coming in next task"))
```

- [ ] **Step 5: Run tests — verify pass**

```bash
python -m pytest tests/test_app_window.py -v
```
Expected: 2 PASSED

- [ ] **Step 6: Commit**

```bash
git add app_window.py screens/ tests/test_app_window.py
git commit -m "feat: add MainWindow shell with QStackedWidget navigation"
```

---

### Task 5: Login and Signup screens

**Files:**
- Modify: `screens/login.py` (replace stub with full implementation)
- Modify: `screens/signup.py` (replace stub with full implementation)
- Test: `tests/test_login_signup.py`

**Interfaces:**
- Consumes: `AppController.show_main_window()`, `AppController.show_signup()`, `AppController.show_login()`.
- Produces:
  - `LoginScreen(controller)` — standalone `QWidget` (no sidebar). 1000×650 window. Centered card.
  - `SignupScreen(controller)` — same layout pattern as Login.

- [ ] **Step 1: Write failing tests**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)

def test_login_screen_creates(controller):
    from screens.login import LoginScreen
    s = LoginScreen(controller)
    assert s is not None

def test_signup_screen_creates(controller):
    from screens.signup import SignupScreen
    s = SignupScreen(controller)
    assert s is not None

def test_login_has_login_button(controller):
    from screens.login import LoginScreen
    from PySide6.QtWidgets import QPushButton
    s = LoginScreen(controller)
    buttons = s.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    assert any("Login" in t or "login" in t.lower() for t in labels)

def test_signup_has_create_button(controller):
    from screens.signup import SignupScreen
    from PySide6.QtWidgets import QPushButton
    s = SignupScreen(controller)
    buttons = s.findChildren(QPushButton)
    labels = [b.text() for b in buttons]
    assert any("Create" in t or "Account" in t for t in labels)
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_login_signup.py -v
```
Expected: FAIL (stubs don't have real buttons)

- [ ] **Step 3: Create full `screens/login.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class LoginScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker File Sync — Login")
        self.resize(1000, 650)
        self.setMinimumSize(800, 550)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        h = QHBoxLayout()
        h.addStretch()

        card = QFrame()
        card.setFixedWidth(420)
        card.setObjectName("loginCard")
        t = self._controller.theme
        card.setStyleSheet(
            f"QFrame#loginCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 40, 40, 40)
        card_layout.setSpacing(16)

        title = QLabel("BROKER FILE SYNC")
        title.setFont(QFont("Courier New", 20, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = QLabel("Excel Processing Software")
        subtitle.setFont(QFont("Courier New", 11))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(16)

        email_label = QLabel("EMAIL")
        email_label.setFont(QFont("Courier New", 10))
        email_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(email_label)

        self._email = QLineEdit()
        self._email.setPlaceholderText("Enter your email")
        self._email.setFixedHeight(38)
        card_layout.addWidget(self._email)

        pwd_label = QLabel("PASSWORD")
        pwd_label.setFont(QFont("Courier New", 10))
        pwd_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(pwd_label)

        self._password = QLineEdit()
        self._password.setPlaceholderText("Enter your password")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.setFixedHeight(38)
        card_layout.addWidget(self._password)

        card_layout.addSpacing(8)

        login_btn = QPushButton("Login")
        login_btn.setFixedHeight(42)
        login_btn.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        login_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        login_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px;"
        )
        login_btn.clicked.connect(self._controller.show_main_window)
        card_layout.addWidget(login_btn)

        signup_link = QPushButton("Don't have an account? Sign Up")
        signup_link.setFlat(True)
        signup_link.setCursor(Qt.CursorShape.PointingHandCursor)
        signup_link.setFont(QFont("Courier New", 11))
        signup_link.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        signup_link.clicked.connect(self._controller.show_signup)
        card_layout.addWidget(signup_link, alignment=Qt.AlignmentFlag.AlignCenter)

        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()
```

- [ ] **Step 4: Create full `screens/signup.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QFrame
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class SignupScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self.setWindowTitle("Broker File Sync — Sign Up")
        self.resize(1000, 700)
        self.setMinimumSize(800, 600)
        self._build()

    def _build(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addStretch()

        h = QHBoxLayout()
        h.addStretch()

        card = QFrame()
        card.setFixedWidth(420)
        card.setObjectName("signupCard")
        t = self._controller.theme
        card.setStyleSheet(
            f"QFrame#signupCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )

        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(40, 40, 40, 40)
        card_layout.setSpacing(14)

        title = QLabel("CREATE ACCOUNT")
        title.setFont(QFont("Courier New", 18, QFont.Weight.Bold))
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        card_layout.addWidget(title)

        subtitle = QLabel("Broker File Sync")
        subtitle.setFont(QFont("Courier New", 11))
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        card_layout.addWidget(subtitle)

        card_layout.addSpacing(12)

        for field_label, placeholder, echo in [
            ("FULL NAME",        "Enter your full name",      False),
            ("EMAIL",            "Enter your email",          False),
            ("PASSWORD",         "Create a password",         True),
            ("CONFIRM PASSWORD", "Confirm your password",     True),
        ]:
            lbl = QLabel(field_label)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            card_layout.addWidget(lbl)

            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFixedHeight(36)
            if echo:
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            card_layout.addWidget(inp)

        card_layout.addSpacing(8)

        create_btn = QPushButton("Create Account")
        create_btn.setFixedHeight(42)
        create_btn.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        create_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        create_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px;"
        )
        create_btn.clicked.connect(self._controller.show_main_window)
        card_layout.addWidget(create_btn)

        login_link = QPushButton("Already have an account? Login")
        login_link.setFlat(True)
        login_link.setCursor(Qt.CursorShape.PointingHandCursor)
        login_link.setFont(QFont("Courier New", 11))
        login_link.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        login_link.clicked.connect(self._controller.show_login)
        card_layout.addWidget(login_link, alignment=Qt.AlignmentFlag.AlignCenter)

        h.addWidget(card)
        h.addStretch()
        outer.addLayout(h)
        outer.addStretch()
```

- [ ] **Step 5: Run tests — verify pass**

```bash
python -m pytest tests/test_login_signup.py -v
```
Expected: 4 PASSED

- [ ] **Step 6: Commit**

```bash
git add screens/login.py screens/signup.py tests/test_login_signup.py
git commit -m "feat: add Login and Signup screens"
```

---

### Task 6: Dashboard screen

**Files:**
- Modify: `screens/dashboard.py` (replace stub with full implementation)
- Test: `tests/test_dashboard.py`

**Interfaces:**
- Consumes: `AppController.theme`, `AppController` (for "Go to Data Import" navigation).
- Produces: `DashboardScreen(controller)` — full dashboard with stat cards, broker sources, activity panel, info banner.

- [ ] **Step 1: Write failing test**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def dashboard(qapp):
    from app import AppController
    from screens.dashboard import DashboardScreen
    ctrl = AppController(qapp)
    return DashboardScreen(ctrl)

def test_dashboard_creates(dashboard):
    assert dashboard is not None

def test_dashboard_has_stat_cards(dashboard):
    from PySide6.QtWidgets import QFrame
    frames = dashboard.findChildren(QFrame)
    assert len(frames) >= 4
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_dashboard.py -v
```
Expected: FAIL (stub returns no frames)

- [ ] **Step 3: Create full `screens/dashboard.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class StatCard(QFrame):
    def __init__(self, label: str, value: str, icon: str, theme):
        super().__init__()
        t = theme
        self.setObjectName("statCard")
        self.setStyleSheet(
            f"QFrame#statCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(120)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFont(QFont("Courier New", 9))
        lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Courier New", 16))
        icon_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        top_row.addWidget(lbl)
        top_row.addStretch()
        top_row.addWidget(icon_lbl)
        layout.addLayout(top_row)

        val_lbl = QLabel(value)
        val_lbl.setFont(QFont("Courier New", 36, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {t.get('text_primary')};")
        layout.addWidget(val_lbl)


class DashboardScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header
        title = QLabel("Dashboard")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("File import overview and processing activity")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Stat cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        stats = [
            ("TOTAL FILES IMPORTED",  "0",   "📄"),
            ("TOTAL ROWS PROCESSED",  "0",   "⊞"),
            ("IMPORT ERRORS",         "0",   "⚠"),
            ("BROKER SOURCES ACTIVE", "0/3", "⬡"),
        ]
        for label, value, icon in stats:
            cards_row.addWidget(StatCard(label, value, icon, t))
        layout.addLayout(cards_row)

        # Two-column section
        two_col = QHBoxLayout()
        two_col.setSpacing(16)

        # Broker Sources
        broker_panel = QFrame()
        broker_panel.setObjectName("brokerPanel")
        broker_panel.setStyleSheet(
            f"QFrame#brokerPanel {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        bp_layout = QVBoxLayout(broker_panel)
        bp_layout.setContentsMargins(16, 16, 16, 16)
        bp_layout.setSpacing(12)

        bp_title = QLabel("BROKER SOURCES")
        bp_title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        bp_layout.addWidget(bp_title)

        brokers = [
            ("Sharekhan",        t.get("status_red")),
            ("ReliableSoftware", t.get("status_blue")),
            ("NiftyInvest",      t.get("status_orange")),
        ]
        for name, color in brokers:
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setFixedWidth(16)
            dot.setStyleSheet(f"color: {color};")
            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
            stats_lbl = QLabel("0 files – 0 imported")
            stats_lbl.setFont(QFont("Courier New", 11))
            stats_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            status_lbl = QLabel("Awaiting")
            status_lbl.setFont(QFont("Courier New", 11))
            status_lbl.setStyleSheet(f"color: {t.get('status_blue')};")
            row.addWidget(dot)
            row.addWidget(name_lbl)
            row.addWidget(stats_lbl)
            row.addStretch()
            row.addWidget(status_lbl)
            bp_layout.addLayout(row)

        bp_layout.addStretch()
        two_col.addWidget(broker_panel, 1)

        # Recent File Activity
        activity_panel = QFrame()
        activity_panel.setObjectName("activityPanel")
        activity_panel.setStyleSheet(
            f"QFrame#activityPanel {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        ap_layout = QVBoxLayout(activity_panel)
        ap_layout.setContentsMargins(16, 16, 16, 16)
        ap_layout.setSpacing(12)

        ap_header = QHBoxLayout()
        ap_title = QLabel("RECENT FILE ACTIVITY")
        ap_title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        total_lbl = QLabel("0 total")
        total_lbl.setFont(QFont("Courier New", 10))
        total_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        ap_header.addWidget(ap_title)
        ap_header.addStretch()
        ap_header.addWidget(total_lbl)
        ap_layout.addLayout(ap_header)

        ap_layout.addStretch()
        folder_icon = QLabel("📁")
        folder_icon.setFont(QFont("Courier New", 32))
        folder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        folder_icon.setStyleSheet(f"color: {t.get('text_secondary')};")
        ap_layout.addWidget(folder_icon)

        empty_msg = QLabel("No files imported yet.")
        empty_msg.setFont(QFont("Courier New", 14))
        empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(empty_msg)

        go_import_btn = QPushButton("Go to Data Import to upload broker files.")
        go_import_btn.setFlat(True)
        go_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_import_btn.setFont(QFont("Courier New", 12))
        go_import_btn.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        go_import_btn.clicked.connect(
            lambda: self._controller.show_main_window() or True
        )
        ap_layout.addWidget(go_import_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        ap_layout.addStretch()
        two_col.addWidget(activity_panel, 1)

        layout.addLayout(two_col)

        # Info banner
        banner = QFrame()
        banner.setObjectName("infoBanner")
        banner.setStyleSheet(
            f"QFrame#infoBanner {{ background: {t.get('info_banner_bg')};"
            f"border-left: 4px solid {t.get('accent')}; border-radius: 4px; }}"
        )
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        info_icon = QLabel("ℹ")
        info_icon.setFont(QFont("Courier New", 16))
        info_icon.setStyleSheet(f"color: {t.get('accent')};")
        info_icon.setFixedWidth(24)
        banner_text = QLabel(
            "Before importing, verify your column mappings in "
            "<b>Config Editor → Column Name Mapping</b> and script names in "
            "<b>Script Name Mapping</b>."
        )
        banner_text.setFont(QFont("Courier New", 11))
        banner_text.setWordWrap(True)
        banner_layout.addWidget(info_icon)
        banner_layout.addWidget(banner_text)
        layout.addWidget(banner)

        layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_dashboard.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add screens/dashboard.py tests/test_dashboard.py
git commit -m "feat: add Dashboard screen with stat cards and broker sources"
```

---

### Task 7: Data Import screen

**Files:**
- Modify: `screens/data_import.py` (replace stub)
- Test: `tests/test_data_import.py`

**Interfaces:**
- Consumes: `AppController.theme`.
- Produces: `DataImportScreen(controller)` — file picker, broker selector, import button with progress animation, log area.

- [ ] **Step 1: Write failing test**

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
    from screens.data_import import DataImportScreen
    return DataImportScreen(AppController(qapp))

def test_data_import_creates(screen):
    assert screen is not None

def test_has_import_button(screen):
    from PySide6.QtWidgets import QPushButton
    buttons = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Import" in t for t in buttons)

def test_has_combobox(screen):
    from PySide6.QtWidgets import QComboBox
    combos = screen.findChildren(QComboBox)
    assert len(combos) >= 1
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_data_import.py -v
```
Expected: FAIL (stub has no buttons/combobox)

- [ ] **Step 3: Create full `screens/data_import.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QProgressBar, QPlainTextEdit, QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from datetime import datetime


class DataImportScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_file = None
        self._progress_value = 0
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Data Import")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Upload broker Excel files for processing")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Broker selector
        row = QHBoxLayout()
        row.setSpacing(12)
        broker_lbl = QLabel("SELECT BROKER")
        broker_lbl.setFont(QFont("Courier New", 10))
        broker_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._broker_combo = QComboBox()
        self._broker_combo.addItems(["Sharekhan", "ReliableSoftware", "NiftyInvest"])
        self._broker_combo.setFixedHeight(36)
        self._broker_combo.setMinimumWidth(220)
        row.addWidget(broker_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._broker_combo)
        row.addStretch()
        layout.addLayout(row)

        # Drop area
        self._drop_area = QFrame()
        self._drop_area.setObjectName("dropArea")
        self._drop_area.setFixedHeight(130)
        self._drop_area.setStyleSheet(
            f"QFrame#dropArea {{ background: {t.get('card_bg')};"
            f"border: 2px dashed {t.get('border')}; border-radius: 8px; }}"
        )
        self._drop_area.setCursor(Qt.CursorShape.PointingHandCursor)
        drop_layout = QVBoxLayout(self._drop_area)
        self._drop_label = QLabel("📂  Drop Excel files here or click to browse")
        self._drop_label.setFont(QFont("Courier New", 13))
        self._drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        drop_layout.addWidget(self._drop_label)
        self._drop_area.mousePressEvent = lambda _: self._browse_file()
        layout.addWidget(self._drop_area)

        self._file_name_lbl = QLabel("")
        self._file_name_lbl.setFont(QFont("Courier New", 11))
        self._file_name_lbl.setStyleSheet(f"color: {t.get('accent')};")
        layout.addWidget(self._file_name_lbl)

        # Import button
        import_btn = QPushButton("⬆  Import Files")
        import_btn.setFixedHeight(42)
        import_btn.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px;"
        )
        import_btn.clicked.connect(self._start_import)
        layout.addWidget(import_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(10)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Log area
        log_lbl = QLabel("IMPORT LOG")
        log_lbl.setFont(QFont("Courier New", 10))
        log_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(log_lbl)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Courier New", 11))
        self._log.setMinimumHeight(160)
        self._log.setStyleSheet(
            f"background: {t.get('card_bg')}; border: 1px solid {t.get('border')};"
            "border-radius: 4px;"
        )
        layout.addWidget(self._log)
        layout.addStretch()

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel File", "", "Excel Files (*.xlsx *.xls)"
        )
        if path:
            self._selected_file = path
            filename = path.split("/")[-1]
            self._file_name_lbl.setText(f"Selected: {filename}")

    def _start_import(self):
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._progress_value = 0
        self._log.appendPlainText(
            f"[{datetime.now().strftime('%H:%M:%S')}] Starting import for "
            f"{self._broker_combo.currentText()}..."
        )
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_progress)
        self._timer.start(40)

    def _tick_progress(self):
        self._progress_value += 2
        self._progress.setValue(self._progress_value)
        if self._progress_value >= 100:
            self._timer.stop()
            ts = datetime.now().strftime("%H:%M:%S")
            self._log.appendPlainText(f"[{ts}] Reading file headers...")
            self._log.appendPlainText(f"[{ts}] Validating column mappings...")
            self._log.appendPlainText(f"[{ts}] Processing rows...")
            self._log.appendPlainText(f"[{ts}] Import complete! 0 rows processed.")
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_data_import.py -v
```
Expected: 3 PASSED

- [ ] **Step 5: Commit**

```bash
git add screens/data_import.py tests/test_data_import.py
git commit -m "feat: add Data Import screen with file picker and progress animation"
```

---

### Task 8: Config Editor screen

**Files:**
- Modify: `screens/config_editor.py` (replace stub)
- Test: `tests/test_config_editor.py`

**Interfaces:**
- Consumes: `AppController.theme`.
- Produces: `ConfigEditorScreen(controller)` — two-tab editable table interface.

- [ ] **Step 1: Write failing test**

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
    from screens.config_editor import ConfigEditorScreen
    return ConfigEditorScreen(AppController(qapp))

def test_config_editor_creates(screen):
    assert screen is not None

def test_has_tab_widget(screen):
    from PySide6.QtWidgets import QTabWidget
    tabs = screen.findChildren(QTabWidget)
    assert len(tabs) == 1

def test_has_two_tabs(screen):
    from PySide6.QtWidgets import QTabWidget
    tab = screen.findChildren(QTabWidget)[0]
    assert tab.count() == 2

def test_has_save_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Save" in t for t in btns)
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_config_editor.py -v
```
Expected: FAIL

- [ ] **Step 3: Create full `screens/config_editor.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


COLUMN_MAPPING_DATA = [
    ("Date",          "trade_date"),
    ("Symbol",        "scrip_symbol"),
    ("Quantity",      "trade_qty"),
    ("Price",         "trade_price"),
    ("Transaction",   "txn_type"),
]

SCRIPT_MAPPING_DATA = [
    ("SCR001", "NSE_EQ_PROCESSOR",    "Sharekhan"),
    ("SCR002", "BSE_EQ_PROCESSOR",    "ReliableSoftware"),
    ("SCR003", "FNO_PROCESSOR",       "NiftyInvest"),
    ("SCR004", "COMMODITY_PROCESSOR", "Sharekhan"),
]


class ConfigEditorScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Config Editor")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Manage column and script name mappings")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.setFont(QFont("Courier New", 12))

        # Tab 1: Column Name Mapping
        col_tab = QWidget()
        col_layout = QVBoxLayout(col_tab)
        col_layout.setContentsMargins(16, 16, 16, 16)

        col_table = QTableWidget(len(COLUMN_MAPPING_DATA), 2)
        col_table.setHorizontalHeaderLabels(["SOURCE COLUMN", "TARGET COLUMN"])
        col_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        col_table.verticalHeader().setVisible(False)
        col_table.setFont(QFont("Courier New", 12))
        for row, (src, tgt) in enumerate(COLUMN_MAPPING_DATA):
            col_table.setItem(row, 0, QTableWidgetItem(src))
            col_table.setItem(row, 1, QTableWidgetItem(tgt))
        col_layout.addWidget(col_table)
        tabs.addTab(col_tab, "Column Name Mapping")

        # Tab 2: Script Name Mapping
        scr_tab = QWidget()
        scr_layout = QVBoxLayout(scr_tab)
        scr_layout.setContentsMargins(16, 16, 16, 16)

        scr_table = QTableWidget(len(SCRIPT_MAPPING_DATA), 3)
        scr_table.setHorizontalHeaderLabels(["SCRIPT ID", "SCRIPT NAME", "BROKER"])
        scr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scr_table.verticalHeader().setVisible(False)
        scr_table.setFont(QFont("Courier New", 12))
        for row, (sid, name, broker) in enumerate(SCRIPT_MAPPING_DATA):
            scr_table.setItem(row, 0, QTableWidgetItem(sid))
            scr_table.setItem(row, 1, QTableWidgetItem(name))
            scr_table.setItem(row, 2, QTableWidgetItem(broker))
        scr_layout.addWidget(scr_table)
        tabs.addTab(scr_tab, "Script Name Mapping")

        layout.addWidget(tabs)

        save_btn = QPushButton("💾  Save Configuration")
        save_btn.setFixedHeight(40)
        save_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; padding: 0 20px;"
        )
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def _on_save(self):
        QMessageBox.information(self, "Saved", "Configuration saved successfully.")
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_config_editor.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add screens/config_editor.py tests/test_config_editor.py
git commit -m "feat: add Config Editor screen with editable mapping tables"
```

---

### Task 9: Notifications screen

**Files:**
- Modify: `screens/notifications.py` (replace stub)
- Test: `tests/test_notifications.py`

**Interfaces:**
- Consumes: `AppController.theme`.
- Produces: `NotificationsScreen(controller)` — scrollable list of 5 dummy notifications, mark-all-read button.

- [ ] **Step 1: Write failing test**

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
    from screens.notifications import NotificationsScreen
    return NotificationsScreen(AppController(qapp))

def test_notifications_creates(screen):
    assert screen is not None

def test_has_mark_all_read_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("read" in t.lower() or "Read" in t for t in btns)
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_notifications.py -v
```
Expected: FAIL

- [ ] **Step 3: Create full `screens/notifications.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


NOTIFICATIONS = [
    ("info",    "Import Ready",          "Sharekhan files are queued for import.", "2026-06-19  11:30"),
    ("success", "Import Complete",       "ReliableSoftware batch processed: 0 rows.", "2026-06-19  10:15"),
    ("warning", "Config Warning",        "Script SCR003 mapping not found for NiftyInvest.", "2026-06-18  17:42"),
    ("error",   "Import Failed",         "Failed to read header row in sharekhan_june.xlsx.", "2026-06-18  09:05"),
    ("info",    "System Update",         "Broker File Sync v2.4.1 is available.", "2026-06-17  08:00"),
]

ICONS = {"info": ("ℹ", "status_blue"), "success": ("✔", "accent"),
         "warning": ("⚠", "status_orange"), "error": ("✖", "status_red")}


class NotificationsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._icon_labels = []
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        header_row = QHBoxLayout()
        title = QLabel("Notifications")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        mark_btn = QPushButton("Mark All as Read")
        mark_btn.setFixedHeight(34)
        mark_btn.setFont(QFont("Courier New", 11))
        mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mark_btn.clicked.connect(self._mark_all_read)
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(mark_btn)
        layout.addLayout(header_row)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(10)

        for kind, title_text, body, ts in NOTIFICATIONS:
            item = QFrame()
            item.setObjectName("notifItem")
            item.setStyleSheet(
                f"QFrame#notifItem {{ background: {t.get('card_bg')};"
                f"border: 1px solid {t.get('border')}; border-radius: 6px; }}"
            )
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(16, 12, 16, 12)
            item_layout.setSpacing(14)

            icon_char, color_token = ICONS[kind]
            icon_lbl = QLabel(icon_char)
            icon_lbl.setFont(QFont("Courier New", 18))
            icon_lbl.setFixedWidth(24)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            icon_lbl.setStyleSheet(f"color: {t.get(color_token)};")
            self._icon_labels.append(icon_lbl)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            t_title = QLabel(title_text)
            t_title.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            t_body = QLabel(body)
            t_body.setFont(QFont("Courier New", 11))
            t_body.setStyleSheet(f"color: {t.get('text_secondary')};")
            text_col.addWidget(t_title)
            text_col.addWidget(t_body)

            ts_lbl = QLabel(ts)
            ts_lbl.setFont(QFont("Courier New", 10))
            ts_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            ts_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

            item_layout.addWidget(icon_lbl)
            item_layout.addLayout(text_col, 1)
            item_layout.addWidget(ts_lbl)
            c_layout.addWidget(item)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _mark_all_read(self):
        t = self._controller.theme
        for lbl in self._icon_labels:
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_notifications.py -v
```
Expected: 2 PASSED

- [ ] **Step 5: Commit**

```bash
git add screens/notifications.py tests/test_notifications.py
git commit -m "feat: add Notifications screen"
```

---

### Task 10: My Profile screen

**Files:**
- Modify: `screens/profile.py` (replace stub)
- Test: `tests/test_profile.py`

**Interfaces:**
- Consumes: `AppController.theme`, `AppController.show_login()`, `ThemeManager.toggle()`.
- Produces: `ProfileScreen(controller)` — user info, theme toggle checkbox, change password dialog, logout button.

- [ ] **Step 1: Write failing test**

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
    from screens.profile import ProfileScreen
    return ProfileScreen(AppController(qapp))

def test_profile_creates(screen):
    assert screen is not None

def test_has_logout_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Logout" in t or "logout" in t.lower() for t in btns)

def test_has_theme_checkbox(screen):
    from PySide6.QtWidgets import QCheckBox
    checks = screen.findChildren(QCheckBox)
    assert len(checks) >= 1

def test_has_change_password_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Password" in t for t in btns)
```

- [ ] **Step 2: Run — verify fail**

```bash
python -m pytest tests/test_profile.py -v
```
Expected: FAIL

- [ ] **Step 3: Create full `screens/profile.py`**

```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QCheckBox, QDialog, QDialogButtonBox, QMessageBox
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class ProfileScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("My Profile")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Account settings and preferences")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # User info card
        info_card = QFrame()
        info_card.setObjectName("infoCard")
        info_card.setStyleSheet(
            f"QFrame#infoCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(24, 20, 24, 20)
        info_layout.setSpacing(14)

        section_lbl = QLabel("USER INFORMATION")
        section_lbl.setFont(QFont("Courier New", 10))
        section_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        info_layout.addWidget(section_lbl)

        for field_label, value in [
            ("FULL NAME", "Rajesh Kumar"),
            ("EMAIL",     "rajesh.kumar@example.com"),
            ("ROLE",      "Administrator"),
        ]:
            row = QHBoxLayout()
            lbl = QLabel(field_label)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setFixedWidth(120)
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            val = QLineEdit(value)
            val.setReadOnly(True)
            val.setFixedHeight(34)
            val.setStyleSheet(
                f"background: {t.get('input_bg')}; color: {t.get('text_primary')};"
                f"border: 1px solid {t.get('border')}; border-radius: 4px; padding: 0 10px;"
            )
            row.addWidget(lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
            row.addWidget(val, 1)
            info_layout.addLayout(row)

        layout.addWidget(info_card)

        # Preferences card
        pref_card = QFrame()
        pref_card.setObjectName("prefCard")
        pref_card.setStyleSheet(
            f"QFrame#prefCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        pref_layout = QVBoxLayout(pref_card)
        pref_layout.setContentsMargins(24, 20, 24, 20)
        pref_layout.setSpacing(14)

        pref_lbl = QLabel("PREFERENCES")
        pref_lbl.setFont(QFont("Courier New", 10))
        pref_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        pref_layout.addWidget(pref_lbl)

        theme_row = QHBoxLayout()
        theme_lbl = QLabel("Dark Mode")
        theme_lbl.setFont(QFont("Courier New", 13))
        self._theme_check = QCheckBox()
        self._theme_check.setChecked(t.current_mode == "dark")
        self._theme_check.setCursor(Qt.CursorShape.PointingHandCursor)
        self._theme_check.stateChanged.connect(self._on_theme_toggle)
        theme_row.addWidget(theme_lbl)
        theme_row.addWidget(self._theme_check)
        theme_row.addStretch()
        pref_layout.addLayout(theme_row)

        layout.addWidget(pref_card)

        # Action buttons
        btn_row = QHBoxLayout()
        btn_row.setSpacing(12)

        pwd_btn = QPushButton("🔑  Change Password")
        pwd_btn.setFixedHeight(40)
        pwd_btn.setFont(QFont("Courier New", 12))
        pwd_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        pwd_btn.clicked.connect(self._open_change_password)
        btn_row.addWidget(pwd_btn)

        logout_btn = QPushButton("⏻  Logout")
        logout_btn.setFixedHeight(40)
        logout_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        logout_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        logout_btn.setStyleSheet(
            f"background: {t.get('destructive')}; color: white;"
            "border: none; border-radius: 4px; padding: 0 20px;"
        )
        logout_btn.clicked.connect(self._controller.show_login)
        btn_row.addWidget(logout_btn)
        btn_row.addStretch()

        layout.addLayout(btn_row)
        layout.addStretch()

    def _on_theme_toggle(self, state):
        t = self._controller.theme
        wants_dark = bool(state)
        if (wants_dark and t.current_mode != "dark") or \
           (not wants_dark and t.current_mode != "light"):
            t.toggle()

    def _open_change_password(self):
        t = self._controller.theme
        dialog = QDialog(self)
        dialog.setWindowTitle("Change Password")
        dialog.setFixedWidth(360)
        dlg_layout = QVBoxLayout(dialog)
        dlg_layout.setContentsMargins(24, 24, 24, 24)
        dlg_layout.setSpacing(12)

        for lbl_text, placeholder, echo in [
            ("CURRENT PASSWORD", "Enter current password", True),
            ("NEW PASSWORD",     "Enter new password",     True),
            ("CONFIRM PASSWORD", "Confirm new password",   True),
        ]:
            lbl = QLabel(lbl_text)
            lbl.setFont(QFont("Courier New", 10))
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            inp = QLineEdit()
            inp.setPlaceholderText(placeholder)
            inp.setFixedHeight(34)
            if echo:
                inp.setEchoMode(QLineEdit.EchoMode.Password)
            dlg_layout.addWidget(lbl)
            dlg_layout.addWidget(inp)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.accepted.connect(lambda: (
            QMessageBox.information(dialog, "Success", "Password updated successfully."),
            dialog.accept()
        ))
        btns.rejected.connect(dialog.reject)
        dlg_layout.addWidget(btns)
        dialog.exec()
```

- [ ] **Step 4: Run tests — verify pass**

```bash
python -m pytest tests/test_profile.py -v
```
Expected: 4 PASSED

- [ ] **Step 5: Commit**

```bash
git add screens/profile.py tests/test_profile.py
git commit -m "feat: add My Profile screen with theme toggle and change password dialog"
```

---

### Task 11: Wire up AppController + smoke test full app

**Files:**
- Modify: `app.py` (verify stub is complete — no changes needed if Task 1 stub is correct)
- Test: `tests/test_integration.py`

**Interfaces:**
- Consumes: All screens and components from Tasks 1–10.
- Produces: Fully wired app that launches, navigates all screens, and toggles theme without crashing.

- [ ] **Step 1: Write integration smoke test**

```python
import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)

def test_full_navigation_cycle(controller):
    from app_window import MainWindow
    w = MainWindow(controller)
    for screen in ["dashboard", "data_import", "config_editor", "notifications", "profile"]:
        w.navigate(screen)

def test_theme_toggle_does_not_crash(controller):
    controller.theme.toggle()
    controller.theme.toggle()

def test_login_to_main_flow(controller):
    from screens.login import LoginScreen
    login = LoginScreen(controller)
    assert login is not None

def test_signup_to_main_flow(controller):
    from screens.signup import SignupScreen
    signup = SignupScreen(controller)
    assert signup is not None
```

- [ ] **Step 2: Run all tests**

```bash
python -m pytest tests/ -v
```
Expected: All tests PASSED

- [ ] **Step 3: Run the app manually to verify UI**

```bash
python main.py
```

Verify:
- Login screen opens centered.
- "Login" button navigates to Dashboard.
- "Sign Up" link navigates to Signup screen.
- Sidebar items switch screens.
- Sun/moon button in TopBar toggles theme.
- Dark Mode checkbox in My Profile toggles theme.
- Import button on Data Import shows progress bar.
- Config Editor tabs and Save button work.
- Notifications "Mark All as Read" grays icons.
- Logout returns to Login.

- [ ] **Step 4: Commit**

```bash
git add tests/test_integration.py
git commit -m "feat: integration smoke tests — full user journey verified"
```

---

## Run All Tests

```bash
python -m pytest tests/ -v --tb=short
```

Expected: All tests in `test_theme.py`, `test_sidebar.py`, `test_topbar.py`,
`test_app_window.py`, `test_login_signup.py`, `test_dashboard.py`,
`test_data_import.py`, `test_config_editor.py`, `test_notifications.py`,
`test_profile.py`, `test_integration.py` pass.
