import sys
from datetime import date, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from api import inception_api
from api.client import api_client


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def controller(qapp):
    from app import AppController
    return AppController(qapp)


@pytest.fixture
def bars_db(tmp_path, monkeypatch):
    """Points services.inception_bars_store at a throwaway SQLite file for
    the duration of one test, so tests never touch (or depend on leftover
    state in) the real inception_bars.db next to the app.

    Also clears services.inception_compute_service's module-level
    _row_cache on both ends — that cache is keyed by (symbol, len(bars),
    last_trade_date, settings), which says nothing about WHICH database the
    bars came from, so two tests using the same symbol/date/bar-count (e.g.
    every _bar("ABB_I", date(2026, 8, 18), ...) call) but different OHLC
    values can silently read each other's cached Group A/B result even
    though each has its own isolated SQLite file. Clearing before AND after
    means neither a preceding test's leftovers nor this test's own (e.g.
    one that deliberately re-upserts different data mid-test to exercise a
    "changed since last Load" diff) can leak into a different test.
    """
    from services import inception_bars_store, inception_compute_service
    monkeypatch.setattr(inception_bars_store, "_DB_FILE", str(tmp_path / "inception_bars_test.db"))
    inception_compute_service.clear_cache()
    yield inception_bars_store
    inception_compute_service.clear_cache()


def _run_worker(qapp, screen, timeout_ms=5000):
    """View by Date / HMV now compute on a background QThread (see
    screens.inception_view_by_date._SnapshotLoadWorker / screens.
    inception_hmv._HmvLoadWorker) — real threads, but running the REAL local
    compute (no network), so letting them actually run in a test is safe and
    simpler than mocking. Waits for the worker to finish, then pumps the Qt
    event loop so its queued succeeded/failed signal actually reaches its
    slot (cross-thread signals are queued, not delivered synchronously)."""
    assert screen._worker is not None
    assert screen._worker.wait(timeout_ms)
    qapp.processEvents()


def _bar(symbol, d, o, h, low, c, vol=1000, oi=500):
    return {
        "symbol": symbol, "trade_date": d, "open": o, "high": h, "low": low, "close": c,
        "volume": vol, "open_interest": oi,
    }


# ── api/inception_api.py: wrapper -> api_client call shape ──────────────────

def test_get_availability_hits_expected_path_and_params(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_availability(date(2026, 1, 1), date(2026, 1, 31))
    assert captured["path"] == "/inception/availability"
    assert captured["params"] == {"from": "2026-01-01", "to": "2026-01-31"}


def test_get_bars_omits_symbols_param_when_not_given(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_bars(date(2025, 1, 1), date(2025, 12, 31))
    assert captured["path"] == "/inception/bars"
    assert captured["params"] == {"from": "2025-01-01", "to": "2025-12-31"}


def test_get_bars_includes_symbols_param_when_given(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "get", lambda path, params=None: captured.update(path=path, params=params) or {})
    inception_api.get_bars(date(2025, 1, 1), date(2025, 12, 31), symbols=["ABB_I"])
    assert captured["params"]["symbols"] == ["ABB_I"]


def test_upsert_strategy_hits_expected_path_and_body(monkeypatch):
    captured = {}
    monkeypatch.setattr(api_client, "put", lambda path, json_body=None: captured.update(path=path, body=json_body) or {})
    inception_api.upsert_strategy("s1", "My Strategy", True, "Daily", [{"name": "c1"}], [])
    assert captured["path"] == "/inception/strategies/s1"
    assert captured["body"]["name"] == "My Strategy"
    assert captured["body"]["columns"] == [{"name": "c1"}]


def test_sync_vendor_data_sends_email_password_exchange_from_caller(monkeypatch):
    """Confirms the request carries whatever the caller passes — see
    screens.inception_settings, which reads its Username/Password/Exchange
    fields and passes them straight through (api.inception_api.
    sync_vendor_data's docstring)."""
    captured = {}
    monkeypatch.setattr(
        api_client, "post",
        lambda path, json_body=None, timeout=None: captured.update(path=path, body=json_body, timeout=timeout) or {
            "status": "ok", "exchange": "NFOFUT", "date_from": "2026-08-18", "date_to": "2026-08-25",
            "last_available_before": "2026-08-17", "last_available_after": "2026-08-24",
            "instruments_added": 0, "bars_written": 428,
        },
    )
    result = inception_api.sync_vendor_data("e@x.com", "pw123", "NFOFUT")
    assert captured["path"] == "/inception/vendor-sync"
    assert captured["body"] == {"email": "e@x.com", "password": "pw123", "exchange": "NFOFUT"}
    assert captured["timeout"] >= 300   # generous — a real vendor fetch, not a quick CRUD call
    assert result["bars_written"] == 428


# ── FormulaBuilder: new params default to prior behavior ────────────────────

def test_formula_builder_defaults_preserve_lmv_label_and_aggregates(qapp, controller):
    from screens.strategy_builder import FormulaBuilder

    fb = FormulaBuilder([], ["Open", "Close"], theme=controller.theme, mode="value")
    assert fb._field_label == "LMV Columns"
    assert fb._show_aggregates is True


def test_formula_builder_inception_overrides(qapp, controller):
    from screens.strategy_builder import FormulaBuilder

    fb = FormulaBuilder(
        [], ["OPEN", "52WH"], theme=controller.theme, mode="value",
        field_label="Inception Fields", show_aggregates=False,
    )
    assert fb._field_label == "Inception Fields"
    assert fb._show_aggregates is False
    assert fb.get_tokens() == []


# ── topbar menu ──────────────────────────────────────────────────────────────

def test_topbar_has_inception_menu_before_help(qapp, controller):
    from components.topbar import TopBar

    bar = TopBar(controller.theme)
    buttons = [w for w in bar.children() if w.__class__.__name__ == "QPushButton"]
    labels = [b.text() for b in buttons if b.menu() is not None]
    assert "Inception" in labels
    assert labels.index("Inception") < labels.index("Help")

    inception_btn = next(b for b in buttons if b.text() == "Inception")
    actions = [a.text() for a in inception_btn.menu().actions()]
    assert actions == ["View by Date", "Strategy Builder", "HMV", "Formula Stats", "", "Data & Settings"]


# ── services.inception_columns ────────────────────────────────────────────

def test_group_b_has_24_gap_codes_each_producing_3_metrics():
    from services.inception_columns import GROUP_B, gap_metric_names

    assert len(GROUP_B) == 24
    for code in GROUP_B:
        assert gap_metric_names(code) == [f"{code} LOW", f"{code} HIGH", f"{code} DATE"]


def test_group_a_has_47_codes_and_no_overlap_with_raw_or_group_b():
    from services.inception_columns import GROUP_A, GROUP_B, RAW_FIELDS

    assert len(GROUP_A) == 47
    assert not (set(GROUP_A) & set(GROUP_B))
    assert not (set(GROUP_A) & set(RAW_FIELDS))


def test_column_catalogue_exposes_bare_gap_code_plus_low_high_date():
    from services.inception_columns import GROUP_A, GROUP_B, RAW_FIELDS, column_catalogue

    catalogue = column_catalogue()
    codes = {c.code for c in catalogue}
    assert len(catalogue) == len(RAW_FIELDS) + len(GROUP_A) + len(GROUP_B) * 4
    for code in GROUP_B:
        assert code in codes
        assert f"{code} LOW" in codes and f"{code} HIGH" in codes and f"{code} DATE" in codes


# ── services.inception_formula_engine: Group A (ported from the backend's
# now-removed test_inception.py — same hand-traced fixtures, verifying the
# relocated copy) ─────────────────────────────────────────────────────────

def test_compute_group_a_period_bookkeeping():
    from services.inception_formula_engine import compute_group_a

    bars = [
        _bar("X", date(2024, 12, 30), 100, 105, 95, 100),
        _bar("X", date(2024, 12, 31), 101, 106, 96, 102),
        _bar("X", date(2025, 1, 2), 103, 110, 100, 108),
        _bar("X", date(2025, 1, 3), 109, 112, 107, 110),
        _bar("X", date(2025, 4, 1), 111, 115, 109, 113),
    ]
    result = compute_group_a(bars)
    d1, d2, d3, d4, d5 = (b["trade_date"] for b in bars)

    assert result[d1]["P.OPEN"] is None
    assert result[d1]["ATH"] == 105 and result[d1]["ATL"] == 95
    assert result[d1]["CQO"] == 100 and result[d1]["CQH"] == 105 and result[d1]["CQL"] == 95

    assert result[d2]["P.OPEN"] == 100 and result[d2]["P.CLOSE"] == 100
    assert result[d2]["% CHG PDC AND OPEN"] == pytest.approx(1.0)
    assert result[d2]["DAY % CHANGE"] == pytest.approx(2.0)
    assert result[d2]["ATH"] == 106 and result[d2]["ATL"] == 95

    # New quarter/year at d3; FY (Apr-Mar) does NOT reset (Jan 2025 is FY2024).
    assert result[d3]["CQO"] == 103 and result[d3]["PQC"] == 102
    assert result[d3]["QT"] == 102 and result[d3]["QB"] == 102
    assert result[d3]["CFYO"] == 100 and result[d3]["PFYO"] is None

    assert result[d4]["CQH"] == 112 and result[d4]["PQC"] == 102

    # Crosses Apr 1 at d5: quarter and FY both reset; calendar year doesn't.
    assert result[d5]["CQO"] == 111 and result[d5]["PQC"] == 110
    assert result[d5]["QT"] == 110 and result[d5]["QB"] == 102
    assert result[d5]["CYO"] == 103 and result[d5]["CYH"] == 115  # year unchanged
    assert result[d5]["CFYO"] == 111 and result[d5]["PFYO"] == 100
    assert result[d5]["ATH"] == 115 and result[d5]["ATL"] == 95


def test_compute_group_a_weekly_pwc_updates_only_on_new_week():
    from services.inception_formula_engine import compute_group_a

    bars = [
        _bar("X", date(2025, 1, 6), 100, 101, 99, 100),
        _bar("X", date(2025, 1, 7), 100, 101, 99, 101),
        _bar("X", date(2025, 1, 10), 101, 102, 100, 102),  # week 1's close = 102
        _bar("X", date(2025, 1, 13), 105, 106, 104, 105),  # first day of week 2
        _bar("X", date(2025, 1, 14), 106, 107, 105, 106),  # still week 2
    ]
    result = compute_group_a(bars)
    d1, d2, d3, d4, d5 = (b["trade_date"] for b in bars)

    assert result[d1]["% CHG PWC AND OPEN"] is None
    assert result[d3]["% CHG PWC AND OPEN"] is None
    assert result[d4]["% CHG PWC AND OPEN"] == pytest.approx((105 - 102) / 102 * 100)
    assert result[d5]["% CHG PWC AND OPEN"] == pytest.approx((106 - 102) / 102 * 100)


def test_compute_group_a_52_week_window_evicts_old_bars():
    from services.inception_formula_engine import compute_group_a

    bars = [
        _bar("X", date(2024, 1, 1), 100, 200, 50, 100),
        _bar("X", date(2025, 6, 1), 100, 110, 90, 100),
    ]
    result = compute_group_a(bars)
    last = bars[-1]["trade_date"]
    assert result[last]["52WH"] == 110 and result[last]["52WL"] == 90
    assert result[last]["ATH"] == 200 and result[last]["ATL"] == 50  # never windowed


def test_compute_group_a_52_week_window_matches_naive_scan():
    """52WH/52WL are tracked via a sliding-window-maximum/-minimum (two
    monotonic deques) for O(n) performance instead of a naive max()/min()
    rescan of the whole window on every bar (see inception_formula_engine's
    module docstring — profiling a cold HMV load showed the naive rescan
    dominating total load time, worse than every other Group A/B column's
    computation combined, once window sizes grow to ~250+ trading days).
    Regression guard: randomized bar sequences must produce IDENTICAL
    52WH/52WL to the naive reference, across several window sizes — a
    correctness bug in the monotonic-deque bookkeeping wouldn't show up in
    the small hand-picked fixtures above."""
    import random
    from collections import deque
    from services.inception_formula_engine import compute_group_a

    def naive_52w(bars, week_window_days):
        window = deque()
        out = []
        for bar in bars:
            d = bar["trade_date"]
            window.append((d, bar["high"], bar["low"]))
            cutoff = d - timedelta(days=week_window_days)
            while window and window[0][0] < cutoff:
                window.popleft()
            out.append((max(h for _, h, _ in window), min(lo for _, _, lo in window)))
        return out

    rng = random.Random(12345)
    for _trial in range(15):
        n = rng.randint(1, 250)
        d, price, bars = date(2015, 1, 1), 100.0, []
        made = 0
        while made < n:
            if d.weekday() < 5:
                price *= 1 + rng.uniform(-0.05, 0.05)
                bars.append(_bar("X", d, price, price * 1.02, price * 0.98, price))
                made += 1
            d += timedelta(days=1)
        week_window_days = rng.choice([364, 250, 30, 5])
        naive = naive_52w(bars, week_window_days)
        result = compute_group_a(bars, week_window_days=week_window_days)
        for bar, (naive_high, naive_low) in zip(bars, naive):
            row = result[bar["trade_date"]]
            assert row["52WH"] == naive_high
            assert row["52WL"] == naive_low


def test_compute_group_a_week_window_days_is_configurable():
    from services.inception_formula_engine import compute_group_a

    bars = [
        _bar("X", date(2024, 1, 1), 100, 200, 50, 100),
        _bar("X", date(2025, 6, 1), 100, 110, 90, 100),
    ]
    last = bars[-1]["trade_date"]
    # A wider custom window pulls the 2024 extremes back into 52WH/52WL.
    result = compute_group_a(bars, week_window_days=600)
    assert result[last]["52WH"] == 200 and result[last]["52WL"] == 50


# ── services.inception_formula_engine: Group B ────────────────────────────

def test_compute_group_b_opens_and_fills_a_daily_gap_up():
    from services.inception_formula_engine import compute_group_b

    d1, d2, d3 = date(2025, 2, 3), date(2025, 2, 4), date(2025, 2, 5)
    bars = [
        _bar("X", d1, 99, 101, 98, 100),
        _bar("X", d2, 106, 108, 105, 106),
        _bar("X", d3, 107, 109, 98, 99),
    ]
    result = compute_group_b(bars, threshold_pct=0.5)

    assert result[d1]["DAY UF GUP 1"] is None
    assert result[d3]["DAY FD GUP 1"] == (100, 106, d2)
    assert result[d3]["DAY UF GUP 1"] == (106, 107, d3)
    assert result[d3]["DAY UF GUP 2"] is None
    assert result[d3]["DAY UF GDN 1"] is None
    assert result[d3]["WEEK UF GUP 1"] is None


def test_compute_group_b_fifo_caps_at_configured_depth():
    from services.inception_formula_engine import compute_group_b

    bars = [_bar("X", date(2025, 3, 3), 100, 101, 99, 100)]
    price = 100
    for i in range(1, 6):
        price *= 1.10
        bars.append(_bar("X", date(2025, 3, 3 + i), price, price * 1.02, price * 0.98, price))

    result = compute_group_b(bars, threshold_pct=0.5, fifo_cap=3)
    last_day = bars[-1]["trade_date"]
    ranks = [result[last_day][f"DAY UF GUP {r}"] for r in (1, 2, 3)]
    assert all(area is not None for area in ranks)
    opened_dates = [area[2] for area in ranks]
    assert opened_dates == sorted(opened_dates, reverse=True)
    assert opened_dates[0] == last_day

    # A shallower configured depth caps at 2.
    result2 = compute_group_b(bars, threshold_pct=0.5, fifo_cap=2)
    assert result2[last_day]["DAY UF GUP 3"] is None
    assert result2[last_day]["DAY UF GUP 2"] is not None


def test_compute_group_b_gap_down_uses_mirror_condition():
    from services.inception_formula_engine import compute_group_b

    d1, d2 = date(2025, 5, 5), date(2025, 5, 6)
    bars = [_bar("X", d1, 100, 101, 99, 100), _bar("X", d2, 94, 95, 93, 94)]
    result = compute_group_b(bars, threshold_pct=0.5)
    assert result[d2]["DAY UF GDN 1"] == (94, 100, d2)
    assert result[d2]["DAY UF GUP 1"] is None


# ── services.inception_formula_engine: required_lookback_start ──────────────

def test_required_lookback_fixed_buffer_codes():
    from services.inception_formula_engine import required_lookback_start

    as_of = date(2026, 8, 18)
    assert required_lookback_start("P.OPEN", as_of) == as_of - timedelta(days=7)
    assert required_lookback_start("% CHG PWC AND OPEN", as_of) == as_of - timedelta(days=14)
    assert required_lookback_start("52WH", as_of) == as_of - timedelta(days=364)
    assert required_lookback_start("52WH", as_of, week_window_days=100) == as_of - timedelta(days=100)


def test_required_lookback_all_time_uses_first_traded_date():
    from services.inception_formula_engine import required_lookback_start

    as_of = date(2026, 8, 18)
    assert required_lookback_start("ATH", as_of, first_traded_date=date(2022, 1, 28)) == date(2022, 1, 28)
    assert required_lookback_start("ATL", as_of, first_traded_date=None) is None


def test_required_lookback_current_and_previous_and_last2_period_codes():
    from services.inception_formula_engine import required_lookback_start

    as_of = date(2026, 8, 18)  # Q3 2026, FY2026 (Apr start)
    assert required_lookback_start("CQO", as_of) == date(2026, 7, 1)
    assert required_lookback_start("CFYO", as_of) == date(2026, 4, 1)
    assert required_lookback_start("PQC", as_of) == date(2026, 4, 1)
    assert required_lookback_start("PYC", as_of) == date(2025, 1, 1)
    assert required_lookback_start("QT", as_of) == date(2026, 1, 1)
    assert required_lookback_start("YT", as_of) == date(2024, 1, 1)


def test_required_lookback_unrecognized_code_is_ungated():
    from services.inception_formula_engine import required_lookback_start

    assert required_lookback_start("OPEN", date(2026, 8, 18)) is None
    assert required_lookback_start("SOME_UNKNOWN_CODE", date(2026, 8, 18)) is None


# ── services.inception_bars_store ────────────────────────────────────────

def test_upsert_and_query_bars_for_symbol(bars_db):
    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100),
        _bar("ABB_I", date(2025, 1, 2), 100, 103, 99, 102),
    ])
    rows = bars_db.bars_for_symbol("ABB_I")
    assert [r["trade_date"] for r in rows] == [date(2025, 1, 1), date(2025, 1, 2)]
    assert rows[1]["close"] == 102


