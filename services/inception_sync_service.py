"""Syncs services.inception_bars_store's local cache from the backend's
bulk raw-bar feed (api.inception_api.get_bars -> GET /inception/bars). Two
entry points:

full_backfill(progress_cb=None): first-ever sync, or a user-requested "Full
Resync". The full historical range.

incremental_sync(progress_cb=None): every subsequent sync. Just what's new
since services.inception_bars_store.last_synced_date().

Both are just _sync_range with different start dates — ALWAYS chunked into
~1-year windows (the backend caps a single /inception/bars request at 366
days — see app.services.inception_service._MAX_BARS_RANGE_DAYS on the
backend repo), never a single unbounded request. A small delta naturally
chunks into exactly one request, so this costs nothing in the common case
and avoids a whole class of bug: an empty store, or a resync that was
interrupted partway through the historical range, both leave
last_synced_date() far enough behind "today" that an un-chunked "just sync
the delta" request would exceed the cap and get rejected outright.

Each chunk is retried up to _MAX_RETRIES times (NetworkError only — a
dropped connection / DNS hiccup / laptop-network-blip mid-backfill, not a
real rejection an immediate retry won't fix) with a short backoff, since
a full backfill is dozens of sequential requests over a minute or more —
long enough that hitting ONE transient network blip somewhere in there
is a real, observed failure mode, not a hypothetical one. Each chunk that
does succeed is upserted immediately, so even a chunk that exhausts its
retries and ultimately fails still leaves every earlier chunk's data
usable — a subsequent incremental_sync() resumes from last_synced_date()
rather than losing that progress.

progress_cb, when given, is called as progress_cb(message: str, fraction:
float | None) — fraction reflects completed chunks (never None, now that
both entry points always chunk). Callers driving this from a UI should run
it on a background QThread (see screens/inception_settings.py's
_SyncWorker) and marshal progress_cb calls back to the GUI thread
themselves; this module does no threading of its own.
"""

import time
from datetime import date, timedelta

from api import inception_api
from api.exceptions import ApiError, NetworkError
from services import inception_bars_store

# Dataset starts 2000-06-12 (see docs/INCEPTION_DATA.md in the backend
# repo) — starting a little earlier costs nothing (those chunks just come
# back with zero rows) and avoids this client needing to know the exact
# floor.
_BACKFILL_FLOOR = date(2000, 1, 1)
_CHUNK_DAYS = 365  # backend caps a single /inception/bars request at 366 days
_MAX_RETRIES = 3
_RETRY_BACKOFF_SECONDS = 1.5  # multiplied by attempt number: 1.5s, 3s, ...


class SyncError(Exception):
    """Wraps an ApiError/NetworkError raised mid-sync, after retries are
    exhausted. Each chunk commits independently (inception_bars_store.
    upsert_bars is called per chunk), so a caller retrying via
    incremental_sync afterwards — which starts from last_synced_date() —
    picks up wherever the failed run left off rather than restarting from
    scratch."""


def full_backfill(progress_cb=None, today: date | None = None) -> int:
    """First-ever sync (or a user-requested Full Resync): the full
    historical range. Returns the total number of bar-rows upserted.
    *today*, when given, overrides date.today() — lets tests control "now"
    without monkeypatching the stdlib date class."""
    return _sync_range(_BACKFILL_FLOOR, today or date.today(), progress_cb)


def incremental_sync(progress_cb=None, today: date | None = None) -> int:
    """Every subsequent sync: just what's new since last_synced_date() (the
    whole history, if nothing's synced yet at all)."""
    since = inception_bars_store.last_synced_date()
    today = today or date.today()
    date_from = (since + timedelta(days=1)) if since else _BACKFILL_FLOOR
    if date_from > today:
        return 0
    return _sync_range(date_from, today, progress_cb)


def _sync_range(date_from: date, date_to: date, progress_cb) -> int:
    chunks = _chunk_dates(date_from, date_to)
    total_rows = 0
    for i, (chunk_from, chunk_to) in enumerate(chunks):
        if progress_cb:
            progress_cb(f"Syncing {chunk_from.isoformat()} .. {chunk_to.isoformat()}…", i / len(chunks))
        result = _fetch_chunk_with_retry(chunk_from, chunk_to)
        total_rows += inception_bars_store.upsert_bars(result.get("rows", []))
    if progress_cb:
        progress_cb(f"Synced {total_rows} rows.", 1.0)
    return total_rows


def _fetch_chunk_with_retry(chunk_from: date, chunk_to: date) -> dict:
    last_exc: Exception | None = None
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return inception_api.get_bars(chunk_from, chunk_to)
        except ApiError as exc:
            # A real rejection (e.g. bad range) — retrying won't help.
            raise SyncError(str(exc)) from exc
        except NetworkError as exc:
            last_exc = exc
            if attempt < _MAX_RETRIES:
                time.sleep(_RETRY_BACKOFF_SECONDS * attempt)
    raise SyncError(str(last_exc)) from last_exc


def _chunk_dates(date_from: date, date_to: date) -> list[tuple[date, date]]:
    chunks = []
    start = date_from
    while start <= date_to:
        end = min(start + timedelta(days=_CHUNK_DAYS - 1), date_to)
        chunks.append((start, end))
        start = end + timedelta(days=1)
    return chunks
