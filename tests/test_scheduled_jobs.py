import datetime as dt_module
from datetime import date

import pytest

from services import scheduled_jobs, trading_calendar


class _FixedDate(date):
    """A `date.today()` that always returns a known Monday with no holidays,
    so trading-day checks are deterministic regardless of when tests run."""

    @classmethod
    def today(cls):
        return cls(2026, 7, 20)   # Monday


class _FakeController:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot
        self.navigated_to = []

    def get_lmv_snapshot(self):
        return self._snapshot

    def show_and_navigate(self, screen_name):
        self.navigated_to.append(screen_name)


class _FakeNotifier:
    def __init__(self):
        self.notifications = []

    def notify(self, title, message, action=None, **kwargs):
        self.notifications.append((title, message, action))


@pytest.fixture(autouse=True)
def fixed_today(monkeypatch):
    monkeypatch.setattr(scheduled_jobs, "date", _FixedDate)


@pytest.fixture(autouse=True)
def no_holidays(monkeypatch):
    monkeypatch.setattr(trading_calendar.holidays_api, "list_holidays", lambda year: [])


# ── _build_rows_payload ──────────────────────────────────────────────────────

SHAREKHAN_HEADERS = [
    "Scrip Name", "Lot Size", "% Change", "Current", "Open", "High", "Low",
    "Close", "Avg Rate", "OI Difference Percentage", "P.High", "P.Low",
    "Qty", "P.Quantity", "TurnOver",
]


def _sharekhan_row(scrip="INFY", pct=1.5, current=1800, open_=1790, high=1810,
                    low=1780, close=1795, avg=1798, phigh=1815, plow=1775,
                    qty=1000, pqty=900):
    row = [None] * len(SHAREKHAN_HEADERS)
    row[SHAREKHAN_HEADERS.index("Scrip Name")] = scrip
    row[SHAREKHAN_HEADERS.index("% Change")] = pct
    row[SHAREKHAN_HEADERS.index("Current")] = current
    row[SHAREKHAN_HEADERS.index("Open")] = open_
    row[SHAREKHAN_HEADERS.index("High")] = high
    row[SHAREKHAN_HEADERS.index("Low")] = low
    row[SHAREKHAN_HEADERS.index("Close")] = close
    row[SHAREKHAN_HEADERS.index("Avg Rate")] = avg
    row[SHAREKHAN_HEADERS.index("P.High")] = phigh
    row[SHAREKHAN_HEADERS.index("P.Low")] = plow
    row[SHAREKHAN_HEADERS.index("Qty")] = qty
    row[SHAREKHAN_HEADERS.index("P.Quantity")] = pqty
    return row


def test_build_rows_payload_maps_raw_metric_names():
    data = [_sharekhan_row()]
    rows = scheduled_jobs._build_rows_payload(SHAREKHAN_HEADERS, data, script_name_data=[])
    assert len(rows) == 1
    metrics = rows[0]["metrics"]
    assert metrics == {
        "DiffPcnt": 1.5, "Open": 1790, "High": 1810, "Low": 1780,
        "Close": 1800, "pdh": 1815, "pdl": 1775, "PClose": 1795,
        "AvgRate": 1798, "Quantity": 1000, "PQuantity": 900,
    }


def test_build_rows_payload_resolves_symbol_via_script_name_map():
    data = [_sharekhan_row(scrip="Infosys Limited")]
    script_name_data = [("Infosys Limited", "INFY")]
    rows = scheduled_jobs._build_rows_payload(SHAREKHAN_HEADERS, data, script_name_data)
    assert rows[0]["symbol"] == "INFY"
    assert rows[0]["display_name"] == "Infosys Limited"


def test_build_rows_payload_falls_back_to_display_name_when_unmapped():
    data = [_sharekhan_row(scrip="Unknown Corp")]
    rows = scheduled_jobs._build_rows_payload(SHAREKHAN_HEADERS, data, script_name_data=[])
    assert rows[0]["symbol"] == "Unknown Corp"


# ── run_lmv_check ────────────────────────────────────────────────────────────

