"""
Back-test of a LMV strategy's alerts over past days (issue #79), so the LMV EOD
report can cover a period whether or not the strategy was selected / alerting in
LMV at the time.

It replays the alert engine's own rules (services.strategy_alerts.engine) over
the stored daily LMV snapshots (api.lmv_snapshot_api.get_range — one end-of-day
row per stock per day, every LMV column):

  * each day the strategy is applied to that day's rows (row filter included)
    and its Strategy Notifications trigger condition is tested per stock;
  * a stock whose trigger turns true (and isn't cooling down from its last
    trade) ENTERS at that day's closing price, with Stop Loss / Targets /
    Trailing Exit computed from that day's row — frozen at entry, exactly like
    a live entry; a target/SL on the wrong side of entry is a cancelled trade;
  * from the NEXT day on, a day's High / Low decide the outcome: every target
    reached -> "all_targets_achieved" (exit at the farthest target), stop-loss
    (or trailing exit) touched -> "stopped_out" (exit at that level). When one
    day touches both a stop and a target the stop wins (the intraday order is
    unknowable from end-of-day data, so this is the cautious reading);
  * a trade still open at the end of the range is left open (not reported).

Approximations, stated in the report itself: entries use the closing price (no
intraday trigger time), exits use the level touched (or the day's open when the day gapped through a stop), an intraday-mode strategy
is replayed as positional, and a formula that needs live-only data (Sector
aside, which is filled in from the sector map) reads blank, and a fixed-date lookup (VALUE_ON_DATE)
resolves only for days after that date. History reaches back
only as far as the backend's stored LMV days (at most 90 trading days).
"""

import uuid
from datetime import date, datetime, timedelta

from services import formula_stats_engine as fse
from services.strategy_alerts.models import ROLE_STOP_LOSS, ROLE_TARGET, ROLE_TRAILING_EXIT
from services.strategy_engine import (
    SYMBOL_COLUMN, apply_strategies, build_symbol_index, evaluate, evaluate_condition, get_compiled,
)

MAX_SNAPSHOT_DAYS = 90          # the backend's /lmv-snapshot/range cap
_LOOKBACK_MARGIN_DAYS = 25      # extra stored days kept before the range for N-day formulas
_CLOSE_TIME = "15:30:00"
_PRICE_COLUMNS = ("Current", "LTP", "Close")


class BacktestUnavailable(Exception):
    """The strategy can't be back-tested (message is shown in the report)."""


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(row: dict):
    for column in _PRICE_COLUMNS:
        value = _to_float(row.get(column))
        if value is not None:
            return value
    return None


def _all_formulas(strategy: dict, config: dict) -> list:
    """Every token list the replay evaluates (to know which N-day lookbacks it needs)."""
    out = [c.get("formula") for c in strategy.get("columns", [])]
    out.append(strategy.get("row_filter"))
    out.append(config.get("trigger_condition"))
    out += [m.get("formula") for m in config.get("metrics", [])]
    rr = config.get("risk_reward") or {}
    out += [rr.get("numerator"), rr.get("denominator")]
    return [f for f in out if f]


def fetch_range(date_from: date) -> dict:
    """The stored LMV days reaching back to *date_from* (plus a lookback
    margin), via the backend. Raises ApiError/NetworkError on failure."""
    from api import lmv_snapshot_api

    calendar_days = (date.today() - date_from).days + 1 + _LOOKBACK_MARGIN_DAYS
    return lmv_snapshot_api.get_range(min(MAX_SNAPSHOT_DAYS, max(calendar_days, 1)))


def _sector_lookup():
    from services import inception_sector
    cache: dict = {}

    def lookup(symbol):
        if symbol not in cache:
            try:
                cache[symbol] = inception_sector.sector_for(symbol)
            except Exception:
                cache[symbol] = None
        return cache[symbol]
    return lookup


def _invalid_levels(direction: str, entry_price, metrics: dict) -> list:
    from services.strategy_alerts.engine import _invalid_metrics
    return _invalid_metrics(direction, entry_price, metrics)


_NO_LEVELS = "no_levels"


