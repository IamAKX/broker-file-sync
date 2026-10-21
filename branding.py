"""
Fuku Lens branding: product name, report title prefix, and the logo/icon
files (issue #80).

The artwork lives in ``assets/branding/`` — drop the files in under these
names and they are picked up everywhere (no code change):

  fuku_lens_logo.png   stacked logo: Dashboard
  fuku_lens_header.png wide banner (3:1): header of every report
  fuku_lens_icon.png   app icon (taskbar / window); .ico (Windows) and
                       .icns (macOS) variants of the same name are preferred
                       on those platforms

A missing file falls back gracefully (reports simply have no logo; the window
keeps the existing icon), so the rename can ship before the artwork does.
Logos are always scaled with their aspect ratio kept (never stretched).
"""

import base64
import os
import sys

APP_NAME = "Fuku Lens"
REPORT_PREFIX = "Fuku Lens"

_BRANDING_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "branding")
_LEGACY_ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icons")


def _existing(*names: str) -> str | None:
    for name in names:
        path = os.path.join(_BRANDING_DIR, name)
        if os.path.isfile(path):
            return path
    return None


def logo_path() -> str | None:
    return _existing("fuku_lens_logo.png", "fuku_lens_logo.jpg", "fuku_lens_logo.jpeg")


def header_path() -> str | None:
    """The wide banner for report headers (falls back to the stacked logo)."""
    return _existing("fuku_lens_header.png", "fuku_lens_header.jpg") or logo_path()


def icon_path() -> str:
    """The app icon file: the Fuku Lens one when supplied, else the previous
    app logo."""
    if sys.platform == "win32":
        preferred, legacy = ("fuku_lens_icon.ico", "fuku_lens_icon.png"), "app_logo.ico"
    elif sys.platform == "darwin":
        preferred, legacy = ("fuku_lens_icon.icns", "fuku_lens_icon.png"), "app_logo.icns"
    else:
        preferred, legacy = ("fuku_lens_icon.png",), "app_logo.png"
    return _existing(*preferred) or os.path.join(_LEGACY_ICON_DIR, legacy)


def prefixed_report_title(title: str) -> str:
    """"EMV EOD Report" -> "Fuku Lens EMV EOD Report"; a title that already
    starts with the product name is left alone and a leading "Fuku " becomes
    "Fuku Lens " ("Fuku Live Report" -> "Fuku Lens Live Report")."""
    if title.startswith(REPORT_PREFIX):
        return title
    if title.startswith("Fuku "):
        return f"{REPORT_PREFIX} {title[len('Fuku '):]}"
    return f"{REPORT_PREFIX} {title}"


_MIME = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg"}


def report_logo_html(height_px: int = 64) -> str:
    """An <img> of the logo for a report header, embedded as a data URI (the
    report HTML must stay self-contained). Height-bound with width:auto so the
    aspect ratio is kept at any size; "" when there is no logo file."""
    path = header_path()
    if not path:
        return ""
    try:
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return ""
    mime = _MIME.get(os.path.splitext(path)[1].lower(), "image/png")
    return (f'<img class="brand-logo" alt="{APP_NAME}" src="data:{mime};base64,{encoded}" '
            f'style="height:{int(height_px)}px;width:auto;max-width:260px;object-fit:contain;border-radius:4px;"/>')


def make_logo_label(max_height: int = 110, max_width: int = 330):
    """A QLabel showing the logo scaled to fit max_width x max_height with its
    aspect ratio kept, re-fitted whenever it is resized (e.g. by a layout or a
    different DPI). None when there is no logo file."""
    path = logo_path()
    if not path:
        return None
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QPixmap
    from PySide6.QtWidgets import QLabel, QSizePolicy

    class _LogoLabel(QLabel):
        def __init__(self):
            super().__init__()
            self._source = QPixmap(path)
            self.setAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
            self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
            self.setMaximumHeight(max_height)
            self._refit(max_width, max_height)

        def _refit(self, width: int, height: int):
            if self._source.isNull():
                return
            self.setPixmap(self._source.scaled(
                max(1, min(width, max_width)), max(1, min(height, max_height)),
                Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation))

        def resizeEvent(self, event):
            super().resizeEvent(event)
            self._refit(self.width(), max_height)

        def sizeHint(self):
            pm = self.pixmap()
            return pm.size() if pm is not None and not pm.isNull() else super().sizeHint()

    return _LogoLabel()


TAGLINE = "Research. Technology. Systems."


def make_header_logo(height: int = 56):
    """The wide banner as a fixed-height QLabel (width follows the artwork's
    aspect ratio) for the top-right corner of every main screen (#91). None
    when there is no artwork. The pixmap is scaled once, at device-pixel
    resolution, so it stays crisp on HiDPI."""
    path = header_path()
    if not path:
        return None
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QGuiApplication, QPixmap
    from PySide6.QtWidgets import QLabel

    src = QPixmap(path)
    if src.isNull():
        return None
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen is not None else 1.0
    scaled = src.scaledToHeight(int(height * dpr), Qt.TransformationMode.SmoothTransformation)
    scaled.setDevicePixelRatio(dpr)
    label = QLabel()
    label.setObjectName("headerLogo")
    label.setPixmap(scaled)
    label.setFixedSize(int(scaled.width() / dpr), height)
    label.setStyleSheet("background: transparent; border: none;")
    return label
