import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from app import AppController
import font_scale

_ICONS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")
APP_NAME = "Broker Sync"

if sys.platform == "win32":
    APP_ICON_PATH = os.path.join(_ICONS_DIR, "app_logo.ico")
elif sys.platform == "darwin":
    APP_ICON_PATH = os.path.join(_ICONS_DIR, "app_logo.icns")
else:
    APP_ICON_PATH = os.path.join(_ICONS_DIR, "app_logo.png")


def _apply_app_icon(app: QApplication):
    icon = QIcon(APP_ICON_PATH)
    app.setWindowIcon(icon)   # taskbar/title bar icon on Windows/Linux
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)

    if sys.platform == "win32":
        # Without an explicit AppUserModelID, Windows groups the app under the
        # python.exe process and shows the generic Python icon/name in the
        # taskbar instead of ours.
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("BrokerSync.App")
        except Exception:
            pass

    elif sys.platform == "darwin":
        # Running as a plain script (not a bundled .app), macOS shows the
        # Python.framework stub's own name/icon in the Dock and menu bar
        # instead of ours. Patch the running NSApplication directly so dev
        # runs match what a properly bundled .app shows.
        try:
            from AppKit import NSApplication, NSImage
            from Foundation import NSBundle

            info = NSBundle.mainBundle().infoDictionary()
            info["CFBundleName"] = APP_NAME

            nsimage = NSImage.alloc().initByReferencingFile_(APP_ICON_PATH)
            NSApplication.sharedApplication().setApplicationIconImage_(nsimage)
        except ImportError:
            pass   # pyobjc not installed; dock icon/menu name fall back to defaults

def main():
    from services.error_logging import install_excepthook
    install_excepthook()

    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)   # tray-resident: hiding the window must not exit the process
    app.setFont(font_scale.F_MEDIUM())   # now uses Segoe UI + scaled size on Windows
    _apply_app_icon(app)

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--minimized", action="store_true")
    args, _ = parser.parse_known_args()

    from services.single_instance import SingleInstanceGuard
    guard = SingleInstanceGuard()

    controller = AppController(app)

    def _activate_existing():
        controller.show_and_navigate("dashboard")

    if not guard.try_acquire(_activate_existing):
        return   # another instance is already running and has been pinged to activate itself

    from services.tray import AppTray
    tray = AppTray(controller, APP_ICON_PATH)
    controller.attach_tray(tray)

    controller.start(minimized=args.minimized)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()