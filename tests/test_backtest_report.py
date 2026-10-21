"""The shared Back-test report (#82 LMV, #83 EMV)."""
from datetime import date, timedelta

import pytest

from services import backtest_report as br


def _trade(symbol, y, exit_offset, sector="IT", direction="BUY", days_held=3, outcome="TARGET HIT", extra=None):
    entry = date(2026, 8, 3) + timedelta(days=exit_offset - days_held)
    return {"symbol": symbol, "sector": sector, "direction": direction, "entry_date": entry,
            "exit_date": date(2026, 8, 3) + timedelta(days=exit_offset), "entry": 100.0,
            "exit": 100.0 * (1 + y / 100), "yield": y, "outcome": outcome,
            "kind": "positive" if y >= 0 else "negative", "extra": extra or {}}


def _result(trades, symbol=None, amount=5000.0, **kw):
    return {"kind": "LMV", "name": "Put OI Sell", "symbol": symbol, "date_from": date(2026, 8, 1),
            "date_to": date(2026, 9, 30), "investment_amount": amount, "trades": trades, "notes": [],
            "method": "<p>how</p>", **kw}


TRADES = [_trade("A", 4.0, 5), _trade("B", -2.0, 9, sector="BANK", outcome="STOP LOSS"),
          _trade("A", 3.0, 20), _trade("C", -1.0, 40, sector="BANK", outcome="STOP LOSS"),
          _trade("B", 6.0, 41, sector="BANK")]


def test_metrics_are_computed_from_the_trades_in_closing_order():
    m = br.compute_metrics(TRADES, 5000)
    assert m["trades"] == 5 and m["wins"] == 3 and m["losses"] == 2
    assert m["total_yield"] == pytest.approx(10.0) and m["avg_yield"] == pytest.approx(2.0)
    assert m["win_rate"] == pytest.approx(60.0)
    assert m["best"] == 6.0 and m["worst"] == -2.0
    assert m["profit_factor"] == pytest.approx(13.0 / 3.0)
    # the last trade (B, entered day 38) opens before C (exit day 40) has closed -> not taken
    assert m["one_at_a_time_trades"] == 4
    assert m["compounded_pct"] == pytest.approx((1.04 * 0.98 * 1.03 * 0.99 - 1) * 100)
    assert m["curve"] == pytest.approx([4.0, 2.0, 5.0, 4.0, 10.0])
    assert m["max_drawdown"] == pytest.approx(2.0)                 # 1.04 -> 1.0192
    assert m["avg_days"] == pytest.approx(3.0)
    inv = m["investment"]
    assert inv["per_trade"]["deployed"] == 25000 and inv["per_trade"]["profit"] == pytest.approx(500.0)
    assert inv["per_trade"]["return_pct"] == pytest.approx(2.0)
    assert inv["single_pot"]["ending"] == pytest.approx(5000 * 1.04 * 0.98 * 1.03 * 0.99)
    assert inv["single_pot"]["trades"] == 4


def test_minimum_investment_is_5000():
    m = br.compute_metrics(TRADES, 100)
    assert m["investment"]["amount"] == 5000.0
    assert br.compute_metrics(TRADES, 12000)["investment"]["amount"] == 12000.0


def test_empty_and_unknown_yields_do_not_crash():
    m = br.compute_metrics([], 5000)
    assert m["trades"] == 0 and m["total_yield"] is None and m["investment"]["single_pot"]["ending"] is None
    html = br.build_html(_result([]))
    assert "No completed trades" in html and "<!DOCTYPE html>" in html
    assert br.compute_metrics([dict(TRADES[0], **{"yield": None})], 5000)["trades"] == 0


def test_strategy_report_has_sector_distribution_and_leaders_single_stock_does_not():
    whole = br.build_html(_result(TRADES))
    assert "Sector Distribution" in whole and "Best and Worst Stocks" in whole
    assert "All stocks" in whole and "SIMULATED" in whole

    one = br.build_html(_result([t for t in TRADES if t["symbol"] == "A"], symbol="A"))
    assert "Sector Distribution" not in one and "Best and Worst Stocks" not in one
    assert "Put OI Sell — A" in one
    for section in ("Investment Simulation", "Efficiency Ratios", "Cumulative Yield", "Month by Month", "Trade Ledger"):
        assert section in one, section


def test_ledger_lists_every_trade_with_extra_columns_and_paginates():
    many = [_trade(f"S{i}", 1.0 if i % 2 else -1.0, 3 + i % 50, extra={"RSI": 41.5}) for i in range(150)]
    pages = br.build_pages(_result(many, extra_columns=["RSI"]))
    assert len(pages) > 1
    html = "".join(pages)
    assert "S0" in html and "S149" in html and ">RSI<" in html and "41.50" in html


def test_curve_goes_weekly_for_long_ranges():
    ordered = br.compute_metrics([_trade("A", 1.0, i) for i in range(100)], 5000)["ordered"]
    labels, points = br.curve_points(ordered, list(range(1, 101)))
    assert len(points) < 25 and labels[0].startswith("wk")
    labels, points = br.curve_points(ordered[:10], list(range(1, 11)))
    assert len(points) == 10 and not labels[0].startswith("wk")


def test_open_trades_and_notes_are_stated():
    html = br.build_html(_result(TRADES, open_trades=3, notes=["2 entries skipped"]))
    assert "3 trade(s) were still open" in html and "2 entries skipped" in html


def test_one_at_a_time_skips_overlapping_trades_so_the_pot_never_goes_to_zero():
    """Real-data lesson: compounding 806 overlapping trades through one pot read -100%."""
    base = date(2026, 8, 3)

    def t(symbol, start, end, y):
        return {"symbol": symbol, "sector": None, "direction": "BUY", "entry_date": base + timedelta(days=start),
                "exit_date": base + timedelta(days=end), "entry": 100.0, "exit": 100 + y, "yield": y,
                "outcome": "x", "kind": "neutral", "extra": {}}
    trades = [t("A", 0, 10, -5.0), t("B", 1, 3, -5.0), t("C", 2, 4, -5.0),      # B, C overlap A -> skipped
              t("D", 10, 12, 2.0),                                              # enters the day A exits -> taken
              t("E", 11, 20, 50.0)]                                             # overlaps D -> skipped
    taken = br.one_at_a_time(trades)
    assert [x["symbol"] for x in taken] == ["A", "D"]
    m = br.compute_metrics(trades, 5000)
    assert m["one_at_a_time_trades"] == 2
    assert m["compounded_pct"] == pytest.approx((0.95 * 1.02 - 1) * 100)
    assert m["max_drawdown"] == pytest.approx(5.0)                              # the first trade's -5%
    # the per-trade view still counts every trade
    assert m["investment"]["per_trade"]["deployed"] == 5000 * 5
    assert m["total_yield"] == pytest.approx(-5 - 5 - 5 + 2 + 50)
