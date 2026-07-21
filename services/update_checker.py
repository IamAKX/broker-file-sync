"""
Checks GitHub Releases for a newer packaged build of this app, and (once the
user confirms) downloads and applies it.

This module is pure logic + network/filesystem — no Qt. See
components/update_dialog.py for the UI that drives it on a worker thread,
and docs/updating.md-equivalent notes below for why the "apply" step works
the way it does.

Packaging shape (.github/workflows/ci.yml): CI builds an unsigned
`pyinstaller --onedir` folder per platform, zips it, and attaches it to a
GitHub Release. There is no installer, so "update" means replacing that
whole folder while the app running *from inside it* is still alive — the
running exe's own files are locked (Windows) / in use (macOS) and can't be
overwritten in place. The standard fix for exactly this packaging shape is
a small detached helper script: stage the new build in a temp dir, write a
platform-native script that waits for this process's PID to exit, renames
the current install dir aside (a cheap safety net, not deleted outright),
moves the staged build into place, launches the new build, then deletes
itself — launch that script detached and let the caller quit the app
normally so the helper's wait-for-PID step completes.
"""

import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import requests

from version import APP_VERSION

GITHUB_REPO = "IamAKX/broker-file-sync"
RELEASES_API = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"

_ASSET_BY_PLATFORM = {
    "win32": "BrokerFileSync-windows.zip",
    "darwin": "BrokerFileSync-macos.zip",
}
_CHECKSUMS_ASSET = "checksums.txt"
_REQUEST_TIMEOUT = 10
_DOWNLOAD_TIMEOUT = 30
_CHUNK_SIZE = 256 * 1024


class UpdateCheckError(Exception):
    """The release check itself failed (network, bad response, unparseable tag)."""


class UpdateApplyError(Exception):
    """A newer release exists but couldn't be downloaded/verified/staged."""


class UpdateNotSupported(Exception):
    """No build published for this platform, or nothing to apply to (dev run)."""


def _parse_semver(tag: str):
    """"v1.2.3" / "1.2.3" -> (1, 2, 3); anything else -> None."""
    if not tag:
        return None
    m = re.match(r"v?(\d+)\.(\d+)\.(\d+)", tag.strip())
    if not m:
        return None
    return tuple(int(x) for x in m.groups())


def is_frozen() -> bool:
    """True in a PyInstaller-packaged build, False running from source."""
    return bool(getattr(sys, "frozen", False))


def current_version_tuple():
    return _parse_semver(APP_VERSION)


def fetch_latest_release() -> dict:
    """Return the latest GitHub release, normalised for this app's needs.

    Raises UpdateCheckError on any network/parsing failure — callers never
    need to handle raw `requests` exceptions.
    """
    try:
        resp = requests.get(
            RELEASES_API, timeout=_REQUEST_TIMEOUT,
            headers={"Accept": "application/vnd.github+json"},
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        raise UpdateCheckError(f"Could not reach GitHub: {exc}") from exc
    except ValueError as exc:
        raise UpdateCheckError(f"Unexpected response from GitHub: {exc}") from exc

    tag = data.get("tag_name", "")
    version_tuple = _parse_semver(tag)
    if version_tuple is None:
        raise UpdateCheckError(f"Latest release tag '{tag}' isn't a version I understand")

    asset_name = _ASSET_BY_PLATFORM.get(sys.platform)
    asset_url = None
    checksum_url = None
    for asset in data.get("assets", []):
        name = asset.get("name")
        if name == asset_name:
            asset_url = asset.get("browser_download_url")
        elif name == _CHECKSUMS_ASSET:
            checksum_url = asset.get("browser_download_url")

    return {
        "tag": tag,
        "version": ".".join(str(p) for p in version_tuple),
        "version_tuple": version_tuple,
        "notes": data.get("body") or "",
        "html_url": data.get("html_url", ""),
        "asset_name": asset_name,
        "asset_url": asset_url,
        "checksum_url": checksum_url,
    }


def has_update(release: dict) -> bool:
    """True if release is newer than the running app's version — also True
    for a dev build (APP_VERSION unparseable), since there's always "a
    newer packaged release" than no packaged version at all; is_frozen()
    is what actually gates whether an update can be *applied*."""
    current = current_version_tuple()
    if current is None:
        return True
    return release["version_tuple"] > current


def download_asset(release: dict, dest_dir: Path, progress_cb=None) -> Path:
    """Stream the platform asset to dest_dir, calling progress_cb(written,
    total) as it arrives (total is 0 if the server didn't send a
    Content-Length). Returns the downloaded file's path."""
    if not release.get("asset_url"):
        raise UpdateNotSupported(f"No build published for this platform ({sys.platform})")

    dest = Path(dest_dir) / release["asset_name"]
    try:
        resp = requests.get(release["asset_url"], stream=True, timeout=_DOWNLOAD_TIMEOUT)
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        written = 0
        with open(dest, "wb") as f:
            for chunk in resp.iter_content(chunk_size=_CHUNK_SIZE):
                if not chunk:
                    continue
                f.write(chunk)
                written += len(chunk)
                if progress_cb:
                    progress_cb(written, total)
    except requests.RequestException as exc:
        raise UpdateApplyError(f"Download failed: {exc}") from exc
    return dest


def verify_checksum(release: dict, downloaded_path: Path) -> bool:
    """True if the download matches the published SHA256, OR if this
    release doesn't publish checksums.txt at all (older release — can't
    verify, caller proceeds; a *mismatched* checksum is the only thing
    that blocks applying the update)."""
    if not release.get("checksum_url"):
        return True
    try:
        resp = requests.get(release["checksum_url"], timeout=_REQUEST_TIMEOUT)
        resp.raise_for_status()
    except requests.RequestException as exc:
        raise UpdateApplyError(f"Could not fetch checksums: {exc}") from exc

    expected = None
    for line in resp.text.splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].lstrip("*") == release["asset_name"]:
            expected = parts[0].lower()
            break
    if expected is None:
        return True

    digest = hashlib.sha256()
    with open(downloaded_path, "rb") as f:
        for chunk in iter(lambda: f.read(_CHUNK_SIZE), b""):
            digest.update(chunk)
    return digest.hexdigest().lower() == expected


