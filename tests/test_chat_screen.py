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
    def ask(question, history, live=None):
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
    def boom(question, history, live=None):
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

    def ask(question, history, live=None):
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


# ── answer options: save as PDF / translate to Tamil ─────────────────────

_ROWS = ("rows", {"columns": ["symbol", "close"], "rows": [["TCS", 3500.5]], "row_count": 1, "truncated": False})


def _answered(qapp, screen, monkeypatch, events):
    from components.chat_widgets import MessageBubble
    monkeypatch.setattr(chat_api, "ask", _fake_ask(events))
    screen.ask("How did TCS close?")
    _drain(qapp, screen)
    return [b for b in screen.findChildren(MessageBubble) if b.role == "assistant"][-1]


def _wait(qapp, condition, timeout_s=3.0):
    import time
    end = time.time() + timeout_s
    while not condition() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.01)
    assert condition()


def test_options_button_appears_only_on_a_finished_answer(qapp, screen, monkeypatch):
    from components.chat_widgets import MessageBubble
    bubble = _answered(qapp, screen, monkeypatch, [_ROWS, ("token", {"text": "TCS closed at 3,500.5."}), ("done", {})])
    assert not bubble.options_btn.isHidden()
    assert [a.text() for a in bubble.build_options_menu().actions()] == ["Save chat as PDF", "Translate to Tamil"]
    # the options button stays the last thing in the bubble, below the data table
    assert bubble.layout().indexOf(bubble.options_btn) > bubble.layout().indexOf(bubble._details)
    user = [b for b in screen.findChildren(MessageBubble) if b.role == "user"][0]
    assert user.options_btn is None

    def boom(question, history, live=None):
        raise ApiError("nope", "x", 500)
        yield  # pragma: no cover
    monkeypatch.setattr(chat_api, "ask", boom)
    screen.ask("again")
    _drain(qapp, screen)
    failed = [b for b in screen.findChildren(MessageBubble) if b.role == "assistant"][-1]
    assert failed.is_error and failed.options_btn.isHidden()


def test_translate_to_tamil_and_back_without_a_second_server_call(qapp, screen, monkeypatch):
    bubble = _answered(qapp, screen, monkeypatch, [("token", {"text": "TCS closed at 3,500.5."}), ("done", {})])
    calls = []

    def translate(text, target="ta"):
        calls.append((text, target))
        return "TCS 3,500.5 இல் முடிந்தது."
    monkeypatch.setattr(chat_api, "translate", translate)

    bubble.toggle_language()
    assert bubble.is_translating()
    assert [a.text() for a in bubble.build_options_menu().actions()][1] == "Translating to Tamil…"
    _wait(qapp, lambda: bubble.language() == "ta")
    assert bubble.body.full_text() == "TCS 3,500.5 இல் முடிந்தது."
    assert bubble.original_text() == "TCS closed at 3,500.5."
    assert [a.text() for a in bubble.build_options_menu().actions()][1] == "Show in English"

    # Tamil is drawn with a Tamil-capable font behind the Latin one (the macOS
    # system font alone renders it as empty boxes); English goes back to the app font.
    from PySide6.QtGui import QFontDatabase
    if QFontDatabase.families(QFontDatabase.WritingSystem.Tamil):
        assert set(bubble.body.font().families()) & set(QFontDatabase.families(QFontDatabase.WritingSystem.Tamil))

    bubble.toggle_language()
    assert bubble.language() == "en" and bubble.body.full_text() == "TCS closed at 3,500.5."
    import font_scale
    assert bubble.body.font().families() == font_scale.font(font_scale.SMALL, False).families()
    bubble.toggle_language()                         # Tamil again: served from the bubble's own copy
    assert bubble.language() == "ta" and calls == [("TCS closed at 3,500.5.", "ta")]
    # follow-up questions still carry the original English answer
    assert screen._history[-1] == {"role": "assistant", "text": "TCS closed at 3,500.5."}


def test_translate_failure_keeps_english_and_says_why(qapp, screen, monkeypatch):
    bubble = _answered(qapp, screen, monkeypatch, [("answer", {"text": "Hello."}), ("done", {})])

    def translate(text, target="ta"):
        raise ApiError("Not Found", "not_found", 404)
    monkeypatch.setattr(chat_api, "translate", translate)
    bubble.toggle_language()
    _wait(qapp, lambda: not bubble.is_translating())
    assert bubble.language() == "en" and bubble.body.full_text() == "Hello."
    assert "newer server version" in bubble._note.text() and not bubble._note.isHidden()


def test_export_turns_carry_shown_language_and_data_rows(qapp, screen, monkeypatch):
    bubble = _answered(qapp, screen, monkeypatch, [_ROWS, ("token", {"text": "TCS closed at 3,500.5."}), ("done", {})])
    bubble.set_translation("TCS 3,500.5 இல் முடிந்தது.")
    turns = screen.export_turns()
    assert [t["role"] for t in turns] == ["user", "assistant"]
    assert turns[1]["text"] == "TCS 3,500.5 இல் முடிந்தது."
    assert turns[1]["details"]["rows"] == [["TCS", 3500.5]]      # saved even though "Show data" is collapsed
    assert not bubble.details_visible()

    from datetime import datetime
    from services import chat_export
    html = chat_export.build_html(turns, datetime(2026, 11, 13, 12, 30))
    assert "How did TCS close?" in html and "இல் முடிந்தது" in html
    assert "<th>symbol</th><th>close</th>" in html and '<td class="num">3500.5</td>' in html
    assert "Saved 13 Nov 2026, 12:30" in html
    assert chat_export.default_filename(datetime(2026, 11, 13, 12, 30)) == "Ask_Fuku_chat_2026-11-13_1230.pdf"


def test_export_html_escapes_questions_and_renders_answer_markdown(qapp):
    from services import chat_export
    html = chat_export.build_html([
        {"role": "user", "text": "is 5 < 6 & <b>bold</b>?"},
        {"role": "assistant", "text": "**RELIANCE** rose.\n\n- one\n- two", "details": None},
    ])
    assert "is 5 &lt; 6 &amp; &lt;b&gt;bold&lt;/b&gt;?" in html
    assert "font-weight:700" in html and "<li" in html and "**RELIANCE**" not in html


def test_save_chat_pdf_writes_the_chosen_file(qapp, screen, monkeypatch, tmp_path):
    from screens import chat as chat_screen
    _answered(qapp, screen, monkeypatch, [_ROWS, ("token", {"text": "TCS closed at 3,500.5."}), ("done", {})])
    target = tmp_path / "my chat"
    monkeypatch.setattr(chat_screen.QFileDialog, "getSaveFileName", lambda *a, **k: (str(target), ""))
    seen = {}
    monkeypatch.setattr(screen, "_export_pdf", lambda turns, path: seen.update(turns=turns, path=path))
    screen.save_chat_pdf()
    assert seen["path"] == str(target) + ".pdf" and len(seen["turns"]) == 2

    monkeypatch.setattr(chat_screen.QFileDialog, "getSaveFileName", lambda *a, **k: ("", ""))
    seen.clear()
    screen.save_chat_pdf()                           # cancelled dialog: nothing is written
    assert seen == {}


def test_theme_refresh_keeps_data_rows_for_export(qapp, screen, monkeypatch):
    _answered(qapp, screen, monkeypatch, [_ROWS, ("token", {"text": "kept"}), ("done", {})])
    screen.refresh_theme()
    assert screen.export_turns()[1]["details"]["rows"] == [["TCS", 3500.5]]
