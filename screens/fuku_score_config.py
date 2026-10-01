"""
Fuku Score configuration dialog — the per-strategy scoring-rule UI the
Reports specs require ("score components, weights, maximum score and score
bands should be configurable"). Edits one services.fuku_score config bound
to a strategy id: a max score, a list of weighted rules (each condition
authored in the shared ExpressionEditorDialog, same token format as Strategy
Builder's row filter), and the Weak/Moderate/Strong-style score bands.

Until a strategy has a saved config, every score falls back to
services.fuku_score.default_config() (one always-true rule, 100/100).
"""

import font_scale
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QLabel,
    QLineEdit, QMessageBox, QPushButton, QTableWidget, QTableWidgetItem,
    QVBoxLayout,
)

from services import fuku_score
from services.strategy_alerts import config_store as alerts_config_store

_BASE_FIELDS = ["Entry Price", "High", "Low", "Exit Price", "Score"]
_RULE_COLS = ["On", "Rule", "Condition", "Points", "Weight", ""]
_BAND_COLS = ["Label", "From", "To", "Colour"]


def _tokens_text(tokens: list) -> str:
    from screens.strategy_builder import _tokens_to_display
    return _tokens_to_display(tokens) if tokens else "(not set)"


def available_fields(strategy_id: str) -> list:
    """The row fields a score rule's condition can reference: the signal's
    price fields plus every target/stop-loss metric configured for the
    strategy (see services.fuku_score.signal_row_data)."""
    cfg = alerts_config_store.load_config(strategy_id) or {}
    names = [m.get("name") for m in cfg.get("metrics", []) if m.get("name")]
    return _BASE_FIELDS + [n for n in names if n not in _BASE_FIELDS]


