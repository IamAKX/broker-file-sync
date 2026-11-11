"""Ask Fuku's live-market context: the LMV grid (or why it isn't available)
that is attached to every chat question — services/lmv_chat_context.py, its
use in screens/chat.py and api/chat_api.py."""

import sys
import time
from datetime import datetime, timedelta

import pytest
from PySide6.QtWidgets import QApplication

from api import chat_api
from api.exceptions import ApiError
from services import lmv_chat_context

SCRIPTS = []   # no symbol overrides: the display name is the symbol


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


class Card:
    def __init__(self, mode="file"):
        self._source_mode = mode


class DataImport:
    _REQUIRED_BROKERS = {"Sharekhan", "ReliableSoftware", "NiftyInvest", "ExternalImport", "MarketProfile"}

    def __init__(self, imported=(), db_mode=(), viewer=None):
        self._imported_brokers = set(imported)
        self._cards = {b: Card("database" if b in db_mode else "file") for b in self._REQUIRED_BROKERS}
        self._live_viewer = viewer


ALL = DataImport._REQUIRED_BROKERS


@pytest.fixture
def viewer(qapp):
    from screens.live_viewer import LiveViewerWindow
    v = LiveViewerWindow("", "", "", [])
    v._headers = ["Scrip Name", "Sector", "Current", "% Change", "CWH"]
    v._data = [
        ["RELIANCE", "Energy", 2945.5, 1.23456789, ""],
        ["TCS", "IT", 3500.0, float("nan"), "—"],
        ["", "IT", 1.0, 1.0, 1.0],                       # no name: not a stock row
    ]
    v._populate_table(v._data, set())                    # what a tick does; records the displayed grid
    v._chat_updated_at = datetime(2026, 11, 11, 10, 32, 5)
    v._status_lbl.setText("Updated: 10:32:05")
    v.show()
    yield v
    v.close()


NOW = datetime(2026, 11, 11, 10, 32, 20)


# ── is LMV running, and are the files loaded? ────────────────────────────

def test_never_opened_data_import_means_not_running():
    block = lmv_chat_context.build(None, SCRIPTS)
    assert block == {"running": False, "reason": lmv_chat_context.NOT_OPEN}


def test_names_the_files_that_are_not_loaded():
    block = lmv_chat_context.build(DataImport(imported={"Sharekhan"}, db_mode={"NiftyInvest"}), SCRIPTS)
    assert not block["running"] and "rows" not in block
    assert "External Import, Market Profile, Reliable Software" in block["reason"]
    assert "Nifty Invest" not in block["reason"] and "Sharekhan" not in block["reason"]   # loaded / database mode


def test_files_loaded_but_watcher_not_started():
    block = lmv_chat_context.build(DataImport(imported=ALL), SCRIPTS)
    assert not block["running"] and "click Run Watcher" in block["reason"] and "not loaded" not in block["reason"]


def test_closed_lmv_window_is_not_live(viewer):
    viewer.close()                                       # the user closed LMV: its last grid is stale
    block = lmv_chat_context.build(DataImport(imported=ALL, viewer=viewer), SCRIPTS)
    assert not block["running"] and "not running" in block["reason"]


def test_open_lmv_without_data_is_not_live(viewer):
    viewer._chat_disp = None
    viewer._headers, viewer._data = [], []
    viewer._status_lbl.setText("Error loading: file locked")
    block = lmv_chat_context.build(DataImport(imported=ALL, viewer=viewer), SCRIPTS)
    assert not block["running"] and "no data loaded yet" in block["reason"] and "file locked" in block["reason"]


# ── the grid ─────────────────────────────────────────────────────────────

def test_running_lmv_sends_the_grid(viewer):
    block = lmv_chat_context.build(DataImport(imported=ALL, viewer=viewer), SCRIPTS, now=NOW)
    assert block["running"] and block["as_of"] == "2026-11-11 10:32:05" and block["warning"] == ""
    assert block["columns"] == ["Current", "% Change", "CWH"]
    assert block["rows"] == [
        ["RELIANCE", "RELIANCE", "Energy", 2945.5, 1.2346, None],     # rounded; empty cell -> None
        ["TCS", "TCS", "IT", 3500.0, None, None],                     # NaN and "—" are not values
    ]
    import json
    json.dumps(block, allow_nan=False)                                 # strictly valid JSON for the server


def test_status_only_build_carries_no_rows(viewer):
    block = lmv_chat_context.build(DataImport(imported=ALL, viewer=viewer), SCRIPTS, include_rows=False, now=NOW)
    assert block["running"] and "rows" not in block and block["stocks"] == 3
    connected, text = lmv_chat_context.summary(block)
    assert connected and "10:32:05" in text


