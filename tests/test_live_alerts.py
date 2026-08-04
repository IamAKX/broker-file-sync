import sys
from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from services.strategy_alerts import state_store


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.live_alerts import LiveAlertsScreen
    return LiveAlertsScreen(AppController(qapp))


def _open_signal(strategy_id="strat-1", symbol="INFY", state="open", **extra):
    signal = {
        "state": state,
        "strategy_id": strategy_id, "strategy_name": "PWHBUY", "symbol": symbol,
        "sector": "FINANCE", "direction": "BUY",
        "entry_time": datetime.now().isoformat(), "entry_price": 100.0,
        "metrics": {
            "m1": {"name": "Stop Loss", "role": "stop_loss", "value": 95.0},
            "m2": {"name": "Target 1", "role": "target", "value": 110.0, "achieved": False, "achieved_at": None},
        },
        "risk_reward": None, "score": 150,
        "running_high": 105.0, "running_low": 98.0,
    }
    signal.update(extra)
    return signal


def test_screen_creates(screen):
    assert screen is not None


def test_empty_state_shows_no_rows(screen):
    assert screen._table.rowCount() == 0


def test_open_signal_appears_in_table(screen):
    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen._refresh_table()

    assert screen._table.rowCount() == 1
    assert screen._table.item(0, 1).text() == "PWHBUY"
    assert screen._table.item(0, 3).text() == "INFY"
    assert screen._table.item(0, 5).text() == "Open"


def test_pending_signal_shows_pending_status(screen):
    state_store.set_open_signal(
        "strat-1::TCS",
        _open_signal(symbol="TCS", state="pending", first_true_at=datetime.now().isoformat()),
        force_flush=True,
    )
    screen._refresh_table()

    row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, 3).text() == "TCS")
    assert screen._table.item(row, 5).text() == "Pending"


def test_resolved_alert_shows_resolution_status(screen):
    resolved = _open_signal(symbol="WIPRO")
    resolved["resolution"] = "stopped_out"
    resolved["resolved_at"] = datetime.now().isoformat()
    state_store.append_alert_history(resolved)
    screen._refresh_table()

    row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, 3).text() == "WIPRO")
    assert screen._table.item(row, 5).text() == "Stopped Out"


def test_metrics_summary_shows_target_achieved_marker(screen):
    signal = _open_signal(symbol="HDFC")
    signal["metrics"]["m2"]["achieved"] = True
    state_store.set_open_signal("strat-1::HDFC", signal, force_flush=True)
    screen._refresh_table()

    row = next(r for r in range(screen._table.rowCount()) if screen._table.item(r, 3).text() == "HDFC")
    details = screen._table.item(row, 7).text()
    assert "Target 1: 110.00 ✓" in details
    assert "Stop Loss: 95.00" in details


def test_recency_filter_excludes_old_entries(screen):
    old_time = (datetime.now() - timedelta(hours=5)).isoformat()
    state_store.set_open_signal(
        "strat-1::OLD", _open_signal(symbol="OLD", entry_time=old_time), force_flush=True,
    )
    state_store.set_open_signal(
        "strat-1::NEW", _open_signal(symbol="NEW"), force_flush=True,
    )

    screen._recency_combo.setCurrentText("Last 30 minutes")
    symbols = [screen._table.item(r, 3).text() for r in range(screen._table.rowCount())]
    assert "NEW" in symbols
    assert "OLD" not in symbols

    screen._recency_combo.setCurrentText("All")
    symbols = [screen._table.item(r, 3).text() for r in range(screen._table.rowCount())]
    assert "OLD" in symbols


def test_clear_history_button_confirms_and_clears(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)

    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen._refresh_table()
    assert screen._table.rowCount() > 0

    screen._on_clear_history()

    assert screen._table.rowCount() == 0
    assert state_store.get_open_signals() == {}
    assert state_store.get_alert_history() == []


def test_clear_history_declined_keeps_data(screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.No)

    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen._on_clear_history()

    assert state_store.get_open_signals() != {}


def test_reload_alerts_rerenders_table(screen):
    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen.reload_alerts()
    assert screen._table.rowCount() == 1


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
    # Regression guard for the original bug: every column sharing one Stretch
    # mode divided width evenly regardless of content, truncating long
    # columns (Date/Time, Details, High/Low) while short ones (Direction, %
    # Move) had room to spare.
    date_col = screen._COLUMNS.index("Date / Time")
    direction_col = screen._COLUMNS.index("Direction")
    assert screen._table.columnWidth(date_col) > screen._table.columnWidth(direction_col)


def test_cells_have_full_text_tooltip(screen):
    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen._refresh_table()
    strategy_col = screen._COLUMNS.index("Strategy")
    item = screen._table.item(0, strategy_col)
    assert item.toolTip() == item.text() == "PWHBUY"


def test_status_column_is_color_coded_by_outcome(screen):
    resolved = _open_signal(symbol="STOPPED")
    resolved["resolution"] = "stopped_out"
    state_store.append_alert_history(resolved)
    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)  # "Open"
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

    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
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

    signal = _open_signal(symbol="INFY")
    signal["metrics"]["m2"]["achieved"] = True
    signal["metrics"]["m2"]["achieved_at"] = datetime.now().isoformat()
    state_store.set_open_signal("strat-1::INFY", signal, force_flush=True)
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

    signal = _open_signal(symbol="INFY")
    signal["score"] = 150
    signal["risk_reward"] = {"numerator": 7.0, "denominator": 13.0, "ratio": 0.54}
    state_store.set_open_signal("strat-1::INFY", signal, force_flush=True)
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

    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen._refresh_table()

    calls = []
    monkeypatch.setattr(QDialog, "exec", lambda self: calls.append(1) or QDialog.DialogCode.Accepted)

    screen._table.cellClicked.emit(0, 0)

    assert calls == []


def test_double_click_opens_dialog(screen, monkeypatch):
    from PySide6.QtWidgets import QDialog

    state_store.set_open_signal("strat-1::INFY", _open_signal(), force_flush=True)
    screen._refresh_table()

    calls = []
    monkeypatch.setattr(QDialog, "exec", lambda self: calls.append(1) or QDialog.DialogCode.Accepted)

    screen._table.cellDoubleClicked.emit(0, 0)

    assert calls == [1]
