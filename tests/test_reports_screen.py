import sys
import time

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    # tests/conftest.py's autouse _isolate_disk_stores fixture redirects
    # config_store to a per-test tmp path.
    from app import AppController
    from screens.reports import ReportsScreen
    return ReportsScreen(AppController(qapp))


def test_reports_screen_creates_on_gallery_page(screen):
    assert screen._stack.currentWidget() is screen._gallery_page


def test_gallery_starts_with_no_saved_reports(screen):
    assert screen._saved_table.rowCount() == 0


def test_new_report_opens_wizard_prefilled(screen):
    from services import report_store

    screen._start_new_report(report_store.REPORT_TYPE_LMV)

    assert screen._stack.currentWidget() is screen._wizard_page
    assert screen._active_report["type"] == report_store.REPORT_TYPE_LMV
    assert screen._name_edit.text() == screen._active_report["name"]


def test_save_and_generate_requires_a_name(screen, monkeypatch):
    from services import report_store

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen._start_new_report(report_store.REPORT_TYPE_EMV)
    screen._name_edit.setText("   ")

    screen._save_and_generate()

    assert report_store.load_all() == []
    assert screen._stack.currentWidget() is screen._wizard_page


def test_save_and_generate_persists_report_and_shows_preview(screen, qapp):
    from services import report_store

    screen._start_new_report(report_store.REPORT_TYPE_LMV)
    screen._name_edit.setText("My Weekly LMV Report")
    screen._recipients_edit.setText("a@example.com;b@example.com")

    screen._save_and_generate()
    qapp.processEvents()

    saved = report_store.load_all()
    assert len(saved) == 1
    assert saved[0]["name"] == "My Weekly LMV Report"

    from services import report_recipients
    assert report_recipients.load_recipients(saved[0]["id"]) == ["a@example.com", "b@example.com"]

    assert screen._stack.currentWidget() is screen._preview_page
    assert "My Weekly LMV Report" in screen._last_rendered_html
    assert "Page 1 of 1" in screen._last_rendered_html


def test_save_and_generate_rejects_invalid_recipient(screen, monkeypatch):
    from services import report_store

    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))
    screen._start_new_report(report_store.REPORT_TYPE_FUKU_LIVE)
    screen._name_edit.setText("Bad recipients")
    screen._recipients_edit.setText("not-an-email")

    screen._save_and_generate()

    assert report_store.load_all() == []


def test_generate_and_preview_renders_placeholder_for_unbuilt_report_type(screen):
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_EMV, "Preview only")
    screen._generate_and_preview(report)

    assert screen._stack.currentWidget() is screen._preview_page
    assert "coming soon" in screen._last_rendered_html.lower()


def test_delete_report_removes_it_from_gallery(screen, monkeypatch):
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "To delete")
    report_store.save_report(report)
    screen.refresh_gallery()
    assert screen._saved_table.rowCount() == 1

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    screen._delete_report(report)

    assert report_store.load_all() == []
    assert screen._saved_table.rowCount() == 0


def test_download_pdf_writes_a_real_file(screen, qapp, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog
    from services import report_store

    report = report_store.new_report(report_store.REPORT_TYPE_LMV, "Downloadable")
    screen._generate_and_preview(report)

    out_path = str(tmp_path / "downloadable.pdf")
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (out_path, "")))

    shown = {}
    monkeypatch.setattr(
        QMessageBox, "information",
        staticmethod(lambda *a, **k: shown.setdefault("called", True)),
    )

    screen._download_pdf()

    deadline = time.time() + 15
    while "called" not in shown and time.time() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    import os
    assert os.path.exists(out_path)
    assert os.path.getsize(out_path) > 0
    assert screen._download_btn.text() == "Download PDF"
    assert screen._download_btn.isEnabled()


def test_refresh_theme_rebuilds_pages_without_crashing(screen):
    screen.refresh_theme()
    assert screen._stack.currentWidget() is screen._gallery_page