def test_upsert_bars_replaces_existing_row_for_same_key(bars_db):
    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100)])
    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 200, 201, 199, 200)])
    rows = bars_db.bars_for_symbol("ABB_I")
    assert len(rows) == 1 and rows[0]["close"] == 200


def test_last_synced_date_and_latest_synced_date_on_or_before(bars_db):
    assert bars_db.last_synced_date() is None
    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100),
        _bar("ABB_I", date(2025, 3, 1), 100, 101, 99, 100),
    ])
    assert bars_db.last_synced_date() == date(2025, 3, 1)
    assert bars_db.latest_synced_date_on_or_before(date(2025, 2, 1)) == date(2025, 1, 1)
    assert bars_db.latest_synced_date_on_or_before(date(2024, 1, 1)) is None


def test_bars_for_date_returns_all_symbols(bars_db):
    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100),
        _bar("TCS_I", date(2025, 1, 1), 200, 201, 199, 200),
    ])
    rows = bars_db.bars_for_date(date(2025, 1, 1))
    assert {r["symbol"] for r in rows} == {"ABB_I", "TCS_I"}


def test_clear_local_cache_resets_store(bars_db, tmp_path):
    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100)])
    assert bars_db.row_count() == 1
    bars_db.clear_local_cache()
    assert bars_db.row_count() == 0


# ── services.inception_sync_service ──────────────────────────────────────

def test_incremental_sync_fetches_from_day_after_last_synced(bars_db, monkeypatch):
    from services import inception_sync_service

    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100)])

    captured = {}
    monkeypatch.setattr(inception_api, "get_bars", lambda date_from, date_to, symbols=None: (
        captured.update(date_from=date_from, date_to=date_to) or {"rows": []}
    ))

    inception_sync_service.incremental_sync(today=date(2025, 1, 5))
    assert captured["date_from"] == date(2025, 1, 2)
    assert captured["date_to"] == date(2025, 1, 5)


def test_incremental_sync_on_empty_store_chunks_like_full_backfill(bars_db, monkeypatch):
    """Regression guard: "Sync Now" on a fresh install used to send one
    un-chunked ~26-year request, which the backend's per-request range cap
    always rejected — see inception_sync_service.incremental_sync's
    docstring."""
    from services import inception_sync_service

    calls = []
    monkeypatch.setattr(inception_api, "get_bars", lambda date_from, date_to, symbols=None: (
        calls.append((date_from, date_to)) or {"rows": []}
    ))

    inception_sync_service.incremental_sync(today=date(2001, 6, 1))
    assert len(calls) >= 2  # chunked, not one giant request
    assert all((to - frm).days <= inception_sync_service._CHUNK_DAYS for frm, to in calls)


def test_incremental_sync_noop_when_already_up_to_date(bars_db, monkeypatch):
    from services import inception_sync_service

    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 5), 100, 101, 99, 100)])

    called = []
    monkeypatch.setattr(inception_api, "get_bars", lambda *a, **k: called.append(1) or {"rows": []})

    total = inception_sync_service.incremental_sync(today=date(2025, 1, 5))
    assert total == 0 and called == []


