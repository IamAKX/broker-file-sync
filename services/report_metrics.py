"""
Pure-math helpers shared by every report type's data layer — directional
trade yield, blended horizon yield, win rate, efficiency ratios (Sharpe/
Sortino/Calmar), Alpha vs a benchmark return series, a simple hypothetical-
investment simulation, and date-bucketing for a horizon performance curve.
No I/O, no framework dependency — easy to unit test in isolation from
whatever gathers the underlying return series (services.lmv_report_data
etc.).
"""

import math
import statistics
from datetime import date, datetime, timedelta

TIMEFRAME_DAILY = "daily"
TIMEFRAME_WEEKLY = "weekly"
TIMEFRAME_MONTHLY = "monthly"
TIMEFRAME_QUARTERLY = "quarterly"
TIMEFRAME_CUSTOM = "custom"


def directional_yield(entry_price, exit_price, direction: str) -> float | None:
    """((Exit - Entry) / Entry) * 100 * (+1 BUY / -1 SELL) — the core LMV
    EOD calculation (spec section 1.1)."""
    if entry_price is None or exit_price is None or entry_price == 0:
        return None
    pct = (exit_price - entry_price) / entry_price * 100
    return pct if direction == "BUY" else -pct


def blended_yield(directional_yields: list) -> float | None:
    """Arithmetic mean of directional yields — spec section 1.2."""
    values = [v for v in directional_yields if v is not None]
    if not values:
        return None
    return sum(values) / len(values)


def win_rate(directional_yields: list) -> float | None:
    values = [v for v in directional_yields if v is not None]
    if not values:
        return None
    wins = sum(1 for v in values if v > 0)
    return wins / len(values) * 100


def sharpe_ratio(returns: list, risk_free_rate: float = 0.0) -> float | None:
    values = [r for r in returns if r is not None]
    if len(values) < 2:
        return None
    excess = [v - risk_free_rate for v in values]
    stdev = statistics.pstdev(excess)
    if stdev == 0:
        return None
    return statistics.mean(excess) / stdev


def sortino_ratio(returns: list, target_return: float = 0.0) -> float | None:
    values = [r for r in returns if r is not None]
    if len(values) < 2:
        return None
    downside = [min(0.0, v - target_return) for v in values]
    downside_dev = math.sqrt(sum(d ** 2 for d in downside) / len(downside))
    if downside_dev == 0:
        return None
    return (statistics.mean(values) - target_return) / downside_dev


def max_drawdown(cumulative_curve: list) -> float | None:
    """*cumulative_curve*: running cumulative return values. Returns the
    largest peak-to-trough decline as a positive number (percentage
    points), or None for an empty curve."""
    values = [v for v in cumulative_curve if v is not None]
    if not values:
        return None
    peak = values[0]
    max_dd = 0.0
    for v in values:
        peak = max(peak, v)
        max_dd = max(max_dd, peak - v)
    return max_dd


def calmar_ratio(returns: list) -> float | None:
    values = [r for r in returns if r is not None]
    if not values:
        return None
    cumulative = []
    running = 0.0
    for v in values:
        running += v
        cumulative.append(running)
    dd = max_drawdown(cumulative)
    total_return = cumulative[-1] if cumulative else None
    if not dd or total_return is None:
        return None
    return total_return / dd


def alpha(returns: list, benchmark_returns: list) -> float | None:
    """Simple Alpha: mean(returns) - mean(benchmark_returns). Both series
    are assumed already aligned/trimmed by the caller (e.g. Strategy A's
    per-trade yields vs Strategy B's, or vs an index return series)."""
    values = [r for r in returns if r is not None]
    bench = [b for b in benchmark_returns if b is not None]
    if not values or not bench:
        return None
    return statistics.mean(values) - statistics.mean(bench)


def investment_simulation(starting_amount: float, return_pct: float | None) -> dict:
    """Ending Value = Starting Investment x (1 + Return / 100) — spec
    section 14.4. Labeled a hypothetical simulation by every caller, never
    presented as an actual P&L."""
    if return_pct is None:
        return {"starting": starting_amount, "ending": None, "profit": None, "return_pct": None}
    ending = starting_amount * (1 + return_pct / 100)
    return {
        "starting": starting_amount,
        "ending": ending,
        "profit": ending - starting_amount,
        "return_pct": return_pct,
    }


