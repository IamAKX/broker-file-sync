import sys
from datetime import datetime

import pytest
from PySide6.QtWidgets import QApplication

from api import strategy_signals_api
from services.strategy_alerts import state_store


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.live_alerts import LiveAlertsScreen
    return LiveAlertsScreen(AppController(qapp))


def _api_item(symbol="INFY", status="open", **extra):
    """StrategySignalResponse-shaped dict, as api/strategy_signals_api.py's
    list_signals() would return one item — see screens/live_alerts.py's
    _signal_from_api_item for how the screen adapts this."""
    item = {
        "id": "sig-1", "strategy_id": "strat-1", "strategy_name": "PWHBUY",
        "symbol": symbol, "sector": "FINANCE", "direction": "BUY", "status": status,
        "entry_time": datetime.now().isoformat(), "entry_price": 100.0,
        "resolved_at": None,
        "running_high": 105.0, "running_low": 98.0, "score": 150.0,
        "risk_reward": None,
        "metrics": {
            "m1": {"name": "Stop Loss", "role": "stop_loss", "value": 95.0},
            "m2": {"name": "Target 1", "role": "target", "value": 110.0,
                   "achieved": False, "achieved_at": None},
        },
    }
    item.update(extra)
    return item


class _FakeListApi:
    """Records every list_signals() call (for filter/pagination assertions)
    and returns a fixed page — matching StrategySignalListResponse's shape."""

    def __init__(self, items=None, total=None, total_pages=None):
        self.items = items or []
        self.total = total if total is not None else len(self.items)
        self.total_pages = total_pages if total_pages is not None else (1 if self.items else 0)
        self.calls = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return {
            "items": self.items, "total": self.total,
            "page": kwargs.get("page", 1), "page_size": kwargs.get("page_size", 25),
            "total_pages": self.total_pages,
        }


def _local_pending(strategy_id="strat-1", symbol="TCS"):
    return {
        "state": "pending", "strategy_id": strategy_id, "strategy_name": "PWHBUY",
        "symbol": symbol, "direction": "BUY", "first_true_at": datetime.now().isoformat(),
    }


def test_screen_creates(screen):
    assert screen is not None


def test_empty_state_shows_no_rows(screen):
    assert screen._table.rowCount() == 0


def test_open_signal_appears_in_table(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item()])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    assert screen._table.rowCount() == 1
    assert screen._table.item(0, 1).text() == "PWHBUY"
    assert screen._table.item(0, 3).text() == "INFY"
    assert screen._table.item(0, 5).text() == "Open"


def test_resolved_alert_shows_resolution_status(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item(
        symbol="WIPRO", status="stopped_out", resolved_at=datetime.now().isoformat(),
    )])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, 3).text() == "WIPRO")
    assert screen._table.item(row, 5).text() == "Stopped Out"


def test_targets_achieved_status(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item(
        symbol="HDFC", status="all_targets_achieved", resolved_at=datetime.now().isoformat(),
    )])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, 3).text() == "HDFC")
    assert screen._table.item(row, 5).text() == "Targets Achieved"


def test_metrics_summary_shows_target_achieved_marker(screen, monkeypatch):
    item = _api_item(symbol="HDFC")
    item["metrics"]["m2"]["achieved"] = True
    fake = _FakeListApi(items=[item])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, 3).text() == "HDFC")
    details = screen._table.item(row, 7).text()
    assert "Target 1: 110.00 ✓" in details
    assert "Stop Loss: 95.00" in details


# ── Pending strip (local, unfiltered — never synced to the backend) ─────────

def test_pending_signal_shows_in_pending_strip_not_the_table(screen, monkeypatch):
    fake = _FakeListApi(items=[])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    state_store.set_open_signal("strat-1::TCS", _local_pending(), force_flush=True)

    screen._refresh_pending()
    screen._refresh_table()

    assert screen._table.rowCount() == 0   # pending never reaches the backend-driven table
    # isVisible() only reflects reality once the screen is actually shown in
    # a real window (which this test fixture never does) — check the
    # rendered text and the explicit-visibility flag instead.
    assert not screen._pending_lbl.isHidden()
    assert "TCS" in screen._pending_lbl.text()


def test_pending_strip_hidden_when_nothing_pending(screen):
    screen._refresh_pending()
    assert screen._pending_lbl.isHidden()


# ── Filters live in a popup dialog — nothing re-queries until Apply Filters
# is clicked (screen._on_apply_filters_clicked), not on every combo change.