def test_full_backfill_chunks_into_year_windows_and_upserts_each(bars_db, monkeypatch):
    from services import inception_sync_service

    calls = []

    def _fake_get_bars(date_from, date_to, symbols=None):
        calls.append((date_from, date_to))
        return {"rows": [dict(_bar("ABB_I", date_from, 100, 101, 99, 100))]}

    monkeypatch.setattr(inception_api, "get_bars", _fake_get_bars)

    total = inception_sync_service.full_backfill(today=date(2001, 6, 1))
    assert len(calls) >= 2  # spans more than one _CHUNK_DAYS window
    assert all((to - frm).days <= inception_sync_service._CHUNK_DAYS for frm, to in calls)
    assert total == len(calls)
    assert bars_db.row_count() == len(calls)


def test_sync_wraps_api_error_as_sync_error(bars_db, monkeypatch):
    """A real rejection (bad range, etc.) fails immediately — no retries,
    since retrying an ApiError wouldn't change the outcome."""
    from services import inception_sync_service
    from api.exceptions import ApiError

    calls = []

    def _boom(*a, **k):
        calls.append(1)
        raise ApiError("boom", "server_error", 500)

    monkeypatch.setattr(inception_api, "get_bars", _boom)
    monkeypatch.setattr(inception_sync_service.time, "sleep", lambda s: None)
    with pytest.raises(inception_sync_service.SyncError):
        inception_sync_service.incremental_sync(today=date(2025, 1, 5))
    assert len(calls) == 1


def test_transient_network_error_is_retried_and_succeeds(bars_db, monkeypatch):
    """Regression guard: a Full Resync used to abort entirely on the first
    transient network blip anywhere across its ~27 sequential chunk
    requests — see inception_sync_service's module docstring."""
    from services import inception_sync_service
    from api.exceptions import NetworkError

    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100)])  # small delta -> one chunk

    calls = []

    def _flaky(date_from, date_to, symbols=None):
        calls.append((date_from, date_to))
        if len(calls) == 1:
            raise NetworkError("connection aborted")
        return {"rows": [dict(_bar("ABB_I", date_from, 100, 101, 99, 100))]}

    monkeypatch.setattr(inception_api, "get_bars", _flaky)
    monkeypatch.setattr(inception_sync_service.time, "sleep", lambda s: None)  # skip the real backoff delay

    total = inception_sync_service.incremental_sync(today=date(2025, 1, 5))
    assert total == 1
    assert len(calls) == 2   # failed once, succeeded on retry


def test_network_error_gives_up_after_max_retries(bars_db, monkeypatch):
    from services import inception_sync_service
    from api.exceptions import NetworkError

    calls = []

    def _always_fails(*a, **k):
        calls.append(1)
        raise NetworkError("connection aborted")

    monkeypatch.setattr(inception_api, "get_bars", _always_fails)
    monkeypatch.setattr(inception_sync_service.time, "sleep", lambda s: None)

    with pytest.raises(inception_sync_service.SyncError):
        inception_sync_service.incremental_sync(today=date(2025, 1, 5))
    assert len(calls) == inception_sync_service._MAX_RETRIES


def test_incremental_sync_still_chunks_a_stale_partial_backfill(bars_db, monkeypatch):
    """Regression guard: if a previous Full Resync got interrupted partway
    (some old data already synced, but last_synced_date() is still years
    behind today), a later "Sync Now" must chunk the remaining gap instead
    of sending one oversized request — same bug as the empty-store case,
    just with SOME data already present instead of none."""
    from services import inception_sync_service

    bars_db.upsert_bars([_bar("ABB_I", date(2001, 1, 1), 100, 101, 99, 100)])

    calls = []
    monkeypatch.setattr(inception_api, "get_bars", lambda date_from, date_to, symbols=None: (
        calls.append((date_from, date_to)) or {"rows": []}
    ))

    inception_sync_service.incremental_sync(today=date(2005, 1, 1))
    assert len(calls) >= 2
    assert all((to - frm).days <= inception_sync_service._CHUNK_DAYS for frm, to in calls)


# ── services.inception_compute_service ───────────────────────────────────

def test_snapshot_computes_group_a_and_raw_fields_from_local_bars(bars_db):
    from services import inception_compute_service

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 105, 95, 102),
        _bar("ABB_I", date(2025, 1, 2), 103, 110, 100, 108),
    ])
    rows = inception_compute_service.snapshot(date(2025, 1, 2))
    assert len(rows) == 1
    values = rows[0]["values"]
    assert rows[0]["symbol"] == "ABB_I"
    assert values["CLOSE"] == 108 and values["OPEN"] == 103
    assert values["P.CLOSE"] == 102  # previous day's close
    assert values["ATH"] == 110


def test_snapshot_skips_instruments_with_no_bar_on_that_date(bars_db):
    from services import inception_compute_service

    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100)])
    rows = inception_compute_service.snapshot(date(2025, 1, 2))
    assert rows == []


def test_hmv_returns_none_as_of_date_when_nothing_synced_in_range(bars_db):
    from services import inception_compute_service

    bars_db.upsert_bars([_bar("ABB_I", date(2024, 1, 1), 100, 101, 99, 100)])
    as_of, rows = inception_compute_service.hmv(date(2025, 1, 1), date(2025, 12, 31))
    assert as_of is None and rows == []


def test_hmv_applies_range_gate_to_52wh(bars_db):
    from services import inception_compute_service

    # Two bars far enough apart that 52WH needs the earlier one, but the
    # requested range only covers the later one.
    bars_db.upsert_bars([
        _bar("ABB_I", date(2024, 1, 1), 100, 500, 50, 100),
        _bar("ABB_I", date(2025, 6, 1), 100, 110, 90, 100),
    ])
    as_of, rows = inception_compute_service.hmv(date(2025, 5, 1), date(2025, 6, 1))
    assert as_of == date(2025, 6, 1)
    assert rows[0]["values"]["52WH"] is None  # range too short to cover the 364-day window
    assert rows[0]["values"]["OPEN"] == 100   # raw fields are never gated


# ── services.inception_compute_service: row cache ────────────────────────

def test_snapshot_reuses_cached_row_on_repeated_calls(bars_db, monkeypatch):
    """The expensive part (compute_group_a/b) should run once per (symbol,
    data+settings fingerprint) — a second identical call must not re-walk
    the instrument's history. See inception_compute_service's module
    docstring on why this matters (a cold walk is tens of seconds across
    the full instrument universe)."""
    from services import inception_compute_service

    inception_compute_service.clear_cache()
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    calls = []
    real_compute_group_a = inception_compute_service.compute_group_a
    monkeypatch.setattr(
        inception_compute_service, "compute_group_a",
        lambda bars, **kw: (calls.append(1) or real_compute_group_a(bars, **kw)),
    )

    inception_compute_service.snapshot(date(2026, 8, 18))
    inception_compute_service.snapshot(date(2026, 8, 18))
    assert len(calls) == 1


def test_snapshot_recomputes_after_new_bars_synced(bars_db, monkeypatch):
    from services import inception_compute_service

    inception_compute_service.clear_cache()
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    calls = []
    real_compute_group_a = inception_compute_service.compute_group_a
    monkeypatch.setattr(
        inception_compute_service, "compute_group_a",
        lambda bars, **kw: (calls.append(1) or real_compute_group_a(bars, **kw)),
    )

    inception_compute_service.snapshot(date(2026, 8, 18))
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 19), 100, 106, 95, 101)])
    inception_compute_service.snapshot(date(2026, 8, 19))
    assert len(calls) == 2   # new trade date -> different fingerprint -> recompute


def test_snapshot_and_hmv_progress_cb_called_once_per_instrument(bars_db):
    from services import inception_compute_service

    inception_compute_service.clear_cache()
    bars_db.upsert_bars([
        _bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100),
        _bar("TCS_I", date(2026, 8, 18), 190, 205, 185, 200),
    ])

    ticks = []
    inception_compute_service.snapshot(date(2026, 8, 18), progress_cb=lambda done, total: ticks.append((done, total)))
    assert ticks == [(1, 2), (2, 2)]

    ticks.clear()
    inception_compute_service.hmv(date(2026, 1, 1), date(2026, 8, 18), progress_cb=lambda done, total: ticks.append((done, total)))
    assert ticks == [(1, 2), (2, 2)]


# ── services.inception_compute_service.range_rows (Formula Stats) ────────────

def test_range_rows_returns_one_day_entry_per_trading_day_in_range(bars_db):
    from services import inception_compute_service

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 105, 95, 102),
        _bar("ABB_I", date(2025, 1, 2), 103, 110, 100, 108),
        _bar("ABB_I", date(2025, 1, 3), 108, 112, 104, 109),
    ])
    result = inception_compute_service.range_rows(date(2025, 1, 2), date(2025, 1, 3))
    assert [d["trade_date"] for d in result["days"]] == ["2025-01-02", "2025-01-03"]
    day1 = result["days"][0]
    assert day1["stocks"] == [{
        "symbol": "ABB_I", "display_name": "ABB_I",
        "metrics": day1["stocks"][0]["metrics"],
    }]
    assert day1["stocks"][0]["metrics"]["CLOSE"] == 108
    assert day1["stocks"][0]["metrics"]["P.CLOSE"] == 102


def test_range_rows_matches_hmv_for_the_same_single_day(bars_db):
    """range_rows' per-day values must be identical to what hmv()/snapshot()
    would compute for that same as-of-date — same underlying forward pass,
    just not discarding every day but the last."""
    from services import inception_compute_service

    bars_db.upsert_bars([
        _bar("ABB_I", date(2024, 1, 1), 100, 500, 50, 100),
        _bar("ABB_I", date(2025, 6, 1), 100, 110, 90, 100),
    ])
    range_result = inception_compute_service.range_rows(date(2025, 6, 1), date(2025, 6, 1))
    snapshot_rows = inception_compute_service.snapshot(date(2025, 6, 1))
    assert range_result["days"][0]["stocks"][0]["metrics"] == snapshot_rows[0]["values"]


def test_range_rows_excludes_instruments_with_no_bar_in_range(bars_db):
    from services import inception_compute_service

    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 101, 99, 100)])
    result = inception_compute_service.range_rows(date(2025, 2, 1), date(2025, 2, 28))
    assert result["days"] == []


def test_range_rows_progress_cb_called_once_per_instrument(bars_db):
    from services import inception_compute_service

    bars_db.upsert_bars([
        _bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100),
        _bar("TCS_I", date(2026, 8, 18), 190, 205, 185, 200),
    ])
    ticks = []
    inception_compute_service.range_rows(
        date(2026, 8, 1), date(2026, 8, 18),
        progress_cb=lambda done, total: ticks.append((done, total)),
    )
    assert ticks == [(1, 2), (2, 2)]


# ── services.inception_sector ────────────────────────────────────────────

def test_sector_for_known_and_unknown_symbol():
    from services import inception_sector

    known = next(iter(inception_sector._MAP))
    assert inception_sector.sector_for(known) == inception_sector._MAP[known]
    assert inception_sector.sector_for(known.lower()) == inception_sector._MAP[known]  # case-insensitive
    assert inception_sector.sector_for("NOT_A_REAL_SYMBOL_XYZ") == "—"


