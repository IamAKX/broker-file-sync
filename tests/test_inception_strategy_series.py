"""Per-date history of an Inception strategy column (issue #61 follow-up): the
RSC strategy uses a row reference ("NIFTY") so it can't be a Formula Builder
field — it's recomputed day by day on a small per-day set of rows."""
from datetime import date, timedelta

import pytest

from services import inception_bars_store, inception_formula_builder_columns, inception_strategy_store
from services import inception_historical_field_series as hfs
from services import inception_strategy_series as iss


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "bars.db"))
    inception_formula_builder_columns.clear_cache()
    from services import inception_compute_service
    inception_compute_service.clear_cache()


def _seed(symbol, start, days, base, step):
    rows, d, price, count = [], start, base, 0
    while count < days:
        if d.weekday() < 5:
            rows.append({"symbol": symbol, "trade_date": d, "open": price, "high": price + 1,
                         "low": price - 1, "close": price, "volume": 1000})
            price += step
            count += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)
    return rows


def _col(value, of=None):
    tok = {"type": "col", "value": value}
    if of:
        tok["of"] = of
    return tok


def _op(v):
    return {"type": "op", "value": v}


def _num(v):
    return {"type": "num", "value": str(v)}


def _paren(v):
    return {"type": "paren", "value": v}


def _rsc_like():
    # (CLOSE / PMC) / (NIFTY CLOSE / NIFTY PMC) * 100 — exactly the real RSC strategy's shape
    formula = [_paren("("), _paren("("), _col("CLOSE"), _op("/"), _col("PMC"), _paren(")"), _op("/"),
               _paren("("), _col("CLOSE", "NIFTY"), _op("/"), _col("PMC", "NIFTY"), _paren(")"), _paren(")"),
               _op("*"), _num(100)]
    return {"id": "rsc", "name": "RSC", "active": True, "category": "Daily", "row_filter": [],
            "columns": [{"name": "RSC", "formula": formula, "fmt_rules": []}]}


def _ratio():
    # CLOSE / (NIFTY CLOSE) * 100, then a second column built on the first
    return {"id": "ratio", "name": "Ratio", "active": True, "category": "Daily", "row_filter": [_col("CLOSE"), _op(">"), _num(10 ** 9)],
            "columns": [{"name": "Rel", "formula": [_col("CLOSE"), _op("/"), _col("CLOSE", "NIFTY"), _op("*"), _num(100)]},
                        {"name": "Rel2", "formula": [_col("Rel"), _op("*"), _num(2)]}]}


def _use(monkeypatch, *strategies):
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: list(strategies))


def test_field_codes_and_resolution(monkeypatch):
    _use(monkeypatch, _rsc_like(), _ratio())
    assert iss.strategy_field_codes() == ["RSC [RSC]", "Rel [Ratio]", "Rel2 [Ratio]"]
    strategy, column = iss.resolve_field("Rel2 [Ratio]")
    assert strategy["id"] == "ratio" and column == "Rel2"
    assert iss.resolve_field("CLOSE") is None and iss.resolve_field("nope [x]") is None
    assert "RSC [RSC]" in hfs.available_fields() and "RSC [RSC]" not in hfs.available_fields(include_strategy_columns=False)


def test_referenced_symbols_found_through_all_columns_and_nested_tokens():
    assert iss.referenced_symbols(_rsc_like()) == ["NIFTY"]
    assert iss.referenced_symbols(_ratio()) == ["NIFTY"]
    nested = {"columns": [{"name": "x", "formula": [{"type": "func", "value": "F(", "args": [_col("CLOSE", "bank")]}]}]}
    assert iss.referenced_symbols(nested) == ["bank"]
    assert iss.referenced_symbols({"columns": [{"name": "y", "formula": [_col("CLOSE")]}]}) == []


