import pytest

from services import indicator_library as il


@pytest.fixture(autouse=True)
def _fresh_cache():
    il.reload_cache()
    yield
    il.reload_cache()


def _bars(closes, spread=1.0, volume=100):
    return [{"open": c, "high": c + spread, "low": c - spread, "close": c, "volume": volume} for c in closes]


def test_sma_matches_hand_computation_with_warmup_none():
    out = il.compute("SMA", _bars([1, 2, 3, 4, 5]), {"period": 3})["SMA"]
    assert out == [None, None, 2.0, 3.0, 4.0]


def test_ema_is_seeded_with_sma_then_recursive():
    out = il.compute("EMA", _bars([1, 2, 3, 4, 5]), {"period": 3})["EMA"]
    # seed = 2.0 at i=2; k = 0.5 -> 4*.5+2*.5 = 3.0, then 5*.5+3*.5 = 4.0
    assert out == [None, None, 2.0, 3.0, 4.0]


def test_wma_weights_recent_bars_more():
    out = il.compute("WMA", _bars([1, 2, 3]), {"period": 3})["WMA"]
    assert out[2] == pytest.approx((1 * 1 + 2 * 2 + 3 * 3) / 6)


def test_rsi_is_100_on_a_strictly_rising_series_and_0_on_falling():
    up = il.compute("RSI", _bars(list(range(1, 30))), {"period": 14})["RSI"]
    down = il.compute("RSI", _bars(list(range(30, 1, -1))), {"period": 14})["RSI"]
    assert up[13] is None and up[14] == 100.0
    assert down[14] == pytest.approx(0.0)


def test_rsi_wilder_textbook_value():
    # Classic Wilder/StockCharts sample (14-period), first RSI value ~70.53
    closes = [44.34, 44.09, 44.15, 43.61, 44.33, 44.83, 45.10, 45.42, 45.84, 46.08,
              45.89, 46.03, 45.61, 46.28, 46.28]
    out = il.compute("RSI", _bars(closes), {"period": 14})["RSI"]
    assert out[14] == pytest.approx(70.53, abs=0.1)


def test_macd_histogram_is_line_minus_signal():
    closes = [10 + (i % 7) + i * 0.3 for i in range(80)]
    res = il.compute("MACD", _bars(closes))
    i = 79
    assert res["Histogram"][i] == pytest.approx(res["MACD"][i] - res["Signal"][i])
    assert res["MACD"][24] is None and res["MACD"][25] is not None


def test_bollinger_collapses_to_the_mean_on_a_flat_series():
    res = il.compute("BBANDS", _bars([50.0] * 25))
    assert res["Upper"][-1] == res["Middle"][-1] == res["Lower"][-1] == 50.0


def test_bollinger_band_width_uses_population_stddev():
    res = il.compute("BBANDS", _bars([1, 2, 3, 4, 5]), {"period": 5, "stddev": 2.0})
    assert res["Middle"][4] == 3.0
    assert res["Upper"][4] == pytest.approx(3.0 + 2 * (2.0 ** 0.5))


def test_atr_on_constant_range_equals_that_range():
    out = il.compute("ATR", _bars([100.0] * 20, spread=1.5), {"period": 14})["ATR"]
    assert out[-1] == pytest.approx(3.0)


def test_obv_accumulates_signed_volume():
    out = il.compute("OBV", _bars([1, 2, 1, 1], volume=10))["OBV"]
    assert out == [0.0, 10.0, 0.0, 0.0]


def test_stochastic_at_the_top_of_range_is_100():
    bars = [{"open": 1, "high": h, "low": h - 1, "close": h, "volume": 1} for h in range(1, 20)]
    res = il.compute("STOCH", bars, {"period": 14, "smooth": 3})
    assert res["%K"][-1] == 100.0   # close == highest high of the window
    assert res["%D"][-1] is not None


def test_donchian_and_roc():
    bars = _bars([1, 2, 3, 4], spread=0.5)
    assert il.compute("DONCHIAN", bars, {"period": 2})["Upper"][3] == 4.5
    assert il.compute("ROC", bars, {"period": 1})["ROC"][1] == pytest.approx(100.0)


