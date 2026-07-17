from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QApplication
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
        self._topbar.restart_requested.connect(lambda: self.navigate("dashboard"))
        self._topbar.navigate.connect(self.navigate)
        self._topbar.quit_requested.connect(QApplication.quit)
        self._topbar.logout_requested.connect(self._controller.show_login)
        self._topbar.fullscreen_requested.connect(self._toggle_fullscreen)
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
        from screens.strategy_builder import StrategyBuilderScreen
        from screens.historic_upload import HistoricUploadScreen

        dashboard        = DashboardScreen(self._controller)
        data_import      = DataImportScreen(self._controller)
        strategy_builder = StrategyBuilderScreen(self._controller)

        data_import.broker_imported.connect(
            lambda name, rows: self._sidebar.set_broker_active(name, True)
        )
        data_import.broker_reset.connect(
            lambda name: self._sidebar.set_broker_active(name, False)
        )
        data_import.broker_imported.connect(dashboard.on_broker_imported)
        data_import.broker_reset.connect(dashboard.on_broker_reset)

        # When LMV opens: push headers to strategy builder, push strategies to LMV
        def _on_lmv_ready(headers):
            strategy_builder.set_lmv_headers(headers)
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None:
                viewer.set_strategies(strategy_builder.get_active_strategies())

        data_import.lmv_headers_ready.connect(_on_lmv_ready)
        data_import.lmv_data_ready.connect(strategy_builder.set_lmv_data)

        screens = [
            ("dashboard",        dashboard),
            ("data_import",      data_import),
            ("config_editor",    ConfigEditorScreen(self._controller)),
            ("strategy_builder", strategy_builder),
            ("notifications",    NotificationsScreen(self._controller)),
            ("profile",          ProfileScreen(self._controller)),
            ("historic_upload",  HistoricUploadScreen(self._controller)),
        ]
        for name, widget in screens:
            self._screens[name] = widget
            self._stack.addWidget(widget)

    def refresh_user(self):
        self._sidebar.refresh_user()

    def navigate(self, screen_name: str):
        if screen_name in self._screens:
            self._stack.setCurrentWidget(self._screens[screen_name])
            self._sidebar.set_active(screen_name)

    def closeEvent(self, event):
        self._controller.watcher.stop()
        # Close live viewer if open
        data_import = self._screens.get("data_import")
        if data_import is not None:
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None:
                viewer.close()
        # Close any historic-data viewer popups
        historic_upload = self._screens.get("historic_upload")
        if historic_upload is not None:
            for viewer in getattr(historic_upload, "_viewers", []):
                viewer.close()
        super().closeEvent(event)
        QApplication.quit()

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _on_theme_toggled(self):
        self._controller.theme.apply()
        self._sidebar.repaint()
        self._topbar.repaint()
        for w in self._screens.values():
            w.repaint()
        self._sidebar.refresh_theme()
        data_import = self._screens.get("data_import")
        if data_import is not None:
            data_import.refresh_theme()
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None and viewer.isVisible():
                viewer.refresh_theme()
        strategy_builder = self._screens.get("strategy_builder")
        if strategy_builder is not None:
            strategy_builder.refresh_theme()
        historic_upload = self._screens.get("historic_upload")
        if historic_upload is not None:
            historic_upload.refresh_theme()