def test_inject_sector_rows_prepends_sector_looked_up_by_symbol_column():
    from services import inception_sector

    known = next(iter(inception_sector._MAP))
    headers = ["Symbol", "CLOSE"]
    data = [[known, 100.0], ["NOT_A_REAL_SYMBOL_XYZ", 200.0]]
    new_headers, new_data = inception_sector.inject_sector_rows(headers, data)
    assert new_headers == ["Sector", "Symbol", "CLOSE"]
    assert new_data[0] == [inception_sector._MAP[known], known, 100.0]
    assert new_data[1] == ["—", "NOT_A_REAL_SYMBOL_XYZ", 200.0]


# ── components.frozen_table_columns ──────────────────────────────────────

def test_frozen_columns_pins_named_headers_at_visual_zero_and_one(qapp):
    from PySide6.QtWidgets import QTableWidget, QTableWidgetItem
    from components.frozen_table_columns import FrozenColumns

    headers = ["Symbol", "Sector", "CLOSE"]
    table = QTableWidget(2, 3)
    table.setHorizontalHeaderLabels(headers)
    for r in range(2):
        for c, h in enumerate(headers):
            table.setItem(r, c, QTableWidgetItem(f"{h}{r}"))

    freeze = FrozenColumns(table)
    freeze.configure(headers, ["Sector", "Symbol"])

    hdr = table.horizontalHeader()
    assert hdr.logicalIndex(0) == headers.index("Sector")
    assert hdr.logicalIndex(1) == headers.index("Symbol")
    assert freeze._frozen_cols == [headers.index("Sector"), headers.index("Symbol")]


def test_frozen_columns_unfreeze_hides_overlay(qapp):
    from PySide6.QtWidgets import QTableWidget
    from components.frozen_table_columns import FrozenColumns

    headers = ["Symbol", "Sector"]
    table = QTableWidget(1, 2)
    table.setHorizontalHeaderLabels(headers)

    freeze = FrozenColumns(table)
    freeze.configure(headers, ["Sector", "Symbol"])
    assert freeze._frozen_cols

    freeze.configure(headers, [])
    assert freeze._frozen_cols == []
    assert freeze._overlay.isHidden()


# ── services.inception_formula_builder_columns ───────────────────────────

def _daily_bars(symbol, start, n, close_fn=lambda i: 100 + i, skip=frozenset()):
    """n consecutive weekday bars starting at *start*, skipping any offset
    in *skip* (to simulate a holiday gap for _holidays_for tests)."""
    from datetime import timedelta
    bars = []
    d, made = start, 0
    i = 0
    while made < n:
        if d.weekday() < 5:
            if i not in skip:
                c = close_fn(i)
                bars.append(_bar(symbol, d, c, c + 5, c - 5, c))
                made += 1
            i += 1
        d += timedelta(days=1)
    return bars


def test_compute_for_bars_empty_returns_empty_dict():
    from services import inception_formula_builder_columns as fbc

    assert fbc.compute_for_bars("ABB_I", []) == {}


def test_compute_for_bars_computes_month_top_bottom_from_close_only():
    """MT/MB (MONTH TOP/BOTTOM) only need Close — see services.formula_engine
    — so they should compute for real from Inception's OHLC-only bars."""
    from services import inception_formula_builder_columns as fbc

    bars = _daily_bars("ABB_I", date(2026, 1, 1), 160)   # ~7.5 months of daily bars
    values = fbc.compute_for_bars("ABB_I", bars)
    assert values["MT"] is not None
    assert values["MB"] is not None
    assert values["MT"] >= values["MB"]


def test_compute_for_bars_avgrate_dependent_codes_are_none_not_crash():
    """Inception bars carry no AvgRate/DiffPcnt — turnover/ATP codes must
    come back None (services.formula_engine's own "blank rather than crash"
    fallback for missing input), not raise."""
    from services import inception_formula_builder_columns as fbc

    bars = _daily_bars("ABB_I", date(2026, 1, 1), 40)
    values = fbc.compute_for_bars("ABB_I", bars)
    for code in ("PATP", "CWATP", "PWATP", "CMATP", "PMATP", "DAY TO", "PDTO", "CWTO", "PWTO"):
        assert values[code] is None


def test_compute_for_bars_caches_and_clear_cache_forces_recompute(monkeypatch):
    from services import inception_formula_builder_columns as fbc
    from services import formula_engine

    fbc.clear_cache()
    bars = _daily_bars("ABB_I", date(2026, 1, 1), 40)

    calls = []
    real = formula_engine.compute_for_symbol
    monkeypatch.setattr(formula_engine, "compute_for_symbol", lambda *a, **kw: (calls.append(1) or real(*a, **kw)))

    fbc.compute_for_bars("ABB_I", bars)
    fbc.compute_for_bars("ABB_I", bars)
    assert len(calls) == 1   # second call hit the cache

    fbc.clear_cache()
    fbc.compute_for_bars("ABB_I", bars)
    assert len(calls) == 2   # cache cleared -> recomputed


def test_holidays_for_treats_missing_weekday_as_holiday_not_gap():
    from services import inception_formula_builder_columns as fbc

    # A 2-week run of weekday bars with one weekday (offset 2) missing.
    bars = _daily_bars("ABB_I", date(2026, 1, 5), 9, skip={2})  # Jan 5 is a Monday
    holidays = fbc._holidays_for(bars)
    assert len(holidays) == 1
    missing_date = next(iter(holidays))
    assert missing_date.weekday() < 5
    assert missing_date not in {b["trade_date"] for b in bars}


# ── screens: view by date ────────────────────────────────────────────────

def test_view_by_date_display_symbol_strips_roll_suffix():
    from screens.inception_view_by_date import _display_symbol

    assert _display_symbol("ABB_I") == "ABB"
    assert _display_symbol("SOMETHING") == "SOMETHING"  # no suffix to strip


def test_view_by_date_shows_sync_prompt_when_nothing_synced(qapp, controller, bars_db):
    from screens.inception_view_by_date import InceptionViewByDateScreen

    screen = InceptionViewByDateScreen(controller)
    screen._selected_date = date(2026, 8, 18)
    screen._on_view_clicked()
    assert "Sync" in screen._status_lbl.text()


def test_view_by_date_applies_active_strategies_locally(qapp, controller, monkeypatch, bars_db):
    """Group A/B and strategy columns are both computed entirely locally now
    — no network call at all for View by Date (see services.
    inception_compute_service, services.strategy_engine.apply_strategies)."""
    from screens.inception_view_by_date import InceptionViewByDateScreen
    from services import inception_strategy_store

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    screen = InceptionViewByDateScreen(controller)
    screen._selected_date = date(2026, 8, 18)
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Range", "active": True, "row_filter": [],
        "columns": [{
            "name": "Day Range",
            "formula": [{"type": "col", "value": "CLOSE"}, {"type": "op", "value": "-"}, {"type": "col", "value": "OPEN"}],
        }],
    }])

    from unittest.mock import MagicMock
    from screens import inception_view_by_date as ivd
    fake_viewer_cls = MagicMock()
    monkeypatch.setattr(ivd, "HistoricDataViewer", fake_viewer_cls)

    screen._on_view_clicked()
    _run_worker(qapp, screen)
    headers, rows = fake_viewer_cls.call_args.args[:2]
    assert "Day Range" in headers
    assert rows[0][headers.index("Day Range")] == 10.0
    assert rows[0][headers.index("Symbol")] == "ABB"
    assert "Sector" in headers   # see services.inception_sector
    assert fake_viewer_cls.call_args.kwargs["frozen_headers"] == ["Sector", "Symbol"]
    assert screen._strat_btn.text() == "⚡  Strategies  1/1"


def test_view_by_date_strategy_picker_lets_multiple_strategies_be_selected(qapp, controller, monkeypatch, bars_db):
    """The picker (screens.live_viewer.StrategyPickerPopup, reused as-is)
    replaces the old "no way to pick which strategies apply" gap — Apply
    updates this screen's own session state and the button label, same
    shape LMV's own picker uses.

    Deliberately asserts save_strategy is NEVER called here — see screens.
    live_viewer._on_strategies_applied's docstring for the regression this
    guards against: persisting every strategy the picker showed (not just
    the ones toggled) used to silently deactivate every other, unchecked
    strategy in Strategy Builder too ("applied 6 strategies, activated a
    7th, and the 6 disappeared")."""
    from screens.inception_view_by_date import InceptionViewByDateScreen
    from services import inception_strategy_store

    strategies = [
        {"id": "s1", "name": "A", "active": False, "row_filter": [], "columns": []},
        {"id": "s2", "name": "B", "active": False, "row_filter": [], "columns": []},
    ]
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: strategies)
    saved = []
    monkeypatch.setattr(inception_strategy_store, "save_strategy", lambda s: saved.append(dict(s)))

    screen = InceptionViewByDateScreen(controller)
    screen._show_strategy_picker()
    assert screen._strategies == strategies

    updated = [dict(s1, active=True) for s1 in strategies]  # both picked on
    screen._on_strategies_applied(updated)
    assert saved == []
    assert all(s["active"] for s in screen._strategies)
    assert screen._strat_btn.text() == "⚡  Strategies  2/2"


def test_view_by_date_screen_constructs(qapp, controller):
    from screens.inception_view_by_date import InceptionViewByDateScreen

    screen = InceptionViewByDateScreen(controller)
    assert screen is not None
    screen.refresh_theme()


def test_reorder_by_saved_column_order_moves_named_columns_to_front(monkeypatch):
    from screens.inception_view_by_date import _reorder_by_saved_column_order
    from services import config_store

    headers = ["Sector", "Symbol", "OPEN", "HIGH", "LOW", "CLOSE", "52WH"]
    rows = [["CG", "ABB", 90, 105, 85, 100, 200]]

    monkeypatch.setattr(config_store, "load_column_order", lambda key=None: ["CLOSE", "Symbol"])
    new_headers, new_rows = _reorder_by_saved_column_order(headers, rows)

    assert new_headers == ["CLOSE", "Symbol", "Sector", "OPEN", "HIGH", "LOW", "52WH"]
    assert new_rows == [[100, "ABB", "CG", 90, 105, 85, 200]]


def test_reorder_by_saved_column_order_noop_when_nothing_saved(monkeypatch):
    from screens.inception_view_by_date import _reorder_by_saved_column_order
    from services import config_store

    headers = ["Sector", "Symbol", "CLOSE"]
    rows = [["CG", "ABB", 100]]
    monkeypatch.setattr(config_store, "load_column_order", lambda key=None: [])
    new_headers, new_rows = _reorder_by_saved_column_order(headers, rows)
    assert new_headers == headers
    assert new_rows == rows


