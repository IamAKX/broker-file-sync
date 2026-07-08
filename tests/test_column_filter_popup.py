"""Tests for the shared ColumnFilterPopup widget."""
import sys
import os
import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


@pytest.fixture(scope="module")
def qapp():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication(sys.argv)


def test_column_filter_popup_importable_from_components(qapp):
    from components.column_filter_popup import ColumnFilterPopup
    popup = ColumnFilterPopup(["A", "B", "C"], {0, 1, 2}, theme=None)
    assert len(popup._checks) == 3


def test_column_filter_popup_apply_emits_visible_set(qapp):
    from components.column_filter_popup import ColumnFilterPopup
    popup = ColumnFilterPopup(["A", "B", "C"], {0, 1, 2}, theme=None)
    popup._checks[1].setChecked(False)
    emitted = []
    popup.columns_changed.connect(lambda visible: emitted.append(visible))
    popup._apply()
    assert emitted == [{0, 2}]


def test_live_viewer_still_exposes_column_filter_popup(qapp):
    from screens.live_viewer import ColumnFilterPopup
    assert ColumnFilterPopup is not None
