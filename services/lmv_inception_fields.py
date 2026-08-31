"""Bridges Inception's historical derived columns (HMV's ~65 Group A/B
fields — 52WH, ATH, CQO, PQC, QT, the DAY/WEEK gap-area codes, ...) into
Live Master View's strategy formula editor.

These are offered ONLY as formula fields (a dedicated "Inception Field"
section in screens.formula_editor.ExpressionEditorDialog) — they are NOT
added as visible LMV grid columns. When an LMV strategy formula references
one, services.strategy_engine.apply_strategies resolves it against the
snapshot this module produces, keyed by normalized symbol.

── How the values are computed ──────────────────────────────────────────────
Exactly the same way HMV computes them: services.inception_compute_service.
snapshot(as_of_date), the identical call HMV's own grid is built from
(Group A/B one forward pass per instrument, _row_cache-memoized). No
reimplementation, no range gate (an as-of snapshot with no user-chosen date
window — same as services.inception_compute_service.snapshot()).

── Performance ─────────────────────────────────────────────────────────────
A cold walk across the whole synced universe (~217 instruments x up to
~6500 bars) is ~45s in pure Python — far too slow to block LMV's load. So:

1. ensure_loaded_async() computes the snapshot on a daemon thread; LMV
   renders immediately with these fields blank and re-renders (via the
   on_ready callback) once the walk finishes.
2. The finished snapshot is persisted to inception_lmv_snapshot.json next
   to inception_bars.db (same flat-JSON local-persistence pattern as
   services.inception_strategy_store / the repo-root inception_*.json
   files). A fingerprint over (bar count, latest synced date, the three
   inception_settings knobs that feed compute_group_a/b) gates reuse — a
   matching fingerprint means every later launch is an instant dict load,
   no walk at all. A sync (which changes the fingerprint) invalidates it;
   services.inception_compute_service's own post-sync clear_cache() site
   also calls clear_cache() here.
"""

import json
import os
import re
import threading
from datetime import date

from services import inception_columns

_CACHE_FILE = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "inception_lmv_snapshot.json"
)

# The request's exact column list — GROUP_A minus the P.* raw previous-day
# fields, plus the 24 bare GROUP_B gap codes (each aliased to its HIGH
# bound, exactly as services.inception_compute_service already exposes it).
_GROUP_A_FIELDS = [
    "% CHG PDC AND OPEN", "% CHG PWC AND OPEN", "DAY % CHANGE",
    "52WH", "52WL", "ATH", "ATL",
    "CQH", "CQO", "CQL", "PQH", "PQO", "PQL", "PQC", "QT", "QB",
    "CHYH", "CHYO", "CHYL", "PHYH", "PHYO", "PHYL", "PHYC", "HYT", "HYB",
    "CYH", "CYO", "CYL", "PYH", "PYO", "PYL", "PYC", "YT", "YB",
    "CFYH", "CFYO", "CFYL", "PFYH", "PFYO", "PFYL", "PFYC",
]

FIELD_CODES: list[str] = _GROUP_A_FIELDS + list(inception_columns.GROUP_B)

# Fail loud at import if a code ever drifts out of the shared catalogue —
# these MUST stay in lockstep with what inception_compute_service produces.
_CATALOGUE_CODES = set(inception_columns.all_derived_codes())
_missing = [c for c in FIELD_CODES if c not in _CATALOGUE_CODES]
assert not _missing, f"lmv_inception_fields: unknown Inception codes {_missing}"

_FIELD_CODE_SET = set(FIELD_CODES)

# ── In-memory snapshot ──────────────────────────────────────────────────────
# {normalized_symbol: {code: value}} — replaced atomically (never mutated in
# place) so a reader on the LMV worker thread always sees a consistent dict.
_snapshot: dict[str, dict] = {}
_lock = threading.Lock()
_loading = False
_loaded = False


def _description(code: str) -> str:
    return (inception_columns.GROUP_A.get(code)
            or inception_columns.GROUP_B.get(code)
            or f"Inception historical field ({code})")


def field_catalogue() -> list[dict]:
    """{"name", "signature", "description", "token"} entries for the
    "Inception Field" nav section — same shape screens.formula_editor's
    other catalogues use; token is a plain column reference."""
    return [
        {
            "name": f"[{code}]",
            "signature": f"[{code}]",
            "description": (
                f"{_description(code)}\n\n"
                f"Inception (HMV) historical value for this stock's continuous-"
                f"futures series, as of the latest synced trading day. Resolves "
                f"as a point value; blank for a stock with no F&O series."
            ),
            "token": {"type": "col", "value": code},
        }
        for code in FIELD_CODES
    ]