def investment_equity_curve(starting_amount: float, period_returns: list) -> list:
    """Compounded equity curve, one value per *period_returns* entry — a
    None period (no trades that bucket) carries the value forward flat
    rather than breaking the curve."""
    curve = []
    value = starting_amount
    for r in period_returns:
        if r is not None:
            value = value * (1 + r / 100)
        curve.append(value)
    return curve


# ── Date bucketing for a horizon performance curve ──────────────────────

def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def bucket_key(when, timeframe: str) -> str:
    """Maps *when* (date/datetime/iso-str) to a bucket label for the given
    *timeframe* granularity — "custom" buckets daily, same as "daily"."""
    d = _as_date(when)
    if timeframe == TIMEFRAME_WEEKLY:
        iso_year, iso_week, _ = d.isocalendar()
        return f"{iso_year}-W{iso_week:02d}"
    if timeframe == TIMEFRAME_MONTHLY:
        return f"{d.year}-{d.month:02d}"
    if timeframe == TIMEFRAME_QUARTERLY:
        quarter = (d.month - 1) // 3 + 1
        return f"{d.year}-Q{quarter}"
    return d.isoformat()


def bucket_range(date_from, date_to, timeframe: str) -> list:
    """Ordered list of every bucket key between *date_from* and *date_to*
    inclusive (even ones with no data — a report's x-axis should show the
    full selected horizon, not just days that happened to have trades)."""
    start, end = _as_date(date_from), _as_date(date_to)
    if start > end:
        start, end = end, start
    keys = []
    seen = set()
    current = start
    while current <= end:
        key = bucket_key(current, timeframe)
        if key not in seen:
            seen.add(key)
            keys.append(key)
        current += timedelta(days=1)
    return keys


def bucketed_series(items: list, when_key: str, value_key: str, bucket_keys: list,
                     timeframe: str) -> list:
    """Groups *items* (list of dicts) into *bucket_keys* by
    bucket_key(item[when_key], timeframe), averaging item[value_key] within
    each bucket. Returns one value per bucket_keys entry, None where no
    item fell in that bucket."""
    grouped: dict = {}
    for item in items:
        when = item.get(when_key)
        value = item.get(value_key)
        if when is None or value is None:
            continue
        key = bucket_key(when, timeframe)
        grouped.setdefault(key, []).append(value)
    return [
        (sum(grouped[k]) / len(grouped[k])) if k in grouped else None
        for k in bucket_keys
    ]


def resolve_preset_range(mode: str, custom_from: date | None = None,
                          custom_to: date | None = None, today: date | None = None) -> tuple:
    """Turns a wizard's Daily/Weekly/Monthly/Quarterly/Custom horizon
    selection into an explicit (date_from, date_to) lookback window ending
    today — every report spec's "Daily/Weekly/Monthly/Quarterly presets"
    control, resolved once here so each report type's data layer doesn't
    reimplement the same lookback math. Custom uses *custom_from*/
    *custom_to* directly (falling back to a 1-day window on today if either
    is missing, rather than raising)."""
    today = today or date.today()
    if mode == TIMEFRAME_CUSTOM:
        if custom_from and custom_to:
            return (custom_from, custom_to) if custom_from <= custom_to else (custom_to, custom_from)
        return today, today
    lookback_days = {
        TIMEFRAME_DAILY: 0,
        TIMEFRAME_WEEKLY: 6,
        TIMEFRAME_MONTHLY: 29,
        TIMEFRAME_QUARTERLY: 89,
    }.get(mode, 0)
    return today - timedelta(days=lookback_days), today


def cumulative(values: list) -> list:
    """Running sum, treating a None entry as "no change this bucket"
    (carries the prior cumulative value forward) rather than breaking the
    curve — matches investment_equity_curve's same convention."""
    out = []
    running = 0.0
    for v in values:
        if v is not None:
            running += v
        out.append(running)
    return out