def test_params_are_clamped_and_invalid_choices_defaulted():
    assert il.instance_label("SMA", {"period": 99999}) == "SMA(500)"
    assert il.instance_label("SMA", {"period": "abc", "source": "bogus"}) == "SMA(20)"
    assert il.instance_label("SMA", {"period": 10, "source": "high"}) == "SMA(10,high)"


def test_output_codes_name_secondary_outputs():
    inst = il.new_instance("MACD")
    assert il.output_codes(inst) == [
        ("MACD(12,26,9)", "MACD"), ("MACD(12,26,9).Signal", "Signal"), ("MACD(12,26,9).Histogram", "Histogram"),
    ]


def test_latest_values_never_raises_on_bad_instances():
    good = il.new_instance("SMA", {"period": 3})
    unknown = {"id": "x", "key": "NOPE", "params": {}}
    out = il.latest_values(_bars([1, 2, 3, 4]), [good, unknown])
    assert out == {"SMA(3)": 3.0}
    assert il.latest_values(_bars([1, 2]), [good]) == {"SMA(3)": None}


def test_instances_persist_and_dedupe_by_label():
    a = il.new_instance("RSI", {"period": 14})
    il.save_instance(a)
    il.save_instance(il.new_instance("RSI", {"period": 14}))   # same label -> ignored
    il.save_instance(il.new_instance("RSI", {"period": 7}))
    il.reload_cache()
    labels = [il.instance_label(i["key"], i["params"]) for i in il.load_instances()]
    assert labels == ["RSI(14)", "RSI(7)"]

    il.delete_instance(a["id"])
    assert [il.instance_label(i["key"], i["params"]) for i in il.load_instances()] == ["RSI(7)"]


def test_peek_instances_never_loads_from_the_network(monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "load_json", lambda *a, **k: pytest.fail("network call"))
    assert il.peek_instances() == []


def test_every_definition_computes_on_a_realistic_series():
    closes = [100 + (i * 7 % 13) - (i % 5) for i in range(120)]
    for defn in il.list_definitions():
        res = il.compute(defn["key"], _bars(closes))
        assert set(res) == set(defn["outputs"]), defn["key"]
        assert all(len(s) == 120 for s in res.values()), defn["key"]


def test_compute_for_bars_exposes_configured_indicators_as_fields():
    from datetime import date, timedelta
    from services import inception_formula_builder_columns as fbc

    bars = [{"trade_date": date(2026, 1, 1) + timedelta(days=i), "open": 1.0 + i, "high": 2.0 + i,
             "low": 0.5 + i, "close": 1.0 + i, "volume": 10} for i in range(10)]
    fbc.clear_cache()
    assert "SMA(3)" not in fbc.compute_for_bars("X", bars)

    il.save_instance(il.new_instance("SMA", {"period": 3}))   # also clears the memoized rows
    values = fbc.compute_for_bars("X", bars)

    assert values["SMA(3)"] == pytest.approx((8.0 + 9.0 + 10.0) / 3)
    il.reload_cache()
    fbc.clear_cache()


def test_indicator_sections_split_overlay_and_sub_panels():
    from datetime import date, timedelta
    from services import indicator_charts

    bars = [{"trade_date": date(2026, 1, 1) + timedelta(days=i), "open": 1.0, "high": 2.0 + i % 3,
             "low": 0.5, "close": 1.0 + i % 4, "volume": 10} for i in range(30)]
    dates = [b["trade_date"] for b in bars[-10:]]
    instances = [il.new_instance("SMA", {"period": 5}), il.new_instance("RSI", {"period": 5})]

    sections = indicator_charts.build_indicator_sections(bars, dates, instances)

    assert [t for t, _ in sections] == ["Price with SMA(5)", "RSI(5) — Relative Strength Index"]
    assert all(svg.startswith("<svg") for _, svg in sections)
    assert indicator_charts.build_indicator_sections(bars, dates, []) == []
