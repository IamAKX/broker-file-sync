"""Tests for services.formula_tokens — the token vocabulary and built-in defs."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services import formula_tokens as ft


def test_56_builtin_formulas():
    assert len(ft.BUILTIN_FORMULAS) == 56
    assert len(ft.BUILTIN_CODES) == 56


def test_every_formula_has_required_keys():
    for code, defn in ft.BUILTIN_FORMULAS.items():
        assert set(defn.keys()) == {"name", "tokens", "description", "frequency"}
        assert defn["frequency"] in ("DAILY", "WEEKLY", "MONTHLY")
        assert isinstance(defn["tokens"], list)
        assert len(defn["tokens"]) > 0


def test_every_token_is_well_formed():
    valid_kinds = {"field", "num", "op", "paren", "func"}
    for code, defn in ft.BUILTIN_FORMULAS.items():
        for tok in defn["tokens"]:
            assert tok.get("type") in valid_kinds, f"{code}: bad token {tok}"


def test_window_and_timepoint_values_are_from_the_vocabulary():
    for code, defn in ft.BUILTIN_FORMULAS.items():
        for tok in defn["tokens"]:
            if tok.get("type") != "func":
                continue
            if "window" in tok:
                assert tok["window"] in ft.WINDOWS, f"{code}: unknown window {tok['window']}"
            if "timepoint" in tok:
                assert tok["timepoint"] in ft.TIMEPOINTS, f"{code}: unknown timepoint {tok['timepoint']}"


def test_tokens_to_display_window_aggregate():
    tokens = [{"type": "func", "value": "MAX_OF(", "field": "HIGH", "window": "CURRENT_MONTH"}]
    assert ft.tokens_to_display(tokens) == "MAX_OF([HIGH], CURRENT_MONTH)"


def test_tokens_to_display_point_lookup():
    tokens = [{"type": "func", "value": "AT(", "field": "CLOSE", "timepoint": "PREVIOUS_TRADING_DAY"}]
    assert ft.tokens_to_display(tokens) == "AT([CLOSE], PREVIOUS_TRADING_DAY)"


def test_tokens_to_display_arithmetic():
    tokens = [
        {"type": "field", "value": "PCLOSE"}, {"type": "op", "value": "+"},
        {"type": "paren", "value": "("}, {"type": "field", "value": "PDH"},
        {"type": "op", "value": "-"}, {"type": "field", "value": "PDL"},
        {"type": "paren", "value": ")"}, {"type": "op", "value": "*"},
        {"type": "num", "value": "1.1"}, {"type": "op", "value": "/"}, {"type": "num", "value": "4"},
    ]
    assert ft.tokens_to_display(tokens) == "[PCLOSE] + ([PDH] - [PDL]) * 1.1 / 4"


def test_tokens_to_display_empty_is_dash():
    assert ft.tokens_to_display([]) == "—"


def test_camarilla_formulas_reference_only_raw_fields():
    # DR3..DS6 must only reference PCLOSE/PDH/PDL/DR6 — no window aggregates.
    for code in ("DR3", "DR4", "DS3", "DS4"):
        for tok in ft.BUILTIN_FORMULAS[code]["tokens"]:
            if tok["type"] == "field":
                assert tok["value"] in ("PCLOSE", "PDH", "PDL")


def test_ds6_references_dr6():
    values = [t["value"] for t in ft.BUILTIN_FORMULAS["DS6"]["tokens"] if t["type"] == "field"]
    assert "DR6" in values


def test_pwto_is_at_cwto_last_trading_day_of_previous_week():
    tokens = ft.BUILTIN_FORMULAS["PWTO"]["tokens"]
    assert len(tokens) == 1
    tok = tokens[0]
    assert tok["value"] == "AT("
    assert tok["field"] == "CWTO"
    assert tok["timepoint"] == "LAST_TRADING_DAY_OF_PREVIOUS_WEEK"