def test_reorder_by_saved_column_order_ignores_unknown_names(monkeypatch):
    from screens.inception_view_by_date import _reorder_by_saved_column_order
    from services import config_store

    headers = ["Sector", "Symbol", "CLOSE"]
    rows = [["CG", "ABB", 100]]
    monkeypatch.setattr(config_store, "load_column_order", lambda key=None: ["CLOSE", "NOT_A_REAL_COLUMN"])
    new_headers, new_rows = _reorder_by_saved_column_order(headers, rows)
    assert new_headers == ["CLOSE", "Sector", "Symbol"]
    assert new_rows == [[100, "CG", "ABB"]]


def test_view_by_date_applies_saved_column_order_from_config_editor(qapp, controller, bars_db, tmp_path, monkeypatch):
    """Config Editor's "Inception Column Order" tab (services.config_store.
    INCEPTION_HMV_COLUMN_ORDER — shared with screens.inception_hmv's own
    identical fix) applies here too, not just to HMV. Sector/Symbol still
    win the leftmost two spots regardless (see components.
    frozen_table_columns) — the saved order applies to everything after
    that."""
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    config_store.save_column_order(["CLOSE", "OPEN"], key=config_store.INCEPTION_HMV_COLUMN_ORDER)

    from screens.inception_view_by_date import InceptionViewByDateScreen

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    from unittest.mock import MagicMock
    from screens import inception_view_by_date as ivd
    fake_viewer_cls = MagicMock()
    monkeypatch.setattr(ivd, "HistoricDataViewer", fake_viewer_cls)

    screen = InceptionViewByDateScreen(controller)
    screen._selected_date = date(2026, 8, 18)
    screen._on_view_clicked()
    _run_worker(qapp, screen)

    headers = fake_viewer_cls.call_args.args[0]
    assert headers[0] == "CLOSE"
    assert headers[1] == "OPEN"


def test_view_by_date_highlights_cells_changed_since_last_view(qapp, controller, monkeypatch, bars_db):
    """Same "changed since last Load/View" idea as screens.inception_hmv's
    identical fix (there's no live tick here to flash on) — cell_highlights
    passed into HistoricDataViewer, computed AFTER the saved column reorder
    so indices line up with what the popup actually builds."""
    from screens.inception_view_by_date import InceptionViewByDateScreen
    from services import inception_compute_service, inception_strategy_store

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [])
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    from unittest.mock import MagicMock
    from screens import inception_view_by_date as ivd
    fake_viewer_cls = MagicMock()
    monkeypatch.setattr(ivd, "HistoricDataViewer", fake_viewer_cls)

    screen = InceptionViewByDateScreen(controller)
    screen._highlight_color = "#ff0000"
    screen._selected_date = date(2026, 8, 18)
    screen._on_view_clicked()
    _run_worker(qapp, screen)
    assert fake_viewer_cls.call_args.kwargs["cell_highlights"] == {}   # first View — nothing to compare against

    inception_compute_service.clear_cache()
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 150)])
    screen._on_view_clicked()
    _run_worker(qapp, screen)

    headers = fake_viewer_cls.call_args.args[0]
    close_idx = headers.index("CLOSE")
    highlights = fake_viewer_cls.call_args.kwargs["cell_highlights"]
    assert highlights.get((0, close_idx)) == "#ff0000"


def test_view_by_date_includes_formula_builder_columns(qapp, controller, monkeypatch, bars_db):
    """MT/MB and friends (services.inception_formula_builder_columns) used
    to be HMV-only — merged in here too now (_SnapshotLoadWorker, same
    merge screens.inception_hmv's own worker does) so they're both visible
    in View by Date's popup and, since screens.inception_strategy_builder's
    "real sample data" load reuses this exact worker, actually resolvable
    when a Strategy Builder formula references one — see
    test_strategy_builder_fields_include_formula_builder_columns."""
    from screens.inception_view_by_date import InceptionViewByDateScreen

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    from unittest.mock import MagicMock
    from screens import inception_view_by_date as ivd
    fake_viewer_cls = MagicMock()
    monkeypatch.setattr(ivd, "HistoricDataViewer", fake_viewer_cls)

    screen = InceptionViewByDateScreen(controller)
    screen._selected_date = date(2026, 8, 18)
    screen._on_view_clicked()
    _run_worker(qapp, screen)

    headers = fake_viewer_cls.call_args.args[0]
    assert "MT" in headers and "MB" in headers
    assert "DT" in headers and "DB" in headers


def test_view_by_date_resolves_avg_days_on_raw_field(qapp, controller, monkeypatch, bars_db):
    """Regression: a strategy column using AVG_DAYS on a raw OHLCV field
    (e.g. the reported "200 Average" -> AVG_DAYS(CLOSE, 200)) used to
    always evaluate to None here — apply_strategies was never given a
    day_history at all (see services.inception_day_history's module
    docstring), and even once it started being built and passed through, a
    second bug (day_history keyed by the raw "_I" symbol, while the row's
    own "Symbol" column is display-stripped) meant the lookup still never
    found a match — see screens.inception_view_by_date._SnapshotLoadWorker
    ._merge_formula_builder_columns_and_day_history's own comment on that."""
    from screens.inception_view_by_date import InceptionViewByDateScreen
    from services import inception_strategy_store

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1) + timedelta(days=i), 100 + i, 101 + i, 99 + i, 100 + i)
        for i in range(210)
    ])
    as_of = date(2025, 1, 1) + timedelta(days=209)

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "200 Average", "active": True, "row_filter": [],
        "columns": [{"name": "200 Average", "formula": [
            {"type": "func", "value": "AVG_DAYS(", "col_arg": "CLOSE", "days_arg": 200},
        ]}],
    }])

    from unittest.mock import MagicMock
    from screens import inception_view_by_date as ivd
    fake_viewer_cls = MagicMock()
    monkeypatch.setattr(ivd, "HistoricDataViewer", fake_viewer_cls)

    screen = InceptionViewByDateScreen(controller)
    screen._selected_date = as_of
    screen._on_view_clicked()
    _run_worker(qapp, screen)

    headers, rows = fake_viewer_cls.call_args.args[:2]
    idx = headers.index("200 Average")
    # last 200 closes out of 100..309 are 110..309 -> average 209.5
    assert rows[0][idx] == 209.5


# ── screens: HMV ─────────────────────────────────────────────────────────

def test_hmv_screen_current_range_reads_the_date_pickers(qapp, controller):
    from PySide6.QtCore import QDate
    from screens.inception_hmv import InceptionHmvScreen

    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(2025, 12, 31))
    assert screen._current_range() == (date(2025, 1, 1), date(2025, 12, 31))


def test_hmv_screen_rejects_from_after_to_without_computing(qapp, controller):
    from PySide6.QtCore import QDate
    from screens.inception_hmv import InceptionHmvScreen

    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2025, 12, 31))
    screen._to_date.setDate(QDate(2025, 1, 1))

    screen._on_load()
    assert screen._data == []
    assert "must be on or before" in screen._status_lbl.text()


def test_hmv_screen_shows_sync_prompt_when_nothing_synced(qapp, controller, bars_db):
    from screens.inception_hmv import InceptionHmvScreen

    screen = InceptionHmvScreen(controller)
    screen._on_load()
    assert "Sync" in screen._status_lbl.text()


def test_hmv_screen_displays_underlying_symbol_not_roll_series(qapp, controller, bars_db):
    from screens.inception_hmv import InceptionHmvScreen

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])
    screen = InceptionHmvScreen(controller)
    from PySide6.QtCore import QDate
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))

    screen._on_load()
    _run_worker(qapp, screen)
    assert screen._data[0][screen._headers.index("Symbol")] == "ABB"
    assert screen._data[0][screen._headers.index("CLOSE")] == 100


def test_hmv_screen_applies_active_strategies_locally(qapp, controller, monkeypatch, bars_db):
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_strategy_store
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Range", "active": True, "row_filter": [],
        "columns": [{
            "name": "Day Range",
            "formula": [{"type": "col", "value": "CLOSE"}, {"type": "op", "value": "-"}, {"type": "col", "value": "OPEN"}],
        }],
    }])

    screen._on_load()
    _run_worker(qapp, screen)
    assert "Day Range" in screen._headers
    assert screen._data[0][screen._headers.index("Day Range")] == 10.0


def test_hmv_screen_does_not_add_row_filter_streak_columns(qapp, controller, monkeypatch, bars_db):
    """services.strategy_engine.apply_strategies' "Days True"/"Since"
    streak columns (for a strategy with a row filter) are LMV-only —
    Inception has no day_history/historic-value support wired up, so this
    screen calls apply_strategies with include_streak_columns=False. A
    strategy WITH a row filter here must NOT gain those two extra columns."""
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_strategy_store
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Range", "active": True,
        "row_filter": [{"type": "col", "value": "CLOSE"}, {"type": "op", "value": ">"}, {"type": "num", "value": "0"}],
        "columns": [],
    }])

    screen._on_load()
    _run_worker(qapp, screen)
    assert not any("Days True" in h or "Since" in h for h in screen._headers)
    assert "Sector" in screen._headers   # see services.inception_sector
    assert screen._strat_btn.text() == "⚡  Strategies  1/1"


def test_hmv_screen_includes_formula_builder_columns(qapp, controller, bars_db):
    """MT/MB and friends (services.inception_formula_builder_columns) —
    merged into every row alongside Group A/B, computed from that same
    instrument's local bars. See test_view_by_date_includes_formula_
    builder_columns for View by Date's identical merge."""
    from screens.inception_hmv import InceptionHmvScreen
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))

    screen._on_load()
    _run_worker(qapp, screen)
    assert "MT" in screen._headers and "MB" in screen._headers
    assert "DT" in screen._headers and "DB" in screen._headers


def test_hmv_screen_resolves_avg_days_on_raw_field(qapp, controller, monkeypatch, bars_db):
    """Regression: a strategy column using AVG_DAYS on a raw OHLCV field
    (the reported "200 Average" -> AVG_DAYS(CLOSE, 200)) used to always
    evaluate to None here — see screens.inception_view_by_date.
    test_view_by_date_resolves_avg_days_on_raw_field's docstring for the
    two-part fix this guards."""
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_strategy_store
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1) + timedelta(days=i), 100 + i, 101 + i, 99 + i, 100 + i)
        for i in range(210)
    ])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "200 Average", "active": True, "row_filter": [],
        "columns": [{"name": "200 Average", "formula": [
            {"type": "func", "value": "AVG_DAYS(", "col_arg": "CLOSE", "days_arg": 200},
        ]}],
    }])

    as_of = date(2025, 1, 1) + timedelta(days=209)
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(as_of.year, as_of.month, as_of.day))
    screen._on_load()
    _run_worker(qapp, screen)

    idx = screen._headers.index("200 Average")
    assert screen._data[0][idx] == 209.5


