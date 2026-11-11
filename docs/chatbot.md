# Ask Fuku (AI assistant)

Sidebar → **Ask Fuku**. A chat over your own Fuku Lens data: ask in plain English and get an
answer built from a read-only database query. The backend and guardrails are
documented in the API repo — `broker-sync-api/docs/CHATBOT.md`;
the HTTP/SSE contract is `broker-sync-api/docs/API_CONTRACT.md#chat`.

## Using it

- Type a question and press **Enter**, or click one of the suggested questions.
- While it works you'll see an animated indicator with four steps — *Understanding your
  question → Building the query → Searching Fuku Lens data → Writing the answer* — then the
  answer types out.
- **Show data** under an answer reveals a preview of the result rows. The generated SQL is
  never sent to or shown in the app; the server logs it (see the backend's audit logs).
- **Stop** (the Send button while a question runs) cancels it. **New chat** clears the
  conversation. Follow-up questions ("and for Banking?") work — the last 6 turns are sent along.
- It only answers about markets, stocks and Fuku Lens data. Anything else gets a polite
  refusal. It describes what the data shows; it does not give buy/sell recommendations.
- Some things are not in the database and it will say so: sector/index reports, EMV/HMV trend
  classifications, backtests, Market Profile, option chain, real-time ticks.

## Live market questions (from the running LMV)

Ask about the market **right now** — "What is Reliance trading at now?", "Which stocks are falling
the most right now?", "Which sector is strongest in the live market?", "Show the current DT and DB
for TCS" — and Fuku answers from your **Live Master View** as it is at that moment, starting the
answer with *Live as of <time>*.

- The line under the input shows the state: **● Live market data: on — LMV as of 10:32:05, 216
  stocks**, or **○ Live market data: off — …** with what is missing.
- Before answering a live question Fuku checks that LMV is running with data. If it isn't, it
  does not fall back to old data; it tells you exactly what to do — which Data Import files are
  not loaded yet, or that the files are loaded and **Run Watcher** has not been clicked, or that
  the LMV window was closed.
- Any column in your LMV grid can be asked about, including your active strategy columns.
- If the live Excel feed is unreadable (LMV shows the stale-prices warning) or the grid has not
  updated for more than 5 minutes, the answer says so.
- It is one snapshot taken when you ask. It cannot tell what a value was a few minutes ago or how
  it moved between two moments today.
- Questions about past dates, closes and history work exactly as before, whether or not LMV is running.

## Voice mode

Switch **Voice mode** on (top right of the screen) to talk to Fuku hands-free:

1. The strip above the input shows **Listening…** with a live microphone level. Ask your question
   and stop talking — about a second of silence sends it.
2. The question appears in the chat exactly like a typed one, the answer types out as usual and is
   **read aloud** at the same time. Tables are not read out (Fuku says the table is on screen).
3. When it finishes speaking it listens again. Carry on until you switch voice mode off.

- **Stop** interrupts a spoken answer (or cancels a running question) and goes back to listening.
- You can still type while voice mode is on; typed questions are answered aloud too.
- The microphone is closed while Fuku is thinking or speaking, so it never hears itself — which
  also means you can't interrupt by talking; use **Stop**.
- Voice mode switches itself off when you leave the screen or minimise the app.
- Your speech is turned into text **on your computer** (offline Whisper model); no audio is
  uploaded. Only the resulting text goes to the server, like any typed question. The voice is
  a neural one that also runs on your computer (Kokoro); if a build doesn't include it, the
  operating system's own voice is used instead.
- If the strip says it *can't hear anything*, check the microphone and the OS microphone
  permission (Windows: Settings → Privacy & security → Microphone → "Let desktop apps access your
  microphone"; macOS: System Settings → Privacy & Security → Microphone).
- Stock names are the hardest thing for speech recognition — check the transcribed question in the
  chat if an answer looks off, and type the symbol when it keeps mishearing one.

If the banner says *"not enabled for this deployment"*, the server has `CHAT_ENABLED=false`.

## How it's built

| File | Role |
|---|---|
| `screens/chat.py` | `ChatScreen`: transcript, input, suggestion chips, Stop/New chat, event handling |
| `components/chat_widgets.py` | `ThinkingIndicator` (painted animation), `TypewriterLabel` (smooth streamed text), `MessageBubble` (+ collapsible query/data, fade-in) |
| `services/voice_io.py` | Voice mode: `MicListener` (QtMultimedia capture) + `UtteranceDetector` (end-of-speech), `Transcriber` (faster-whisper, offline), `NeuralSpeaker` (offline neural voice via sherpa-onnx, played with QAudioSink) with `Speaker` (QTextToSpeech, the OS voice) as fallback, `SpeechChunker` (Markdown → sentences), `VoiceConversation` (the listen → transcribe → ask → speak loop) |
| `tools/fetch_voice_model.py` | Build step: downloads the Whisper model and the neural voice into `assets/voice_models/` so they ship inside the build |
| `services/lmv_chat_context.py` | The "live" block sent with every question: the LMV grid as displayed (`build()`), or `running: False` + the reason (which files are missing / Run Watcher not clicked); `summary()` for the status line. Read via `AppController.get_lmv_chat_context()` |
| `api/chat_api.py` | `get_status()`, `ask()` (generator of `(event, data)`), `parse_sse()` |
| `api/client.py` → `post_stream()` | Authenticated streaming POST with the same 401-refresh behaviour as other calls |
| `api/endpoints.py` | `CHAT_STATUS`, `CHAT_ASK` |

Flow: `ChatScreen.ask()` starts a daemon thread that iterates `chat_api.ask()` and emits each
event to the GUI thread through one Qt signal tagged with a conversation token (events from a
cleared/superseded conversation are dropped). `stage` events advance the indicator, `token`
events feed the typewriter, `rows`/`sql` fill the details panel, `error` turns the bubble into
an error message and removes the failed question from the history so it doesn't skew
follow-ups.

Animation is all `QPainter` + `QTimer` (no assets), follows the active theme, and its timers
stop when the widget is hidden. Theme changes rebuild the screen and keep the transcript
(`refresh_theme`); a theme change mid-question abandons that question.

Live questions: `ChatScreen.ask()` snapshots the LMV on the GUI thread
(`LiveViewerWindow._chat_disp` / `_chat_updated_at`, recorded on every tick) and sends it as
`live` in the `/chat/ask` body (columnar, ~230 KB for 216 stocks × 110 columns). The backend loads
it into a per-request `lmv_live` table next to the archive views, so the same query pipeline
answers it; when LMV is off the backend replies with the `reason` text. If the server or a proxy
rejects the body (400/413/422) the question is re-sent without the grid, and if the LMV state
can't be read at all the question goes out without a `live` block — a live-data problem never
stops a question from being answered.

Nothing is persisted locally; the conversation lives in memory for the session.

## Changing it

- **Starter questions** come from the server (`GET /chat/status`); the offline fallback list is
  `chat_api_default_suggestions()` in `screens/chat.py`.
- **Stage names/labels** — `STAGES` in `components/chat_widgets.py` must match the stage keys the
  backend emits (`services/chat/pipeline.py`).
- **Speech model** — `MODEL_NAME` in `services/voice_io.py` (`base.en`, ~145 MB; override with the
  `FUKU_VOICE_MODEL` environment variable, e.g. `small.en` for better accuracy at ~480 MB and slower
  transcription). A build bundles whatever `tools/fetch_voice_model.py` downloaded; a dev run without
  the bundled copy downloads the model on first use into the Hugging Face cache.
- **The voice** — `TTS_MODEL_NAME` / `TTS_SPEAKER_ID` / `TTS_SPEED` in `services/voice_io.py`, or the
  `FUKU_TTS_MODEL`, `FUKU_TTS_SPEAKER`, `FUKU_TTS_SPEED` environment variables. The default is Kokoro
  (`kokoro-en-v0_19`, ~360 MB) speaker 1. Its speakers: 0 af, 1 af_bella, 2 af_nicole, 3 af_sarah,
  4 af_sky, 5 am_adam, 6 am_michael (American); 7 bf_emma, 8 bf_isabella, 9 bm_george, 10 bm_lewis
  (British). Any sherpa-onnx Kokoro or Piper model folder works — e.g. `vits-piper-en_US-amy-medium`
  (~80 MB) is less natural but about 8x faster, for slow PCs. Run `python tools/fetch_voice_model.py`
  after changing the model; dev runs without the folder fall back to the OS voice.
- **Recognition vocabulary / end-of-speech timing** — `_VOCABULARY_HINT` and `UtteranceDetector`'s
  `silence_ms` in `services/voice_io.py`.
- **Backend URL** — the usual `BROKER_SYNC_API_URL` environment variable (`api/config.py`).

## Tests

`tests/test_chat_screen.py` — SSE parsing, a full streamed turn (history, thinking → answer,
details toggle), server error handling, refusals, follow-up history, clear/stale events,
disabled banner, theme refresh, and the indicator's painting/stage tracking.

`tests/test_lmv_chat_context.py` — LMV not running (never opened, files missing, watcher not
started, window closed, no data), the grid payload (symbols, sector, empty/NaN cells, strict JSON),
feed/staleness warnings, request body with and without `live`, the rejected-grid retry, and the
screen's status line and failure fallback.

`tests/test_voice_io.py` — end-of-speech detection on synthetic audio, Markdown → speech
chunking, the conversation loop with a fake microphone/speaker/transcriber (noise, interrupt,
failures, stale results), and the screen wiring (spoken question → transcript + spoken answer,
Stop, failure notice, theme refresh, hide). No real audio device or model is used.