class FukuScoreConfigDialog(QDialog):
    def __init__(self, strategy_id: str, strategy_name: str, theme=None, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._strategy_id = strategy_id
        self._config = fuku_score.config_for_strategy(strategy_id) or fuku_score.new_config(
            f"{strategy_name} Score", strategy_id=strategy_id
        )
        self._config.setdefault("strategy_id", strategy_id)
        self._fields = available_fields(strategy_id)
        self.setWindowTitle(f"Fuku Score — {strategy_name}")
        self.setMinimumSize(720, 560)
        self._build()
        self._load_into_widgets()

    # ── Build ────────────────────────────────────────────────────────────

    def _build(self):
        layout = QVBoxLayout(self)

        top = QHBoxLayout()
        top.addWidget(QLabel("Max score"))
        self._max_spin = QDoubleSpinBox()
        self._max_spin.setRange(1, 10000)
        self._max_spin.setDecimals(0)
        top.addWidget(self._max_spin)
        top.addStretch()
        layout.addLayout(top)

        title = QLabel("Rules")
        title.setFont(font_scale.font(font_scale.SMALL, True))
        layout.addWidget(title)
        self._rules_table = QTableWidget(0, len(_RULE_COLS))
        self._rules_table.setHorizontalHeaderLabels(_RULE_COLS)
        hh = self._rules_table.horizontalHeader()
        hh.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self._rules_table.verticalHeader().setVisible(False)
        layout.addWidget(self._rules_table, 2)

        rule_btns = QHBoxLayout()
        add_rule = QPushButton("Add Rule")
        add_rule.clicked.connect(self._add_rule)
        rule_btns.addWidget(add_rule)
        rule_btns.addStretch()
        layout.addLayout(rule_btns)

        btitle = QLabel("Score bands")
        btitle.setFont(font_scale.font(font_scale.SMALL, True))
        layout.addWidget(btitle)
        self._bands_table = QTableWidget(0, len(_BAND_COLS))
        self._bands_table.setHorizontalHeaderLabels(_BAND_COLS)
        self._bands_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._bands_table.verticalHeader().setVisible(False)
        layout.addWidget(self._bands_table, 1)

        band_btns = QHBoxLayout()
        add_band = QPushButton("Add Band")
        add_band.clicked.connect(lambda: self._append_band_row(fuku_score.new_band("New", 0, 0)))
        rm_band = QPushButton("Remove Band")
        rm_band.clicked.connect(self._remove_band)
        band_btns.addWidget(add_band)
        band_btns.addWidget(rm_band)
        band_btns.addStretch()
        layout.addLayout(band_btns)

        btns = QHBoxLayout()
        reset = QPushButton("Reset to Default")
        reset.setToolTip("Delete this strategy's custom score config — scores revert to 100/100.")
        reset.clicked.connect(self._reset)
        btns.addWidget(reset)
        btns.addStretch()
        cancel = QPushButton("Cancel")
        cancel.clicked.connect(self.reject)
        save = QPushButton("Save")
        save.clicked.connect(self._save)
        btns.addWidget(cancel)
        btns.addWidget(save)
        layout.addLayout(btns)

    # ── Rules ────────────────────────────────────────────────────────────

    def _load_into_widgets(self):
        self._max_spin.setValue(float(self._config.get("max_score", 100)))
        self._rules = [dict(r) for r in self._config.get("rules", [])]
        self._render_rules()
        self._bands_table.setRowCount(0)
        for band in self._config.get("bands", []):
            self._append_band_row(band)

    def _spin(self, value: float, lo: float, hi: float) -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(2)
        sp.setValue(float(value))
        return sp

    def _render_rules(self):
        self._rules_table.setRowCount(len(self._rules))
        for r, rule in enumerate(self._rules):
            on = QCheckBox()
            on.setChecked(rule.get("enabled", True))
            on.toggled.connect(lambda v, i=r: self._rules[i].__setitem__("enabled", v))
            self._rules_table.setCellWidget(r, 0, on)

            name = QLineEdit(rule.get("label", ""))
            name.textChanged.connect(lambda v, i=r: self._rules[i].__setitem__("label", v))
            self._rules_table.setCellWidget(r, 1, name)

            cond_btn = QPushButton(_tokens_text(rule.get("condition", [])))
            cond_btn.setStyleSheet("text-align: left;")
            cond_btn.clicked.connect(lambda _=False, i=r: self._edit_condition(i))
            self._rules_table.setCellWidget(r, 2, cond_btn)

            pts = self._spin(rule.get("points", 0), -10000, 10000)
            pts.valueChanged.connect(lambda v, i=r: self._rules[i].__setitem__("points", v))
            self._rules_table.setCellWidget(r, 3, pts)

            wt = self._spin(rule.get("weight", 1), -100, 100)
            wt.valueChanged.connect(lambda v, i=r: self._rules[i].__setitem__("weight", v))
            self._rules_table.setCellWidget(r, 4, wt)

            rm = QPushButton("Remove")
            rm.clicked.connect(lambda _=False, i=r: self._remove_rule(i))
            self._rules_table.setCellWidget(r, 5, rm)

    def _add_rule(self):
        self._rules.append(fuku_score.new_rule(f"Rule {len(self._rules) + 1}"))
        self._render_rules()

    def _remove_rule(self, index: int):
        del self._rules[index]
        self._render_rules()

    def _edit_condition(self, index: int):
        from screens.formula_editor import ExpressionEditorDialog
        row = {f: 1.0 for f in self._fields}
        dlg = ExpressionEditorDialog(
            tokens=list(self._rules[index].get("condition", [])),
            lmv_headers=self._fields, strategy_col_headers=[],
            lmv_first_row=row, all_lmv_data=[row], theme=self._theme,
            mode="condition", allow_self=False, real_lmv_headers=list(self._fields),
            parent=self,
        )
        if dlg.exec() == QDialog.DialogCode.Accepted:
            self._rules[index]["condition"] = dlg.get_tokens()
            self._render_rules()

    # ── Bands ────────────────────────────────────────────────────────────

    def _append_band_row(self, band: dict):
        r = self._bands_table.rowCount()
        self._bands_table.insertRow(r)
        self._bands_table.setItem(r, 0, QTableWidgetItem(str(band.get("label", ""))))
        self._bands_table.setCellWidget(r, 1, self._spin(band.get("min", 0), -10000, 10000))
        self._bands_table.setCellWidget(r, 2, self._spin(band.get("max", 0), -10000, 10000))
        self._bands_table.setItem(r, 3, QTableWidgetItem(str(band.get("color", "#39d353"))))

    def _remove_band(self):
        r = self._bands_table.currentRow()
        if r >= 0:
            self._bands_table.removeRow(r)

    def _collect_bands(self) -> list:
        bands = []
        for r in range(self._bands_table.rowCount()):
            bands.append(fuku_score.new_band(
                self._bands_table.item(r, 0).text().strip() or "Band",
                self._bands_table.cellWidget(r, 1).value(),
                self._bands_table.cellWidget(r, 2).value(),
                self._bands_table.item(r, 3).text().strip() or "#39d353",
            ))
        return bands

    # ── Actions ──────────────────────────────────────────────────────────

    def _save(self):
        bands = self._collect_bands()
        if any(b["min"] > b["max"] for b in bands):
            QMessageBox.warning(self, "Invalid Bands", "Each band's From must not exceed its To.")
            return
        self._config["max_score"] = self._max_spin.value()
        self._config["rules"] = self._rules
        self._config["bands"] = bands
        fuku_score.save_config(self._config)
        self.accept()

    def _reset(self):
        existing = fuku_score.config_for_strategy(self._strategy_id)
        if existing:
            fuku_score.delete_config(existing["id"])
        self.accept()