def test_hmv_screen_resolves_value_before_change_on_formula_builder_column(qapp, controller, monkeypatch, bars_db):
    """The reported example: MT reads 400 for both August and July but was
    382 in June -> VALUE_BEFORE_CHANGE([MT], 6) resolves to 382 end to end
    through InceptionHmvScreen. See services.inception_value_before_change
    for the resolution logic itself."""
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_strategy_store
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1) + timedelta(days=i), 1, 1, 1, 1)
        for i in range(210)
    ])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "MT Change", "active": True, "row_filter": [],
        "columns": [{"name": "MT Before", "formula": [
            {"type": "func", "value": "VALUE_BEFORE_CHANGE(", "col_arg": "MT", "days_arg": 6},
        ]}],
    }])

    def fake_compute_for_bars(symbol, bar_slice):
        if not bar_slice:
            return {}
        return {"MT": 400 if bar_slice[-1]["trade_date"] >= date(2025, 6, 15) else 382}

    monkeypatch.setattr("services.inception_formula_builder_columns.compute_for_bars", fake_compute_for_bars)

    as_of = date(2025, 1, 1) + timedelta(days=209)
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(as_of.year, as_of.month, as_of.day))
    screen._on_load()
    _run_worker(qapp, screen)

    idx = screen._headers.index("MT Before")
    assert screen._data[0][idx] == 382


def test_hmv_screen_highlights_cells_changed_since_last_load(qapp, controller, monkeypatch, bars_db):
    """"Select a colour for each column" (LMV's value-change highlight,
    screens.live_viewer.HighlightColorManagerDialog) ported for HMV/View by
    Date as "changed since the last Load/View" (services.
    inception_change_highlight) — there's no live tick here to flash on."""
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_compute_service, inception_strategy_store
    from PySide6.QtCore import QDate
    from PySide6.QtGui import QColor

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [])
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    screen = InceptionHmvScreen(controller)
    screen._highlight_color = "#ff0000"
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))
    screen._on_load()
    _run_worker(qapp, screen)
    assert screen._changed_cells == set()   # first Load ever — nothing to compare against

    inception_compute_service.clear_cache()
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 150)])
    screen._on_load()
    _run_worker(qapp, screen)

    close_idx = screen._headers.index("CLOSE")
    assert (0, close_idx) in screen._changed_cells
    item = screen._table.item(0, close_idx)
    assert item.background().color() == QColor("#ff0000")


def test_hmv_screen_applies_saved_column_order_from_config_editor(qapp, controller, bars_db, tmp_path, monkeypatch):
    """Config Editor's "Inception HMV Column Order" tab (services.
    config_store.INCEPTION_HMV_COLUMN_ORDER) — same idea as LMV's own "Main
    Column Order" tab, an alternative to dragging one column at a time
    across a table this wide. Sector/Symbol still win the leftmost two
    spots regardless (see components.frozen_table_columns) — the saved
    order applies to everything after that."""
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))
    config_store.save_column_order(["CLOSE", "OPEN"], key=config_store.INCEPTION_HMV_COLUMN_ORDER)

    from screens.inception_hmv import InceptionHmvScreen
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))

    screen._on_load()
    _run_worker(qapp, screen)

    hdr = screen._table.horizontalHeader()
    sector_logical = screen._headers.index("Sector")
    symbol_logical = screen._headers.index("Symbol")
    close_logical = screen._headers.index("CLOSE")
    open_logical = screen._headers.index("OPEN")
    assert hdr.visualIndex(sector_logical) == 0
    assert hdr.visualIndex(symbol_logical) == 1
    assert hdr.visualIndex(close_logical) == 2
    assert hdr.visualIndex(open_logical) == 3


def test_hmv_strategy_picker_lets_multiple_strategies_be_selected_and_applied(qapp, controller, monkeypatch, bars_db):
    """Before the picker, HMV silently unioned every persisted-active
    strategy together (services.strategy_engine.apply_strategies) with no
    way to isolate one — a row filter on any single strategy looked broken
    whenever another active strategy had none. The picker (screens.
    live_viewer.StrategyPickerPopup) fixes both: pick exactly which
    strategies apply, Apply persists that choice and re-renders without
    another Load."""
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_strategy_store
    from PySide6.QtCore import QDate

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])
    screen = InceptionHmvScreen(controller)
    screen._from_date.setDate(QDate(2026, 1, 1))
    screen._to_date.setDate(QDate(2026, 8, 18))

    strategies = [{
        "id": "s1", "name": "Range", "active": True, "row_filter": [],
        "columns": [{
            "name": "Day Range",
            "formula": [{"type": "col", "value": "CLOSE"}, {"type": "op", "value": "-"}, {"type": "col", "value": "OPEN"}],
        }],
    }]
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: strategies)
    saved = []
    monkeypatch.setattr(inception_strategy_store, "save_strategy", lambda s: saved.append(dict(s)))

    screen._on_load()
    _run_worker(qapp, screen)
    assert "Day Range" in screen._headers

    # Toggle it off via the picker's apply path (no re-Load needed) — the
    # column should disappear from the re-derived display immediately.
    # NOT persisted server-side (see this screen's own _on_strategies_
    # applied docstring) — session-local only.
    screen._on_strategies_applied([dict(strategies[0], active=False)])
    assert saved == []
    assert "Day Range" not in screen._headers
    assert screen._strat_btn.text() == "⚡  Strategies  0/1"


def test_hmv_strategies_applied_never_deactivates_unchecked_ones_server_side(qapp, controller, monkeypatch, bars_db):
    """End-to-end regression for the "6 strategies disappear when a 7th is
    activated" bug — applying a subset via the picker must not silently
    persist active=False for OTHER strategies that were offered but not
    part of this Apply. See services.strategy_engine... no, see screens.
    live_viewer._on_strategies_applied's docstring for the full story;
    inception_hmv.InceptionHmvScreen copied the same (buggy, now fixed)
    pattern this session."""
    from screens.inception_hmv import InceptionHmvScreen
    from services import inception_strategy_store as store
    from api import inception_api

    saved_server = {}

    def fake_upsert(strategy_id, name, active, category, columns, row_filter):
        saved_server[strategy_id] = {
            "id": strategy_id, "name": name, "active": active,
            "category": category, "columns": columns, "row_filter": row_filter,
        }
        return saved_server[strategy_id]

    monkeypatch.setattr(inception_api, "upsert_strategy", fake_upsert)
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": list(saved_server.values())})

    for i in range(3):
        store.save_strategy({"id": f"s{i}", "name": f"S{i}", "active": True, "category": "Daily", "columns": [], "row_filter": []})

    screen = InceptionHmvScreen(controller)
    screen._strategies = store.load_all()

    # Apply s0/s1, leaving s2 offered-but-unchecked.
    updated = [dict(s, active=(s["id"] != "s2")) for s in screen._strategies]
    screen._on_strategies_applied(updated)

    assert saved_server["s2"]["active"] is True   # never touched server-side
    assert any(s["id"] == "s2" and s.get("active") for s in store.load_all())


# ── screens: Formula Stats ────────────────────────────────────────────────

def test_formula_stats_screen_current_range_reads_the_date_pickers(qapp, controller):
    from PySide6.QtCore import QDate
    from screens.inception_formula_stats import InceptionFormulaStatsScreen

    screen = InceptionFormulaStatsScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(2025, 12, 31))
    assert screen._current_range() == (date(2025, 1, 1), date(2025, 12, 31))


def test_formula_stats_screen_rejects_from_after_to_without_computing(qapp, controller, monkeypatch):
    from PySide6.QtCore import QDate
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Range", "active": True, "row_filter": [],
        "columns": [{"name": "C", "formula": [{"type": "col", "value": "CLOSE"}]}],
    }])
    screen = InceptionFormulaStatsScreen(controller)
    screen._from_date.setDate(QDate(2025, 12, 31))
    screen._to_date.setDate(QDate(2025, 1, 1))

    screen._on_compute()
    assert screen._worker is None
    assert "must be on or before" in screen._status_lbl.text()


def test_formula_stats_screen_shows_sync_prompt_when_nothing_synced(qapp, controller, bars_db, monkeypatch):
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Range", "active": True, "row_filter": [],
        "columns": [{"name": "C", "formula": [{"type": "col", "value": "CLOSE"}]}],
    }])
    screen = InceptionFormulaStatsScreen(controller)
    screen._on_compute()
    assert "Sync" in screen._status_lbl.text()


def test_formula_stats_screen_disables_compute_with_no_strategies(qapp, controller, monkeypatch):
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [])
    screen = InceptionFormulaStatsScreen(controller)
    assert screen._compute_btn.isEnabled() is False
    assert "No strategies" in screen._status_lbl.text()


def test_formula_stats_screen_reports_no_columns_for_empty_strategy(qapp, controller, monkeypatch):
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Empty", "active": True, "row_filter": [], "columns": [],
    }])
    screen = InceptionFormulaStatsScreen(controller)
    screen._on_compute()
    assert screen._worker is None
    assert "no formula columns" in screen._status_lbl.text()


def test_formula_stats_screen_computes_aggregates_over_the_range(qapp, controller, monkeypatch, bars_db):
    from PySide6.QtCore import QDate
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 105, 95, 102),
        _bar("ABB_I", date(2025, 1, 2), 103, 110, 100, 108),
        _bar("ABB_I", date(2025, 1, 3), 108, 112, 104, 109),
    ])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "CloseStat", "active": True, "row_filter": [],
        "columns": [{"name": "C", "formula": [{"type": "col", "value": "CLOSE"}], "fmt_rules": []}],
    }])

    screen = InceptionFormulaStatsScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(2025, 1, 3))
    screen._on_compute()
    _run_worker(qapp, screen)

    assert screen._table.rowCount() == 1
    assert screen._table.item(0, 0).text() == "ABB_I"
    assert screen._table.item(0, 1).text() == "ABB"
    headers = [screen._table.horizontalHeaderItem(c).text() for c in range(screen._table.columnCount())]
    assert "C (Min)" in headers and "C (Max)" in headers
    assert screen._table.item(0, headers.index("C (Min)")).text() == "102"
    assert screen._table.item(0, headers.index("C (Max)")).text() == "109"
    assert "3 day(s) of data" in screen._status_lbl.text()


def test_formula_stats_screen_resolves_sibling_column_reference(qapp, controller, monkeypatch, bars_db):
    """The exact fix from earlier this session (services.strategy_engine.
    expand_columns_for_stats), reused verbatim by this screen's worker —
    a column referencing another of the SAME strategy's own columns must
    resolve correctly here too, not just in LMV's Formula Stats screen."""
    from PySide6.QtCore import QDate
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    bars_db.upsert_bars([_bar("ABB_I", date(2025, 1, 1), 100, 105, 95, 102)])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "Chain", "active": True, "row_filter": [],
        "columns": [
            {"name": "Floor", "formula": [{"type": "col", "value": "LOW"}], "fmt_rules": []},
            {"name": "Trigger", "formula": [
                {"type": "col", "value": "Floor"}, {"type": "op", "value": "*"}, {"type": "num", "value": "1.01"},
            ], "fmt_rules": []},
        ],
    }])

    screen = InceptionFormulaStatsScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(2025, 1, 1))
    screen._on_compute()
    _run_worker(qapp, screen)

    headers = [screen._table.horizontalHeaderItem(c).text() for c in range(screen._table.columnCount())]
    assert screen._table.item(0, headers.index("Trigger (Min)")).text() == "95.95"


