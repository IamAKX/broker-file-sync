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