def test_strategy_filter_passes_selected_strategy_id(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._strategy_combo.addItem("My Strategy", "strat-42")
    screen._strategy_combo.setCurrentIndex(screen._strategy_combo.count() - 1)
    screen._on_apply_filters_clicked()

    assert fake.calls[-1]["strategy_id"] == "strat-42"


def test_direction_filter_passes_selected_direction(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    idx = screen._direction_combo.findData("SELL")
    screen._direction_combo.setCurrentIndex(idx)
    screen._on_apply_filters_clicked()

    assert fake.calls[-1]["direction"] == "SELL"


def test_status_filter_passes_selected_status(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    idx = screen._status_combo.findData("stopped_out")
    screen._status_combo.setCurrentIndex(idx)
    screen._on_apply_filters_clicked()

    assert fake.calls[-1]["status"] == "stopped_out"


def test_sector_and_stock_filters_pass_selected_values(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    sector_idx = screen._sector_combo.findData("FINANCE")
    screen._sector_combo.setCurrentIndex(sector_idx)
    stock_idx = screen._stock_combo.findData("INFY")
    screen._stock_combo.setCurrentIndex(stock_idx)
    screen._on_apply_filters_clicked()

    assert fake.calls[-1]["sector"] == "FINANCE"
    assert fake.calls[-1]["symbol"] == "INFY"


def test_filters_combine_with_and_in_one_request(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)

    screen._direction_combo.setCurrentIndex(screen._direction_combo.findData("BUY"))
    screen._status_combo.setCurrentIndex(screen._status_combo.findData("open"))
    screen._on_apply_filters_clicked()

    last = fake.calls[-1]
    assert last["direction"] == "BUY"
    assert last["status"] == "open"


def test_combo_change_alone_does_not_refresh(screen, monkeypatch):
    """Regression guard for the redesign itself: changing a filter combo
    must NOT fire a request on its own — only Apply Filters does. This is
    also what eliminated the whole class of construction-order/signal-timing
    bugs the old inline auto-refreshing panel had."""
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    fake.calls.clear()

    screen._direction_combo.setCurrentIndex(screen._direction_combo.findData("SELL"))
    screen._status_combo.setCurrentIndex(screen._status_combo.findData("open"))

    assert fake.calls == []


# ── Filter button + popup dialog ─────────────────────────────────────────

def test_filter_button_shows_no_count_when_nothing_active(screen):
    assert screen._filter_btn.text() == "Filter"


def test_filter_button_shows_count_after_apply(screen, monkeypatch):
    monkeypatch.setattr(strategy_signals_api, "list_signals", _FakeListApi())
    screen._direction_combo.setCurrentIndex(screen._direction_combo.findData("SELL"))
    screen._status_combo.setCurrentIndex(screen._status_combo.findData("open"))
    screen._on_apply_filters_clicked()

    assert screen._filter_btn.text() == "Filter (2)"


def test_clear_filters_resets_button_label_to_no_count(screen, monkeypatch):
    monkeypatch.setattr(strategy_signals_api, "list_signals", _FakeListApi())
    screen._direction_combo.setCurrentIndex(screen._direction_combo.findData("SELL"))
    screen._on_apply_filters_clicked()
    assert screen._filter_btn.text() == "Filter (1)"

    screen._on_clear_filters()
    assert screen._filter_btn.text() == "Filter"


def test_open_filter_dialog_calls_exec(screen, monkeypatch):
    calls = []
    monkeypatch.setattr(screen._filter_dialog, "exec", lambda: calls.append(1))
    screen._filter_btn.click()
    assert calls == [1]


def test_apply_filters_closes_dialog_before_refreshing(screen, monkeypatch):
    monkeypatch.setattr(strategy_signals_api, "list_signals", _FakeListApi())
    accept_calls = []
    monkeypatch.setattr(screen._filter_dialog, "accept", lambda: accept_calls.append(1))

    screen._on_apply_filters_clicked()

    assert accept_calls == [1]


def test_no_filter_selected_sends_none_for_every_field(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table(reset_page=True)

    last = fake.calls[-1]
    for key in ("strategy_id", "direction", "symbol", "sector", "status", "start_time", "end_time"):
        assert last[key] is None


def test_time_range_unchecked_sends_no_time_filter(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._time_range_check.setChecked(False)
    screen._refresh_table(reset_page=True)

    last = fake.calls[-1]
    assert last["start_time"] is None
    assert last["end_time"] is None


def test_time_range_checked_sends_from_and_to(screen, monkeypatch):
    from PySide6.QtCore import QDateTime

    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._time_range_check.setChecked(True)
    screen._from_edit.setDateTime(QDateTime(2026, 8, 11, 10, 0, 0))
    screen._to_edit.setDateTime(QDateTime(2026, 8, 11, 13, 0, 0))
    screen._refresh_table(reset_page=True)

    last = fake.calls[-1]
    assert last["start_time"].startswith("2026-08-11T10:00")
    assert last["end_time"].startswith("2026-08-11T13:00")


def test_time_range_checkbox_enables_the_date_edits(screen):
    assert not screen._from_edit.isEnabled()
    assert not screen._to_edit.isEnabled()
    screen._time_range_check.setChecked(True)
    assert screen._from_edit.isEnabled()
    assert screen._to_edit.isEnabled()


# ── Regression: page_size always valid, no duplicate "All" ─────────────────
# Bug seen live: "query.page_size: Input should be 25, 50 or 100" fired at
# app startup — traced to _DIRECTION_OPTIONS/_STATUS_OPTIONS being appended
# AFTER the old inline panel's combo helper already added its own "All" (a
# duplicate, and an addItem call issued after a change signal was already
# connected), interacting with widget construction order. The redesign here
# (filters moved into a popup dialog — see the block above) removes the
# whole signal-timing hazard by not connecting any change signal to these
# combos at all; _dialog_combo_row takes the full option list up front
# regardless, and _resolved_page_size's defensive clamp stays as a second,
# independent safety net.

def test_direction_and_status_combos_have_no_duplicate_all(screen):
    direction_items = [screen._direction_combo.itemText(i) for i in range(screen._direction_combo.count())]
    status_items = [screen._status_combo.itemText(i) for i in range(screen._status_combo.count())]
    assert direction_items.count("All") == 1
    assert status_items.count("All") == 1


def test_resolved_page_size_is_always_valid(screen):
    assert screen._resolved_page_size() in (25, 50, 100)


def test_resolved_page_size_falls_back_when_combo_missing(screen):
    real_combo = screen._page_size_combo
    screen._page_size_combo = None
    try:
        assert screen._resolved_page_size() == 25
    finally:
        screen._page_size_combo = real_combo


def test_clear_filters_resets_every_combo_and_time_range(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)

    screen._direction_combo.setCurrentIndex(screen._direction_combo.findData("SELL"))
    screen._status_combo.setCurrentIndex(screen._status_combo.findData("open"))
    screen._time_range_check.setChecked(True)

    screen._on_clear_filters()

    assert screen._direction_combo.currentData() is None
    assert screen._status_combo.currentData() is None
    assert screen._time_range_check.isChecked() is False


# ── Pagination ───────────────────────────────────────────────────────────

def test_page_size_change_resets_to_page_one(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._page = 3
    idx = screen._page_size_combo.findData(50)
    screen._page_size_combo.setCurrentIndex(idx)

    assert fake.calls[-1]["page"] == 1
    assert fake.calls[-1]["page_size"] == 50


def test_next_and_prev_page_buttons(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item()], total=100, total_pages=4)
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table(reset_page=True)
    assert screen._page == 1
    assert not screen._prev_btn.isEnabled()
    assert screen._next_btn.isEnabled()

    screen._on_next_page()
    assert screen._page == 2
    assert fake.calls[-1]["page"] == 2
    assert screen._prev_btn.isEnabled()

    screen._on_prev_page()
    assert screen._page == 1
    assert fake.calls[-1]["page"] == 1


def test_next_page_disabled_on_last_page(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item()], total=10, total_pages=1)
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table(reset_page=True)

    assert not screen._next_btn.isEnabled()


def test_page_label_shows_total_count(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item()], total=57, total_pages=3)
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table(reset_page=True)

    assert "57 total" in screen._page_lbl.text()
    assert "Page 1 of 3" in screen._page_lbl.text()


# ── Clear History: local AND backend ────────────────────────────────────────

def test_clear_history_button_confirms_and_clears_both_stores(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)

    state_store.set_open_signal("strat-1::INFY", _local_pending(symbol="INFY"), force_flush=True)
    clear_calls = []
    monkeypatch.setattr(strategy_signals_api, "clear_signals", lambda: clear_calls.append(1))
    monkeypatch.setattr(strategy_signals_api, "list_signals", _FakeListApi())

    screen._on_clear_history()

    assert state_store.get_open_signals() == {}
    assert clear_calls == [1]


def test_clear_history_declined_keeps_local_data(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)

    state_store.set_open_signal("strat-1::INFY", _local_pending(symbol="INFY"), force_flush=True)
    clear_calls = []
    monkeypatch.setattr(strategy_signals_api, "clear_signals", lambda: clear_calls.append(1))

    screen._on_clear_history()

    assert state_store.get_open_signals() != {}
    assert clear_calls == []


def test_reload_alerts_resets_filters_and_refreshes(screen, monkeypatch):
    fake = _FakeListApi()
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._direction_combo.setCurrentIndex(screen._direction_combo.findData("SELL"))

    screen.reload_alerts()

    assert screen._direction_combo.currentData() is None


# ── Column layout (regression guard for the truncation fix) ─────────────────

def test_high_and_low_are_separate_columns(screen):
    assert "High" in screen._COLUMNS
    assert "Low" in screen._COLUMNS
    assert "High / Low" not in screen._COLUMNS


def test_only_details_column_stretches(screen):
    from PySide6.QtWidgets import QHeaderView
    header = screen._table.horizontalHeader()
    for col, name in enumerate(screen._COLUMNS):
        mode = header.sectionResizeMode(col)
        if name == "Details":
            assert mode == QHeaderView.ResizeMode.Stretch
        else:
            assert mode == QHeaderView.ResizeMode.Interactive


def test_non_stretch_columns_have_a_sensible_default_width(screen):
    date_col = screen._COLUMNS.index("Date / Time")
    direction_col = screen._COLUMNS.index("Direction")
    assert screen._table.columnWidth(date_col) > screen._table.columnWidth(direction_col)


def test_cells_have_full_text_tooltip(screen, monkeypatch):
    fake = _FakeListApi(items=[_api_item()])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()
    strategy_col = screen._COLUMNS.index("Strategy")
    item = screen._table.item(0, strategy_col)
    assert item.toolTip() == item.text() == "PWHBUY"


def test_status_column_is_color_coded_by_outcome(screen, monkeypatch):
    fake = _FakeListApi(items=[
        _api_item(symbol="STOPPED", status="stopped_out"),
        _api_item(symbol="INFY", status="open"),
    ])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    status_col = screen._COLUMNS.index("Status")
    stock_col = screen._COLUMNS.index("Stock")

    open_row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, stock_col).text() == "INFY")
    stopped_row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, stock_col).text() == "STOPPED")

    open_color = screen._table.item(open_row, status_col).foreground().color()
    stopped_color = screen._table.item(stopped_row, status_col).foreground().color()
    assert open_color != stopped_color


