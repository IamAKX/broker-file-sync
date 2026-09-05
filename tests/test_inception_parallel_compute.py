"""Tests for services/inception_parallel_compute.py — see that module's
own docstring (issue #25) for why Inception's Group A/B walk needed real
OS-process parallelism, not just a background QThread, to stop freezing
the GUI thread on a cold load."""
from datetime import date

from services import inception_parallel_compute as parallel
from services.inception_formula_engine import (
    DEFAULT_FIFO_CAP, DEFAULT_GAP_THRESHOLD_PCT, DEFAULT_WEEK_WINDOW_DAYS,
)


def _bars(symbol: str, n_days: int, start=date(2026, 1, 1)):
    from datetime import timedelta
    out = []
    for i in range(n_days):
        d = start + timedelta(days=i)
        base = 100.0 + i
        out.append({
            "trade_date": d, "open": base, "high": base + 5, "low": base - 5,
            "close": base + 1, "volume": 1000, "open_interest": 500,
        })
    return out


def _settings():
    return {
        "gap_threshold_pct": DEFAULT_GAP_THRESHOLD_PCT,
        "week_window_days": DEFAULT_WEEK_WINDOW_DAYS,
        "fifo_cap": DEFAULT_FIFO_CAP,
    }


# ── _compute_row_worker: correctness in isolation ────────────────────────

def test_compute_row_worker_matches_direct_compute_row():
    from services.inception_compute_service import _compute_row
    bars = _bars("ABB_I", 10)
    settings = _settings()

    direct = _compute_row(bars, settings)
    symbol, via_worker = parallel._compute_row_worker(("ABB_I", bars, settings))

    assert symbol == "ABB_I"
    assert via_worker == direct


# ── compute_rows_parallel: threshold routing ─────────────────────────────

def test_below_threshold_never_touches_the_process_pool(monkeypatch):
    """A small work list must go through the cheap sequential path — a
    process pool's own startup cost isn't worth paying for a handful of
    instruments."""
    def _boom(*a, **k):
        raise AssertionError("ProcessPoolExecutor should not be used below the threshold")
    monkeypatch.setattr(parallel, "ProcessPoolExecutor", _boom)

    work_items = [(f"SYM{i}_I", _bars(f"SYM{i}", 5), _settings())
                  for i in range(parallel._MIN_ITEMS_TO_PARALLELIZE - 1)]
    results = parallel.compute_rows_parallel(work_items)
    assert set(results.keys()) == {item[0] for item in work_items}


def test_empty_work_items_returns_empty_dict():
    assert parallel.compute_rows_parallel([]) == {}


def test_progress_cb_called_once_per_item_below_threshold():
    work_items = [(f"SYM{i}_I", _bars(f"SYM{i}", 5), _settings()) for i in range(3)]
    ticks = []
    parallel.compute_rows_parallel(work_items, progress_cb=lambda d, t: ticks.append((d, t)))
    assert ticks == [(1, 3), (2, 3), (3, 3)]


# ── compute_rows_parallel: the real process pool ─────────────────────────
# Genuinely spawns worker processes (macOS/Windows both default to 'spawn',
# the only method Windows has — this exercises the SAME bootstrap path a
# real frozen build's workers use, see main.py's freeze_support() call and
# this module's own docstring). Slower than everything else in this file;
# worth it for real confidence rather than mocking the pool away entirely.

def test_pool_path_produces_correct_results_above_threshold(monkeypatch):
    monkeypatch.setattr(parallel, "_MIN_ITEMS_TO_PARALLELIZE", 2)
    from services.inception_compute_service import _compute_row

    work_items = [(f"SYM{i}_I", _bars(f"SYM{i}", 8, start=date(2026, 1, i + 1)), _settings())
                  for i in range(4)]
    expected = {symbol: _compute_row(bars, settings) for symbol, bars, settings in work_items}

    results = parallel.compute_rows_parallel(work_items, max_workers=2)

    assert results == expected


def test_pool_path_progress_cb_reaches_full_count(monkeypatch):
    monkeypatch.setattr(parallel, "_MIN_ITEMS_TO_PARALLELIZE", 2)
    work_items = [(f"SYM{i}_I", _bars(f"SYM{i}", 6), _settings()) for i in range(4)]

    ticks = []
    parallel.compute_rows_parallel(work_items, progress_cb=lambda d, t: ticks.append((d, t)), max_workers=2)

    # Completion order across processes isn't guaranteed — only the final
    # tally and a monotonically increasing "done" count are.
    assert ticks[-1] == (4, 4)
    assert [d for d, _ in ticks] == sorted(d for d, _ in ticks)
    assert all(t == 4 for _, t in ticks)


# ── compute_rows_parallel: falls back, never hangs or crashes ────────────

def test_pool_failure_falls_back_to_sequential_and_still_returns_correct_results(monkeypatch):
    monkeypatch.setattr(parallel, "_MIN_ITEMS_TO_PARALLELIZE", 2)

    def _boom(*a, **k):
        raise RuntimeError("pool could not start in this environment")
    monkeypatch.setattr(parallel, "_compute_via_pool", _boom)

    logged = []
    from services import error_logging
    monkeypatch.setattr(error_logging.error_logger, "exception", lambda msg: logged.append(msg))

    from services.inception_compute_service import _compute_row
    work_items = [(f"SYM{i}_I", _bars(f"SYM{i}", 6), _settings()) for i in range(4)]
    expected = {symbol: _compute_row(bars, settings) for symbol, bars, settings in work_items}

    results = parallel.compute_rows_parallel(work_items)

    assert results == expected
    assert len(logged) == 1
