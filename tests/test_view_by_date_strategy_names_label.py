"""Tests for InceptionViewByDateScreen's bottom-right "applied strategies"
display (issue #47) — the EMV/View by Date counterpart of LiveViewerWindow's
own _strategy_names_lbl (see tests/test_lmv_strategy_names_label.py, whose
taxonomy this mirrors)."""
import sys

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)


@pytest.fixture
def screen(qapp, controller):
    from screens.inception_view_by_date import InceptionViewByDateScreen
    return InceptionViewByDateScreen(controller)


def _strategies(n, active=True):
    return [
        {"id": str(i), "name": f"Strategy {i}", "active": active, "row_filter": [], "columns": []}
        for i in range(n)
    ]


def test_no_active_strategies_shows_empty_label(screen):
    screen._strategies = _strategies(3, active=False)
    screen._update_strat_btn_label()
    assert screen._strategy_names_lbl.text() == ""
    assert screen._all_active_strategy_names == []


def test_few_active_strategies_shown_inline_no_link(screen):
    screen._strategies = _strategies(3, active=True)
    screen._update_strat_btn_label()
    text = screen._strategy_names_lbl.text()
    assert text == "Strategies : Strategy 0, Strategy 1, Strategy 2"
    assert "view more" not in text


def test_font_matches_status_label(screen):
    screen._strategies = _strategies(1, active=True)
    screen._update_strat_btn_label()
    sf = screen._status_lbl.font()
    nf = screen._strategy_names_lbl.font()
    assert sf.pointSize() == nf.pointSize()
    assert sf.bold() == nf.bold()
    assert sf.family() == nf.family()


def test_more_than_max_shows_truncated_with_view_more_link(screen):
    screen._strategies = _strategies(20, active=True)
    screen._update_strat_btn_label()
    text = screen._strategy_names_lbl.text()
    assert "Strategy 0" in text and "Strategy 9" in text
    assert "Strategy 10" not in text   # 11th name, past the 10-name cap
    assert "view more" in text
    assert len(screen._all_active_strategy_names) == 20


def test_exactly_max_count_has_no_view_more_link(screen):
    screen._strategies = _strategies(10, active=True)
    screen._update_strat_btn_label()
    text = screen._strategy_names_lbl.text()
    assert "Strategy 9" in text
    assert "view more" not in text


def test_view_more_link_opens_popup_with_all_names(screen):
    from screens.live_viewer import _StrategyNamesPopup

    screen._strategies = _strategies(20, active=True)
    screen._update_strat_btn_label()
    screen._show_strategy_names_popup("more")

    popups = [c for c in screen.children() if isinstance(c, _StrategyNamesPopup)]
    assert len(popups) == 1
    assert popups[0]._names == screen._all_active_strategy_names
    assert len(popups[0]._names) == 20


def test_strategy_name_html_is_escaped(screen):
    screen._strategies = [
        {"id": "1", "name": "A & B <script>", "active": True, "row_filter": [], "columns": []},
    ]
    screen._update_strat_btn_label()
    text = screen._strategy_names_lbl.text()
    assert "A &amp; B &lt;script&gt;" in text


def test_label_updates_after_strategies_applied(screen):
    """The actual hook path issue #47 needs working, not just the render
    logic in isolation — _on_strategies_applied (the picker's Apply
    callback) must refresh the label, same as it already refreshes the
    button's count text."""
    screen._strategies = _strategies(2, active=False)
    screen._update_strat_btn_label()
    assert screen._strategy_names_lbl.text() == ""

    screen._on_strategies_applied([
        {"id": "0", "name": "Strategy 0", "active": True},
        {"id": "1", "name": "Strategy 1", "active": False},
    ])

    assert screen._strategy_names_lbl.text() == "Strategies : Strategy 0"
