import sys

import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _make_editor(qapp, columns=None):
    from services.strategy_store import new_strategy
    from screens.strategy_builder import StrategyEditor

    s = new_strategy("T")
    if columns:
        s["columns"] = columns
    editor = StrategyEditor(s, ["Scrip Name", "Current", "High", "Low"], None)
    return editor


def _rule_column(name="Signal"):
    return {
        "name": name,
        "formula": [{"type": "col", "value": "Current"}],
        "fmt_rules": [
            {"condition": [{"type": "self"}, {"type": "op", "value": ">"}, {"type": "num", "value": "0"}],
             "color": "#39d353", "target_column": None},
        ],
    }


# ── Defaults / construction ─────────────────────────────────────────────────

def test_notification_section_defaults(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    assert section.result_config()["enabled"] is False
    assert section.result_config()["direction"] == "BUY"
    assert section.result_config()["metrics"] == []


def test_enabled_toggle_updates_config(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._enabled_toggle.toggled.emit(True)
    assert section.result_config()["enabled"] is True


def test_direction_combo_updates_config(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._direction_combo.setCurrentText("SELL")
    assert section.result_config()["direction"] == "SELL"


# ── Trigger ──────────────────────────────────────────────────────────────────
#
# Deliberately a single standalone condition, not "pick one column's existing
# conditional-formatting rule" — a strategy can have several columns, and
# conditional formatting is inherently per-column, so there's no one
# well-defined "the strategy's rule" to point at (see models.py's
# trigger_condition docstring).

def test_trigger_condition_defaults_empty(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    assert section.result_config()["trigger_condition"] == []
    assert section._trigger_preview.text() == "—"


def test_custom_condition_editor_uses_combined_headers(qapp, monkeypatch):
    editor = _make_editor(qapp, columns=[{"name": "Out", "formula": [], "fmt_rules": []}])
    section = editor._notif_section
    from screens import formula_editor

    captured = {}

    class _FakeDlg:
        def __init__(self, *a, **kw):
            captured.update(kw)
        def exec(self):
            return 0
        def get_tokens(self):
            return []

    monkeypatch.setattr(formula_editor, "ExpressionEditorDialog", _FakeDlg)
    section._open_trigger_condition_editor()

    assert captured.get("allow_self") is False
    assert "Out" in captured.get("lmv_headers", [])


def test_accepting_condition_editor_saves_trigger_condition(qapp, monkeypatch):
    editor = _make_editor(qapp)
    section = editor._notif_section
    from screens import formula_editor
    from PySide6.QtWidgets import QDialog as _QD

    tokens = [{"type": "col", "value": "Current"}, {"type": "op", "value": ">"}, {"type": "num", "value": "100"}]

    class _FakeDlg:
        def __init__(self, *a, **kw):
            pass
        def exec(self):
            return _QD.DialogCode.Accepted
        def get_tokens(self):
            return tokens

    monkeypatch.setattr(formula_editor, "ExpressionEditorDialog", _FakeDlg)
    section._open_trigger_condition_editor()

    assert section.result_config()["trigger_condition"] == tokens
    assert "Current" in section._trigger_preview.text()


# ── Debounce / Score ─────────────────────────────────────────────────────────

def test_debounce_spin_updates_config(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._debounce_spin.setValue(5)
    assert section.result_config()["debounce_minutes"] == 5


def test_score_parses_float(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._score_edit.setText("150")
    assert section.result_config()["score"] == 150.0


def test_score_blank_is_none(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._score_edit.setText("150")
    section._score_edit.setText("")
    assert section.result_config()["score"] is None


def test_score_invalid_text_keeps_last_valid_value(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._score_edit.setText("150")
    section._score_edit.setText("15x")
    assert section.result_config()["score"] == 150.0


# ── Risk:Reward ──────────────────────────────────────────────────────────────

def test_risk_reward_disabled_by_default(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    assert section.result_config()["risk_reward"] is None
    assert section._rr_widget.isHidden()


def test_enabling_risk_reward_creates_empty_formulas(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._rr_enabled_check.setChecked(True)
    rr = section.result_config()["risk_reward"]
    assert rr == {"numerator": [], "denominator": []}
    assert not section._rr_widget.isHidden()


def test_disabling_risk_reward_clears_it(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._rr_enabled_check.setChecked(True)
    section._rr_enabled_check.setChecked(False)
    assert section.result_config()["risk_reward"] is None


def test_risk_reward_formula_editor_uses_combined_headers(qapp, monkeypatch):
    editor = _make_editor(qapp, columns=[{"name": "Out", "formula": [], "fmt_rules": []}])
    section = editor._notif_section
    section._rr_enabled_check.setChecked(True)
    from screens import formula_editor

    captured = {}

    class _FakeDlg:
        def __init__(self, *a, **kw):
            captured.update(kw)
        def exec(self):
            return 1  # Accepted
        def get_tokens(self):
            return [{"type": "col", "value": "Out"}]

    monkeypatch.setattr(formula_editor, "ExpressionEditorDialog", _FakeDlg)
    from PySide6.QtWidgets import QDialog as _QD
    monkeypatch.setattr(_QD, "DialogCode", _QD.DialogCode)
    section._open_rr_formula_editor("numerator", section._rr_num_preview)

    assert "Out" in captured.get("lmv_headers", [])
    assert section.result_config()["risk_reward"]["numerator"] == [{"type": "col", "value": "Out"}]


# ── Metrics ──────────────────────────────────────────────────────────────────

def test_add_metric_appends_default(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._add_metric()
    metrics = section.result_config()["metrics"]
    assert len(metrics) == 1
    assert metrics[0]["role"] == "informational"
    assert "id" in metrics[0]


def test_delete_metric_removes_it(qapp):
    editor = _make_editor(qapp)
    section = editor._notif_section
    section._add_metric()
    section._add_metric()
    section._delete_metric(0)
    assert len(section.result_config()["metrics"]) == 1


def test_metric_formula_editor_uses_combined_headers(qapp, monkeypatch):
    editor = _make_editor(qapp, columns=[{"name": "Out", "formula": [], "fmt_rules": []}])
    section = editor._notif_section
    section._add_metric()
    from screens import formula_editor

    captured = {}

    class _FakeDlg:
        def __init__(self, *a, **kw):
            captured.update(kw)
        def exec(self):
            return 1
        def get_tokens(self):
            return [{"type": "num", "value": "95"}]

    monkeypatch.setattr(formula_editor, "ExpressionEditorDialog", _FakeDlg)
    from PySide6.QtWidgets import QLabel
    section._open_metric_formula_editor(0, QLabel())

    assert "Out" in captured.get("lmv_headers", [])
    assert section.result_config()["metrics"][0]["formula"] == [{"type": "num", "value": "95"}]


# ── Persistence via StrategyEditor ───────────────────────────────────────────

def test_strategy_editor_loads_existing_notification_config(qapp):
    from services.strategy_store import new_strategy
    from services.strategy_alerts import config_store as alerts_config_store
    from services.strategy_alerts.models import new_notification_config
    from screens.strategy_builder import StrategyEditor

    s = new_strategy("T")
    cfg = new_notification_config()
    cfg["enabled"] = True
    cfg["debounce_minutes"] = 7
    alerts_config_store.save_config(s["id"], cfg)

    editor = StrategyEditor(s, [], None)
    assert editor._notif_section.result_config()["enabled"] is True
    assert editor._notif_section.result_config()["debounce_minutes"] == 7


def test_strategy_editor_save_persists_notification_config(qapp):
    from services.strategy_store import new_strategy
    from services.strategy_alerts import config_store as alerts_config_store
    from screens.strategy_builder import StrategyEditor

    s = new_strategy("T")
    editor = StrategyEditor(s, [], None)
    editor._notif_section._enabled_toggle.toggled.emit(True)
    editor._notif_section._debounce_spin.setValue(9)

    editor._save()

    saved = alerts_config_store.load_config(s["id"])
    assert saved["enabled"] is True
    assert saved["debounce_minutes"] == 9


# ── Deletion cleanup ─────────────────────────────────────────────────────────

def test_deleting_strategy_purges_notification_config_and_open_signals(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from services import strategy_store as store
    from services.strategy_alerts import config_store as alerts_config_store
    from services.strategy_alerts import state_store as alerts_state_store
    from services.strategy_alerts.models import new_notification_config
    from screens.strategy_builder import StrategyBuilderScreen
    from app import AppController

    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)

    strat = store.new_strategy("ToDelete")
    store.save_strategy(strat)
    alerts_config_store.save_config(strat["id"], new_notification_config())
    alerts_state_store.set_open_signal(
        alerts_state_store.signal_key(strat["id"], "INFY"), {"state": "open"}, force_flush=True
    )

    screen = StrategyBuilderScreen(AppController(qapp))
    screen._strategies = [strat]
    screen._delete_strategy(strat["id"])

    assert alerts_config_store.load_config(strat["id"]) is None
    assert alerts_state_store.get_open_signals() == {}