def _entry(strategy, config, row, grid, sym_index, agg_cache, history, symbol, direction, day):
    entry_price = _price(row)
    if entry_price is None:
        return None
    metrics = {}
    for m in config.get("metrics", []):
        value = evaluate(m.get("formula", []), row, grid, agg_cache=agg_cache,
                         sym_index=sym_index, day_history=history)
        entry = {"name": m.get("name", ""), "role": m.get("role"), "value": _to_float(value)}
        if m.get("role") == ROLE_TARGET:
            entry["achieved"] = False
            entry["achieved_at"] = None
        metrics[m["id"]] = entry
    # A Stop Loss / Target that can't be computed yet (a formula needing more
    # stored days than exist at this point of the replay) would leave a trade
    # that can only ever stop out — don't open it; it's counted and reported.
    if any(m.get("value") is None for m in metrics.values() if m.get("role") in (ROLE_STOP_LOSS, ROLE_TARGET)):
        return _NO_LEVELS
    when = f"{day}T{_CLOSE_TIME}"
    signal = {
        "id": str(uuid.uuid4()), "state": "open", "backtest": True,
        "strategy_id": strategy["id"], "strategy_name": strategy.get("name", ""),
        "symbol": symbol, "sector": row.get("Sector"), "direction": direction,
        "entry_time": when, "entry_price": entry_price, "metrics": metrics,
        "risk_reward": None, "score": config.get("score"),
        "last_price": entry_price, "last_tick_time": when,
        "running_high": _to_float(row.get("High")), "running_low": _to_float(row.get("Low")),
    }
    if _invalid_levels(direction, entry_price, metrics):
        signal["resolved_at"] = when
        signal["resolution"] = "trade_cancelled"
        signal["state"] = "resolved"
    return signal


def _step_open(config, signal, raw, grid_row, grid, sym_index, agg_cache, history, day):
    """Apply one later day to an open signal. Returns True once it resolved."""
    high, low, price = _to_float(raw.get("High")), _to_float(raw.get("Low")), _price(raw)
    day_open = _to_float(raw.get("Open"))
    if price is not None:
        signal["last_price"], signal["last_tick_time"] = price, f"{day}T{_CLOSE_TIME}"
    if high is not None:
        signal["running_high"] = max(signal["running_high"], high) if signal.get("running_high") is not None else high
    if low is not None:
        signal["running_low"] = min(signal["running_low"], low) if signal.get("running_low") is not None else low

    cfg_by_id = {m.get("id"): m for m in config.get("metrics", [])}
    row_for_formulas = grid_row if grid_row is not None else raw
    for metric_id, m in signal["metrics"].items():
        cfg = cfg_by_id.get(metric_id)
        if cfg is None:
            continue
        # Trailing exit moves with price; a Stop/Target that couldn't be
        # computed at entry is retried — same rules as the live engine.
        if m.get("role") == ROLE_TRAILING_EXIT or (m.get("role") in (ROLE_STOP_LOSS, ROLE_TARGET) and m.get("value") is None):
            value = _to_float(evaluate(cfg.get("formula", []), row_for_formulas, grid, agg_cache=agg_cache,
                                       sym_index=sym_index, day_history=history))
            if value is not None:
                m["value"] = value

    buy = signal.get("direction", "BUY") == "BUY"
    stop_levels = [m["value"] for m in signal["metrics"].values()
                   if m.get("role") in (ROLE_STOP_LOSS, ROLE_TRAILING_EXIT) and m.get("value") is not None]
    if buy:
        stop_hit = [lvl for lvl in stop_levels if low is not None and low <= lvl]
    else:
        stop_hit = [lvl for lvl in stop_levels if high is not None and high >= lvl]
    when = f"{day}T{_CLOSE_TIME}"
    if stop_hit:
        # The stop touched first on the way down (BUY) / up (SELL) — filled at
        # that level, or at the day's open when the day gapped through it (a
        # level already breached at entry fills at the next open, never at a
        # price better than where the market actually opened).
        level = max(stop_hit) if buy else min(stop_hit)
        if day_open is not None:
            level = min(level, day_open) if buy else max(level, day_open)
        signal["exit_price"] = level
        signal["resolved_at"], signal["resolution"], signal["state"] = when, "stopped_out", "resolved"
        return True

    targets = [m for m in signal["metrics"].values() if m.get("role") == ROLE_TARGET]
    for m in targets:
        if m.get("achieved") or m.get("value") is None:
            continue
        reached = (high is not None and high >= m["value"]) if buy else (low is not None and low <= m["value"])
        if reached:
            m["achieved"], m["achieved_at"] = True, when
    if targets and all(m.get("achieved") for m in targets):
        values = [m["value"] for m in targets if m.get("value") is not None]
        level = max(values) if buy else min(values)
        if day_open is not None and len(values) == 1:
            # a single target the market gapped over fills at the open
            level = max(level, day_open) if buy else min(level, day_open)
        signal["exit_price"] = level
        signal["resolved_at"], signal["resolution"], signal["state"] = when, "all_targets_achieved", "resolved"
        return True
    return False


