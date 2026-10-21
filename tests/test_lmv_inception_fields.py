"""Tests for services.lmv_inception_fields — the bridge that surfaces HMV's
historical Group A/B columns as LMV formula fields."""

from datetime import date

import pytest

from services import inception_columns, lmv_inception_fields as lif

# conftest's autouse fixture stubs ensure_loaded_async to a no-op for every
# test (LiveViewerWindow construction would otherwise trigger a real walk);
# this module tests it for real, so keep a handle to the genuine function.
_REAL_ENSURE_LOADED_ASYNC = lif.ensure_loaded_async


@pytest.fixture(autouse=True)
def _reset_module_state(tmp_path, monkeypatch):
    monkeypatch.setattr(lif, "_CACHE_FILE", str(tmp_path / "inception_lmv_snapshot.json"))
    monkeypatch.setattr(lif, "ensure_loaded_async", _REAL_ENSURE_LOADED_ASYNC)
    monkeypatch.setattr(lif, "_INDICATOR_CACHE_FILE", str(tmp_path / "inception_lmv_indicators.json"))
    monkeypatch.setattr(lif, "_snapshot", {})
    monkeypatch.setattr(lif, "_base_snapshot", {})
    monkeypatch.setattr(lif, "_indicator_snapshot", {})
    monkeypatch.setattr(lif, "_on_ready_cb", None)
    monkeypatch.setattr(lif, "_loading", False)
    monkeypatch.setattr(lif, "_loaded", False)
    yield


# ── Field catalogue ────────────────────────────────────────────────────────

def test_field_codes_are_all_real_inception_codes():
    catalogue = set(inception_columns.all_derived_codes()) | set(inception_columns.gap_sub_fields())
    assert lif.FIELD_CODES
    assert all(code in catalogue for code in lif.FIELD_CODES)


def test_field_codes_exclude_raw_previous_day_fields():
    # The request's list deliberately drops P.OPEN/P.HIGH/... raw fields.
    assert not any(code.startswith("P.") for code in lif.FIELD_CODES)


def test_field_codes_include_group_b_gap_codes():
    for code in ("DAY UF GUP 1", "WEEK FD GDN 3"):
        assert code in lif.FIELD_CODES


def test_field_catalogue_shape_matches_editor_contract():
    entries = lif.field_catalogue()
    assert len(entries) == len(lif.FIELD_CODES)
    for e in entries:
        assert set(e) == {"name", "signature", "description", "token"}
        assert e["token"] == {"type": "col", "value": e["token"]["value"]}
        assert e["name"] == f"[{e['token']['value']}]"
        assert e["description"]


# ── Symbol normalization ───────────────────────────────────────────────────

@pytest.mark.parametrize("lmv_name, inception_symbol", [
    ("RELIANCE", "RELIANCE_I"),
    ("BAJAJ-AUTO", "BAJAJ_AUTO_I"),
    ("M&M", "M_M_I"),
    ("NAM-INDIA", "NAM_INDIA_I"),
    ("NIFTY", "NIFTY_I"),
    ("BAJAJ-AUTO", "BAJAJ_AUTO_II"),
])
def test_symbol_normalization_matches_across_spellings(lmv_name, inception_symbol):
    assert lif.normalize_lmv_symbol(lmv_name) == lif._normalize_inception_symbol(inception_symbol)


def test_strategy_engine_norm_helper_agrees():
    from services.strategy_engine import _norm_for_inception
    assert _norm_for_inception("BAJAJ-AUTO") == lif.normalize_lmv_symbol("BAJAJ-AUTO")
    assert _norm_for_inception(None) == ""


# ── Fingerprint ────────────────────────────────────────────────────────────

def _stub_sources(monkeypatch, *, rows=100, last=date(2026, 8, 31), settings=None):
    settings = settings or {"gap_threshold_pct": 3.0, "week_window_days": 260, "fifo_cap": 5}
    from services import inception_bars_store, inception_settings
    monkeypatch.setattr(inception_bars_store, "row_count", lambda: rows)
    monkeypatch.setattr(inception_bars_store, "last_synced_date", lambda: last)
    monkeypatch.setattr(inception_settings, "load", lambda: dict(settings))


