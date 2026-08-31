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
    monkeypatch.setattr(lif, "_snapshot", {})
    monkeypatch.setattr(lif, "_loading", False)
    monkeypatch.setattr(lif, "_loaded", False)
    yield


# ── Field catalogue ────────────────────────────────────────────────────────

def test_field_codes_are_all_real_inception_codes():
    catalogue = set(inception_columns.all_derived_codes())
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
