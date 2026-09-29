from datetime import date, timedelta

from services import support_resistance as sr


def _bar(d, high, low, close):
    return {"date": d, "high": high, "low": low, "close": close}


def _daily_bars(start: date, days: int, base=100.0, step=1.0):
    bars = []
    d = start
    price = base
    count = 0
    while count < days:
        if d.weekday() < 5:
            bars.append(_bar(d, price + 2, price - 2, price))
            price += step
            count += 1
        d += timedelta(days=1)
    return bars


def test_level_sources_empty_for_no_bars():
    assert sr.level_sources([]) == {}


def test_level_sources_includes_current_and_previous_day():
    bars = _daily_bars(date(2026, 1, 5), 5)  # Mon..Fri
    sources = sr.level_sources(bars)
    assert "Current Day" in sources
    assert "Previous Day" in sources
    assert sources["Current Day"]["high"] == bars[-1]["high"]
    assert sources["Previous Day"]["high"] == bars[-2]["high"]


def test_level_sources_no_previous_day_with_single_bar():
    bars = _daily_bars(date(2026, 1, 5), 1)
    sources = sr.level_sources(bars)
    assert "Previous Day" not in sources
    assert "Camarilla" not in sources   # needs a previous day's H/L/C


def test_level_sources_camarilla_uses_previous_day_hlc():
    bars = _daily_bars(date(2026, 1, 5), 2)
    sources = sr.level_sources(bars)
    prev = bars[-2]
    rng = prev["high"] - prev["low"]
    assert sources["Camarilla"]["R3"] == prev["close"] + rng * 1.1 / 4
    assert sources["Camarilla"]["S3"] == prev["close"] - rng * 1.1 / 4


def test_level_sources_respects_as_of_cutoff():
    bars = _daily_bars(date(2026, 1, 5), 10)
    cutoff = bars[3]["date"]
    sources = sr.level_sources(bars, as_of=cutoff)
    assert sources["Current Day"]["high"] == bars[3]["high"]


def test_level_sources_week_and_month_present_for_enough_history():
    bars = _daily_bars(date(2026, 1, 1), 40)
    sources = sr.level_sources(bars)
    assert "Current Week" in sources
    assert "Previous Week" in sources
    assert "Current Month" in sources
    assert "Previous Month" in sources


def test_nearby_levels_buy_picks_resistance_above_price():
    bars = _daily_bars(date(2026, 1, 5), 3, base=100)
    sources = sr.level_sources(bars)
    levels = sr.nearby_levels(sources, current_price=100, direction="BUY", max_levels=3)
    assert all(l["price"] > 100 for l in levels)
    assert len(levels) <= 3


def test_nearby_levels_sell_picks_support_below_price():
    bars = _daily_bars(date(2026, 1, 5), 3, base=100)
    sources = sr.level_sources(bars)
    levels = sr.nearby_levels(sources, current_price=100, direction="SELL", max_levels=3)
    assert all(l["price"] < 100 for l in levels)


def test_nearby_levels_sorted_by_closeness():
    sources = {
        "A": {"high": 110, "low": None},
        "B": {"high": 105, "low": None},
        "C": {"high": 120, "low": None},
    }
    levels = sr.nearby_levels(sources, current_price=100, direction="BUY", max_levels=3)
    assert [l["price"] for l in levels] == [105, 110, 120]


def test_confluence_zones_groups_close_levels():
    sources = {
        "A": {"high": 100.0, "low": None},
        "B": {"high": 100.4, "low": None},
        "C": {"high": 150.0, "low": None},
    }
    zones = sr.confluence_zones(sources, tolerance_pct=1.0, min_factors=2)
    assert len(zones) == 1
    assert zones[0]["count"] == 2


def test_confluence_zones_empty_when_nothing_clusters():
    sources = {
        "A": {"high": 100.0, "low": None},
        "B": {"high": 200.0, "low": None},
    }
    zones = sr.confluence_zones(sources, tolerance_pct=0.5, min_factors=2)
    assert zones == []
