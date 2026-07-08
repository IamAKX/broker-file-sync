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
        self.output_dir = ""    # set from Profile → Preferences
        from services.watcher import FileWatcher
        self.watcher = FileWatcher()
        api_client.set_session_expired_callback(self.show_login)

    def start(self):
        self.theme.apply()   # re-apply now that primaryScreen() is available
        if token_manager.load_persisted():
            self.show_main_window()
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
        self._main_window.show()
        self._main_window.navigate("dashboard")

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
