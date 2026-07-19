import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    return config_store


@pytest.fixture
def screen(qapp, isolated_store):
    from app import AppController
    from screens.notifications import NotificationsScreen
    return NotificationsScreen(AppController(qapp))


def test_notifications_creates(screen):
    assert screen is not None


def test_has_send_test_sms_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("SMS" in t for t in btns)


def test_has_send_test_message_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Message" in t for t in btns)


def test_has_two_action_buttons(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert len([t for t in btns if t.strip()]) >= 2


def test_trigger_table_has_three_rows(screen):
    assert screen._table.rowCount() == 3


def test_system_default_checked_telegram_sms_default_unchecked(screen):
    from PySide6.QtWidgets import QCheckBox
    for row in range(screen._table.rowCount()):
        system_cb = screen._table.cellWidget(row, 2).findChild(QCheckBox)
        telegram_cb = screen._table.cellWidget(row, 3).findChild(QCheckBox)
        sms_cb = screen._table.cellWidget(row, 4).findChild(QCheckBox)
        assert system_cb.isChecked() is True
        assert telegram_cb.isChecked() is False
        assert sms_cb.isChecked() is False


def test_edited_time_persists(screen, isolated_store):
    from datetime import time as dtime
    from services import trigger_config

    cfg = screen._configs[0]
    cfg.time = dtime(9, 30)
    screen._save_configs()

    reloaded = trigger_config.load_trigger_configs()
    match = next(c for c in reloaded if c.id == cfg.id)
    assert match.time == dtime(9, 30)


def test_checkbox_toggle_persists(screen, isolated_store):
    from services import trigger_config

    cfg = screen._configs[0]
    screen._on_checkbox_changed(cfg, "telegram", True)

    reloaded = trigger_config.load_trigger_configs()
    match = next(c for c in reloaded if c.id == cfg.id)
    assert match.telegram_enabled is True
