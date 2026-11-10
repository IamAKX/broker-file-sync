"""Voice mode (services/voice_io.py + its wiring in screens/chat.py). No real
microphone, speech engine or Whisper model is touched: the conversation is
driven with fakes, the detector with synthetic PCM."""

import math
import sys
import time
from array import array

import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from api import chat_api
from services import voice_io
from services.voice_io import SpeechChunker, UtteranceDetector, VoiceConversation, VoiceUnavailable, speakable


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


def _pump(qapp, until, timeout_s=3.0):
    end = time.time() + timeout_s
    while not until() and time.time() < end:
        qapp.processEvents()
        time.sleep(0.005)
    qapp.processEvents()
    assert until()


# ── end-of-speech detection ──────────────────────────────────────────────

def _tone(ms, amplitude=8000):
    n = voice_io.SAMPLE_RATE * ms // 1000
    return array("h", (int(amplitude * math.sin(i * 0.3)) for i in range(n))).tobytes()


def _quiet(ms):
    return _tone(ms, amplitude=40)


def test_detector_emits_one_utterance_after_trailing_silence():
    d = UtteranceDetector()
    assert d.feed(_quiet(500)) == []
    assert d.feed(_tone(900)) == [] and d.in_speech
    out = d.feed(_quiet(1500))
    assert len(out) == 1 and not d.in_speech
    seconds = len(out[0]) / 2 / voice_io.SAMPLE_RATE
    assert 1.5 < seconds < 2.6                 # the speech + pre-roll + the closing silence


def test_detector_ignores_clicks_and_keeps_a_mid_sentence_pause_together():
    d = UtteranceDetector()
    assert d.feed(_quiet(300) + _tone(60) + _quiet(1500)) == []          # too short to be speech
    out = d.feed(_tone(600) + _quiet(500) + _tone(600) + _quiet(1500))  # a 0.5s pause is not the end
    assert len(out) == 1


def test_detector_handles_arbitrary_chunk_sizes_and_caps_length():
    d = UtteranceDetector(max_utterance_s=2)
    data = _tone(5000)
    out = []
    for i in range(0, len(data), 333):
        out += d.feed(data[i:i + 333])
    assert len(out) >= 2                        # nonstop sound is cut at the cap, not buffered forever


# ── answer → speech ──────────────────────────────────────────────────────

def test_speakable_strips_markdown():
    assert speakable("**TCS** closed at `₹3,500.5` — see [the chart](http://x)") == \
        "TCS closed at rupees 3,500.5 — see the chart"
    assert speakable("## Top movers") == "Top movers"
    assert speakable("- F&O ban list") == "F and O ban list"


def test_chunker_streams_sentences_and_skips_tables():
    c = SpeechChunker()
    out = []
    for piece in ["TCS closed at 3,5", "00.5 today. It ", "rose 1.2%.\n\n| Symbol | Close |\n|---|---|\n",
                  "| TCS | 3,500.5 |\n| INFY | 1. 5 |\n\nThat is ", "all"]:
        out += c.feed(piece)
    out += c.flush()
    assert out == ["TCS closed at 3,500.5 today.", "It rose 1.2%.", "The full table is on screen.", "That is all"]


# ── the conversation loop ────────────────────────────────────────────────

class FakeMic(QObject):
    level = Signal(float)
    speech_started = Signal()
    utterance = Signal(bytes)
    silent = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.open = False

    def start(self):
        self.open = True

    def stop(self):
        self.open = False


class FakeSpeaker(QObject):
    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self.said, self.pending = [], 0

    def is_busy(self):
        return self.pending > 0

    def say(self, text):
        self.said.append(text)
        self.pending += 1

    def stop(self):
        self.pending = 0
        self.idle.emit()

    def finish_speaking(self):
        self.pending = 0
        self.idle.emit()