def _extract_staged_root(zip_path: Path, staging_dir: Path) -> Path:
    """Extract zip_path into staging_dir and return the path to the new
    build's root — the directory (Windows) or .app bundle (macOS) that
    should replace the current install dir. Raises UpdateApplyError if the
    expected shape isn't found, before anything live is touched."""
    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(staging_dir)

    if sys.platform == "darwin":
        bundles = list(staging_dir.glob("*.app")) or list(staging_dir.glob("**/*.app"))
        if not bundles:
            raise UpdateApplyError("Downloaded build doesn't contain a .app bundle")
        return bundles[0]

    # Windows: CI zips the *contents* of the onedir folder, so the exe
    # should be directly inside staging_dir.
    if not list(staging_dir.glob("*.exe")):
        raise UpdateApplyError("Downloaded build doesn't contain an .exe")
    return staging_dir


def _current_install_dir() -> Path:
    """The directory that IS the running packaged app (to be replaced)."""
    exe = Path(sys.executable).resolve()
    if sys.platform == "darwin":
        for parent in exe.parents:
            if parent.suffix == ".app":
                return parent
        raise UpdateNotSupported("Could not locate the running .app bundle")
    return exe.parent


_WINDOWS_HELPER = """@echo off
setlocal
set PID=%~1
set INSTALL_DIR=%~2
set STAGED_DIR=%~3
set EXE_NAME=%~4

:wait
tasklist /FI "PID eq %PID%" 2>NUL | find "%PID%" >NUL
if not errorlevel 1 (
    timeout /t 1 /nobreak >nul
    goto wait
)

if exist "%INSTALL_DIR%.old" rmdir /s /q "%INSTALL_DIR%.old"
move "%INSTALL_DIR%" "%INSTALL_DIR%.old"
move "%STAGED_DIR%" "%INSTALL_DIR%"
start "" "%INSTALL_DIR%\\%EXE_NAME%"

del "%~f0"
"""

_POSIX_HELPER = """#!/bin/bash
PID="$1"
INSTALL_DIR="$2"
STAGED_DIR="$3"

while kill -0 "$PID" 2>/dev/null; do
    sleep 1
done

rm -rf "${INSTALL_DIR}.old"
mv "$INSTALL_DIR" "${INSTALL_DIR}.old"
mv "$STAGED_DIR" "$INSTALL_DIR"
open "$INSTALL_DIR"

rm -- "$0"
"""


def stage_and_apply(zip_path: Path) -> None:
    """Extract+verify the downloaded build, then hand off to a detached
    helper script that swaps it in once this process exits. Does NOT quit
    the app itself — call AppController.request_quit() right after this
    returns so the helper's wait-for-PID step actually completes.

    Nothing live is touched by this function — only staging (a fresh temp
    dir) and writing/launching the helper script, which does the real
    swap after this process is gone. A failure here leaves the running
    install completely untouched.
    """
    if not is_frozen():
        raise UpdateNotSupported("Running from source — nothing packaged to replace")

    staging_dir = Path(tempfile.mkdtemp(prefix="brokersync_update_"))
    staged_root = _extract_staged_root(Path(zip_path), staging_dir)
    install_dir = _current_install_dir()

    if sys.platform == "darwin":
        helper_path = Path(tempfile.gettempdir()) / "brokersync_apply_update.sh"
        helper_path.write_text(_POSIX_HELPER)
        helper_path.chmod(0o755)
        args = ["/bin/bash", str(helper_path), str(os.getpid()), str(install_dir), str(staged_root)]
        subprocess.Popen(args, start_new_session=True)
    elif sys.platform == "win32":
        helper_path = Path(tempfile.gettempdir()) / "brokersync_apply_update.bat"
        helper_path.write_text(_WINDOWS_HELPER)
        exe_name = Path(sys.executable).name
        args = [str(helper_path), str(os.getpid()), str(install_dir), str(staged_root), exe_name]
        subprocess.Popen(
            args, shell=False,
            creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    else:
        raise UpdateNotSupported(f"No build published for this platform ({sys.platform})")
