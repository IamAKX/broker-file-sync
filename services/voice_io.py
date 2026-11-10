"""Voice mode for the Ask Fuku screen (screens/chat.py): speech in, speech out.

Everything runs on the user's machine — no audio leaves it:

* ``MicListener``   — microphone capture (QtMultimedia) cut into utterances by
                      ``UtteranceDetector`` (energy-based end-of-speech detection).
* ``Transcriber``   — offline speech-to-text with faster-whisper. The model is
                      taken from ``assets/voice_models/<name>`` when the build
                      bundled it (tools/fetch_voice_model.py), otherwise it is
                      downloaded once into the Hugging Face cache.
* ``Speaker``       — the operating system's voice through Qt's QTextToSpeech.
* ``SpeechChunker`` — turns the streamed Markdown answer into speakable sentences.
* ``VoiceConversation`` — the hands-free loop tying them together:
                      listen → transcribe → (screen asks) → speak → listen again.

Qt's multimedia/speech modules and faster-whisper are imported lazily so the
rest of the app (and the test-suite) works on machines without them; a missing
piece turns voice mode off with a message instead of breaking the chat.
See docs/chatbot.md ("Voice mode").
"""

import os
import re
import threading
from array import array
from collections import deque

from PySide6.QtCore import QObject, QTimer, Signal

SAMPLE_RATE = 16000          # what Whisper wants: 16 kHz mono 16-bit PCM
_BYTES_PER_SAMPLE = 2

MODEL_NAME = os.environ.get("FUKU_VOICE_MODEL", "base.en")
_APP_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BUNDLED_MODELS_DIR = os.path.join(_APP_ROOT, "assets", "voice_models")

# Whisper leans towards words it has just "seen"; this nudges it to spell
# market vocabulary the way the chatbot expects it.
_VOCABULARY_HINT = (
    "Questions about Indian stock markets: NIFTY, BANKNIFTY, FINNIFTY, Sensex, F&O, futures, "
    "open interest, OI, VWAP, PCR, 52-week high, Reliance, TCS, Infosys, HDFC Bank, ICICI Bank, "
    "SBI, Divi's Lab, Bajaj Finance, Tata Motors, Adani Ports, Maruti, L&T, ITC."
)
# What Whisper typically invents for a cough, a keyboard click or room noise.
_PHANTOM_PHRASES = {
    "", "you", "thank you", "thanks", "thank you very much", "thanks for watching",
    "thank you for watching", "bye", "bye bye", "okay", "ok", "so", "hmm", "uh", "um",
}


class VoiceUnavailable(Exception):
    """Voice mode can't run here; str(exc) is safe to show to the user."""


# ── end-of-speech detection ──────────────────────────────────────────────────