def test_column_series_uses_each_days_row_reference_value(monkeypatch):
    _use(monkeypatch, _ratio())
    stock = _seed("ABB_I", date(2026, 1, 5), 30, 200, 2)
    nifty = _seed("NIFTY_I", date(2026, 1, 5), 30, 20000, 50)
    series = hfs.historical_field_series("ABB", "Rel [Ratio]", date(2026, 1, 12), date(2026, 2, 13))
    assert len(series) > 10
    close_of = {b["trade_date"]: b["close"] for b in stock}
    nifty_close = {b["trade_date"]: b["close"] for b in nifty}
    for e in series:
        assert e["value"] == pytest.approx(close_of[e["date"]] / nifty_close[e["date"]] * 100)   # THAT day's NIFTY
        assert e["close"] == close_of[e["date"]]
    # a column built on an earlier column of the same strategy
    second = hfs.historical_field_series("ABB", "Rel2 [Ratio]", date(2026, 1, 12), date(2026, 2, 13))
    assert [e["value"] for e in second] == pytest.approx([e["value"] * 2 for e in series])


def test_the_real_rsc_formula_shape_evaluates_per_day(monkeypatch):
    _use(monkeypatch, _rsc_like())
    _seed("ABB_I", date(2025, 12, 1), 60, 200, 2)
    _seed("NIFTY_I", date(2025, 12, 1), 60, 20000, 50)
    series = hfs.historical_field_series("ABB", "RSC [RSC]", date(2026, 1, 15), date(2026, 2, 20))
    values = [e["value"] for e in series]
    assert values and all(v is not None for v in values)
    assert all(50 < v < 200 for v in values)                  # a relative-strength ratio around 100
    assert len({round(v, 6) for v in values}) > 5             # genuinely changes day to day, not a constant


def test_missing_reference_stock_gives_none_not_zero_and_unknown_stock_gives_nothing(monkeypatch):
    _use(monkeypatch, _ratio())
    _seed("ABB_I", date(2026, 1, 5), 20, 200, 2)              # no NIFTY bars at all
    series = hfs.historical_field_series("ABB", "Rel [Ratio]", date(2026, 1, 12), date(2026, 1, 30))
    assert series and all(e["value"] is None for e in series)
    assert hfs.historical_field_series("NOPE", "Rel [Ratio]", date(2026, 1, 12), date(2026, 1, 30)) == []


def test_reference_stock_missing_a_day_only_blanks_that_day(monkeypatch):
    _use(monkeypatch, _ratio())
    _seed("ABB_I", date(2026, 1, 5), 12, 200, 2)
    nifty = _seed("NIFTY_I", date(2026, 1, 5), 12, 20000, 50)
    skipped = nifty[6]["trade_date"]
    import sqlite3
    con = sqlite3.connect(str(inception_bars_store._DB_FILE))
    con.execute("DELETE FROM eod_bars WHERE symbol='NIFTY_I' AND trade_date=?", (skipped.isoformat(),))
    con.commit(); con.close()
    series = {e["date"]: e["value"] for e in hfs.historical_field_series("ABB", "Rel [Ratio]", date(2026, 1, 5), date(2026, 1, 30))}
    assert series[skipped] is None
    assert sum(v is not None for v in series.values()) == len(series) - 1


def test_stock_report_plots_a_strategy_column_with_its_legend(monkeypatch):
    from services import emv_report_data
    _use(monkeypatch, _ratio())
    _seed("ABB_I", date(2026, 1, 5), 40, 200, 2)
    _seed("NIFTY_I", date(2026, 1, 5), 40, 20000, 50)
    data = emv_report_data.build_stock_report_data("ABB_I", "CLOSE", date(2026, 2, 2), date(2026, 2, 27),
                                                    extra_fields=[{"field": "Rel [Ratio]", "color": "#aa00aa"}])
    html = "".join(emv_report_data.build_stock_report_pages(data))
    # Rel (~0.01) is on a far smaller scale than the price (~230), so it gets the right-hand axis
    assert "CLOSE, Rel [Ratio] vs Close" in html and ">Rel [Ratio] (right axis)<" in html and 'stroke="#aa00aa"' in html