def test_fingerprint_changes_with_bar_count(monkeypatch):
    _stub_sources(monkeypatch, rows=100)
    fp1 = lif._fingerprint()
    _stub_sources(monkeypatch, rows=101)
    assert lif._fingerprint() != fp1


def test_fingerprint_changes_with_settings(monkeypatch):
    _stub_sources(monkeypatch, settings={"gap_threshold_pct": 3.0, "week_window_days": 260, "fifo_cap": 5})
    fp1 = lif._fingerprint()
    _stub_sources(monkeypatch, settings={"gap_threshold_pct": 4.0, "week_window_days": 260, "fifo_cap": 5})
    assert lif._fingerprint() != fp1


# ── Snapshot build + disk cache ────────────────────────────────────────────

def _stub_snapshot(monkeypatch, rows):
    from services import inception_bars_store, inception_compute_service
    monkeypatch.setattr(inception_bars_store, "latest_synced_date_on_or_before",
                        lambda _as_of: date(2026, 8, 31))
    monkeypatch.setattr(inception_compute_service, "snapshot", lambda _as_of: rows)


def test_build_snapshot_rekeys_and_projects(monkeypatch):
    _stub_snapshot(monkeypatch, [
        {"symbol": "BAJAJ_AUTO_I", "values": {
            "52WH": 123.0, "ATH": 200.0, "NOT_A_FIELD": 9, "DAY UF GUP 1": 5.0,
        }},
        {"symbol": "RELIANCE_I", "values": {"52WH": 3000.0}},
    ])
    as_of, snap = lif._build_snapshot()
    assert as_of == "2026-08-31"
    assert set(snap) == {"BAJAJAUTO", "RELIANCE"}
    # projected to exactly FIELD_CODES, no extras
    assert set(snap["BAJAJAUTO"]) == set(lif.FIELD_CODES)
    assert "NOT_A_FIELD" not in snap["BAJAJAUTO"]
    assert snap["BAJAJAUTO"]["52WH"] == 123.0
    assert snap["RELIANCE"]["52WH"] == 3000.0
    assert snap["RELIANCE"]["ATH"] is None  # absent in source -> None


def test_do_load_writes_and_reuses_disk_cache(monkeypatch):
    _stub_sources(monkeypatch, rows=42)
    _stub_snapshot(monkeypatch, [{"symbol": "TCS_I", "values": {"52WH": 10.0}}])

    calls = []
    orig = lif._build_snapshot
    monkeypatch.setattr(lif, "_build_snapshot", lambda: (calls.append(1), orig())[1])

    lif._do_load(on_ready=None)
    assert lif.current_snapshot()["TCS"]["52WH"] == 10.0
    assert len(calls) == 1

    # Second load, same fingerprint -> served from disk, no recompute.
    monkeypatch.setattr(lif, "_snapshot", {})
    monkeypatch.setattr(lif, "_loaded", False)
    lif._do_load(on_ready=None)
    assert lif.current_snapshot()["TCS"]["52WH"] == 10.0
    assert len(calls) == 1  # unchanged


def test_clear_cache_removes_file_and_memory(monkeypatch):
    _stub_sources(monkeypatch)
    _stub_snapshot(monkeypatch, [{"symbol": "TCS_I", "values": {"52WH": 10.0}}])
    lif._do_load(on_ready=None)
    import os
    assert os.path.exists(lif._CACHE_FILE)
    lif.clear_cache()
    assert not os.path.exists(lif._CACHE_FILE)
    assert lif.current_snapshot() == {}


def test_ensure_loaded_async_completes(monkeypatch):
    _stub_sources(monkeypatch)
    _stub_snapshot(monkeypatch, [{"symbol": "INFY_I", "values": {"ATH": 77.0}}])
    done = []
    lif.ensure_loaded_async(on_ready=lambda: done.append(1))
    for t in __import__("threading").enumerate():
        if t.name == "lmv-inception-fields":
            t.join(timeout=10)
    assert lif.current_snapshot().get("INFY", {}).get("ATH") == 77.0
    assert done


# ── Indicator Library fields ────────────────────────────────────────────────

def _bars(n=60):
    from datetime import timedelta
    start = date(2026, 6, 1)
    return [
        {"trade_date": start + timedelta(days=i), "open": 100 + i, "high": 101 + i,
         "low": 99 + i, "close": 100 + i, "volume": 1000, "open_interest": 0}
        for i in range(n)
    ]


