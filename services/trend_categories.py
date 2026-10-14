"""
User-defined trend categories for the EMV EOD "Trend" report (resources/
report/EMV_EOD_Report_Requirements... sections 5-7): Bullish, Bottom Up, ...
are NOT hard-coded rules — each category simply names, per timeframe, which
Inception strategies (already built in Inception > Strategy Builder, where
the actual conditions live) put a stock in that category. A stock is in a
category for a timeframe when it passes ANY of that cell's strategies, so a
"Monthly Strong Bullish" built from three strategies lists the stocks of all
three. Categories are editable, orderable, can be deactivated, coloured and
added to; saved as one JSON blob under a config_store key like Fuku score
configs and saved reports.
"""

import re
import uuid

from services import config_store

_KEY = "emv_trend_categories"

TIMEFRAMES = ["Daily", "Weekly", "Monthly", "Quarterly"]

# Spec 5.1's default set, in display order, with a colour family each
# (greens bullish, reds bearish, ambers/blues for the in-between states).
_DEFAULTS = [
    ("Bullish", "#16a34a", "User-defined conditions indicating a bullish trend state."),
    ("Extremely Bullish", "#15803d", "Stronger/more restrictive bullish conditions."),
    ("Bearish", "#dc2626", "User-defined conditions indicating a bearish trend state."),
    ("Extremely Bearish", "#991b1b", "Stronger/more restrictive bearish conditions."),
    ("Bottom Up", "#0891b2", "Improvement/reversal beginning from lower levels."),
    ("Top Down", "#be123c", "Deterioration/reversal beginning from higher levels."),
    ("Bullish Sideways", "#65a30d", "Bullish bias while conditions remain within a sideways regime."),
    ("Bearish Sideways", "#ea580c", "Bearish bias while conditions remain within a sideways regime."),
    ("Sideways", "#64748b", "Range/neutral condition."),
]


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or uuid.uuid4().hex[:8]


def new_category(name: str, color: str = "#2979FF", description: str = "", order: int | None = None) -> dict:
    return {
        "id": _slug(name), "name": name, "description": description, "color": color,
        "active": True, "order": order if order is not None else 0,
        "rules": {tf: [] for tf in TIMEFRAMES},
    }


def default_categories() -> list:
    return [new_category(n, c, d, i) for i, (n, c, d) in enumerate(_DEFAULTS)]


def _normalize(category: dict) -> dict:
    cat = dict(category)
    rules = cat.get("rules") if isinstance(cat.get("rules"), dict) else {}
    cat["rules"] = {tf: [s for s in (rules.get(tf) or []) if isinstance(s, str)] for tf in TIMEFRAMES}
    cat.setdefault("active", True)
    cat.setdefault("color", "#2979FF")
    cat.setdefault("description", "")
    cat.setdefault("order", 0)
    return cat


def load_all() -> list:
    """Every category (active or not) in display order; the spec's default
    set when nothing has been saved yet."""
    saved = config_store.load_json(_KEY, None)
    valid = [c for c in saved if isinstance(c, dict) and c.get("id") and c.get("name")] \
        if isinstance(saved, list) else []
    cats = [_normalize(c) for c in valid]
    if not cats:
        cats = default_categories()
    return sorted(cats, key=lambda c: c.get("order", 0))


def save_all(categories: list) -> None:
    """Persists *categories* in the order given (their position becomes
    their display order)."""
    out = []
    for i, c in enumerate(categories):
        cat = _normalize(c)
        cat["order"] = i
        out.append(cat)
    config_store.save_json(_KEY, out)


def active_categories() -> list:
    return [c for c in load_all() if c.get("active")]


def strategies_for(category: dict, timeframe: str) -> list:
    """Inception strategy ids behind (category, timeframe)."""
    return list((category.get("rules") or {}).get(timeframe) or [])


def all_strategy_ids(categories: list, timeframes: list | None = None) -> list:
    """Every distinct strategy id used by *categories* across *timeframes*
    (all by default), first-seen order."""
    seen = {}
    for cat in categories:
        for tf in (timeframes or TIMEFRAMES):
            for sid in strategies_for(cat, tf):
                seen.setdefault(sid, True)
    return list(seen)