def test_lmv_check_notifies_when_not_loaded():
    controller = _FakeController(snapshot=None)
    notifier = _FakeNotifier()
    scheduled_jobs.run_lmv_check(controller, notifier)
    assert len(notifier.notifications) == 1
    title, message, action = notifier.notifications[0]
    assert "Load" in title
    action()
    assert controller.navigated_to == ["data_import"]


def test_lmv_check_silent_when_loaded():
    controller = _FakeController(snapshot=(SHAREKHAN_HEADERS, [_sharekhan_row()]))
    notifier = _FakeNotifier()
    scheduled_jobs.run_lmv_check(controller, notifier)
    assert notifier.notifications == []


# ── run_historic_save ────────────────────────────────────────────────────────

def test_historic_save_notifies_when_lmv_not_loaded():
    controller = _FakeController(snapshot=None)
    notifier = _FakeNotifier()
    scheduled_jobs.run_historic_save(controller, notifier)
    assert len(notifier.notifications) == 1
    title, message, action = notifier.notifications[0]
    assert "not saved" in message.lower()
    action()
    assert controller.navigated_to == ["historic_upload"]


def test_historic_save_uploads_when_lmv_loaded(monkeypatch):
    uploaded = {}

    def fake_upload_daily(trade_date, rows):
        uploaded["trade_date"] = trade_date
        uploaded["rows"] = rows
        return {"values_upserted": len(rows)}

    monkeypatch.setattr(scheduled_jobs.historic_api, "upload_daily", fake_upload_daily)

    controller = _FakeController(snapshot=(SHAREKHAN_HEADERS, [_sharekhan_row(scrip="INFY")]))
    notifier = _FakeNotifier()
    scheduled_jobs.run_historic_save(controller, notifier)

    assert notifier.notifications == []
    assert uploaded["trade_date"] == _FixedDate.today()
    assert uploaded["rows"][0]["symbol"] == "INFY"


def test_historic_save_notifies_on_api_error(monkeypatch):
    from api.exceptions import ApiError

    def fake_upload_daily(trade_date, rows):
        raise ApiError("server exploded", "internal_error", 500)

    monkeypatch.setattr(scheduled_jobs.historic_api, "upload_daily", fake_upload_daily)

    controller = _FakeController(snapshot=(SHAREKHAN_HEADERS, [_sharekhan_row()]))
    notifier = _FakeNotifier()
    scheduled_jobs.run_historic_save(controller, notifier)

    assert len(notifier.notifications) == 1


def test_historic_save_silent_on_session_expired(monkeypatch):
    from api.exceptions import ApiError

    def fake_upload_daily(trade_date, rows):
        raise ApiError("unauthorized", "unauthorized", 401)

    monkeypatch.setattr(scheduled_jobs.historic_api, "upload_daily", fake_upload_daily)

    controller = _FakeController(snapshot=(SHAREKHAN_HEADERS, [_sharekhan_row()]))
    notifier = _FakeNotifier()
    scheduled_jobs.run_historic_save(controller, notifier)

    assert notifier.notifications == []


# ── run_availability_check ───────────────────────────────────────────────────

def test_availability_check_notifies_when_missing(monkeypatch):
    monkeypatch.setattr(
        scheduled_jobs.historic_api, "get_availability",
        lambda date_from, date_to: {"dates": [{"trade_date": date_from.isoformat(), "has_data": False}]},
    )
    controller = _FakeController()
    notifier = _FakeNotifier()
    scheduled_jobs.run_availability_check(controller, notifier)
    assert len(notifier.notifications) == 1
    _, _, action = notifier.notifications[0]
    action()
    assert controller.navigated_to == ["historic_upload"]


def test_availability_check_silent_when_present(monkeypatch):
    monkeypatch.setattr(
        scheduled_jobs.historic_api, "get_availability",
        lambda date_from, date_to: {"dates": [{"trade_date": date_from.isoformat(), "has_data": True}]},
    )
    controller = _FakeController()
    notifier = _FakeNotifier()
    scheduled_jobs.run_availability_check(controller, notifier)
    assert notifier.notifications == []
