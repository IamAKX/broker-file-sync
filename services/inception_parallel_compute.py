"""Parallelizes services.inception_compute_service's per-instrument Group
A/B walk across OS processes.

── Why a background QThread alone doesn't fix this (issue #25) ─────────────
services.inception_compute_service's own "Performance" docstring already
flags the cost: computing one instrument's full Group A/B history is
genuinely expensive pure-Python work (~0.3-0.5s x ~213 canonical
instruments — tens of seconds to ~2 minutes cold). That walk already runs
on a background QThread (screens.inception_hmv._HmvLoadWorker, screens.
inception_view_by_date._SnapshotLoadWorker, screens.
inception_strategy_builder's own sample-data loader), which keeps the
network/IO side of things off the GUI thread just fine — but Group A/B
itself is pure CPU-bound Python, not I/O, and Python's GIL serializes
bytecode execution across every THREAD in one process. A busy background
thread doing tight CPU-bound work still starves the GUI thread of actual
CPU time, so the window can go "Not Responding" — frozen mid-render, with
whatever was already drawn just sitting there — even though the work is
nominally "off the GUI thread". A separate OS PROCESS has its own GIL, so
the main process (GUI thread included) stays fully responsive the entire
time worker processes are crunching independently.

── Windows / PyInstaller — read before touching this ────────────────────
multiprocessing.freeze_support() MUST be the very first call inside
main.py's `if __name__ == "__main__":` guard, before anything else runs.
Windows has no fork(): every worker process is a fresh interpreter that
re-executes the frozen executable from the top. freeze_support() is what
lets the multiprocessing bootstrap protocol detect "this particular launch
is actually a worker, not a real app start" and return immediately,
before main() itself would ever run — without it, a frozen build spawns a
full second copy of the entire app (tray icon, single-instance guard, the
works) per worker, repeatedly. This module cannot enforce that placement
from here; it's a hard requirement on the process's own entry point, and
it's already in place — see main.py.

── Design ────────────────────────────────────────────────────────────────
compute_rows_parallel() takes already-fetched bars (this module never
touches services.inception_bars_store's SQLite connection itself — sqlite3
connections aren't spawn-safe to hand to a worker, and re-opening one per
worker per call is unnecessary complexity when the caller already has the
bars in hand) plus a plain settings dict — both cheap to pickle across the
process boundary — and _compute_row_worker is a pure function of exactly
those two inputs: no shared state, no I/O, safe to run in any process.

Falls back to sequential, in-process computation for a small work list
(_MIN_ITEMS_TO_PARALLELIZE) or if the pool fails outright — spinning up a
process pool has real fixed overhead (spawn + full module re-import per
worker) that isn't worth paying for a handful of instruments, and if
process-based parallelism doesn't work for some reason in a given install
(e.g. something about that machine's Python/OS blocking process spawn),
this must degrade to "slow like before", never "hangs forever" or
"crashes". Errors are never silently swallowed with no trace: see
services.error_logging.
"""
import os
from concurrent.futures import ProcessPoolExecutor, as_completed

# Below this, ProcessPoolExecutor's own startup cost (spawning N worker
# processes, each re-importing this module and its own dependencies) isn't
# worth it — a handful of instruments computes faster sequentially,
# in-process, than round-tripping through a pool at all. Chosen well above
# the row counts (1-2 instruments) this module's own test suite and
# services.inception_compute_service's existing unit tests use, so those
# keep exercising the plain sequential path unchanged.
_MIN_ITEMS_TO_PARALLELIZE = 12


def _compute_row_worker(item: tuple) -> tuple:
    """item: (symbol, bars, settings) — see compute_rows_parallel. Runs in
    a worker process: imports its own copy of inception_compute_service
    fresh (spawn semantics), so this never touches whatever state (row
    cache included) exists in the calling process. Returns (symbol,
    values)."""
    from services.inception_compute_service import _compute_row
    symbol, bars, settings = item
    return symbol, _compute_row(bars, settings)


def _compute_sequential(work_items: list[tuple], progress_cb=None) -> dict[str, dict]:
    from services.inception_compute_service import _compute_row
    total = len(work_items)
    results: dict[str, dict] = {}
    for symbol, bars, settings in work_items:
        results[symbol] = _compute_row(bars, settings)
        if progress_cb:
            progress_cb(len(results), total)
    return results


def _compute_via_pool(work_items: list[tuple], progress_cb=None, max_workers: int | None = None) -> dict[str, dict]:
    total = len(work_items)
    results: dict[str, dict] = {}
    with ProcessPoolExecutor(max_workers=max_workers) as pool:
        futures = [pool.submit(_compute_row_worker, item) for item in work_items]
        # as_completed, not the submission order — results arrive as each
        # worker finishes, not necessarily in the order submitted. The
        # caller (services.inception_compute_service) reassembles its own
        # output in a stable, deterministic order afterward; progress_cb
        # here only reports COUNT (done, total), which is order-independent.
        for future in as_completed(futures):
            symbol, values = future.result()
            results[symbol] = values
            if progress_cb:
                progress_cb(len(results), total)
    return results


def compute_rows_parallel(work_items: list[tuple[str, list, dict]], progress_cb=None,
                          max_workers: int | None = None) -> dict[str, dict]:
    """work_items: [(symbol, bars, settings), ...] — bars already fetched
    by the caller (services.inception_compute_service). Returns
    {symbol: values}, one entry per work_item, in no particular order
    (the caller reassembles its own row order). progress_cb(done, total),
    when given, is called once per instrument as its result becomes
    available.

    max_workers defaults to os.cpu_count() (ProcessPoolExecutor's own
    default) — exposed as a param mainly so tests can force a small,
    deterministic pool without depending on the host machine's core count.
    """
    if not work_items:
        return {}
    if len(work_items) < _MIN_ITEMS_TO_PARALLELIZE:
        return _compute_sequential(work_items, progress_cb)
    try:
        return _compute_via_pool(work_items, progress_cb, max_workers)
    except Exception:
        # Never let a process-pool failure (spawn blocked by this specific
        # machine's environment, a pickling surprise, ...) hang or crash
        # the load — degrade to "slow like before" instead. See this
        # module's own docstring.
        from services.error_logging import error_logger
        error_logger.exception(
            f"Inception parallel compute failed for {len(work_items)} instruments, "
            "falling back to sequential"
        )
        return _compute_sequential(work_items, progress_cb)
