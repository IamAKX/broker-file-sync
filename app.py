from PySide6.QtWidgets import QApplication
from theme import ThemeManager
from api.token_store import token_manager
from api.client import api_client


class AppController:
    def __init__(self, app: QApplication):
        self.app = app
        self.theme = ThemeManager(app)
        self._login = None
        self._signup = None
        self._main_window = None
        self.is_quitting = False
        self._tray = None
        self._scheduler = None
        self._notifier = None
        from services.watcher import FileWatcher
        self.watcher = FileWatcher()
        api_client.set_session_expired_callback(self.show_login)

    def attach_tray(self, tray):
        self._tray = tray

    def start(self, minimized: bool = False):
        self.theme.apply()   # re-apply now that primaryScreen() is available
        if token_manager.load_persisted():
            self.show_main_window()
            if minimized:
                self._main_window.hide()
            return
        if minimized:
            # No session and launched minimized (e.g. via OS autostart) —
            # stay tray-only until the user clicks the icon, rather than
            # popping a login window unannounced at OS login.
            return
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
        else:
            self._main_window.refresh_user()
        self._main_window.show()
        self._main_window.check_holiday_gate(initial=True)
        self._ensure_scheduler()

    def _ensure_scheduler(self):
        """Lazily build the background scheduler the first time a main window
        exists — a logout/login cycle within the same process must not
        rebuild it (that would lose today's last-fired state)."""
        if self._scheduler is not None or self._tray is None:
            return
        from services.notification_service import NotificationService
        from services.scheduler import Scheduler
        from services import scheduled_jobs

        self._notifier = NotificationService(self._tray.icon)
        self._scheduler = Scheduler(jobs={
            "lmv_check":          lambda: scheduled_jobs.run_lmv_check(self, self._notifier),
            "historic_save":      lambda: scheduled_jobs.run_historic_save(self, self._notifier),
            "availability_check": lambda: scheduled_jobs.run_availability_check(self, self._notifier),
        })
        self._scheduler.start()

    def get_lmv_snapshot(self):
        """Return (headers, data) from the currently open Live Master View,
        or None if it hasn't been loaded (e.g. Run Watcher never clicked
        today). Centralizes the informal `_live_viewer` access already used
        ad hoc elsewhere in the app."""
        if self._main_window is None:
            return None
        data_import = self._main_window._screens.get("data_import")
        if data_import is None:
            return None
        viewer = getattr(data_import, "_live_viewer", None)
        if viewer is None or not getattr(viewer, "_headers", None):
            return None
        return list(viewer._headers), [list(r) for r in viewer._data]

    def show_and_navigate(self, screen_name: str):
        """Un-hide + focus the main window, then navigate — a bare navigate()
        has no visible effect on a hidden tray-only window."""
        self.show_main_window()
        if self._main_window is not None:
            self._main_window.showNormal()
            self._main_window.raise_()
            self._main_window.activateWindow()
            self._main_window.navigate(screen_name)

    def request_quit(self):
        """The one real quit path — used by both the tray menu's Quit action
        and the in-app File > Quit action, so both run the same teardown."""
        self.is_quitting = True
        if self._main_window is not None:
            self._main_window.close()
        else:
            self.app.quit()

    def show_login(self):
        from screens.login import LoginScreen
        from api import auth_api
        from api.exceptions import ApiError, NetworkError
        refresh_token = token_manager.get_refresh_token()
        if refresh_token:
            try:
                auth_api.logout(refresh_token)
            except (ApiError, NetworkError):
                pass  # best-effort server-side revoke; local logout proceeds regardless
        token_manager.clear()
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

    def navigate(self, screen_name: str):
        if self._main_window is not None:
            self._main_window.navigate(screen_name)

    def refresh_user_display(self):
        if self._main_window is not None:
            self._main_window.refresh_user()

    def recheck_holiday_gate(self):
        if self._main_window is not None:
            self._main_window.check_holiday_gate(initial=False)
