import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def lmv(qapp, tmp_path, monkeypatch):
    from services import strategy_store as store
    monkeypatch.setattr(store, "_STORE_FILE", str(tmp_path / "s.json"))
    from screens.live_viewer import LiveViewerWindow
    w = LiveViewerWindow("", "", "", [])
    w._headers = ["Scrip Name", "Current"]
    w._data    = [["INFY", "100"]]
    w._visible_cols = set(range(2))
    w._populate_table(w._data, changed_keys=set())
    return w


def _strategies(n, active=True):
    return [
        {"id": i, "name": f"Strategy {i}", "active": active, "category": "Daily"}
        for i in range(n)
    ]


def test_no_active_strategies_shows_empty_label(lmv):
    lmv.set_strategies(_strategies(3, active=False))
    assert lmv._strategy_names_lbl.text() == ""
    assert lmv._all_active_strategy_names == []


def test_few_active_strategies_shown_inline_no_link(lmv):
    lmv.set_strategies(_strategies(3, active=True))
    text = lmv._strategy_names_lbl.text()
    assert text == "Strategies : Strategy 0, Strategy 1, Strategy 2"
    assert "view more" not in text


def test_font_matches_stock_count_label(lmv):
    sf = lmv._stock_count_lbl.font()
    nf = lmv._strategy_names_lbl.font()
    assert sf.pointSize() == nf.pointSize()
    assert sf.bold() == nf.bold()
    assert sf.family() == nf.family()


def test_more_than_max_shows_truncated_with_view_more_link(lmv):
    lmv.set_strategies(_strategies(20, active=True))
    text = lmv._strategy_names_lbl.text()
    assert "Strategy 0" in text and "Strategy 9" in text
    assert "Strategy 10" not in text   # 11th name, past the 10-name cap
    assert "view more" in text
    assert len(lmv._all_active_strategy_names) == 20


def test_view_more_link_opens_popup_with_all_names(lmv):
    from screens.live_viewer import _StrategyNamesPopup
    lmv.set_strategies(_strategies(20, active=True))
    lmv._show_strategy_names_popup("more")
    popups = [c for c in lmv.children() if isinstance(c, _StrategyNamesPopup)]
    assert len(popups) == 1
    assert popups[0]._names == lmv._all_active_strategy_names
    assert len(popups[0]._names) == 20


def test_exactly_max_count_has_no_view_more_link(lmv):
    lmv.set_strategies(_strategies(10, active=True))
    text = lmv._strategy_names_lbl.text()
    assert "Strategy 9" in text
    assert "view more" not in text


def test_strategy_name_html_is_escaped(lmv):
    strategies = [{"id": 1, "name": "A & B <script>", "active": True, "category": "Daily"}]
    lmv.set_strategies(strategies)
    text = lmv._strategy_names_lbl.text()
    assert "A &amp; B &lt;script&gt;" in text
