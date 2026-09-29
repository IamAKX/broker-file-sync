"""
Configurable support/resistance level engine for the Fuku Live Report
(resources/report/Fuku_Live_Report_Requirements...) — "for a BUY alert,
show possible nearby resistance levels; for a SELL alert, show possible
nearby support levels."

Operates on a plain ascending list of daily bars ({"date","high","low",
"close"}) — no I/O of its own. services.fuku_live_report_data sources
those bars from services.inception_bars_store (Inception's local, offline-
safe historical cache) rather than a live network fetch — a report-
generation path making an unstubbed/unbounded network call is exactly the
kind of hang this codebase already hit once tonight (see services.
lmv_report_data's own "include_backend" opt-in pattern). A symbol
Inception hasn't synced simply gets no levels (level_sources returns {}),
not a crash or a hang.

Camarilla pivots use the SAME formula every other "camarilla" calculation
in this codebase already uses (services.formula_engine's DR3/DR4/DS3/DS4:
range = High - Low; R3 = Close + range*1.1/4; R4 = Close + range*1.1/2,
mirrored for S3/S4) — not reimplemented differently here.
"""

from datetime import date


def _week_key(d: date) -> tuple:
    iso_year, iso_week, _ = d.isocalendar()
    return iso_year, iso_week


def _month_key(d: date) -> tuple:
    return d.year, d.month


def level_sources(bars: list, as_of: date | None = None) -> dict:
    """{"label": {"high": float|None, "low": float|None}} (or, for
    "Camarilla", {"R3","R4","S3","S4"}) for every configured level source,
    computed from *bars* (ascending daily bars) up to and including
    *as_of* (the whole list if as_of is None). {} if there's no data at
    all — a source with no covering data (e.g. no prior week yet) is
    simply absent, not zero.
    """
    if as_of is not None:
        bars = [b for b in bars if b["date"] <= as_of]
    if not bars:
        return {}

    last = bars[-1]
    prev = bars[-2] if len(bars) >= 2 else None

    sources = {"Current Day": {"high": last["high"], "low": last["low"]}}
    if prev:
        sources["Previous Day"] = {"high": prev["high"], "low": prev["low"]}

    current_week = _week_key(last["date"])
    current_week_bars = [b for b in bars if _week_key(b["date"]) == current_week]
    sources["Current Week"] = {
        "high": max(b["high"] for b in current_week_bars),
        "low": min(b["low"] for b in current_week_bars),
    }
    prior_week_bars = [b for b in bars if _week_key(b["date"]) < current_week]
    if prior_week_bars:
        last_prior_week = _week_key(prior_week_bars[-1]["date"])
        prev_week_bars = [b for b in prior_week_bars if _week_key(b["date"]) == last_prior_week]
        sources["Previous Week"] = {
            "high": max(b["high"] for b in prev_week_bars),
            "low": min(b["low"] for b in prev_week_bars),
        }

    current_month = _month_key(last["date"])
    current_month_bars = [b for b in bars if _month_key(b["date"]) == current_month]
    sources["Current Month"] = {
        "high": max(b["high"] for b in current_month_bars),
        "low": min(b["low"] for b in current_month_bars),
    }
    prior_month_bars = [b for b in bars if _month_key(b["date"]) < current_month]
    if prior_month_bars:
        last_prior_month = _month_key(prior_month_bars[-1]["date"])
        prev_month_bars = [b for b in prior_month_bars if _month_key(b["date"]) == last_prior_month]
        sources["Previous Month"] = {
            "high": max(b["high"] for b in prev_month_bars),
            "low": min(b["low"] for b in prev_month_bars),
        }

    if prev is not None:
        rng = prev["high"] - prev["low"]
        sources["Camarilla"] = {
            "R3": prev["close"] + rng * 1.1 / 4,
            "R4": prev["close"] + rng * 1.1 / 2,
            "S3": prev["close"] - rng * 1.1 / 4,
            "S4": prev["close"] - rng * 1.1 / 2,
        }

    return sources


def _flatten(sources: dict) -> list:
    flat = []
    for label, values in sources.items():
        if label == "Camarilla":
            for sub_label, price in values.items():
                if price is not None:
                    flat.append((f"Camarilla {sub_label}", price))
        else:
            for side in ("high", "low"):
                price = values.get(side)
                if price is not None:
                    flat.append((f'{label} {side.title()}', price))
    return flat


def nearby_levels(sources: dict, current_price: float, direction: str, max_levels: int = 3) -> list:
    """Flattens *sources* into individual {"label","price","distance",
    "distance_pct"} entries on the relevant side of *current_price* —
    "Possible Resistance" (above) for a BUY alert, "Possible Support"
    (below) for a SELL alert — sorted by closeness, capped at *max_levels*
    (spec: "the number of displayed levels must be configurable" — this IS
    that config knob)."""
    want_above = direction == "BUY"
    candidates = [
        (label, price) for label, price in _flatten(sources)
        if (price > current_price if want_above else price < current_price)
    ]
    candidates.sort(key=lambda lp: abs(lp[1] - current_price))

    out = []
    for label, price in candidates[:max_levels]:
        distance = price - current_price
        distance_pct = (distance / current_price * 100) if current_price else None
        out.append({"label": label, "price": price, "distance": distance, "distance_pct": distance_pct})
    return out


def confluence_zones(sources: dict, tolerance_pct: float = 0.5, min_factors: int = 2) -> list:
    """Groups levels that cluster within *tolerance_pct* of each other —
    spec section 9.3: "3 factors near ₹4,321". Returns [{"price","count",
    "labels"}], sorted by factor count desc then price."""
    flat = sorted(_flatten(sources), key=lambda lp: lp[1])
    used = [False] * len(flat)
    zones = []
    for i, (label_i, price_i) in enumerate(flat):
        if used[i] or price_i == 0:
            continue
        group = [(label_i, price_i)]
        used[i] = True
        for j in range(i + 1, len(flat)):
            if used[j]:
                continue
            label_j, price_j = flat[j]
            if abs(price_j - price_i) / abs(price_i) * 100 <= tolerance_pct:
                group.append((label_j, price_j))
                used[j] = True
        if len(group) >= min_factors:
            zones.append({
                "price": sum(p for _, p in group) / len(group),
                "count": len(group),
                "labels": [lbl for lbl, _ in group],
            })

    zones.sort(key=lambda z: (-z["count"], z["price"]))
    return zones
