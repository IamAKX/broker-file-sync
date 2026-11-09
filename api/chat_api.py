# api/chat_api.py
"""Backend client for the AI assistant (see broker-sync-api's app/routers/chat.py
and docs/CHATBOT.md). /chat/ask answers as Server-Sent Events so the UI can
animate each pipeline stage and type the answer out as it streams."""

import json
from collections.abc import Iterable, Iterator

from api.client import api_client
from api.endpoints import CHAT_ASK, CHAT_STATUS
from api.exceptions import NetworkError

# Per-read ceiling while streaming. A model call can sit silent for a while
# (SQL generation) before the first event, but never this long.
_STREAM_READ_TIMEOUT_SECONDS = 90


def get_status() -> dict:
    """{"enabled", "model_id", "suggested_questions"}."""
    return api_client.get(CHAT_STATUS)


def parse_sse(lines: Iterable[str]) -> Iterator[tuple[str, dict]]:
    """Turns raw SSE text lines into (event_name, data_dict) pairs. Events are
    separated by a blank line; unparseable data is skipped rather than aborting
    the whole answer."""
    event, data_lines = "message", []
    for line in lines:
        if line == "":
            if data_lines:
                try:
                    yield event, json.loads("\n".join(data_lines))
                except json.JSONDecodeError:
                    pass
            event, data_lines = "message", []
        elif line.startswith("event:"):
            event = line[6:].strip()
        elif line.startswith("data:"):
            data_lines.append(line[5:].lstrip())
    if data_lines:
        try:
            yield event, json.loads("\n".join(data_lines))
        except json.JSONDecodeError:
            pass


def ask(question: str, history: list[dict]) -> Iterator[tuple[str, dict]]:
    """Yields (event, data) as the server streams them. Raises ApiError for a
    rejected request (chat disabled, rate-limited, ...) and NetworkError if the
    connection drops mid-stream. *history*: [{"role": "user"|"assistant", "text": ...}]."""
    response = api_client.post_stream(
        CHAT_ASK, {"question": question, "history": history}, timeout=_STREAM_READ_TIMEOUT_SECONDS,
    )
    try:
        # requests decodes SSE as latin-1 unless told otherwise (no charset in the header).
        response.encoding = "utf-8"
        yield from parse_sse(response.iter_lines(decode_unicode=True))
    except Exception as exc:  # requests.RequestException and friends
        if isinstance(exc, GeneratorExit):
            raise
        raise NetworkError(f"The connection was interrupted: {exc}") from exc
    finally:
        response.close()
