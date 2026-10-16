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
    monkeypatch.setattr(branding, "logo_path", lambda: None)
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
    png = tmp_path / "fuku_lens_logo.png"
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