class UtteranceDetector:
    """Cuts a stream of 16 kHz mono PCM16 into utterances by loudness.

    Speech starts after ~150 ms above the threshold (which floats above the
    measured room noise) and ends after *silence_ms* of quiet. A little audio
    from before the start is kept so the first syllable isn't clipped.
    feed() returns the utterances completed by that chunk (usually none)."""

    FRAME_MS = 30

    def __init__(self, silence_ms: int = 1100, min_speech_ms: int = 300, max_utterance_s: int = 30,
                 start_frames: int = 5, preroll_ms: int = 300, min_threshold: float = 0.012):
        self._frame_bytes = SAMPLE_RATE * self.FRAME_MS // 1000 * _BYTES_PER_SAMPLE
        self._silence_frames = max(1, silence_ms // self.FRAME_MS)
        self._min_speech_frames = max(1, min_speech_ms // self.FRAME_MS)
        self._max_frames = max_utterance_s * 1000 // self.FRAME_MS
        self._start_frames = start_frames
        self._min_threshold = min_threshold
        self._preroll: deque[bytes] = deque(maxlen=max(1, preroll_ms // self.FRAME_MS))
        self._noise = min_threshold / 3
        self.level = 0.0          # loudness of the latest frame, 0..1
        self.in_speech = False
        self.reset()

    def reset(self) -> None:
        self._pending = b""
        self._preroll.clear()
        self._frames: list[bytes] = []
        self._run = 0             # consecutive loud frames while waiting for speech
        self._quiet = 0           # consecutive quiet frames while in speech
        self._voiced = 0
        self.in_speech = False
        self.level = 0.0

    def feed(self, pcm: bytes) -> list[bytes]:
        done: list[bytes] = []
        self._pending += pcm
        while len(self._pending) >= self._frame_bytes:
            frame, self._pending = self._pending[:self._frame_bytes], self._pending[self._frame_bytes:]
            utterance = self._frame(frame)
            if utterance is not None:
                done.append(utterance)
        return done

    def _frame(self, frame: bytes) -> bytes | None:
        samples = array("h")
        samples.frombytes(frame)
        rms = (sum(s * s for s in samples) / len(samples)) ** 0.5 / 32768.0
        self.level = min(1.0, rms * 6)
        loud = rms > max(self._min_threshold, self._noise * 3)

        if not self.in_speech:
            self._preroll.append(frame)
            if loud:
                self._run += 1
                if self._run >= self._start_frames:
                    self.in_speech = True
                    self._frames = list(self._preroll)
                    self._voiced, self._quiet = self._run, 0
                    self._preroll.clear()
            else:
                self._run = 0
                self._noise = 0.95 * self._noise + 0.05 * rms   # track the room
            return None

        self._frames.append(frame)
        if loud:
            self._voiced += 1
            self._quiet = 0
        else:
            self._quiet += 1
        if self._quiet < self._silence_frames and len(self._frames) < self._max_frames:
            return None
        frames, voiced = self._frames, self._voiced
        self._frames, self._run, self._quiet, self._voiced, self.in_speech = [], 0, 0, 0, False
        if voiced < self._min_speech_frames:
            return None                                          # a click or a cough
        return b"".join(frames)


# ── answer text → speakable sentences ────────────────────────────────────────

_BOUNDARY = re.compile(r"\n+|[.!?][\"')\]*_]*[ \t]+")
_TABLE_NOTE = "The full table is on screen."


def speakable(text: str) -> str:
    """Markdown → plain words a speech engine reads naturally."""
    text = re.sub(r"`{1,3}", "", text)
    text = re.sub(r"!?\[([^\]]*)\]\([^)]*\)", r"\1", text)        # links / images → their label
    text = re.sub(r"^\s{0,3}(#{1,6}|[-*+]|\d+[.)])\s+", "", text)  # heading / list markers
    text = re.sub(r"(\*\*|__|\*|_|~~)", "", text)
    text = text.replace("₹", "rupees ").replace("&", " and ")
    return re.sub(r"\s+", " ", text).strip()


class SpeechChunker:
    """Feed it the answer as it streams; it hands back whole sentences ready to
    speak. Markdown tables are not read out — one short note replaces them."""

    def __init__(self):
        self._buf = ""
        self._line_start = True
        self._in_table = False
        self._table_noted = False

    def feed(self, text: str) -> list[str]:
        self._buf += text
        out: list[str] = []
        while True:
            m = _BOUNDARY.search(self._buf)
            if m is None:
                break
            piece, self._buf = self._buf[:m.end()], self._buf[m.end():]
            self._take(piece, out)
            if "\n" in m.group():
                self._line_start, self._in_table = True, False
        return out

    def flush(self) -> list[str]:
        out: list[str] = []
        piece, self._buf = self._buf, ""
        self._take(piece, out)
        return out

    def _take(self, piece: str, out: list[str]) -> None:
        if not piece.strip():
            return
        if self._line_start and piece.lstrip().startswith("|"):
            self._in_table = True
        self._line_start = False
        if self._in_table:
            if not self._table_noted:
                self._table_noted = True
                out.append(_TABLE_NOTE)
            return
        spoken = speakable(piece)
        if re.search(r"\w", spoken):
            out.append(spoken)


# ── speech to text ───────────────────────────────────────────────────────────

class Transcriber:
    """Offline Whisper. load() and transcribe() block — call them off the GUI thread."""

    def __init__(self, model_name: str = MODEL_NAME):
        self.model_name = model_name
        self._model = None
        self._lock = threading.Lock()

    def bundled_path(self) -> str | None:
        path = os.path.join(BUNDLED_MODELS_DIR, self.model_name)
        return path if os.path.isfile(os.path.join(path, "model.bin")) else None

    def needs_download(self) -> bool:
        """True when load() will have to fetch the model from the internet first."""
        if self._model is not None or self.bundled_path():
            return False
        try:
            from faster_whisper import download_model
            download_model(self.model_name, local_files_only=True)
            return False
        except ImportError:
            return False          # load() reports the real problem
        except Exception:
            return True

    def load(self) -> None:
        with self._lock:
            if self._model is not None:
                return
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise VoiceUnavailable(
                    "Voice input isn't available in this build (the speech recognition component is missing)."
                ) from exc
            try:
                self._model = WhisperModel(
                    self.bundled_path() or self.model_name, device="cpu", compute_type="int8",
                    cpu_threads=max(1, min(4, os.cpu_count() or 2)),
                )
            except Exception as exc:
                raise VoiceUnavailable(
                    "Couldn't load the speech recognition model. The first use needs an internet "
                    f"connection to download it. ({exc})"
                ) from exc

    def transcribe(self, pcm: bytes) -> str:
        """*pcm*: 16 kHz mono PCM16. Returns the recognised text ('' for noise)."""
        import numpy as np        # a dependency of faster-whisper

        self.load()
        audio = np.frombuffer(pcm, dtype=np.int16).astype(np.float32) / 32768.0
        with self._lock:
            segments, _info = self._model.transcribe(
                audio, language="en", beam_size=5, initial_prompt=_VOCABULARY_HINT,
                condition_on_previous_text=False, without_timestamps=True,
            )
            parts = [s.text.strip() for s in segments if s.no_speech_prob < 0.6 and s.avg_logprob > -1.0]
        text = " ".join(p for p in parts if p).strip()
        if re.sub(r"[^a-z ]", "", text.lower()).strip() in _PHANTOM_PHRASES:
            return ""
        return text


# ── microphone ───────────────────────────────────────────────────────────────

def _to_pcm16_mono_16k(data: bytes, rate: int, channels: int, is_float: bool) -> bytes:
    """Converts a device-native chunk for the fallback path (device refused 16 kHz mono)."""
    import numpy as np

    samples = np.frombuffer(data, dtype=np.float32 if is_float else np.int16).astype(np.float32)
    if not is_float:
        samples /= 32768.0
    if channels > 1:
        samples = samples[: len(samples) // channels * channels].reshape(-1, channels).mean(axis=1)
    if rate != SAMPLE_RATE and len(samples):
        n = int(len(samples) * SAMPLE_RATE / rate)
        samples = np.interp(np.linspace(0, len(samples) - 1, n), np.arange(len(samples)), samples)
    return (np.clip(samples, -1.0, 1.0) * 32767).astype(np.int16).tobytes()


class MicListener(QObject):
    """Captures the default microphone and emits one ``utterance`` (PCM16 bytes)
    per spoken phrase. ``silent`` fires once if the mic delivers nothing but
    digital silence for a few seconds — the usual sign of a blocked microphone
    permission."""

    level = Signal(float)
    speech_started = Signal()
    utterance = Signal(bytes)
    silent = Signal()

    _SILENT_AFTER_BYTES = SAMPLE_RATE * _BYTES_PER_SAMPLE * 4

    def __init__(self, parent=None):
        super().__init__(parent)
        self._detector = UtteranceDetector()
        self._source = None
        self._io = None
        self._convert = None
        self._zero_bytes = 0
        self._silent_reported = False

    def start(self) -> None:
        """Raises VoiceUnavailable if there is no usable microphone."""
        if self._source is not None:
            return
        try:
            from PySide6.QtMultimedia import QAudioFormat, QAudioSource, QMediaDevices
        except ImportError as exc:
            raise VoiceUnavailable("Audio input isn't available on this computer.") from exc
        device = QMediaDevices.defaultAudioInput()
        if device.isNull():
            raise VoiceUnavailable("No microphone was found. Connect one and switch voice mode on again.")
        fmt = QAudioFormat()
        fmt.setSampleRate(SAMPLE_RATE)
        fmt.setChannelCount(1)
        fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
        self._convert = None
        if not device.isFormatSupported(fmt):
            fmt = device.preferredFormat()
            is_float = fmt.sampleFormat() == QAudioFormat.SampleFormat.Float
            if not is_float and fmt.sampleFormat() != QAudioFormat.SampleFormat.Int16:
                fmt.setSampleFormat(QAudioFormat.SampleFormat.Int16)
            rate, channels = fmt.sampleRate(), fmt.channelCount()
            self._convert = lambda data: _to_pcm16_mono_16k(data, rate, channels, is_float)
        self._detector.reset()
        self._zero_bytes = 0
        self._source = QAudioSource(device, fmt, self)
        self._io = self._source.start()
        if self._io is None:
            self._source = None
            raise VoiceUnavailable("Couldn't open the microphone. Check that no other app is blocking it.")
        self._io.readyRead.connect(self._on_audio)

    def stop(self) -> None:
        if self._source is None:
            return
        source, self._source, self._io = self._source, None, None
        source.stop()
        source.deleteLater()
        self._detector.reset()
        self.level.emit(0.0)

    def _on_audio(self) -> None:
        if self._io is None:
            return
        data = bytes(self._io.readAll())
        if not data:
            return
        if self._convert is not None:
            data = self._convert(data)
        self._watch_for_dead_mic(data)
        was_speaking = self._detector.in_speech
        utterances = self._detector.feed(data)
        self.level.emit(self._detector.level)
        if self._detector.in_speech and not was_speaking:
            self.speech_started.emit()
        for pcm in utterances:
            self.utterance.emit(pcm)

    def _watch_for_dead_mic(self, data: bytes) -> None:
        if self._silent_reported:
            return
        if any(data):
            self._zero_bytes = 0
            return
        self._zero_bytes += len(data)
        if self._zero_bytes >= self._SILENT_AFTER_BYTES:
            self._silent_reported = True
            self.silent.emit()


# ── text to speech ───────────────────────────────────────────────────────────

class Speaker(QObject):
    """Reads sentences aloud one after another with the system voice.
    ``idle`` fires when everything queued has been spoken (or after stop())."""

    idle = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._queue: deque[str] = deque()
        self._speaking = False
        try:
            from PySide6.QtTextToSpeech import QTextToSpeech
        except ImportError as exc:
            raise VoiceUnavailable("Speech output isn't available on this computer.") from exc
        engines = [e for e in QTextToSpeech.availableEngines() if e != "mock"]
        if not engines:
            raise VoiceUnavailable("No text-to-speech voice is installed on this computer.")
        self._ready_state = QTextToSpeech.State.Ready
        self._error_state = QTextToSpeech.State.Error
        self._tts = QTextToSpeech(self)
        self._prefer_indian_english()
        self._tts.stateChanged.connect(self._on_state)

    def _prefer_indian_english(self) -> None:
        try:
            for locale in self._tts.availableLocales():
                if locale.name() == "en_IN":
                    self._tts.setLocale(locale)
                    return
        except Exception:
            pass                  # keep the system default voice

    def is_busy(self) -> bool:
        return self._speaking or bool(self._queue)

    def say(self, text: str) -> None:
        self._queue.append(text)
        if not self._speaking:
            self._next()

    def stop(self) -> None:
        self._queue.clear()
        if self._speaking:
            self._speaking = False
            self._tts.stop()
        self.idle.emit()

    def _next(self) -> None:
        if not self._queue:
            self._speaking = False
            self.idle.emit()
            return
        if self._tts.state() == self._error_state:   # say() would be a silent no-op
            self._queue.clear()
            self._speaking = False
            self.idle.emit()
            return
        self._speaking = True
        self._tts.say(self._queue.popleft())

    def _on_state(self, state) -> None:
        if self._speaking and state in (self._ready_state, self._error_state):
            self._next()


# ── the hands-free loop ──────────────────────────────────────────────────────

OFF, LOADING, LISTENING, HEARING, TRANSCRIBING, THINKING, SPEAKING = (
    "off", "loading", "listening", "hearing", "transcribing", "thinking", "speaking",
)


class VoiceConversation(QObject):
    """State machine for voice mode. The chat screen owns one and:

    * calls start() / stop() from the switch,
    * asks the question it gets from ``question`` (calling begin_turn() for every
      question, typed ones included, so the microphone closes while Fuku answers),
    * feeds the streamed answer through answer_text() and ends it with answer_done().

    The microphone is only open while LISTENING/HEARING — never while the answer
    is being spoken, so Fuku doesn't hear itself through the speakers."""

    state_changed = Signal(str, str)   # state, text for the status line
    level = Signal(float)              # microphone loudness 0..1 while listening
    question = Signal(str)             # a transcribed question, ready to ask
    failed = Signal(str)               # voice mode had to switch itself off

    _loaded = Signal(int, object)      # generation, None | error message
    _transcribed = Signal(int, object) # generation, text | Exception

    _RELISTEN_DELAY_MS = 250           # let the speaker's tail die out first

    def __init__(self, parent=None, transcriber=None, mic_factory=MicListener, speaker_factory=Speaker):
        super().__init__(parent)
        self._transcriber = transcriber or Transcriber()
        self._mic_factory, self._speaker_factory = mic_factory, speaker_factory
        self._mic = None
        self._speaker = None
        self._chunker = SpeechChunker()
        self._gen = 0                  # bumped on stop(); stale thread results are dropped
        self._answer_open = False
        self.state = OFF
        self._loaded.connect(self._on_loaded)
        self._transcribed.connect(self._on_transcribed)

    def is_on(self) -> bool:
        return self.state != OFF

    # ── switch ───────────────────────────────────────────────────────────
    def start(self) -> None:
        if self.is_on():
            return
        try:
            if self._speaker is None:
                self._speaker = self._speaker_factory(self)
                self._speaker.idle.connect(self._on_speaker_idle)
            if self._mic is None:
                self._mic = self._mic_factory(self)
                self._mic.level.connect(self.level)
                self._mic.speech_started.connect(self._on_speech_started)
                self._mic.utterance.connect(self._on_utterance)
                self._mic.silent.connect(self._on_dead_mic)
        except VoiceUnavailable as exc:
            self.failed.emit(str(exc))
            return
        downloading = self._transcriber.needs_download()
        self._set(LOADING, "Downloading the speech model (about 150 MB, first time only)…" if downloading
                  else "Getting voice mode ready…")
        gen = self._gen

        def load():
            try:
                self._transcriber.load()
                self._loaded.emit(gen, None)
            except Exception as exc:
                self._loaded.emit(gen, str(exc))
        threading.Thread(target=load, name="voice-load", daemon=True).start()

    def stop(self) -> None:
        if not self.is_on():
            return
        self._gen += 1
        self._answer_open = False
        if self._mic is not None:
            self._mic.stop()
        self._set(OFF, "")
        if self._speaker is not None:
            self._speaker.stop()

    def _fail(self, message: str) -> None:
        self.stop()
        self.failed.emit(message)

    # ── listening ────────────────────────────────────────────────────────
    def _on_loaded(self, gen: int, error) -> None:
        if gen != self._gen or self.state != LOADING:
            return
        if error:
            self._fail(error)
        else:
            self._listen()

    def _listen(self) -> None:
        if not self.is_on():
            return
        try:
            self._mic.start()
        except VoiceUnavailable as exc:
            self._fail(str(exc))
            return
        self._set(LISTENING, "Listening… ask your question")

    def _on_speech_started(self) -> None:
        if self.state == LISTENING:
            self._set(HEARING, "Listening…")

    def _on_dead_mic(self) -> None:
        if self.state in (LISTENING, HEARING):
            self._set(self.state, "Can't hear anything — check the microphone and its permission in system settings")

    def _on_utterance(self, pcm: bytes) -> None:
        if self.state not in (LISTENING, HEARING):
            return
        self._mic.stop()
        self._set(TRANSCRIBING, "Working out what you said…")
        gen = self._gen

        def work():
            try:
                self._transcribed.emit(gen, self._transcriber.transcribe(pcm))
            except Exception as exc:
                self._transcribed.emit(gen, exc)
        threading.Thread(target=work, name="voice-transcribe", daemon=True).start()

    def _on_transcribed(self, gen: int, result) -> None:
        if gen != self._gen or self.state != TRANSCRIBING:
            return
        if isinstance(result, Exception):
            self._fail(f"Speech recognition failed: {result}")
        elif not result:
            self._listen()             # noise, not a question
        else:
            self.question.emit(result)
            if self.state == TRANSCRIBING:   # the screen didn't take it (e.g. chat disabled)
                self._listen()

    # ── answering ────────────────────────────────────────────────────────
    def begin_turn(self) -> None:
        """A question (spoken or typed) is on its way to the backend."""
        if not self.is_on() or self.state == LOADING:
            return
        self._mic.stop()
        self._speaker.stop()
        self._chunker = SpeechChunker()
        self._answer_open = True
        self._set(THINKING, "Fuku is thinking…")

    def answer_text(self, text: str) -> None:
        if self._answer_open:
            self._speak(self._chunker.feed(text))

    def answer_done(self) -> None:
        """The turn is over (answered, failed or cancelled)."""
        if not self._answer_open:
            return
        self._answer_open = False
        self._speak(self._chunker.flush())
        if not self._speaker.is_busy():
            self._after_answer()

    def interrupt(self) -> None:
        """Stop talking and go back to listening."""
        if self.state in (THINKING, SPEAKING):
            self._answer_open = False
            self._speaker.stop()
            if self.state != LISTENING:     # stop() → idle normally got us there already
                self._after_answer()

    def _speak(self, sentences: list[str]) -> None:
        for sentence in sentences:
            self._speaker.say(sentence)
        if sentences and self.state == THINKING:
            self._set(SPEAKING, "Speaking… press Stop to interrupt")

    def _on_speaker_idle(self) -> None:
        if self.state == SPEAKING and not self._answer_open:
            self._after_answer()
        elif self.state == SPEAKING:
            self._set(THINKING, "Fuku is thinking…")   # caught up with the stream; more may come

    def _after_answer(self) -> None:
        if not self.is_on():
            return
        self._set(LISTENING, "Listening… ask your question")
        gen = self._gen
        QTimer.singleShot(self._RELISTEN_DELAY_MS, lambda: self._reopen_mic(gen))

    def _reopen_mic(self, gen: int) -> None:
        if gen == self._gen and self.state == LISTENING:
            self._listen()

    def _set(self, state: str, text: str) -> None:
        self.state = state
        self.state_changed.emit(state, text)
