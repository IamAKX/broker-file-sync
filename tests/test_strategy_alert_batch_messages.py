"""Tests for services/strategy_alerts/messages.py's render_batch_* functions
— combining several AlertEvents from one Live Master View tick into ONE
notification per channel instead of one per event. See
screens/live_viewer.py's _run_strategy_alert_checks for the caller that
decides whether to batch (a single event is untouched — render_title/
render_message unchanged) and tests/test_live_viewer_strategy_alerts.py for
the integration-level wiring test."""
from datetime import datetime

from services.notifications.levels import NotificationLevel
from services.strategy_alerts.messages import (
    render_batch_email_message,
    render_batch_level,
    render_batch_title,
    render_batch_tray_message,
    render_summary_line,
)
from services.strategy_alerts.models import EVENT_ENTRY, EVENT_STOP_OUT, EVENT_TARGET, AlertEvent


def _entry(symbol, price=1500.0, strategy_name="PWHBUY"):
    e = AlertEvent(kind=EVENT_ENTRY, strategy_id="s1", strategy_name=strategy_name,
                   symbol=symbol, timestamp=datetime(2026, 1, 5, 10, 0))
    e.payload = {"direction": "BUY", "sector": "IT", "entry_price": price,
                "entry_time": e.timestamp.isoformat(), "metrics": {}, "risk_reward": None,
                "score": None}
    return e


def _target(symbol, price=1600.0, strategy_name="PWHBUY"):
    e = AlertEvent(kind=EVENT_TARGET, strategy_id="s1", strategy_name=strategy_name,
                   symbol=symbol, timestamp=datetime(2026, 1, 5, 10, 5))
    e.payload = {"metric_name": "Target 1", "price": price,
                "achieved_at": e.timestamp.isoformat(), "elapsed": "5 minutes"}
    return e


def _stop_out(symbol, price=1400.0, strategy_name="PWHBUY"):
    e = AlertEvent(kind=EVENT_STOP_OUT, strategy_id="s1", strategy_name=strategy_name,
                   symbol=symbol, timestamp=datetime(2026, 1, 5, 10, 10))
    e.payload = {"metric_name": "Stop Loss", "price": price, "time": e.timestamp.isoformat(),
                "running_high": 1550.0, "running_low": 1390.0, "pct_move": -6.67}
    return e


# ── render_batch_title ───────────────────────────────────────────────────────

def test_batch_title_single_event_matches_render_title():
    from services.strategy_alerts.messages import render_title
    event = _entry("INFY")
    assert render_batch_title([event]) == render_title(event)


def test_batch_title_counts_and_pluralizes_per_kind():
    events = [_entry("INFY"), _entry("TCS"), _target("WIPRO"), _stop_out("RELIANCE")]
    title = render_batch_title(events)
    assert title == "4 Signals — 2 New Entries, 1 Target Achieved, 1 Stopped Out"


def test_batch_title_singular_entry_not_pluralized():
    events = [_entry("INFY"), _target("TCS")]
    title = render_batch_title(events)
    assert "1 New Entry," in title
    assert "New Entries" not in title


# ── render_batch_level ───────────────────────────────────────────────────────

def test_batch_level_failure_wins_when_any_stop_out_present():
    events = [_entry("INFY"), _target("TCS"), _stop_out("RELIANCE")]
    assert render_batch_level(events) == NotificationLevel.FAILURE


def test_batch_level_success_when_target_present_no_stop_out():
    events = [_entry("INFY"), _target("TCS")]
    assert render_batch_level(events) == NotificationLevel.SUCCESS


def test_batch_level_info_when_only_entries():
    events = [_entry("INFY"), _entry("TCS")]
    assert render_batch_level(events) == NotificationLevel.INFO


# ── render_summary_line ──────────────────────────────────────────────────────

def test_summary_line_entry_shows_entry_price():
    assert render_summary_line(_entry("INFY", price=1520.5)) == "INFY @1520.50"


def test_summary_line_target_shows_achieved_price():
    assert render_summary_line(_target("TCS", price=3800.0)) == "TCS @3800.00"


def test_summary_line_stop_out_shows_stop_price():
    assert render_summary_line(_stop_out("RELIANCE", price=2400.0)) == "RELIANCE @2400.00"


# ── render_batch_tray_message ────────────────────────────────────────────────

def test_tray_message_groups_by_kind_one_line_each():
    events = [_entry("INFY"), _entry("TCS"), _target("WIPRO"), _stop_out("RELIANCE")]
    message = render_batch_tray_message(events)
    lines = message.split("\n")
    assert lines == [
        "Entries: INFY @1500.00, TCS @1500.00",
        "Targets: WIPRO @1600.00",
        "Stop-Outs: RELIANCE @1400.00",
    ]


def test_tray_message_caps_long_kind_group_with_more_indicator():
    events = [_entry(f"SYM{i}") for i in range(9)]   # over _MAX_SUMMARIES_PER_LINE (6)
    message = render_batch_tray_message(events)
    assert message.startswith("Entries: SYM0 @1500.00, SYM1 @1500.00")
    assert message.endswith("+3 more")
    assert "SYM8" not in message   # the 9th stock is folded into "+3 more"


def test_tray_message_omits_empty_kind_groups():
    events = [_entry("INFY")]
    message = render_batch_tray_message(events)
    assert "Targets" not in message
    assert "Stop-Outs" not in message


# ── render_batch_email_message ───────────────────────────────────────────────

def test_email_message_includes_full_detail_for_every_event():
    events = [_entry("INFY", price=1520.5), _stop_out("RELIANCE", price=2400.0)]
    message = render_batch_email_message(events)

    assert "INFY" in message
    assert "RELIANCE" in message
    assert "Entry Price: 1520.50" in message   # full render_message() detail, not summarized
    assert "Sector: IT" in message
    assert "Stopped out via" in message
    assert "High/Low since signal: 1550.00/1390.00" in message


def test_email_message_stacks_events_with_distinct_headers():
    events = [_entry("INFY"), _entry("TCS")]
    message = render_batch_email_message(events)
    blocks = message.split("\n\n")
    assert len(blocks) == 2
    assert "INFY" in blocks[0] and "TCS" not in blocks[0]
    assert "TCS" in blocks[1] and "INFY" not in blocks[1]
