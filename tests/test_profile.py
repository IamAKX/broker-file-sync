import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.profile import ProfileScreen
    return ProfileScreen(AppController(qapp))


def test_profile_creates(screen):
    assert screen is not None


def test_has_sign_out_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Sign Out" in t for t in btns)


def test_has_save_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Save" in t for t in btns)


def test_has_change_password_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Password" in t for t in btns)


def test_has_account_fields(screen):
    from PySide6.QtWidgets import QLineEdit
    inputs = screen.findChildren(QLineEdit)
    assert len(inputs) >= 1