def backtest_trades(strategy: dict, config: dict, range_response: dict,
                    date_from: date, date_to: date) -> list:
    """See backtest(); just the trades."""
    return backtest(strategy, config, range_response, date_from, date_to)[0]


def backtest(strategy: dict, config: dict, range_response: dict,
             date_from: date, date_to: date) -> tuple:
    """(trades, stats) — stats = {"skipped_no_levels": entries not opened because
    a Stop Loss/Target couldn't be computed yet}. Resolved trades (alert-history shaped; resolution all_targets_achieved /
    stopped_out / trade_cancelled) the strategy would have produced with entries
    on days within [date_from, date_to], replayed over *range_response*'s days
    (the api.lmv_snapshot_api.get_range shape). See the module docstring."""
    trigger = config.get("trigger_condition")
    if not trigger:
        raise BacktestUnavailable(
            "this strategy has no Strategy Notifications trigger condition, so there are no alerts to replay")

    runnable = dict(strategy, active=True)
    direction = config.get("direction", "BUY")
    compiled = {i: _safe_compiled(tokens) for i, tokens in enumerate(_all_formulas(strategy, config))}
    int_specs, date_specs = fse._needed_int_day_specs(compiled), fse._needed_date_specs(compiled)
    track_history = bool(int_specs or date_specs)
    sector_of = _sector_lookup()
    lo, hi = date_from.isoformat(), date_to.isoformat()

    hist_by_symbol: dict = {}
    open_signals: dict = {}
    cooling: set = set()
    trades: list = []
    stats = {"skipped_no_levels": 0}

    for day in range_response.get("days", []):
        d = day["trade_date"]
        raw_rows, raw_by_symbol = [], {}
        for stock in day.get("stocks", []):
            symbol = stock.get("symbol")
            if not symbol:
                continue
            row = dict(stock.get("metrics", {}))
            row[SYMBOL_COLUMN] = symbol
            if not row.get("Sector"):
                row["Sector"] = sector_of(symbol)
            raw_rows.append(row)
            raw_by_symbol[symbol] = row

        if d > hi:
            break
        if not raw_rows:
            continue
        headers = [SYMBOL_COLUMN] + sorted({k for r in raw_rows for k in r} - {SYMBOL_COLUMN})
        raw_data = [[r.get(h) for h in headers] for r in raw_rows]

        # Like live LMV, "history" is the saved days BEFORE today (today's row is
        # the live one): VALUE_DAYS_AGO(x, 0) is the previous stored day, and an
        # N-day average/max covers the N days before today. A formula can average
        # a strategy COLUMN over those days (ATR = average of TR ...), so each
        # stored day keeps its computed strategy columns (row filter off).
        history = None
        if track_history:
            history = {}
            for symbol, hist in hist_by_symbol.items():
                for key, value in fse._self_contained_day_history(hist, int_specs, date_specs, symbol).items():
                    history.setdefault(key, {}).update(value)
        if track_history:
            full_headers, full_data = apply_strategies(
                [dict(runnable, row_filter=[])], headers, raw_data, day_history=history,
                include_streak_columns=False)
            todays = {r.get(SYMBOL_COLUMN): r for r in (dict(zip(full_headers, x)) for x in full_data)}
        else:
            todays = raw_by_symbol
        for symbol, row in todays.items():
            hist_by_symbol.setdefault(symbol, []).append((d, row))
        new_headers, new_data = apply_strategies(
            [runnable], headers, raw_data, day_history=history, include_streak_columns=False)
        grid = [dict(zip(new_headers, r)) for r in new_data]
        grid_by_symbol = {g.get(SYMBOL_COLUMN): g for g in grid}
        sym_index, agg_cache = build_symbol_index(grid), {}

        # 1) earlier days' open trades see today's High/Low
        for symbol, signal in list(open_signals.items()):
            raw = raw_by_symbol.get(symbol)
            if raw is None:
                continue
            if _step_open(config, signal, raw, grid_by_symbol.get(symbol), grid, sym_index, agg_cache, history, d):
                trades.append(open_signals.pop(symbol))
                cooling.add(symbol)

        # 2) new entries at today's close
        for symbol in list(cooling):
            if symbol not in grid_by_symbol:
                cooling.discard(symbol)            # row filtered out == trigger false
        for row in grid:
            symbol = row.get(SYMBOL_COLUMN)
            if not symbol or symbol in open_signals:
                continue
            is_true = evaluate_condition(trigger, row, grid, agg_cache=agg_cache, sym_index=sym_index,
                                         day_history=history)
            if symbol in cooling:
                if not is_true:
                    cooling.discard(symbol)
                continue
            if not is_true or not (lo <= d <= hi):
                continue
            signal = _entry(strategy, config, row, grid, sym_index, agg_cache, history, symbol, direction, d)
            if signal is None:
                continue
            if signal == _NO_LEVELS:
                stats["skipped_no_levels"] += 1
                continue
            if signal["state"] == "resolved":      # cancelled at entry
                trades.append(signal)
                cooling.add(symbol)
            else:
                open_signals[symbol] = signal
    return trades, stats