def test_warnings_for_stale_feed_and_old_grid(viewer):
    viewer._reader.sharekhan_warning = "COM read failed"
    block = lmv_chat_context.build(DataImport(imported=ALL, viewer=viewer), SCRIPTS,
                                   now=NOW + timedelta(minutes=12))
    assert block["running"]
    assert "may be the last saved ones" in block["warning"] and "12 min ago" in block["warning"]


def test_a_broken_viewer_degrades_to_not_running(monkeypatch):
    class Boom:
        def isHidden(self):
            raise RuntimeError("deleted C++ object")
    monkeypatch.setattr("services.error_logging.error_logger.exception", lambda *a, **k: None)
    block = lmv_chat_context.build(DataImport(imported=ALL, viewer=Boom()), SCRIPTS)
    assert block["running"] is False and block["reason"]


# ── sending it ───────────────────────────────────────────────────────────

class _Resp:
    encoding = None

    def iter_lines(self, decode_unicode=True):
        return iter(["event: done", 'data: {"kind": "live"}', ""])

    def close(self):
        pass


def test_ask_sends_the_live_block_and_omits_it_when_absent(monkeypatch):
    bodies = []
    monkeypatch.setattr(chat_api.api_client, "post_stream", lambda path, body, timeout: bodies.append(body) or _Resp())
    live = {"running": True, "as_of": "t", "stocks": 2, "columns": ["Current"], "rows": [["A", "A", None, 1]]}
    assert list(chat_api.ask("q", [], live)) == [("done", {"kind": "live"})]
    assert bodies[0]["live"] == {"running": True, "as_of": "t", "columns": ["Current"], "rows": [["A", "A", None, 1]]}
    list(chat_api.ask("q", []))
    assert "live" not in bodies[1]                       # exactly the pre-feature request


def test_question_is_still_answered_if_the_server_rejects_the_grid(monkeypatch):
    bodies = []

    def post(path, body, timeout):
        bodies.append(dict(body))
        if body.get("live", {}).get("running"):
            raise ApiError("Request Entity Too Large", "http_413", 413)
        return _Resp()
    monkeypatch.setattr(chat_api.api_client, "post_stream", post)
    live = {"running": True, "columns": ["Current"], "rows": [["A", "A", None, 1]]}
    assert list(chat_api.ask("q", [], live)) == [("done", {"kind": "live"})]
    assert len(bodies) == 2 and bodies[1]["live"]["running"] is False and "rows" not in bodies[1]["live"]

    def always_limited(path, body, timeout):
        raise ApiError("slow down", "chat_rate_limited", 429)
    monkeypatch.setattr(chat_api.api_client, "post_stream", always_limited)
    with pytest.raises(ApiError):                        # other errors are not retried or hidden
        list(chat_api.ask("q", [], live))


# ── chat screen ──────────────────────────────────────────────────────────

@pytest.fixture
def screen(qapp, monkeypatch):
    from app import AppController
    from screens.chat import ChatScreen

    monkeypatch.setattr(chat_api, "get_status", lambda: {"enabled": True, "suggested_questions": []})
    return ChatScreen(AppController(qapp))


def _drain(qapp, screen):
    end = time.time() + 3
    while screen._busy and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


def test_screen_attaches_live_context_and_shows_status(qapp, screen, monkeypatch):
    seen = []

    def ask(question, history, live=None):
        seen.append(live)
        yield "answer", {"text": "ok"}
        yield "done", {}
    monkeypatch.setattr(chat_api, "ask", ask)

    # No main window / LMV in this test app: off, with the instruction.
    screen.ask("what is TCS trading at now?")
    _drain(qapp, screen)
    assert seen[0] == {"running": False, "reason": lmv_chat_context.NOT_OPEN}
    assert screen._live_lbl.text().startswith("○ Live market data: off")

    running = {"running": True, "reason": "", "warning": "", "as_of": "2026-11-11 10:32:05", "stocks": 216,
               "columns": ["Current"], "rows": [["TCS", "TCS", "IT", 3500.5]]}
    monkeypatch.setattr(screen._controller, "get_lmv_chat_context", lambda include_rows=True: running)
    screen.ask("and now?")
    _drain(qapp, screen)
    assert seen[1] is running
    assert screen._live_lbl.text() == "● Live market data: on — LMV as of 10:32:05, 216 stocks"


def test_a_failing_live_lookup_never_blocks_the_question(qapp, screen, monkeypatch):
    seen = []

    def ask(question, history, live=None):
        seen.append(live)
        yield "answer", {"text": "ok"}
        yield "done", {}
    monkeypatch.setattr(chat_api, "ask", ask)

    def boom(include_rows=True):
        raise RuntimeError("LMV exploded")
    monkeypatch.setattr(screen._controller, "get_lmv_chat_context", boom)
    screen.ask("anything")
    _drain(qapp, screen)
    assert seen == [None] and screen._history[-1] == {"role": "assistant", "text": "ok"}
