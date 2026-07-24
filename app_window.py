from PySide6.QtWidgets import QMainWindow, QWidget, QHBoxLayout, QVBoxLayout, QStackedWidget, QApplication
from PySide6.QtCore import Qt
from components.sidebar import Sidebar
from components.topbar import TopBar


class MainWindow(QMainWindow):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._navigation_locked = False
        self.setWindowTitle("Broker Sync")
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
        self._topbar.quit_requested.connect(self._controller.request_quit)
        self._topbar.logout_requested.connect(self._controller.show_login)
        self._topbar.fullscreen_requested.connect(self._toggle_fullscreen)
        self._topbar.check_for_update_requested.connect(self._open_update_dialog)
        self._topbar.export_strategies_requested.connect(self._export_all_strategies)
        self._topbar.import_strategies_requested.connect(self._import_all_strategies)
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
        from screens.formula_builder import FormulaBuilderScreen
        from screens.holidays import HolidaysScreen
        from screens.lmv_upload import LmvUploadScreen

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

        data_import.broker_source_active.connect(
            lambda name, active, rows: self._sidebar.set_broker_active(name, active)
        )
        data_import.broker_source_active.connect(dashboard.on_broker_source_active)

        # When LMV opens: push headers to strategy builder, push strategies to LMV
        def _on_lmv_ready(headers):
            strategy_builder.set_lmv_headers(headers)
            viewer = getattr(data_import, "_live_viewer", None)
            if viewer is not None:
                # Every strategy is available in the picker, but none is
                # auto-applied on open — auto-activating every persisted
                # "active" strategy at once meant a large batch of row
                # filters (each strategy's own) all had to match for a row
                # to survive the union, which can empty the whole table the
                # instant LMV loads. Users opt specific ones in per session.
                all_strats = [dict(s, active=False)
                              for s in strategy_builder.get_all_strategies()]
                viewer.set_strategies(all_strats)

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
            ("formula_builder",  FormulaBuilderScreen(self._controller)),
            ("holidays",         HolidaysScreen(self._controller)),
            ("lmv_upload",       LmvUploadScreen(self._controller)),
        ]
        for name, widget in screens:
            self._screens[name] = widget
            self._stack.addWidget(widget)

    def refresh_user(self):
        self._sidebar.refresh_user()

    def navigate(self, screen_name: str):
        if self._navigation_locked and screen_name != "holidays":
            return
        if screen_name in self._screens:
            self._stack.setCurrentWidget(self._screens[screen_name])
            self._sidebar.set_active(screen_name)

    # ── Current-year holiday gate ───────────────────────────────────────────
    # On every login/session start, and again whenever the holidays screen
    # saves or deletes a row, verify the current year has at least one
    # holiday on file. If not, force the user onto Market Holidays and lock
    # the rest of the app (sidebar + topbar disabled) until it does.

    def check_holiday_gate(self, initial: bool = False):
        from datetime import date
        from api import holidays_api
        from api.exceptions import ApiError, NetworkError
        try:
            holidays = holidays_api.list_holidays(date.today().year)
        except (ApiError, NetworkError):
            # Can't verify right now — don't lock the user out over a
            # transient network issue.
            self._set_navigation_locked(False)
            if initial:
                self.navigate("dashboard")
            return
        if holidays:
            self._set_navigation_locked(False)
            if initial:
                self.navigate("dashboard")
        else:
            self._set_navigation_locked(True)
            self.navigate("holidays")

    def _set_navigation_locked(self, locked: bool):
        self._navigation_locked = locked
        self._sidebar.setEnabled(not locked)
        self._topbar.setEnabled(not locked)

    def closeEvent(self, event):
        if not self._controller.is_quitting:
            # Tray-resident: closing the window (X button) hides it instead
            # of quitting, so the background scheduler keeps running. Real
            # exit only happens via AppController.request_quit() (tray
            # menu's Quit, or File > Quit).
            event.ignore()
            self.hide()
            return

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

    def _open_update_dialog(self):
        from components.update_dialog import UpdateDialog
        dlg = UpdateDialog(self._controller, theme=self._controller.theme, parent=self)
        dlg.exec()

    def _export_all_strategies(self):
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services import strategy_store

        strategies = strategy_store.load_all()
        if not strategies:
            QMessageBox.information(self, "Export All Strategies", "No strategies to export.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export All Strategies", "strategies_export.json", "JSON Files (*.json)"
        )
        if not path:
            return
        if not path.lower().endswith(".json"):
            path += ".json"
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(strategies, f, indent=2, ensure_ascii=False)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not export:\n\n{exc}")
            return
        QMessageBox.information(
            self, "Export All Strategies",
            f"Exported {len(strategies)} strategies to:\n{path}"
        )

    def _import_all_strategies(self):
        import json
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services import strategy_store

        path, _ = QFileDialog.getOpenFileName(
            self, "Import All Strategies", "", "JSON Files (*.json)"
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, list) or not all(
                isinstance(s, dict) and "id" in s and "name" in s for s in data
            ):
                raise ValueError("File does not contain a valid strategies export.")
        except Exception as exc:
            QMessageBox.warning(self, "Import Failed", f"Could not import:\n\n{exc}")
            return

        existing_count = len(strategy_store.load_all())
        reply = QMessageBox.question(
            self, "Import All Strategies",
            f"This will replace all {existing_count} existing strategies with "
            f"{len(data)} strategies from the file. This cannot be undone. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        strategy_store.import_all(data)
        strategy_builder = self._screens.get("strategy_builder")
        if strategy_builder is not None:
            strategy_builder.reload_strategies()
        QMessageBox.information(self, "Import All Strategies", f"Imported {len(data)} strategies.")

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
        formula_builder = self._screens.get("formula_builder")
        if formula_builder is not None:
            formula_builder.refresh_theme()
        holidays = self._screens.get("holidays")
        if holidays is not None:
            holidays.refresh_theme()