def _safe_compiled(tokens):
    try:
        return get_compiled(tokens)
    except Exception:
        return None


def coverage(range_response: dict) -> tuple:
    """(first, last) stored trade dates in *range_response* as dates, or (None, None)."""
    days = [d["trade_date"] for d in range_response.get("days", []) if d.get("trade_date")]
    if not days:
        return None, None
    return date.fromisoformat(min(days)), date.fromisoformat(max(days))


def run(strategy: dict, config: dict, date_from: date, date_to: date) -> tuple:
    """Fetch the stored days and back-test. Returns (trades, notes) — *notes* are
    plain-text caveats for the report (coverage gaps, why nothing ran)."""
    from api.exceptions import ApiError, NetworkError

    notes = []
    try:
        response = fetch_range(date_from)
    except (ApiError, NetworkError) as exc:
        return [], [f"the stored daily LMV data could not be fetched ({exc})"]
    first, last = coverage(response)
    if first is None:
        return [], ["no stored daily LMV data is available"]
    if first > date_from:
        notes.append(f"stored LMV data only reaches back to {first.strftime('%d-%b-%Y')}; "
                     f"{date_from.strftime('%d-%b-%Y')} to {(first - timedelta(days=1)).strftime('%d-%b-%Y')} is not covered")
    try:
        trades, stats = backtest(strategy, config, response, date_from, date_to)
    except BacktestUnavailable as exc:
        return [], notes + [str(exc)]
    cancelled = sum(1 for t in trades if t.get("resolution") == "trade_cancelled")
    if cancelled:
        notes.append(f"{cancelled} entr{'y was' if cancelled == 1 else 'ies were'} left out as cancelled trades: "
                     "at the closing price a stop-loss/target was already on the wrong side of the entry")
    if stats["skipped_no_levels"]:
        notes.append(f"{stats['skipped_no_levels']} entr{'y was' if stats['skipped_no_levels'] == 1 else 'ies were'} "
                     "skipped because its stop-loss/target could not be computed yet (not enough stored days "
                     "for the formula early in the range)")
    return trades, notes