def test_formula_stats_screen_day_by_day_popup_shows_saved_daily_values(qapp, controller, monkeypatch, bars_db):
    from PySide6.QtCore import QDate
    from screens.inception_formula_stats import InceptionFormulaStatsScreen
    from services import inception_strategy_store

    bars_db.upsert_bars([
        _bar("ABB_I", date(2025, 1, 1), 100, 105, 95, 102),
        _bar("ABB_I", date(2025, 1, 2), 103, 110, 100, 108),
    ])
    monkeypatch.setattr(inception_strategy_store, "load_all", lambda: [{
        "id": "s1", "name": "CloseStat", "active": True, "row_filter": [],
        "columns": [{"name": "C", "formula": [{"type": "col", "value": "CLOSE"}], "fmt_rules": []}],
    }])

    screen = InceptionFormulaStatsScreen(controller)
    screen._from_date.setDate(QDate(2025, 1, 1))
    screen._to_date.setDate(QDate(2025, 1, 2))
    screen._on_compute()
    _run_worker(qapp, screen)

    daily = screen._computed["ABB_I"]["columns"]["C"]["daily"]
    assert sorted(daily) == [("2025-01-01", 102), ("2025-01-02", 108)]


# ── screens: strategy builder ────────────────────────────────────────────

def test_strategy_builder_screen_constructs_with_empty_data(qapp, controller, monkeypatch):
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen
    from services import inception_strategy_store

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()
    assert screen._strategies == []
    assert screen._active_editor is None
    assert inception_strategy_store.all_categories() == ["Daily", "Weekly", "Monthly", "Common"]


def test_strategy_builder_fields_come_from_local_catalogue_no_network(qapp, controller, monkeypatch):
    """Confirms the Fields list no longer needs GET /inception/columns —
    Group A/B's catalogue moved entirely client-side (services.
    inception_columns)."""
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()
    assert "OPEN" in screen._fields
    assert "52WH" in screen._fields
    assert "DAY UF GUP 1" in screen._fields


def test_strategy_builder_fields_include_formula_builder_columns(qapp, controller, monkeypatch):
    """MT/MB and friends (services.formula_engine.FORMULA_CODES, the same
    ~56 codes services.inception_formula_builder_columns.compute_for_bars
    produces for a row — see screens.inception_view_by_date/inception_hmv's
    identical merge) must be selectable Fields here too, or a strategy could
    never actually reference one even after View by Date/HMV started
    surfacing it in a real row."""
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen
    from services import formula_engine

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()
    assert "MT" in screen._fields and "MB" in screen._fields
    assert "DT" in screen._fields and "DB" in screen._fields
    assert len(screen._fields) == len(set(screen._fields))   # no duplicates
    assert set(formula_engine.FORMULA_CODES) <= set(screen._fields)


def test_strategy_builder_expression_editor_offers_value_before_change(qapp, controller):
    """VALUE_BEFORE_CHANGE (services.inception_value_before_change) is
    Inception-only — appended to just this editor's "Functions" section via
    ExpressionEditorDialog's extra_functions param, not to screens.
    formula_editor.FUNCTION_CATALOGUE itself (which LMV's own Strategy
    Builder also draws from, and has no engine support to resolve this)."""
    from screens.inception_strategy_builder import INCEPTION_EXTRA_FUNCTIONS
    from screens.formula_editor import ExpressionEditorDialog, FUNCTION_CATALOGUE

    dlg = ExpressionEditorDialog(
        [], ["MT", "CLOSE"], [], {"MT": 1.0, "CLOSE": 1.0},
        all_lmv_data=[{"MT": 1.0, "CLOSE": 1.0}], theme=None, mode="value",
        real_lmv_headers=["MT", "CLOSE"], sections=["Functions"],
        extra_functions=INCEPTION_EXTRA_FUNCTIONS,
    )
    names = [c["name"] for c in dlg._catalogue_for_section("Functions")]
    assert "VALUE_BEFORE_CHANGE" in names
    # Not leaked into the shared catalogue every LMV caller also draws from.
    assert "VALUE_BEFORE_CHANGE" not in [c["name"] for c in FUNCTION_CATALOGUE]


def test_strategy_builder_sample_data_placeholder_when_nothing_synced(qapp, controller, monkeypatch, bars_db):
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._start_sample_load()
    assert screen._sample_rows == []
    assert screen._sample_worker is None
    assert "synced" in screen._sample_status_lbl.text()


def test_strategy_builder_sample_data_loads_real_rows_in_background(qapp, controller, monkeypatch, bars_db):
    """See this module's "Real sample data" docstring section — a background
    snapshot load feeds real per-instrument rows into the formula editor
    instead of every field reading the all-1.0 dummy."""
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})
    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 90, 105, 85, 100)])

    screen = InceptionStrategyBuilderScreen(controller)
    screen._start_sample_load()
    assert screen._sample_worker is not None
    assert screen._sample_progress.isHidden() is False
    assert screen._sample_worker.wait(5000)
    qapp.processEvents()

    assert screen._sample_rows
    assert screen._sample_rows[0].get("CLOSE") == 100
    assert screen._sample_progress.isHidden() is True
    assert "2026-08-18" in screen._sample_status_lbl.text()


def test_open_expression_editor_uses_real_sample_row_when_given(qapp, controller, monkeypatch):
    """_open_expression_editor should feed a real row (not the all-1.0
    dummy) once sample data has loaded."""
    from screens import inception_strategy_builder as isb
    from PySide6.QtWidgets import QDialog

    sample_rows = [{"OPEN": 90.0, "CLOSE": 100.0}, {"OPEN": 190.0, "CLOSE": 200.0}]
    captured = {}

    class _FakeDlg:
        def __init__(self, *args, **kwargs):
            captured["row_arg"] = args[3]
            captured.update(kwargs)

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(isb, "ExpressionEditorDialog", _FakeDlg)

    isb._open_expression_editor([], ["OPEN", "CLOSE"], None, "value", sample_rows=sample_rows)
    assert captured["row_arg"] in sample_rows
    assert captured["all_lmv_data"] == sample_rows


def test_open_expression_editor_falls_back_to_dummy_row_without_sample_data(qapp, controller, monkeypatch):
    from screens import inception_strategy_builder as isb
    from PySide6.QtWidgets import QDialog

    captured = {}

    class _FakeDlg:
        def __init__(self, *args, **kwargs):
            captured["row_arg"] = args[3]

        def exec(self):
            return QDialog.DialogCode.Rejected

    monkeypatch.setattr(isb, "ExpressionEditorDialog", _FakeDlg)

    isb._open_expression_editor([], ["OPEN", "CLOSE"], None, "value", sample_rows=None)
    assert captured["row_arg"] == {"OPEN": 1.0, "CLOSE": 1.0}


def test_strategy_builder_new_strategy_opens_editor(qapp, controller, monkeypatch):
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": []})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()
    screen._new_strategy()

    assert screen._active_editor is not None
    assert screen._active_editor._strategy["name"] == "New Strategy"
    assert screen._active_editor._strategy["columns"] == []
    assert "OPEN" in screen._fields


def test_strategy_editor_field_universe_includes_own_columns(qapp, controller):
    from screens.inception_strategy_builder import _InceptionStrategyEditor

    strategy = {
        "id": "s1", "name": "Test", "active": True, "category": "Daily",
        "columns": [{"name": "Adjusted", "formula": [], "fmt_rules": []}], "row_filter": [],
    }
    editor = _InceptionStrategyEditor(strategy, ["OPEN", "CLOSE"], theme=controller.theme)
    assert editor._field_names() == ["OPEN", "CLOSE", "Adjusted"]


def test_column_editor_always_shows_editable_formula(qapp, controller):
    from screens.inception_strategy_builder import _InceptionColumnEditorDialog

    col = {"name": "MyColumn", "formula": [{"type": "col", "value": "52WH"}, {"type": "op", "value": "+"}, {"type": "num", "value": "1"}], "fmt_rules": []}
    dlg = _InceptionColumnEditorDialog(col, ["52WH"], theme=controller.theme)
    assert hasattr(dlg, "_formula_preview")


def test_strategy_editor_save_emits_strategy_with_name_and_category(qapp, controller):
    from screens.inception_strategy_builder import _InceptionStrategyEditor

    strategy = {
        "id": "s1", "name": "Old Name", "active": True, "category": "Daily",
        "columns": [], "row_filter": [],
    }
    editor = _InceptionStrategyEditor(strategy, ["OPEN"], theme=controller.theme)
    editor._name_edit.setText("Renamed")

    captured = {}
    editor.saved.connect(lambda s: captured.update(s))
    editor._save()

    assert captured["name"] == "Renamed"
    assert captured["category"] == "Daily"


def test_strategy_builder_toggle_active_reverts_on_api_failure(qapp, controller, monkeypatch):
    from screens.inception_strategy_builder import InceptionStrategyBuilderScreen
    from api.exceptions import ApiError

    monkeypatch.setattr(inception_api, "list_variables", lambda: {"variables": []})
    monkeypatch.setattr(inception_api, "list_strategies", lambda: {"strategies": [
        {"id": "s1", "name": "S1", "active": True, "category": "Daily", "columns": [], "row_filter": []},
    ]})

    screen = InceptionStrategyBuilderScreen(controller)
    screen._reload_all()

    def _boom(*a, **k):
        raise ApiError("boom", "server_error", 500)
    monkeypatch.setattr("services.inception_strategy_store.save_strategy", _boom)

    import screens.inception_strategy_builder as isb
    monkeypatch.setattr(isb, "show_api_error", lambda *a, **k: None)

    screen._on_toggle("s1", False)
    assert screen._strategies[0]["active"] is True   # reverted


# ── screens: settings ────────────────────────────────────────────────────

