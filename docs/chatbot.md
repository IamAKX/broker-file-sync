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

If the banner says *"not enabled for this deployment"*, the server has `CHAT_ENABLED=false`.

## How it's built

| File | Role |
|---|---|
| `screens/chat.py` | `ChatScreen`: transcript, input, suggestion chips, Stop/New chat, event handling |
| `components/chat_widgets.py` | `ThinkingIndicator` (painted animation), `TypewriterLabel` (smooth streamed text), `MessageBubble` (+ collapsible query/data, fade-in) |
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

Nothing is persisted locally; the conversation lives in memory for the session.

## Changing it

- **Starter questions** come from the server (`GET /chat/status`); the offline fallback list is
  `chat_api_default_suggestions()` in `screens/chat.py`.
- **Stage names/labels** — `STAGES` in `components/chat_widgets.py` must match the stage keys the
  backend emits (`services/chat/pipeline.py`).
- **Backend URL** — the usual `BROKER_SYNC_API_URL` environment variable (`api/config.py`).

## Tests

`tests/test_chat_screen.py` — SSE parsing, a full streamed turn (history, thinking → answer,
details toggle), server error handling, refusals, follow-up history, clear/stale events,
disabled banner, theme refresh, and the indicator's painting/stage tracking.
