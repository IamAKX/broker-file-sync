"""Tests for services.live_formula.apply_live_overlay."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.live_formula import apply_live_overlay


def _live(**overrides):
    base = {"open": None, "current": None, "avg_rate": None, "qty": None, "diffpcnt": None}
    base.update(overrides)
    return base


# ── CWO / CMO ────────────────────────────────────────────────────────────────

def test_cwo_cmo_use_live_open_on_first_trading_day():
    baseline = {"is_first_trading_day_of_week": True, "is_first_trading_day_of_month": True}
    out = apply_live_overlay(baseline, _live(open=101.5))
    assert out["CWO"] == 101.5
    assert out["CMO"] == 101.5


def test_cwo_cmo_omitted_on_a_later_day():
    baseline = {"is_first_trading_day_of_week": False, "is_first_trading_day_of_month": False}
    out = apply_live_overlay(baseline, _live(open=101.5))
    assert "CWO" not in out
    assert "CMO" not in out


def test_cwo_cmo_omitted_when_live_open_missing_even_on_first_day():
    baseline = {"is_first_trading_day_of_week": True, "is_first_trading_day_of_month": True}
    out = apply_live_overlay(baseline, _live(open=None))
    assert "CWO" not in out
    assert "CMO" not in out


# ── CWATP / CMATP ────────────────────────────────────────────────────────────

def test_cwatp_cmatp_reduce_to_live_value_alone_on_first_day():
    baseline = {"prev_atp_values_week": [], "prev_atp_values_month": []}
    out = apply_live_overlay(baseline, _live(avg_rate=50.0))
    assert out["CWATP"] == 50.0
    assert out["CMATP"] == 50.0


def test_cwatp_cmatp_equal_per_day_average_with_prior_days():
    baseline = {"prev_atp_values_week": [10, 20], "prev_atp_values_month": [10, 20, 30]}
    out = apply_live_overlay(baseline, _live(avg_rate=30))
    assert out["CWATP"] == 20.0   # (10+20+30)/3
    assert out["CMATP"] == 22.5   # (10+20+30+30)/4


def test_cwatp_cmatp_omitted_when_live_avg_rate_missing():
    baseline = {"prev_atp_values_week": [10, 20], "prev_atp_values_month": [10, 20]}
    out = apply_live_overlay(baseline, _live(avg_rate=None))
    assert "CWATP" not in out
    assert "CMATP" not in out


# ── WEEK % CHANGE / MONTH % CHANGE ──────────────────────────────────────────

def test_pct_change_uses_live_current_against_pwc_pmc():
    baseline = {"pwc": 100.0, "pmc": 200.0}
    out = apply_live_overlay(baseline, _live(current=110.0))
    assert out["WEEK % CHANGE"] == 10.0
    assert out["MONTH % CHANGE"] == -45.0


def test_pct_change_omitted_when_pwc_pmc_missing():
    baseline = {"pwc": None, "pmc": None}
    out = apply_live_overlay(baseline, _live(current=110.0))
    assert "WEEK % CHANGE" not in out
    assert "MONTH % CHANGE" not in out


def test_pct_change_omitted_when_live_current_missing():
    baseline = {"pwc": 100.0, "pmc": 200.0}
    out = apply_live_overlay(baseline, _live(current=None))
    assert "WEEK % CHANGE" not in out
    assert "MONTH % CHANGE" not in out


# ── DAY TO ───────────────────────────────────────────────────────────────────

def test_day_to_is_purely_live():
    out = apply_live_overlay({}, _live(qty=1000, avg_rate=50, diffpcnt=2.0))
    assert out["DAY TO"] == (1000 * 50) / 10_000_000 * (abs(2.0) / 100)


def test_day_to_omitted_when_any_live_input_missing():
    assert "DAY TO" not in apply_live_overlay({}, _live(qty=None, avg_rate=50, diffpcnt=2.0))
    assert "DAY TO" not in apply_live_overlay({}, _live(qty=1000, avg_rate=None, diffpcnt=2.0))
    assert "DAY TO" not in apply_live_overlay({}, _live(qty=1000, avg_rate=50, diffpcnt=None))


# ── CWTO ─────────────────────────────────────────────────────────────────────

def test_cwto_reuses_the_computed_cwatp_and_week_pct_change():
    baseline = {
        "prev_atp_values_week": [10, 20],
        "prev_qty_values_week": [100, 200],
        "pwc": 100.0,
    }
    out = apply_live_overlay(baseline, _live(avg_rate=30, current=120.0, qty=300))
    assert out["CWATP"] == 20.0            # (10+20+30)/3
    assert out["WEEK % CHANGE"] == 20.0    # (120-100)/100*100
    week_qty_sum = 100 + 200 + 300
    expected_cwto = (week_qty_sum * out["CWATP"]) / 10_000_000 * (abs(out["WEEK % CHANGE"]) / 100)
    assert out["CWTO"] == expected_cwto


def test_cwto_omitted_when_qty_missing():
    baseline = {"prev_atp_values_week": [10, 20], "prev_qty_values_week": [100, 200], "pwc": 100.0}
    out = apply_live_overlay(baseline, _live(avg_rate=30, current=120.0, qty=None))
    assert "CWTO" not in out


def test_cwto_omitted_when_week_pct_change_unavailable():
    # pwc missing -> WEEK % CHANGE can't be computed -> CWTO must not be either
    baseline = {"prev_atp_values_week": [10, 20], "prev_qty_values_week": [100, 200], "pwc": None}
    out = apply_live_overlay(baseline, _live(avg_rate=30, current=120.0, qty=300))
    assert "WEEK % CHANGE" not in out
    assert "CWTO" not in out


def test_cwto_omitted_when_cwatp_unavailable():
    # avg_rate missing -> CWATP can't be computed -> CWTO must not be either
    baseline = {"prev_atp_values_week": [10, 20], "prev_qty_values_week": [100, 200], "pwc": 100.0}
    out = apply_live_overlay(baseline, _live(avg_rate=None, current=120.0, qty=300))
    assert "CWATP" not in out
    assert "CWTO" not in out


# ── empty baseline (new symbol, no stored history at all) ──────────────────

def test_empty_baseline_still_yields_purely_live_codes_but_omits_the_rest():
    out = apply_live_overlay({}, _live(open=100, current=110, avg_rate=50, qty=1000, diffpcnt=2.0))
    assert out["CWATP"] == 50.0   # no prior days -> live value alone
    assert out["CMATP"] == 50.0
    assert out["DAY TO"] == (1000 * 50) / 10_000_000 * (abs(2.0) / 100)
    assert "CWO" not in out       # baseline.get("is_first_trading_day_of_week") is falsy
    assert "CMO" not in out
    assert "WEEK % CHANGE" not in out   # no pwc
    assert "MONTH % CHANGE" not in out  # no pmc
    assert "CWTO" not in out            # depends on WEEK % CHANGE
