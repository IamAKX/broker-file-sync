import sys
import pytest
from PySide6.QtWidgets import QApplication

@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)

@pytest.fixture
def dashboard(qapp):
    from app import AppController
    from screens.dashboard import DashboardScreen
    ctrl = AppController(qapp)
    return DashboardScreen(ctrl)

def test_dashboard_creates(dashboard):
    assert dashboard is not None

def test_dashboard_has_stat_cards(dashboard):
    from PySide6.QtWidgets import QFrame
    frames = dashboard.findChildren(QFrame)
    assert len(frames) >= 4
