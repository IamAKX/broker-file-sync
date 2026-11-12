"""User-editable parameters for the local Group A/B formula engine: the gap
threshold % and the gap FIFO depth (Group A/B aren't row-level expressions,
so these numeric knobs are the only genuine degrees of freedom in the
algorithm).

The 52-week window is deliberately NOT one of them any more. It used to be
an editable "52-week window (days)" field; it got saved as 750 on the admin
account and was then copied to every new account at signup, so 52WH / 52WL
were silently a ~2-year high / low for everyone (AMBUJACEM showed its July
2025 high of 627.2 as the "52-week high" in November 2026, when the real one
was about 574). A 52-week high has exactly one correct window, so it is now
fixed at DEFAULT_WEEK_WINDOW_DAYS (364 calendar days = 52 weeks): load()
ignores whatever is saved, and save() writes the fixed value back so the
stored copy is corrected too.

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
    all). "week_window_days" is always the fixed 52-week window, whatever
    an older build saved (see the module docstring)."""
    saved = config_store.load_json(_KEY, {})
    if not isinstance(saved, dict):
        saved = {}
    return {
        "gap_threshold_pct": _as_float(saved.get("gap_threshold_pct"), DEFAULT_GAP_THRESHOLD_PCT),
        "week_window_days": DEFAULT_WEEK_WINDOW_DAYS,
        "fifo_cap": _as_int(saved.get("fifo_cap"), DEFAULT_FIFO_CAP),
    }


def save(gap_threshold_pct: float, fifo_cap: int) -> None:
    config_store.save_json(_KEY, {
        "gap_threshold_pct": float(gap_threshold_pct),
        "week_window_days": DEFAULT_WEEK_WINDOW_DAYS,
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
