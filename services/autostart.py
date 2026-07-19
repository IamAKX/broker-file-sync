"""
Cross-platform "start on login" registration so the tray-resident app (and
its background scheduler) comes up automatically without the user manually
launching it every day.

No PyInstaller build pipeline exists in this repo yet, so all three
platforms register the dev-run form (python executable + absolute main.py
path); when a frozen build is introduced, this will need a sys.frozen branch
pointing at the built executable instead.
"""

import os
import sys

_APP_NAME = "BrokerSync"
_MAIN_PY = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "main.py")
_MAIN_PY = os.path.normpath(_MAIN_PY)


def _launch_command() -> list:
    return [sys.executable, _MAIN_PY, "--minimized"]


def is_supported() -> bool:
    return sys.platform in ("win32", "darwin", "linux")


# ── Windows: HKCU Run key (winreg is stdlib — no pywin32 needed) ────────────

def _windows_is_enabled() -> bool:
    import winreg
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Run") as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except FileNotFoundError:
        return False


def _windows_set_enabled(enabled: bool) -> None:
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                         r"Software\Microsoft\Windows\CurrentVersion\Run",
                         0, winreg.KEY_SET_VALUE) as key:
        if enabled:
            cmd = " ".join(f'"{part}"' for part in _launch_command())
            winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, _APP_NAME)
            except FileNotFoundError:
                pass


# ── macOS: LaunchAgent plist ─────────────────────────────────────────────────

def _macos_plist_path() -> str:
    return os.path.expanduser("~/Library/LaunchAgents/com.brokersync.app.plist")


def _macos_is_enabled() -> bool:
    return os.path.exists(_macos_plist_path())


def _macos_set_enabled(enabled: bool) -> None:
    path = _macos_plist_path()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    args_xml = "".join(f"<string>{part}</string>" for part in _launch_command())
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.brokersync.app</string>
    <key>ProgramArguments</key>
    <array>{args_xml}</array>
    <key>RunAtLoad</key>
    <true/>
</dict>
</plist>
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(plist)


# ── Linux: XDG autostart .desktop file ───────────────────────────────────────

def _linux_desktop_path() -> str:
    return os.path.expanduser("~/.config/autostart/broker-sync.desktop")


def _linux_is_enabled() -> bool:
    return os.path.exists(_linux_desktop_path())


def _linux_set_enabled(enabled: bool) -> None:
    path = _linux_desktop_path()
    if not enabled:
        if os.path.exists(path):
            os.remove(path)
        return
    os.makedirs(os.path.dirname(path), exist_ok=True)
    exec_cmd = " ".join(_launch_command())
    desktop = f"""[Desktop Entry]
Type=Application
Name=Broker Sync
Exec={exec_cmd}
X-GNOME-Autostart-enabled=true
"""
    with open(path, "w", encoding="utf-8") as f:
        f.write(desktop)


# ── Public interface ─────────────────────────────────────────────────────────

def is_enabled() -> bool:
    if sys.platform == "win32":
        return _windows_is_enabled()
    if sys.platform == "darwin":
        return _macos_is_enabled()
    if sys.platform == "linux":
        return _linux_is_enabled()
    return False


def set_enabled(enabled: bool) -> None:
    if sys.platform == "win32":
        _windows_set_enabled(enabled)
    elif sys.platform == "darwin":
        _macos_set_enabled(enabled)
    elif sys.platform == "linux":
        _linux_set_enabled(enabled)
