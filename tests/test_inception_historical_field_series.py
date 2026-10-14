from datetime import date, timedelta

import pytest

from services import inception_bars_store, inception_formula_builder_columns
from services import inception_historical_field_series as hfs


@pytest.fixture(autouse=True)
def _isolate_bars_db(tmp_path, monkeypatch):
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "test_bars.db"))
    inception_formula_builder_columns.clear_cache()
    yield
    inception_formula_builder_columns.clear_cache()


def _seed_rising_prices(symbol: str, start: date, days: int, start_price: float = 100.0):
    rows = []
    d = start
    price = start_price
    count = 0
    while count < days:
        if d.weekday() < 5:  # trading days only
            rows.append({
                "symbol": symbol, "trade_date": d, "open": price, "high": price + 1,
                "low": price - 1, "close": price, "volume": 1000,
            })
            price += 1
            count += 1
        d += timedelta(days=1)
    inception_bars_store.upsert_bars(rows)
    return rows


def test_historical_field_series_raw_field_matches_bars():
    _seed_rising_prices("DIVISLAB", date(2026, 1, 1), 10)
    series = hfs.historical_field_series("DIVISLAB", "CLOSE", date(2026, 1, 5), date(2026, 1, 12))
    assert all(e["value"] == e["close"] for e in series)
    assert len(series) > 0


def test_historical_field_series_day_top_field_resolves():
    _seed_rising_prices("DIVISLAB", date(2026, 1, 1), 30)
    series = hfs.historical_field_series("DIVISLAB", "DT", date(2026, 1, 20), date(2026, 1, 30))
    assert len(series) > 0
    assert any(e["value"] is not None for e in series)


def test_historical_field_series_empty_for_unsynced_symbol():
    assert hfs.historical_field_series("NOPE", "CLOSE", date(2026, 1, 1), date(2026, 1, 5)) == []


def test_historical_field_series_excludes_dates_before_window():
    _seed_rising_prices("DIVISLAB", date(2026, 1, 1), 10)
    series = hfs.historical_field_series("DIVISLAB", "CLOSE", date(2026, 1, 8), date(2026, 1, 12))
    assert all(e["date"] >= date(2026, 1, 8) for e in series)


def test_available_fields_includes_raw_and_formula_codes():
    fields = hfs.available_fields()
    assert "CLOSE" in fields
    assert "DT" in fields
    assert "MT" in fields


def test_condition_stats_counts_above_below_and_streaks():
    series = [
        {"date": date(2026, 1, 1), "value": 100, "close": 105},  # above
        {"date": date(2026, 1, 2), "value": 100, "close": 110},  # above
        {"date": date(2026, 1, 3), "value": 100, "close": 95},   # below
        {"date": date(2026, 1, 4), "value": 100, "close": 90},   # below
        {"date": date(2026, 1, 5), "value": 100, "close": 85},   # below
    ]
    stats = hfs.condition_stats(series)
    assert stats["periods_above"] == 2
    assert stats["periods_below"] == 3
    assert stats["current_state"] == "below"
    assert stats["current_streak"] == 3
    assert stats["longest_streak"] == 3


def test_condition_stats_level_change_pct():
    series = [
        {"date": date(2026, 1, 1), "value": 100, "close": 100},
        {"date": date(2026, 1, 2), "value": 110, "close": 110},
    ]
    stats = hfs.condition_stats(series)
    assert stats["level_change"] == 10
    assert stats["level_change_pct"] == 10.0


def test_condition_stats_empty_series():
    stats = hfs.condition_stats([])
    assert stats["current_state"] is None
    assert stats["level_change"] is None


# ── EMV picker columns: Group A/B, synced and indicator fields (issue #60) ──

def test_available_fields_include_group_a_b_synced_and_indicator_columns(monkeypatch):
    from services import indicator_library
    monkeypatch.setattr(indicator_library, "field_codes", lambda: ["RSI(14)"])
    fields = hfs.available_fields()
    for expected in ("CLOSE", "DT", "52WH", "52WL", "ATH", "DAY UF GUP 1",     # raw, formula, Group A/B
                     "PATP", "CWTO", "Avg Rate", "Max Pain", "VAH", "OR.High",   # synced Reliable/Nifty/Profile
                     "RSI(14)"):
        assert expected in fields, expected
    assert len(fields) == len(set(fields))


def test_group_a_field_trend_matches_a_rolling_52_week_high():
    # 300 rising trading days: the 52-week high on each date is that day's own high
    _seed_rising_prices("ABB", date(2025, 1, 1), 300)
    series = hfs.historical_field_series("ABB", "52WH", date(2026, 1, 5), date(2026, 2, 27))
    assert len(series) > 10
    highs = {b["trade_date"]: b["high"] for b in inception_bars_store.bars_for_symbol("ABB")}
    for entry in series:
        assert entry["value"] == pytest.approx(highs[entry["date"]])


def test_field_names_resolve_case_insensitively_including_mixed_case_codes():
    _seed_rising_prices("ABB", date(2026, 1, 1), 12)
    lower = hfs.historical_field_series("ABB", "close", date(2026, 1, 5), date(2026, 1, 16))
    upper = hfs.historical_field_series("ABB", "CLOSE", date(2026, 1, 5), date(2026, 1, 16))
    assert [e["value"] for e in lower] == [e["value"] for e in upper]
    assert hfs._canonical_field("max pain") == "Max Pain"
    assert hfs._canonical_field("or.high") == "OR.High"
    assert hfs._canonical_field("not a field") == "not a field"


def test_synced_field_trend_reads_each_bars_own_synced_value():
    rows = _seed_rising_prices("ABB", date(2026, 1, 1), 8)
    inception_bars_store.upsert_bars([dict(r, patp=100.0 + i) for i, r in enumerate(rows)])
    series = hfs.historical_field_series("ABB", "PATP", date(2026, 1, 1), date(2026, 1, 12))
    assert [e["value"] for e in series] == [100.0 + i for i in range(len(series))]