class FakeTranscriber:
    def __init__(self, texts=("how did TCS close",), load_error=None):
        self._texts, self._load_error = list(texts), load_error

    def needs_download(self):
        return False

    def load(self):
        if self._load_error:
            raise VoiceUnavailable(self._load_error)

    def transcribe(self, pcm):
        return self._texts.pop(0)


def _conversation(qapp, **kw):
    conv = VoiceConversation(transcriber=FakeTranscriber(**kw), mic_factory=FakeMic, speaker_factory=FakeSpeaker)
    conv._RELISTEN_DELAY_MS = 0
    return conv


def test_conversation_full_loop(qapp):
    conv = _conversation(qapp)
    questions, states = [], []
    conv.question.connect(questions.append)
    conv.state_changed.connect(lambda s, _t: states.append(s))
    conv.question.connect(lambda _q: conv.begin_turn())      # what the chat screen's ask() does

    conv.start()
    _pump(qapp, lambda: conv.state == voice_io.LISTENING)
    assert conv._mic.open

    conv._mic.speech_started.emit()
    conv._mic.utterance.emit(b"\0\0")
    _pump(qapp, lambda: questions == ["how did TCS close"])
    assert conv.state == voice_io.THINKING and not conv._mic.open     # never listens while answering

    conv.answer_text("TCS closed at 3,500. ")
    assert conv.state == voice_io.SPEAKING
    conv.answer_text("Up 1%")
    conv.answer_done()
    assert conv._speaker.said == ["TCS closed at 3,500.", "Up 1%"]
    assert conv.state == voice_io.SPEAKING and not conv._mic.open     # still talking

    conv._speaker.finish_speaking()
    _pump(qapp, lambda: conv._mic.open)
    assert conv.state == voice_io.LISTENING
    assert states[:2] == [voice_io.LOADING, voice_io.LISTENING] and voice_io.HEARING in states

    conv.stop()
    assert conv.state == voice_io.OFF and not conv._mic.open


def test_conversation_ignores_noise_and_interrupt_returns_to_listening(qapp):
    conv = _conversation(qapp, texts=["", "second try"])
    questions = []
    conv.question.connect(questions.append)
    conv.question.connect(lambda _q: conv.begin_turn())
    conv.start()
    _pump(qapp, lambda: conv.state == voice_io.LISTENING)

    conv._mic.utterance.emit(b"\0\0")                         # transcribes to nothing
    _pump(qapp, lambda: conv.state == voice_io.LISTENING and conv._mic.open)
    assert questions == []

    conv._mic.utterance.emit(b"\0\0")
    _pump(qapp, lambda: questions == ["second try"])
    conv.answer_text("A long answer. ")
    conv.interrupt()
    assert conv._speaker.pending == 0
    conv.answer_text("Ignored after the interrupt. ")
    conv.answer_done()
    assert conv._speaker.said == ["A long answer."]
    _pump(qapp, lambda: conv._mic.open)
    assert conv.state == voice_io.LISTENING


def test_conversation_reports_failures_and_switches_off(qapp):
    conv = _conversation(qapp, load_error="no model")
    failures = []
    conv.failed.connect(failures.append)
    conv.start()
    _pump(qapp, lambda: failures == ["no model"])
    assert conv.state == voice_io.OFF

    def no_mic(_parent):
        raise VoiceUnavailable("No microphone was found.")
    conv = VoiceConversation(transcriber=FakeTranscriber(), mic_factory=no_mic, speaker_factory=FakeSpeaker)
    conv.failed.connect(failures.append)
    conv.start()
    assert failures[-1] == "No microphone was found." and conv.state == voice_io.OFF


def test_stop_drops_a_transcription_still_in_flight(qapp):
    conv = _conversation(qapp)
    questions = []
    conv.question.connect(questions.append)
    conv.start()
    _pump(qapp, lambda: conv.state == voice_io.LISTENING)
    conv._mic.utterance.emit(b"\0\0")
    conv.stop()
    for _ in range(40):
        qapp.processEvents()
        time.sleep(0.005)
    assert questions == [] and conv.state == voice_io.OFF


