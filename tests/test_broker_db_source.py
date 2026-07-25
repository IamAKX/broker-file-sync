import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from datetime import date

from api import holidays_api, lmv_snapshot_api
from services import broker_db_source


# ── last_trading_day ─────────────────────────────────────────────────────────

def test_last_trading_day_skips_weekend(monkeypatch):
    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: [])
    monday = date(2026, 7, 20)
    assert broker_db_source.last_trading_day(monday) == date(2026, 7, 17)  # Friday


def test_last_trading_day_skips_holiday_and_weekend(monkeypatch):
    friday = date(2026, 7, 17)
    monkeypatch.setattr(
        holidays_api, "list_holidays",
        lambda year: [{"holiday_date": friday.isoformat()}],
    )
    monday = date(2026, 7, 20)
    assert broker_db_source.last_trading_day(monday) == date(2026, 7, 16)  # Thursday


# ── per-broker readers ───────────────────────────────────────────────────────

_TRADE_DATE = date(2026, 7, 17)

_FAKE_STOCKS = [
    {
        "symbol": "INFY",
        "display_name": "Infosys",
        "metrics": {
            "callstrikehighestoi": 1800.0,
            "Callstrikewithsecondhighestoi": 1820.0,
            "PutStrikeWithsecondHighestOI": 1700.0,
            "TodayPutHighestStrike": 1680.0,
            "Max Pain": 1750.0,
            "VAH": 1799.0,
            "POC": 1790.0,
            "VAL": 1780.0,
        },
    },
    {
        # A stock with no ReliableSoftware/NiftyInvest/MarketProfile presence
        # for this trade date — metrics missing entirely, not just blank.
        "symbol": "TCS",
        "display_name": "TCS",
        "metrics": {"Open": 100.0},
    },
]


def test_read_reliable_software_db_shape_and_values(monkeypatch):
    monkeypatch.setattr(lmv_snapshot_api, "get_snapshot", lambda d: {"stocks": _FAKE_STOCKS})
    headers, rows = broker_db_source.read_reliable_software_db(_TRADE_DATE)
    assert headers == broker_db_source.RELIABLE_HEADERS
    assert rows[0] == ["INFY", 1800.0, 1820.0, 1700.0, 1680.0]
    assert rows[1] == ["TCS", None, None, None, None]


def test_read_nifty_invest_db_shape_and_values(monkeypatch):
    monkeypatch.setattr(lmv_snapshot_api, "get_snapshot", lambda d: {"stocks": _FAKE_STOCKS})
    headers, rows = broker_db_source.read_nifty_invest_db(_TRADE_DATE)
    assert headers == ["Symbol", "Max Pain"]
    assert rows[0] == ["INFY", 1750.0]
    assert rows[1] == ["TCS", None]


def test_read_market_profile_db_shape_and_values(monkeypatch):
    monkeypatch.setattr(lmv_snapshot_api, "get_snapshot", lambda d: {"stocks": _FAKE_STOCKS})
    headers, rows = broker_db_source.read_market_profile_db(_TRADE_DATE)
    assert headers == ["stock", "VAH", "POC", "VAL"]
    assert rows[0] == ["INFY", 1799.0, 1790.0, 1780.0]


def test_no_snapshot_data_returns_empty_rows(monkeypatch):
    monkeypatch.setattr(lmv_snapshot_api, "get_snapshot", lambda d: {"stocks": []})
    headers, rows = broker_db_source.read_reliable_software_db(_TRADE_DATE)
    assert headers == broker_db_source.RELIABLE_HEADERS
    assert rows == []


def test_snapshot_cache_avoids_refetching(monkeypatch):
    calls = []

    def fake_get_snapshot(d):
        calls.append(d)
        return {"stocks": _FAKE_STOCKS}

    monkeypatch.setattr(lmv_snapshot_api, "get_snapshot", fake_get_snapshot)
    cache: dict = {}
    broker_db_source.read_reliable_software_db(_TRADE_DATE, snapshot_cache=cache)
    broker_db_source.read_nifty_invest_db(_TRADE_DATE, snapshot_cache=cache)
    broker_db_source.read_market_profile_db(_TRADE_DATE, snapshot_cache=cache)
    assert len(calls) == 1


# ── LiveDataReader integration: database mode for RS / NI / MP ──────────────

def _stub_sk(monkeypatch, rows):
    monkeypatch.setattr(
        "services.live_merge.LiveDataReader._read_sharekhan",
        lambda self: (["Scrip Name", "Current"], rows),
    )