def _stub_indicator_sources(monkeypatch, instances):
    from services import indicator_library, inception_bars_store
    _stub_sources(monkeypatch)
    monkeypatch.setattr(indicator_library, "load_instances", lambda: list(instances))
    monkeypatch.setattr(indicator_library, "field_codes", lambda: ["SMA(5)"])
    monkeypatch.setattr(inception_bars_store, "latest_synced_date_on_or_before", lambda d: date(2026, 7, 29))
    monkeypatch.setattr(inception_bars_store, "available_symbols", lambda: ["ABB_I", "M_M_I"])
    monkeypatch.setattr(inception_bars_store, "bars_for_symbol", lambda sym, a=None, b=None: _bars())


def test_indicator_values_merge_into_snapshot_by_normalized_symbol(monkeypatch):
    from services import indicator_library
    inst = indicator_library.new_instance("SMA", {"period": 5})
    _stub_indicator_sources(monkeypatch, [inst])
    monkeypatch.setattr(lif, "_base_snapshot", {"ABB": {"52WH": 1.0}, "MM": {"52WH": 2.0}})

    lif._load_indicators(force=True)

    snap = lif.current_snapshot()
    assert snap["ABB"]["52WH"] == 1.0                       # base fields untouched
    assert snap["ABB"]["SMA(5)"] == snap["MM"]["SMA(5)"]    # same synthetic bars
    assert snap["ABB"]["SMA(5)"] is not None


def test_indicator_cache_reused_until_indicator_set_changes(monkeypatch):
    from services import indicator_library
    inst = indicator_library.new_instance("SMA", {"period": 5})
    _stub_indicator_sources(monkeypatch, [inst])
    lif._load_indicators(force=True)

    calls = []
    monkeypatch.setattr(lif, "_build_indicator_snapshot", lambda i: calls.append(1) or {})
    lif._load_indicators()                      # same set -> disk cache hit
    assert calls == []
    other = indicator_library.new_instance("SMA", {"period": 9})
    monkeypatch.setattr(indicator_library, "load_instances", lambda: [inst, other])
    lif._load_indicators()                      # set changed -> recompute
    assert calls == [1]


def test_no_indicators_leaves_snapshot_unchanged(monkeypatch):
    from services import indicator_library
    _stub_indicator_sources(monkeypatch, [])
    monkeypatch.setattr(lif, "_base_snapshot", {"ABB": {"52WH": 1.0}})
    lif._load_indicators()
    assert lif.current_snapshot() == {"ABB": {"52WH": 1.0}}


def test_all_field_codes_and_catalogue_include_indicators(monkeypatch):
    from services import indicator_library
    monkeypatch.setattr(indicator_library, "field_codes", lambda: ["RSI(14)", "52WH"])
    codes = lif.all_field_codes()
    assert codes[:len(lif.FIELD_CODES)] == lif.FIELD_CODES
    assert codes.count("52WH") == 1 and "RSI(14)" in codes
    assert "RSI(14)" in [e["token"]["value"] for e in lif.field_catalogue()]


def test_every_gap_area_offers_bare_code_plus_low_high_date_fields():
    """#88: Gap number (bare code = HIGH alias) + LOW / HIGH / DATE sub-fields."""
    for code in inception_columns.GROUP_B:
        assert code in lif.FIELD_CODES
        for suffix in ("LOW", "HIGH", "DATE"):
            assert f"{code} {suffix}" in lif.FIELD_CODES
    assert len(lif.FIELD_CODES) == len(set(lif.FIELD_CODES))           # no duplicates
    names = {e["name"] for e in lif.field_catalogue()}
    assert "[WEEK FD GDN 3 LOW]" in names and "[DAY UF GUP 1 DATE]" in names
    desc = next(e for e in lif.field_catalogue() if e["name"] == "[DAY UF GUP 2 LOW]")["description"]
    assert "lower bound" in desc


def test_field_cache_fingerprint_changes_with_the_field_schema(monkeypatch):
    before = lif._fingerprint()
    monkeypatch.setattr(lif, "_FIELDS_SCHEMA", "something-else")
    assert lif._fingerprint() != before