# ── chat screen wiring ───────────────────────────────────────────────────

@pytest.fixture
def screen(qapp, monkeypatch):
    from app import AppController
    from screens.chat import ChatScreen

    monkeypatch.setattr(chat_api, "get_status", lambda: {"enabled": True, "suggested_questions": []})
    monkeypatch.setattr(ChatScreen, "_make_voice", lambda self: _conversation(qapp, texts=["how did TCS close"]))
    return ChatScreen(AppController(qapp))


def test_spoken_question_lands_in_the_transcript_and_the_answer_is_spoken(qapp, screen, monkeypatch):
    monkeypatch.setattr(chat_api, "ask", lambda q, h: iter([
        ("token", {"text": "**TCS** closed "}), ("token", {"text": "at 3,500.5."}), ("done", {}),
    ]))
    voice = screen._voice
    assert screen._voice_bar.isHidden()
    screen._voice_switch.setChecked(True)
    _pump(qapp, lambda: voice.state == voice_io.LISTENING)
    assert not screen._voice_bar.isHidden() and "Listening" in screen._voice_bar.text()

    voice._mic.utterance.emit(b"\0\0")
    _pump(qapp, lambda: len(screen._history) == 2 and not screen._busy)
    assert screen._history == [
        {"role": "user", "text": "how did TCS close"},
        {"role": "assistant", "text": "**TCS** closed at 3,500.5."},
    ]
    from components.chat_widgets import MessageBubble
    assert sorted(b.role for b in screen.findChildren(MessageBubble)) == ["assistant", "user"]
    assert voice._speaker.said == ["TCS closed at 3,500.5."]
    assert voice.state == voice_io.SPEAKING and screen._send_btn.text() == "Stop"

    screen._on_send_clicked()                                  # Stop cuts the speech short
    assert screen._send_btn.text() == "Send"
    _pump(qapp, lambda: voice._mic.open)

    screen._voice_switch.setChecked(False)
    assert voice.state == voice_io.OFF and screen._voice_bar.isHidden()


def test_typed_question_is_spoken_too_and_errors_are_read_out(qapp, screen, monkeypatch):
    from api.exceptions import ApiError

    def boom(question, history):
        raise ApiError("You can ask up to 12 questions per minute.", "chat_rate_limited", 429)
        yield  # pragma: no cover
    monkeypatch.setattr(chat_api, "ask", boom)
    screen._voice_switch.setChecked(True)
    _pump(qapp, lambda: screen._voice.state == voice_io.LISTENING)
    screen.ask("typed question")
    assert not screen._voice._mic.open
    _pump(qapp, lambda: not screen._busy)
    assert screen._voice._speaker.said == ["You can ask up to 12 questions per minute."]


def test_voice_failure_turns_the_switch_off_with_a_notice(qapp, screen):
    screen._voice._transcriber = FakeTranscriber(load_error="Couldn't load the speech recognition model.")
    screen._voice_switch.setChecked(True)
    _pump(qapp, lambda: not screen._voice_notice.isHidden())
    assert not screen._voice_switch.isChecked() and screen._voice_bar.isHidden()
    assert "Couldn't load" in screen._voice_notice.text()


def test_voice_mode_survives_a_theme_refresh_and_stops_when_hidden(qapp, screen):
    screen._voice_switch.setChecked(True)
    _pump(qapp, lambda: screen._voice.state == voice_io.LISTENING)
    screen.refresh_theme()
    assert screen._voice_switch.isChecked() and not screen._voice_bar.isHidden()
    assert "Listening" in screen._voice_bar.text()
    screen._voice_bar.set_level(0.5)
    screen._voice_bar.grab()                                   # paints without raising
    screen._voice_switch.grab()
    from PySide6.QtGui import QHideEvent
    screen.hideEvent(QHideEvent())
    assert screen._voice.state == voice_io.OFF and not screen._voice_switch.isChecked()