# ── Row click -> detail popup ────────────────────────────────────────────────

def test_clicking_row_opens_detail_dialog_with_strategy_and_symbol(screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    fake = _FakeListApi(items=[_api_item()])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    captured = {}

    def _fake_exec(self):
        captured["title"] = self.windowTitle()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", _fake_exec)
    screen._on_row_clicked(0, 0)

    assert "PWHBUY" in captured["title"]
    assert "INFY" in captured["title"]


def test_detail_dialog_lists_every_metric_with_achievement_status(screen, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel

    item = _api_item()
    item["metrics"]["m2"]["achieved"] = True
    item["metrics"]["m2"]["achieved_at"] = datetime.now().isoformat()
    fake = _FakeListApi(items=[item])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    captured = {}

    def _fake_exec(self):
        captured["labels"] = [w.text() for w in self.findChildren(QLabel)]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", _fake_exec)
    screen._on_row_clicked(0, 0)

    joined = " ".join(captured["labels"])
    assert "Stop Loss" in joined
    assert "Target 1" in joined
    assert "Achieved" in joined


def test_detail_dialog_shows_score_and_risk_reward_when_present(screen, monkeypatch):
    from PySide6.QtWidgets import QDialog, QLabel

    item = _api_item(score=150.0, risk_reward={"numerator": 7.0, "denominator": 13.0, "ratio": 0.54})
    fake = _FakeListApi(items=[item])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    captured = {}

    def _fake_exec(self):
        captured["labels"] = [w.text() for w in self.findChildren(QLabel)]
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(QDialog, "exec", _fake_exec)
    screen._on_row_clicked(0, 0)

    joined = " ".join(captured["labels"])
    assert "150" in joined
    assert "0.54" in joined


def test_row_click_out_of_range_does_not_raise(screen):
    screen._rows = []
    screen._on_row_clicked(5, 0)  # must not raise


def test_single_click_does_not_open_dialog(screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    fake = _FakeListApi(items=[_api_item()])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    calls = []
    monkeypatch.setattr(QDialog, "exec", lambda self: calls.append(1) or QDialog.DialogCode.Accepted)

    screen._table.cellClicked.emit(0, 0)

    assert calls == []


def test_double_click_opens_dialog(screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    fake = _FakeListApi(items=[_api_item()])
    monkeypatch.setattr(strategy_signals_api, "list_signals", fake)
    screen._refresh_table()

    calls = []
    monkeypatch.setattr(QDialog, "exec", lambda self: calls.append(1) or QDialog.DialogCode.Accepted)

    screen._table.cellDoubleClicked.emit(0, 0)

    assert calls == [1]