def test_settings_screen_loads_defaults_when_nothing_saved(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen
    from services.inception_formula_engine import DEFAULT_FIFO_CAP, DEFAULT_GAP_THRESHOLD_PCT, DEFAULT_WEEK_WINDOW_DAYS

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    screen = InceptionSettingsScreen(controller)
    assert screen._threshold_spin.value() == pytest.approx(DEFAULT_GAP_THRESHOLD_PCT)
    assert screen._window_spin.value() == DEFAULT_WEEK_WINDOW_DAYS
    assert screen._fifo_spin.value() == DEFAULT_FIFO_CAP


def test_settings_screen_save_params_persists_via_config_store(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    captured = {}
    monkeypatch.setattr("services.config_store.save_json", lambda key, value: captured.update(key=key, value=value))

    screen = InceptionSettingsScreen(controller)
    screen._threshold_spin.setValue(1.5)
    screen._window_spin.setValue(300)
    screen._fifo_spin.setValue(5)
    screen._save_params()

    assert captured["value"] == {"gap_threshold_pct": 1.5, "week_window_days": 300, "fifo_cap": 5}


def test_settings_screen_sync_progress_slots_update_label(qapp, controller, monkeypatch, bars_db):
    """Drives the worker's slot methods directly rather than spinning up a
    real QThread — same convention screens/live_viewer.py's tests use for
    LiveDataReader (see components/update_dialog.py's docstring)."""
    from screens.inception_settings import InceptionSettingsScreen

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    screen = InceptionSettingsScreen(controller)

    screen._on_sync_progress("Syncing 2025-01-01 .. 2025-12-31…", 0.5)
    assert "50%" in screen._sync_progress_lbl.text()
    assert screen._sync_progress_bar.value() == 50

    screen._on_sync_succeeded(1234)
    assert "1,234" in screen._sync_progress_lbl.text()

    screen._on_sync_failed("network down")
    assert "network down" in screen._sync_progress_lbl.text()


def test_settings_screen_progress_bar_shown_during_sync_hidden_after(qapp, controller, monkeypatch, bars_db):
    """_start_sync's visibility/button-disable effects happen synchronously
    (before the worker thread is even started); the fake sync function below
    just avoids a real background thread making real network calls in a
    unit test."""
    from screens.inception_settings import InceptionSettingsScreen
    from services import inception_sync_service

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    monkeypatch.setattr(inception_sync_service, "incremental_sync", lambda progress_cb=None, today=None: 0)
    # isHidden() (not isVisible()) — the screen is never actually .show()n in
    # this test, so isVisible() would read False regardless of our own
    # setVisible() calls (it also depends on the whole ancestor chain being
    # shown); isHidden() reflects this widget's own explicit shown/hidden
    # state directly.
    screen = InceptionSettingsScreen(controller)
    assert screen._sync_progress_bar.isHidden() is True

    screen._start_sync(full=False)
    assert screen._sync_progress_bar.isHidden() is False
    assert screen._sync_now_btn.isEnabled() is False

    assert screen._worker.wait(2000)   # worker thread finished
    qapp.processEvents()               # deliver its queued `succeeded` signal

    assert screen._sync_progress_bar.isHidden() is True
    assert screen._sync_now_btn.isEnabled() is True


def test_settings_screen_progress_bar_indeterminate_when_fraction_is_none(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    screen = InceptionSettingsScreen(controller)

    screen._on_sync_progress("Syncing 2026-08-19 .. 2026-08-20…", None)
    assert screen._sync_progress_bar.minimum() == 0 and screen._sync_progress_bar.maximum() == 0

    screen._on_sync_progress("Syncing 2000-01-01 .. 2000-12-31…", 0.25)
    assert screen._sync_progress_bar.maximum() == 100
    assert screen._sync_progress_bar.value() == 25


def test_settings_screen_sync_status_reflects_local_store(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    screen = InceptionSettingsScreen(controller)

    screen._refresh_sync_status()
    assert screen._sync_headline_lbl.text() == "Not synced"
    assert "No data synced" in screen._sync_status_lbl.text()

    bars_db.upsert_bars([_bar("ABB_I", date(2026, 8, 18), 100, 101, 99, 100)])
    screen._refresh_sync_status()
    assert screen._sync_headline_lbl.text() == "Synced"
    assert "2026-08-18" in screen._sync_status_lbl.text()


def test_settings_screen_buttons_explain_sync_now_vs_full_resync(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    screen = InceptionSettingsScreen(controller)

    assert "since your last sync" in screen._sync_now_btn.toolTip()
    assert "ENTIRE historical dataset" in screen._resync_btn.toolTip()


# ── screens: settings — "Fetch from Equal Solution" ──────────────────────

def test_settings_screen_vendor_fields_are_readonly_and_prefilled(qapp, controller, monkeypatch, bars_db):
    """Username/Password/Exchange are all prefilled with the real reference
    values, editable-looking plain text (no masking) — see screens.
    inception_settings' module docstring: these ARE sent as typed on every
    click, so there's no "real secret" being hidden here to begin with."""
    from screens.inception_settings import InceptionSettingsScreen

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    screen = InceptionSettingsScreen(controller)

    assert screen._vendor_username_field.text() == "fukulens@gmail.com"
    assert screen._vendor_username_field.isReadOnly() is True
    assert screen._vendor_exchange_field.text() == "NFOFUT"
    assert screen._vendor_exchange_field.isReadOnly() is True
    assert screen._vendor_password_field.text() == "12345678"
    assert screen._vendor_password_field.isReadOnly() is True
    from PySide6.QtWidgets import QLineEdit
    assert screen._vendor_password_field.echoMode() == QLineEdit.EchoMode.Normal


def test_settings_screen_vendor_sync_sends_field_values(qapp, controller, monkeypatch, bars_db):
    """The worker calls api.inception_api.sync_vendor_data() with exactly
    what's in the Username/Password/Exchange fields — confirms the UI
    fields actually feed the request now."""
    from screens.inception_settings import InceptionSettingsScreen
    from api import inception_api
    from services import inception_sync_service

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    # A successful vendor fetch auto-follows with the local "Sync Now" pull
    # (explicitly requested — see _on_vendor_sync_succeeded) — stub it out
    # so this test doesn't make a real network call via a real background
    # QThread.
    monkeypatch.setattr(inception_sync_service, "incremental_sync", lambda progress_cb=None, today=None: 0)
    captured = {}
    monkeypatch.setattr(
        inception_api, "sync_vendor_data",
        lambda email, password, exchange: captured.update(email=email, password=password, exchange=exchange) or {
            "status": "ok", "exchange": "NFOFUT", "date_from": "2026-08-18", "date_to": "2026-08-25",
            "last_available_before": "2026-08-17", "last_available_after": "2026-08-24",
            "instruments_added": 0, "bars_written": 10,
        },
    )

    screen = InceptionSettingsScreen(controller)
    screen._start_vendor_sync()
    assert screen._vendor_worker.wait(2000)
    qapp.processEvents()
    assert screen._worker.wait(2000)   # the auto-triggered local sync worker
    qapp.processEvents()

    assert captured == {"email": "fukulens@gmail.com", "password": "12345678", "exchange": "NFOFUT"}
    assert "10 bar row(s) written" in screen._vendor_status_lbl.text()
    assert "Pulling this into this device's local cache" in screen._vendor_status_lbl.text()


def test_settings_screen_vendor_sync_reports_already_up_to_date(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen
    from services import inception_sync_service

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    monkeypatch.setattr(inception_sync_service, "incremental_sync", lambda progress_cb=None, today=None: 0)
    screen = InceptionSettingsScreen(controller)

    screen._on_vendor_sync_succeeded({
        "status": "already_up_to_date", "exchange": "NFOFUT",
        "last_available_after": "2026-08-24",
    })
    assert screen._worker.wait(2000)   # the auto-triggered local sync worker
    qapp.processEvents()

    assert "Already up to date" in screen._vendor_status_lbl.text()
    assert "2026-08-24" in screen._vendor_status_lbl.text()


def test_settings_screen_vendor_sync_treats_zero_bars_written_as_up_to_date(qapp, controller, monkeypatch, bars_db):
    """A real vendor call that succeeded but found nothing new (e.g. the
    vendor's EOD batch for today hasn't run yet — see app.services.
    eqldata_client.fetch_eod_range_rows's 404-means-"no data yet" handling
    on the backend) must read the same calm "up to date" way as
    already_up_to_date, not the "0 bar row(s) written" phrasing."""
    from screens.inception_settings import InceptionSettingsScreen
    from services import inception_sync_service

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    monkeypatch.setattr(inception_sync_service, "incremental_sync", lambda progress_cb=None, today=None: 0)
    screen = InceptionSettingsScreen(controller)

    screen._on_vendor_sync_succeeded({
        "status": "ok", "exchange": "NFOFUT", "date_from": "2026-08-25", "date_to": "2026-08-25",
        "last_available_before": "2026-08-24", "last_available_after": "2026-08-24",
        "instruments_added": 0, "bars_written": 0,
    })
    assert screen._worker.wait(2000)
    qapp.processEvents()

    assert "Already up to date" in screen._vendor_status_lbl.text()
    assert "2026-08-24" in screen._vendor_status_lbl.text()
    assert "0 bar row(s)" not in screen._vendor_status_lbl.text()


def test_settings_screen_vendor_sync_shows_server_error_message(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen
    from api import inception_api
    from api.exceptions import ApiError

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    monkeypatch.setattr(
        inception_api, "sync_vendor_data",
        lambda email, password, exchange: (_ for _ in ()).throw(
            ApiError("Equal Solution rate/quota limit hit", "vendor_api_failed", 502)
        ),
    )

    screen = InceptionSettingsScreen(controller)
    screen._start_vendor_sync()
    assert screen._vendor_worker.wait(2000)
    qapp.processEvents()

    assert "rate/quota limit hit" in screen._vendor_status_lbl.text()
    assert screen._vendor_fetch_btn.isEnabled() is True


def test_settings_screen_vendor_progress_bar_shown_during_fetch_hidden_after(qapp, controller, monkeypatch, bars_db):
    """isHidden(), not isVisible() — same rationale as the Local Data Sync
    progress-bar test above (this screen is never .show()n in tests)."""
    from screens.inception_settings import InceptionSettingsScreen
    from api import inception_api
    from services import inception_sync_service

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    monkeypatch.setattr(inception_sync_service, "incremental_sync", lambda progress_cb=None, today=None: 0)
    monkeypatch.setattr(inception_api, "sync_vendor_data", lambda email, password, exchange: {"status": "already_up_to_date"})

    screen = InceptionSettingsScreen(controller)
    assert screen._vendor_progress_bar.isHidden() is True

    screen._start_vendor_sync()
    assert screen._vendor_progress_bar.isHidden() is False
    assert screen._vendor_fetch_btn.isEnabled() is False

    assert screen._vendor_worker.wait(2000)
    qapp.processEvents()
    assert screen._worker.wait(2000)   # the auto-triggered local sync worker
    qapp.processEvents()

    assert screen._vendor_progress_bar.isHidden() is True
    assert screen._vendor_fetch_btn.isEnabled() is True


def test_settings_screen_vendor_sync_skipped_while_already_running(qapp, controller, monkeypatch, bars_db):
    from screens.inception_settings import InceptionSettingsScreen
    from api import inception_api
    from services import inception_sync_service
    import threading

    monkeypatch.setattr("services.config_store.load_json", lambda key, default: default)
    monkeypatch.setattr(inception_sync_service, "incremental_sync", lambda progress_cb=None, today=None: 0)
    release = threading.Event()
    calls = []

    def _slow_sync(email, password, exchange):
        calls.append(1)
        release.wait(2)
        return {"status": "already_up_to_date"}

    monkeypatch.setattr(inception_api, "sync_vendor_data", _slow_sync)

    screen = InceptionSettingsScreen(controller)
    screen._start_vendor_sync()
    first_worker = screen._vendor_worker
    screen._start_vendor_sync()   # ignored — first is still running

    release.set()
    assert first_worker.wait(2000)
    qapp.processEvents()
    assert screen._worker.wait(2000)   # the auto-triggered local sync worker
    qapp.processEvents()

    assert len(calls) == 1
    assert screen._vendor_worker is first_worker