# ── Symbol normalization ───────────────────────────────────────────────────
# Mirrors services.inception_sector._normalize: collapse every non-
# alphanumeric char so LMV's "BAJAJ-AUTO"/"M&M" and Inception's
# "BAJAJ_AUTO_I"/"M_M_I" reduce to one comparable key.
_CANONICAL_SUFFIXES = ("_II", "_I")


def normalize_lmv_symbol(name) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(name).strip().upper())


def _normalize_inception_symbol(symbol: str) -> str:
    s = str(symbol).strip().upper()
    for suf in _CANONICAL_SUFFIXES:
        if s.endswith(suf):
            s = s[: -len(suf)]
            break
    return re.sub(r"[^A-Z0-9]", "", s)


# ── Snapshot access ────────────────────────────────────────────────────────

def current_snapshot() -> dict[str, dict]:
    """{normalized_symbol: {code: value}} — whatever's loaded right now
    (disk cache or a finished walk); {} until ensure_loaded_async has had a
    chance to populate it. Safe to call from any thread."""
    return _snapshot


def clear_cache() -> None:
    """Drop the in-memory snapshot and the on-disk cache. Call after an
    Inception sync — the fingerprint would invalidate the file anyway, but
    this also frees the resident dict and forces the next ensure_loaded_async
    to recompute."""
    global _snapshot, _loaded
    with _lock:
        _snapshot = {}
        _loaded = False
    try:
        if os.path.exists(_CACHE_FILE):
            os.remove(_CACHE_FILE)
    except OSError:
        pass


# ── Loading ────────────────────────────────────────────────────────────────

def _fingerprint() -> str:
    from services import inception_bars_store, inception_settings
    settings = inception_settings.load()
    last = inception_bars_store.last_synced_date()
    return "|".join(str(x) for x in (
        inception_bars_store.row_count(),
        last.isoformat() if last else "none",
        settings["gap_threshold_pct"],
        settings["week_window_days"],
        settings["fifo_cap"],
    ))


def _read_disk_cache() -> tuple[str | None, dict]:
    try:
        with open(_CACHE_FILE, encoding="utf-8") as fh:
            blob = json.load(fh)
        return blob.get("fingerprint"), dict(blob.get("rows") or {})
    except (OSError, ValueError):
        return None, {}


def _write_disk_cache(fingerprint: str, as_of: str, rows: dict) -> None:
    try:
        tmp = _CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump({"fingerprint": fingerprint, "as_of": as_of, "rows": rows}, fh)
        os.replace(tmp, _CACHE_FILE)
    except OSError:
        pass


def _build_snapshot() -> tuple[str, dict]:
    """(as_of_iso, {normalized_symbol: {code: value}}) computed the HMV way."""
    from services import inception_bars_store, inception_compute_service

    as_of = inception_bars_store.latest_synced_date_on_or_before(date.today())
    if as_of is None:
        return "none", {}

    rows = inception_compute_service.snapshot(as_of)
    out: dict[str, dict] = {}
    for row in rows:
        key = _normalize_inception_symbol(row["symbol"])
        if not key:
            continue
        values = row.get("values") or {}
        out[key] = {code: values.get(code) for code in FIELD_CODES}
    return as_of.isoformat(), out


def _do_load(on_ready) -> None:
    global _snapshot, _loading, _loaded
    try:
        fingerprint, cached_rows = _read_disk_cache()
        want = _fingerprint()
        if fingerprint == want and cached_rows:
            with _lock:
                _snapshot = cached_rows
                _loaded = True
            return
        # Stale cache still beats nothing while the walk runs.
        if cached_rows:
            with _lock:
                _snapshot = cached_rows
            if on_ready:
                _safe_call(on_ready)
        as_of, rows = _build_snapshot()
        _write_disk_cache(want, as_of, rows)
        with _lock:
            _snapshot = rows
            _loaded = True
    except Exception:  # never let a background walk crash the app
        pass
    finally:
        with _lock:
            _loading = False
        if on_ready:
            _safe_call(on_ready)


def _safe_call(fn) -> None:
    try:
        fn()
    except Exception:
        pass


def ensure_loaded_async(on_ready=None) -> None:
    """Kick a one-time background load of the Inception field snapshot.
    Idempotent — a second call while a walk is in flight, or after one has
    completed, is a no-op (but still fires on_ready if already loaded, so a
    caller can rely on it). on_ready() is invoked (possibly from the daemon
    thread — marshal to the GUI thread yourself) whenever _snapshot changes.
    """
    global _loading
    with _lock:
        if _loaded:
            if on_ready:
                _safe_call(on_ready)
            return
        if _loading:
            return
        _loading = True
    threading.Thread(
        target=_do_load, args=(on_ready,), name="lmv-inception-fields", daemon=True
    ).start()
