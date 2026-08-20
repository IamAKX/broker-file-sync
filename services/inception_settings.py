"""User-editable parameters for the local Group A/B formula engine (see
services.inception_formula_engine's module docstring for why exactly these
three — gap threshold %, 52-week window length, gap FIFO depth — are the
ones exposed: Group A/B aren't row-level expressions, so these numeric
knobs are the only genuine degrees of freedom in the algorithm).

Persisted via services.config_store's generic save_json/load_json (the same
mechanism behind e.g. LMV highlight colors) — server-synced with a local
read-cache fallback, so the setting roams with the user across devices with
no new backend endpoint needed.
"""

from services import config_store
from services.inception_formula_engine import (
    DEFAULT_FIFO_CAP,
    DEFAULT_GAP_THRESHOLD_PCT,
    DEFAULT_WEEK_WINDOW_DAYS,
)

_KEY = "inception_formula_settings"


def load() -> dict:
    """Returns {"gap_threshold_pct": float, "week_window_days": int,
    "fifo_cap": int} — saved values, backfilled with defaults for any key
    never saved (including on a first-ever load, when nothing's saved at
    all)."""
    saved = config_store.load_json(_KEY, {})
    if not isinstance(saved, dict):
        saved = {}
    return {
        "gap_threshold_pct": _as_float(saved.get("gap_threshold_pct"), DEFAULT_GAP_THRESHOLD_PCT),
        "week_window_days": _as_int(saved.get("week_window_days"), DEFAULT_WEEK_WINDOW_DAYS),
        "fifo_cap": _as_int(saved.get("fifo_cap"), DEFAULT_FIFO_CAP),
    }


def save(gap_threshold_pct: float, week_window_days: int, fifo_cap: int) -> None:
    config_store.save_json(_KEY, {
        "gap_threshold_pct": float(gap_threshold_pct),
        "week_window_days": int(week_window_days),
        "fifo_cap": int(fifo_cap),
    })


def _as_float(v, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except (TypeError, ValueError):
        return default


def _as_int(v, default: int) -> int:
    try:
        return int(v) if v is not None else default
    except (TypeError, ValueError):
        return default
