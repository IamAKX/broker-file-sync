import os
import sys

import pytest
from PySide6.QtWidgets import QApplication

import branding
from services.report_engine import templates


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_report_titles_get_the_fuku_lens_prefix_once():
    assert branding.prefixed_report_title("EMV EOD Report") == "Fuku Lens EMV EOD Report"
    assert branding.prefixed_report_title("Fuku Live Report") == "Fuku Lens Live Report"
    assert branding.prefixed_report_title("Fuku EOD Sector Report") == "Fuku Lens EOD Sector Report"
    assert branding.prefixed_report_title("Fuku Lens EMV EOD Report") == "Fuku Lens EMV EOD Report"


def test_report_header_uses_prefixed_title_and_has_no_logo_without_artwork(monkeypatch):
    monkeypatch.setattr(branding, "header_path", lambda: None)
    from datetime import datetime
    html = templates.report_header("EMV EOD Stock Report", "x", datetime(2026, 1, 1))
    assert "<h1>Fuku Lens EMV EOD Stock Report</h1>" in html
    assert "brand-logo" not in html


def _write_png(path):
    from PySide6.QtGui import QImage, QColor
    img = QImage(400, 100, QImage.Format.Format_ARGB32)
    img.fill(QColor("#2979FF"))
    img.save(str(path))


def test_logo_is_embedded_in_reports_with_aspect_ratio_kept(tmp_path, monkeypatch, qapp):
    png = tmp_path / "fuku_lens_header.png"
    _write_png(png)
    monkeypatch.setattr(branding, "_BRANDING_DIR", str(tmp_path))
    html = branding.report_logo_html(40)
    assert "data:image/png;base64," in html
    assert "height:40px" in html and "width:auto" in html          # never stretched
    from datetime import datetime
    assert "brand-logo" in templates.report_header("Sector Report", "x", datetime(2026, 1, 1))


def test_logo_label_fits_inside_its_box_keeping_aspect_ratio(tmp_path, monkeypatch, qapp):
    _write_png(tmp_path / "fuku_lens_logo.png")                   # 4:1
    monkeypatch.setattr(branding, "_BRANDING_DIR", str(tmp_path))
    label = branding.make_logo_label(max_height=50, max_width=300)
    pm = label.pixmap()
    assert pm.height() <= 50 and pm.width() <= 300
    assert abs(pm.width() / pm.height() - 4.0) < 0.1
    from PySide6.QtCore import QSize
    from PySide6.QtGui import QResizeEvent
    label.resize(120, 50)                                         # narrower: shrinks, same ratio
    label.resizeEvent(QResizeEvent(QSize(120, 50), QSize(300, 50)))   # unshown widgets defer the real event
    pm = label.pixmap()
    assert pm.width() <= 120 and abs(pm.width() / pm.height() - 4.0) < 0.15
    assert branding.make_logo_label.__name__ == "make_logo_label"


def test_no_logo_file_means_no_label(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "_BRANDING_DIR", str(tmp_path))
    assert branding.make_logo_label() is None and branding.report_logo_html() == ""


def test_icon_falls_back_to_the_existing_app_logo(tmp_path, monkeypatch):
    monkeypatch.setattr(branding, "_BRANDING_DIR", str(tmp_path))
    assert os.path.basename(branding.icon_path()).startswith("app_logo")


def test_shipped_artwork_is_present_and_has_the_expected_shapes():
    """The three Fuku Lens images from issue #80 ship in assets/branding."""
    from PySide6.QtGui import QImage
    header = QImage(branding.header_path())
    logo = QImage(branding.logo_path())
    assert not header.isNull() and abs(header.width() / header.height() - 3.0) < 0.05
    assert not logo.isNull() and logo.width() == logo.height()
    icon = branding.icon_path()
    assert "fuku_lens_icon" in os.path.basename(icon) and os.path.isfile(icon)


# ── #91: opening window + header logo on the main screens ────────────────

def test_login_screen_is_fuku_lens_with_logo_and_tagline(qapp):
    from PySide6.QtWidgets import QLabel
    from app import AppController
    from screens.login import LoginScreen

    screen = LoginScreen(AppController(qapp))
    texts = [lb.text() for lb in screen.findChildren(QLabel)]
    assert "FUKU LENS" in texts
    assert branding.TAGLINE == "Research. Technology. Systems." and branding.TAGLINE in texts
    assert not any("BROKER FILE SYNC" in t.upper() for t in texts)
    assert "Excel Processing Software" not in texts
    assert any(lb.pixmap() is not None and not lb.pixmap().isNull() for lb in screen.findChildren(QLabel))


def test_header_logo_keeps_aspect_ratio_and_is_fixed_height(qapp):
    logo = branding.make_header_logo(56)
    assert logo is not None and logo.height() == 56
    src = branding.QPixmap(branding.header_path()) if hasattr(branding, "QPixmap") else None
    from PySide6.QtGui import QPixmap
    src = QPixmap(branding.header_path())
    assert abs(logo.width() / 56 - src.width() / src.height()) < 0.02


def test_header_logo_none_without_artwork(qapp, monkeypatch):
    monkeypatch.setattr(branding, "header_path", lambda: None)
    assert branding.make_header_logo() is None


@pytest.mark.parametrize("module, cls", [
    ("screens.dashboard", "DashboardScreen"),
    ("screens.data_import", "DataImportScreen"),
    ("screens.config_editor", "ConfigEditorScreen"),
    ("screens.notifications", "NotificationsScreen"),
    ("screens.live_alerts", "LiveAlertsScreen"),
    ("screens.profile", "ProfileScreen"),
])
def test_main_screens_show_the_header_logo(qapp, module, cls):
    import importlib
    from PySide6.QtWidgets import QLabel
    from app import AppController

    screen = getattr(importlib.import_module(module), cls)(AppController(qapp))
    logos = [lb for lb in screen.findChildren(QLabel) if lb.objectName() == "headerLogo"]
    assert len(logos) == 1


def test_windows_build_uses_fuku_lens_name_icon_and_metadata():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for rel in ("build_windows.ps1", "appveyor.yml", ".github/workflows/ci.yml"):
        text = open(os.path.join(root, rel), encoding="utf-8").read()
        assert '--name "FukuLens"' in text and "fuku_lens_icon.ico" in text, rel
        assert "windows_version_info.txt" in text, rel
        # existing installs self-update by this exact asset name
        assert "BrokerFileSync-windows.zip" in text, rel
    info = open(os.path.join(root, "windows_version_info.txt"), encoding="utf-8").read()
    assert "'FileDescription', 'Fuku Lens'" in info
