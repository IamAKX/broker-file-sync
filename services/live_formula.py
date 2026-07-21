"""
Blends services.formula_engine's stored-history baseline with today's live
Sharekhan tick to produce genuinely live values for the 8 LMV columns that
need an intraday update: CWO, CMO, CWATP, CMATP, WEEK % CHANGE,
MONTH % CHANGE, DAY TO, CWTO. See services.live_merge.LiveDataReader for
where this gets called (every Sharekhan tick, database ExternalImport mode
only) and services.formula_engine.compute_live_baseline_for_symbol for the
baseline this is blended with.

Pure/offline — takes already-fetched baseline + live values, does no I/O and
makes no assumption about polling cadence.
"""


def _avg_with_live(prev_values: list, live_value: float) -> float:
    vals = list(prev_values) + [live_value]
    return sum(vals) / len(vals)


def apply_live_overlay(baseline: dict, live: dict) -> dict:
    """
    baseline: one symbol's dict from formula_engine.compute_live_baseline_for_symbol
              (is_first_trading_day_of_week/month, prev_atp_values_week/month,
              prev_qty_values_week, pwc, pmc). {} is valid (e.g. a symbol with
              no stored history yet) and simply yields fewer/no overrides.
    live: today's Sharekhan tick for this symbol —
          {"open", "current", "avg_rate", "qty", "diffpcnt"}, already coerced
          to float/None by the caller. Any may be None (blank/stale cell).

    Returns only the codes this tick has enough live input to (re)compute —
    a code is OMITTED, never set to None, when its live input is missing, so
    a single bad/blank tick doesn't blank out an otherwise-good displayed
    value. Callers must leave any omitted code's existing value untouched.
    """
    open_v = live.get("open")
    current_v = live.get("current")
    avg_rate_v = live.get("avg_rate")
    qty_v = live.get("qty")
    diffpcnt_v = live.get("diffpcnt")

    out = {}

    cwatp = cmatp = None
    if avg_rate_v is not None:
        cwatp = _avg_with_live(baseline.get("prev_atp_values_week", []), avg_rate_v)
        cmatp = _avg_with_live(baseline.get("prev_atp_values_month", []), avg_rate_v)
        out["CWATP"] = cwatp
        out["CMATP"] = cmatp

    week_pct = month_pct = None
    pwc, pmc = baseline.get("pwc"), baseline.get("pmc")
    if current_v is not None and pwc:
        week_pct = (current_v - pwc) / pwc * 100
        out["WEEK % CHANGE"] = week_pct
    if current_v is not None and pmc:
        month_pct = (current_v - pmc) / pmc * 100
        out["MONTH % CHANGE"] = month_pct

    if qty_v is not None and avg_rate_v is not None and diffpcnt_v is not None:
        out["DAY TO"] = (qty_v * avg_rate_v) / 10_000_000 * (abs(diffpcnt_v) / 100)

    if baseline.get("is_first_trading_day_of_week") and open_v is not None:
        out["CWO"] = open_v
    if baseline.get("is_first_trading_day_of_month") and open_v is not None:
        out["CMO"] = open_v

    if qty_v is not None and cwatp is not None and week_pct is not None:
        week_qty_sum = sum(baseline.get("prev_qty_values_week", [])) + qty_v
        out["CWTO"] = (week_qty_sum * cwatp) / 10_000_000 * (abs(week_pct) / 100)

    return out
