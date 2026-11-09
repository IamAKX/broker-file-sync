import sys

import pytest
from PySide6.QtWidgets import QApplication

from api import chat_api
from api.exceptions import ApiError


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp, monkeypatch):
    from app import AppController
    from screens.chat import ChatScreen

    # The status fetch is a network call on a thread; tests drive events directly.
    monkeypatch.setattr(chat_api, "get_status", lambda: {"enabled": True, "suggested_questions": []})
    return ChatScreen(AppController(qapp))


def _drain(qapp, screen, timeout_s=3.0):
    import time

    end = time.time() + timeout_s
    while screen._busy and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


# ── SSE parsing ──────────────────────────────────────────────────────────

def test_parse_sse_events_and_multiline_data():
    lines = ["event: stage", 'data: {"stage": "understanding"}', "", "event: token", 'data: {"text": "hi"}', ""]
    assert list(chat_api.parse_sse(lines)) == [("stage", {"stage": "understanding"}), ("token", {"text": "hi"})]


def test_parse_sse_skips_garbage_and_flushes_trailing_event():
    lines = ["event: token", "data: not json", "", "event: done", 'data: {"ok": 1}']
    assert list(chat_api.parse_sse(lines)) == [("done", {"ok": 1})]


# ── screen flow ──────────────────────────────────────────────────────────

def _fake_ask(events):
    def ask(question, history):
        yield from events
    return ask


def test_full_turn_streams_answer_and_records_history(qapp, screen, monkeypatch):
    monkeypatch.setattr(chat_api, "ask", _fake_ask([
        ("stage", {"stage": "understanding"}),
        ("stage", {"stage": "running_query"}),
        ("sql", {"sql": "SELECT 1"}),
        ("rows", {"columns": ["symbol", "close"], "rows": [["TCS", 3500.5]], "row_count": 1, "truncated": False}),
        ("stage", {"stage": "writing_answer"}),
        ("token", {"text": "TCS closed "}),
        ("token", {"text": "at 3,500.5."}),
        ("done", {"kind": "sql"}),
    ]))
    screen.ask("How did TCS close?")
    _drain(qapp, screen)
    assert not screen._busy
    assert screen._history == [
        {"role": "user", "text": "How did TCS close?"},
        {"role": "assistant", "text": "TCS closed at 3,500.5."},
    ]
    from components.chat_widgets import MessageBubble
    assistant = [b for b in screen.findChildren(MessageBubble) if b.role == "assistant"][0]
    assert assistant.indicator is None                      # thinking animation replaced by the answer
    assert assistant.body.full_text() == "TCS closed at 3,500.5."
    assert assistant._details is not None and not assistant.details_visible()
    assistant._toggle_details()
    assert assistant.details_visible()


def test_server_error_shows_message_and_does_not_pollute_history(qapp, screen, monkeypatch):
    def boom(question, history):
        raise ApiError("You can ask up to 12 questions per minute.", "chat_rate_limited", 429)
        yield  # pragma: no cover
    monkeypatch.setattr(chat_api, "ask", boom)
    screen.ask("anything")
    _drain(qapp, screen)
    assert screen._history == []
    assert not screen._busy and screen._input.isEnabled()


def test_refusal_answer_is_recorded_like_any_answer(qapp, screen, monkeypatch):
    monkeypatch.setattr(chat_api, "ask", _fake_ask([
        ("stage", {"stage": "understanding"}),
        ("answer", {"text": "I only help with markets."}),
        ("done", {"kind": "refuse"}),
    ]))
    screen.ask("write a poem")
    _drain(qapp, screen)
    assert screen._history[-1] == {"role": "assistant", "text": "I only help with markets."}


def test_second_question_sends_prior_turns_as_history(qapp, screen, monkeypatch):
    seen = []

    def ask(question, history):
        seen.append((question, list(history)))
        yield "answer", {"text": f"re: {question}"}
        yield "done", {}
    monkeypatch.setattr(chat_api, "ask", ask)
    screen.ask("first")
    _drain(qapp, screen)
    screen.ask("second")
    _drain(qapp, screen)
    assert seen[1][1] == [{"role": "user", "text": "first"}, {"role": "assistant", "text": "re: first"}]


def test_clear_chat_resets_and_drops_inflight_events(qapp, screen, monkeypatch):
    monkeypatch.setattr(chat_api, "ask", _fake_ask([("answer", {"text": "x"}), ("done", {})]))
    screen.ask("q")
    _drain(qapp, screen)
    screen.clear_chat()
    assert screen._history == []
    from PySide6.QtCore import QCoreApplication, QEvent
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    from components.chat_widgets import MessageBubble
    assert screen.findChildren(MessageBubble) == []
    # a stale event from the old conversation must be ignored
    screen._on_event(screen._token - 1, "token", {"text": "late"})


def test_disabled_status_locks_input(qapp, screen):
    screen._apply_status({"enabled": False, "suggested_questions": ["Q1"]})
    assert not screen._input.isEnabled() and not screen._send_btn.isEnabled()
    assert not screen._banner.isHidden()


def test_theme_refresh_keeps_transcript(qapp, screen, monkeypatch):
    monkeypatch.setattr(chat_api, "ask", _fake_ask([("answer", {"text": "kept"}), ("done", {})]))
    screen.ask("q")
    _drain(qapp, screen)
    screen.refresh_theme()
    from components.chat_widgets import MessageBubble
    texts = sorted(b.body.full_text() for b in screen.findChildren(MessageBubble))
    assert texts == ["kept", "q"]


# ── widgets ──────────────────────────────────────────────────────────────

def test_thinking_indicator_tracks_stage(qapp):
    from components.chat_widgets import STAGES, ThinkingIndicator
    from theme import DARK

    class T:
        def get(self, k):
            return DARK.get(k, "#888888")

    ind = ThinkingIndicator(T())
    ind.resize(400, 64)
    ind.set_stage("running_query")
    assert ind.stage_index() == [k for k, _ in STAGES].index("running_query")
    ind.set_stage("nonsense")                       # unknown stages are ignored
    assert ind.stage_index() == 2
    ind.grab()                                       # paints without raising
