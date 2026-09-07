"""_LiveDataWorker.refresh_opening_range is a best-effort, once-a-day fetch
that runs on the SAME worker thread as do_read. When the server is
unreachable, the old code let it block that thread for the client's full
default HTTP timeout on every 60s _or_timer tick — so LMV live updates
stalled in visible ~15s bursts and the window read as "not responding" on
GET /opening-range/snapshot.

The fetch now (a) uses a short timeout and (b) backs off exponentially after
each failure so a down server costs at most one short block every few
minutes, not one every minute.
"""

import sys

import pytest
from PySide6.QtWidgets import QApplication

from screens.live_viewer import _LiveDataWorker
from api.exceptions import NetworkError


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _worker():
    return _LiveDataWorker(reader=None, sector_map={}, name_to_symbol={})


def test_or_fetch_uses_a_short_timeout(qapp, monkeypatch):
    from api import opening_range_api

    seen = {}

    def fake_get_snapshot(trade_date, timeout=None):
        seen["timeout"] = timeout
        return {"stocks": []}

    monkeypatch.setattr(opening_range_api, "get_snapshot", fake_get_snapshot)

    w = _worker()
    w.refresh_opening_range()

    assert seen["timeout"] == _LiveDataWorker._OR_TIMEOUT_S
    assert seen["timeout"] <= 5  # never the client's full default


def test_or_fetch_backs_off_after_failures_and_recovers(qapp, monkeypatch):
    from api import opening_range_api

    calls = []

    def failing(trade_date, timeout=None):
        calls.append(1)
        raise NetworkError("Could not reach server: read timeout")

    monkeypatch.setattr(opening_range_api, "get_snapshot", failing)

    w = _worker()

    # 1st tick: actually hits the network, fails -> schedules a back-off.
    w.refresh_opening_range()
    assert len(calls) == 1
    assert w._or_skip_ticks > 0

    # Next few ticks are skipped entirely (no network call) until the
    # back-off counter drains.
    skipped_for = w._or_skip_ticks
    for _ in range(skipped_for):
        w.refresh_opening_range()
    assert len(calls) == 1  # still just the one real attempt

    # Back-off drained -> tries again. Streak grows -> longer back-off.
    w.refresh_opening_range()
    assert len(calls) == 2
    assert w._or_skip_ticks >= skipped_for

    # Server recovers: a success clears the streak and the skip counter.
    monkeypatch.setattr(
        opening_range_api, "get_snapshot",
        lambda trade_date, timeout=None: {"stocks": [{"symbol": "X", "high": 1, "low": 0}]},
    )
    w._or_skip_ticks = 0
    w.refresh_opening_range()
    assert w._or_fail_streak == 0
    assert w._or_skip_ticks == 0
    assert w._opening_range_map == {"X": (1, 0)}


def test_or_backoff_is_capped(qapp, monkeypatch):
    from api import opening_range_api

    monkeypatch.setattr(
        opening_range_api, "get_snapshot",
        lambda trade_date, timeout=None: (_ for _ in ()).throw(NetworkError("down")),
    )
    w = _worker()
    for _ in range(50):
        w._or_skip_ticks = 0  # force a real attempt each loop
        w.refresh_opening_range()
    assert w._or_skip_ticks <= 30