def test_live_merge_reliable_database_mode_joins_by_resolved_symbol(monkeypatch):
    from services.live_merge import LiveDataReader
    from services import broker_db_source

    _stub_sk(monkeypatch, [["INFY", 1800.0]])
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi", lambda paths: (["Symbol", "Max Pain"], []))
    monkeypatch.setattr(
        broker_db_source, "read_reliable_software_db",
        lambda trade_date, snapshot_cache=None: (
            broker_db_source.RELIABLE_HEADERS, [["INFY", 1800.0, 1820.0, 1700.0, 1680.0]],
        ),
    )
    monkeypatch.setattr(broker_db_source, "last_trading_day", lambda: date(2026, 7, 17))

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [], reliable_mode="database")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    assert data[0][headers.index("callstrikehighestoi")] == 1800.0
    assert data[0][headers.index("Callstrikewithsecondhighestoi")] == 1820.0
    assert data[0][headers.index("TodayPutHighestStrike")] == 1680.0


def test_live_merge_nifty_database_mode_joins_by_symbol(monkeypatch):
    from services.live_merge import LiveDataReader
    from services import broker_db_source

    _stub_sk(monkeypatch, [["INFY", 1800.0]])
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software", lambda path: (["ScripName", "callstrikehighestoi"], []))
    monkeypatch.setattr(
        broker_db_source, "read_nifty_invest_db",
        lambda trade_date, snapshot_cache=None: (["Symbol", "Max Pain"], [["INFY", 1750.0]]),
    )
    monkeypatch.setattr(broker_db_source, "last_trading_day", lambda: date(2026, 7, 17))

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [], nifty_mode="database")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    assert data[0][headers.index("Max Pain")] == 1750.0


def test_live_merge_market_profile_database_mode_joins_by_symbol(monkeypatch):
    from services.live_merge import LiveDataReader
    from services import broker_db_source

    _stub_sk(monkeypatch, [["INFY", 1800.0]])
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software", lambda path: (["ScripName", "callstrikehighestoi"], []))
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi", lambda paths: (["Symbol", "Max Pain"], []))
    monkeypatch.setattr(
        broker_db_source, "read_market_profile_db",
        lambda trade_date, snapshot_cache=None: (
            ["stock", "VAH", "POC", "VAL"], [["INFY", 1799.0, 1790.0, 1780.0]],
        ),
    )
    monkeypatch.setattr(broker_db_source, "last_trading_day", lambda: date(2026, 7, 17))

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [], market_profile_mode="database")
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)

    assert data[0][headers.index("VAH")] == 1799.0
    assert data[0][headers.index("VAL")] == 1780.0


def test_live_merge_reliable_and_nifty_and_market_profile_share_one_snapshot_fetch(monkeypatch):
    """All three DB-mode sources fetch the same last-trading-day snapshot —
    services.broker_db_source._fetch_snapshot_stocks must only hit the API
    once per LiveDataReader session, not once per broker per slow refresh."""
    from services.live_merge import LiveDataReader
    from services import broker_db_source

    _stub_sk(monkeypatch, [["INFY", 1800.0]])
    monkeypatch.setattr(holidays_api, "list_holidays", lambda year: [])

    calls = []

    def fake_get_snapshot(trade_date):
        calls.append(trade_date)
        return {"stocks": [{"symbol": "INFY", "display_name": "Infosys", "metrics": {}}]}

    monkeypatch.setattr(lmv_snapshot_api, "get_snapshot", fake_get_snapshot)

    reader = LiveDataReader(
        "sk.xlsx", "rs.xlsx", "ni.csv", [],
        reliable_mode="database", nifty_mode="database", market_profile_mode="database",
    )
    reader._read_slow_sources(force=True)
    reader._read_slow_sources(force=True)  # a second tick — trade date + snapshot both cached

    assert len(calls) == 1


def test_live_merge_reliable_file_mode_unaffected_by_new_params(monkeypatch):
    """Default mode ("file") for the three new params must be a no-op —
    existing behavior for callers that don't pass them stays identical."""
    from services.live_merge import LiveDataReader

    _stub_sk(monkeypatch, [["INFY", 1800.0]])
    monkeypatch.setattr(
        "services.file_reader.read_reliable_software",
        lambda path: (["ScripName", "callstrikehighestoi"], [["Infosys Limited", 5.0]]),
    )
    monkeypatch.setattr(
        "services.file_reader.read_nifty_invest_multi", lambda paths: (["Symbol", "Max Pain"], []))

    reader = LiveDataReader("sk.xlsx", "rs.xlsx", "ni.csv", [("Infosys Limited", "INFY")])
    reader._read_slow_sources(force=True)
    headers, data = reader.read_merged(force_slow=False)
    assert data[0][headers.index("callstrikehighestoi")] == 5.0
