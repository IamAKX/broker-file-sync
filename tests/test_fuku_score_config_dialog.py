import sys

import pytest
from PySide6.QtWidgets import QApplication

from services import fuku_score


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def test_save_persists_rules_and_bands_bound_to_strategy(qapp):
    from screens.fuku_score_config import FukuScoreConfigDialog

    dlg = FukuScoreConfigDialog("strat-1", "PWHBUY")
    dlg._add_rule()
    dlg._rules[0]["label"] = "Moved up"
    dlg._rules[0]["points"] = 70.0
    dlg._rules[0]["condition"] = [{"type": "num", "value": "1"}]
    dlg._save()

    saved = fuku_score.config_for_strategy("strat-1")
    assert saved["rules"][0]["label"] == "Moved up"
    assert saved["rules"][0]["points"] == 70.0
    assert [b["label"] for b in saved["bands"]] == ["Weak", "Moderate", "Strong"]


def test_save_rejects_inverted_band(qapp, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from screens.fuku_score_config import FukuScoreConfigDialog

    warned = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: warned.append(a[1]))
    dlg = FukuScoreConfigDialog("strat-2", "X")
    dlg._bands_table.cellWidget(0, 1).setValue(90)
    dlg._bands_table.cellWidget(0, 2).setValue(10)
    dlg._save()

    assert warned == ["Invalid Bands"]
    assert fuku_score.config_for_strategy("strat-2") is None


def test_reset_deletes_the_strategys_config(qapp):
    from screens.fuku_score_config import FukuScoreConfigDialog

    fuku_score.save_config(fuku_score.new_config("Old", strategy_id="strat-3"))
    FukuScoreConfigDialog("strat-3", "Y")._reset()

    assert fuku_score.config_for_strategy("strat-3") is None
