"""Tests for components/popup_position.py::clamp_to_screen — issue #51 (a
button-anchored popup, e.g. Inception View by Date's "Strategies" dropdown,
rendering partially/entirely below the screen's bottom edge when its
anchor button sits near the bottom of a short window)."""
import sys
from unittest.mock import MagicMock

import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtWidgets import QApplication, QWidget


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _screen(avail_rect: QRect):
    screen = MagicMock()
    screen.availableGeometry.return_value = avail_rect
    return screen


def test_preferred_position_kept_when_it_already_fits(qapp, monkeypatch):
    from components import popup_position

    screen = _screen(QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(popup_position.QApplication, "screenAt", lambda pt: screen)

    popup = QWidget()
    popup.resize(260, 200)

    result = popup_position.clamp_to_screen(popup, QPoint(100, 100))

    assert result == QPoint(100, 100)


def test_shifts_left_when_popup_would_run_off_right_edge(qapp, monkeypatch):
    from components import popup_position

    screen = _screen(QRect(0, 0, 1000, 800))
    monkeypatch.setattr(popup_position.QApplication, "screenAt", lambda pt: screen)

    popup = QWidget()
    popup.resize(260, 200)

    # Preferred x=900 would put the popup's right edge at 1160, past 1000.
    result = popup_position.clamp_to_screen(popup, QPoint(900, 100))

    assert result.x() == 1000 - 260
    assert result.y() == 100


def test_shifts_up_when_popup_would_run_off_bottom_edge(qapp, monkeypatch):
    """The concrete issue #51 case: a "Strategies" button near the bottom
    of a short window/screen, popup opening downward and running off the
    bottom."""
    from components import popup_position

    screen = _screen(QRect(0, 0, 1920, 700))
    monkeypatch.setattr(popup_position.QApplication, "screenAt", lambda pt: screen)

    popup = QWidget()
    popup.resize(320, 450)

    # Preferred y=650 (just below a bottom-of-screen button) would put the
    # popup's bottom edge at 1100, way past the 700px-tall screen.
    result = popup_position.clamp_to_screen(popup, QPoint(1600, 650))

    assert result.y() == 700 - 450
    assert result.x() == 1600   # x already fit, untouched


def test_never_shifted_past_the_screens_own_top_left_corner(qapp, monkeypatch):
    """A popup taller/wider than the whole screen (e.g. a very small
    external monitor) still renders at the screen's origin rather than at
    a negative, even-more-off-screen position."""
    from components import popup_position

    screen = _screen(QRect(0, 0, 200, 200))
    monkeypatch.setattr(popup_position.QApplication, "screenAt", lambda pt: screen)

    popup = QWidget()
    popup.resize(400, 400)

    result = popup_position.clamp_to_screen(popup, QPoint(50, 50))

    assert result == QPoint(0, 0)


def test_falls_back_to_primary_screen_when_point_is_on_no_screen(qapp, monkeypatch):
    """screenAt() returns None for a point off every connected monitor
    (e.g. one just got disconnected) — must not crash, falls back to
    whichever screen QApplication.primaryScreen() reports."""
    from components import popup_position

    primary = _screen(QRect(0, 0, 1920, 1080))
    monkeypatch.setattr(popup_position.QApplication, "screenAt", lambda pt: None)
    monkeypatch.setattr(popup_position.QApplication, "primaryScreen", lambda: primary)

    popup = QWidget()
    popup.resize(260, 200)

    result = popup_position.clamp_to_screen(popup, QPoint(100, 100))

    assert result == QPoint(100, 100)


def test_respects_a_nonzero_screen_origin(qapp, monkeypatch):
    """A secondary monitor's availableGeometry() doesn't start at (0, 0) —
    the clamped position must stay within THAT screen's own bounds, not
    assume the primary screen's origin."""
    from components import popup_position

    screen = _screen(QRect(2000, 100, 800, 600))   # a monitor to the right, offset down
    monkeypatch.setattr(popup_position.QApplication, "screenAt", lambda pt: screen)

    popup = QWidget()
    popup.resize(260, 200)

    # Preferred position near the bottom-right of this secondary screen.
    result = popup_position.clamp_to_screen(popup, QPoint(2750, 650))

    assert result.x() == 2000 + 800 - 260
    assert result.y() == 100 + 600 - 200
