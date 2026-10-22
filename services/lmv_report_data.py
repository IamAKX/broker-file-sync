"""
Data layer for the LMV EOD Report (resources/report/LMV_Based_Strategy_EOD_
Report_Requirements_v5.docx) — pulls resolved strategy-alert trades
(services.strategy_alerts.state_store's local alert_history is the source
of truth for "what actually happened"; api.strategy_signals_api.list_signals
is a best-effort supplement for a Custom range going back further than
local history's ~500-record retention), computes directional/blended yield
(services.report_metrics), and builds the report_engine HTML pages the
Reports screen previews/exports.

A "trade_cancelled" resolution is excluded everywhere here — see services.
strategy_alerts.models: that trade never actually executed (issue #32), so
it contributes no yield and isn't part of win/loss counts.
"""

from datetime import date, datetime, timedelta

from services import emv_report_data, report_columns, report_metrics, strategy_store
from services.report_engine import charts, templates
from services.strategy_alerts import state_store

DEFAULT_INVESTMENT_AMOUNT = 5000.0
_MAX_BACKEND_PAGES = 20

# Not a real resolution: an alert that is still open but has achieved some, not
# all, of its targets (#94). It is reported with its mark-to-market return.
RESOLUTION_PARTIAL = "targets_partially_achieved"

_RESOLUTION_LABELS = {
    RESOLUTION_PARTIAL: ("PARTIAL TARGETS", "positive"),
    "all_targets_achieved": ("TARGET HIT", "positive"),
    "stopped_out": ("STOP LOSS", "negative"),
    "intraday_closed": ("CLOSED", "neutral"),
}


_SECTOR_PALETTE = ["#2979FF", "#16a34a", "#D97706", "#dc2626", "#8250df", "#0969da", "#bf3989", "#65a30d"]
_COMPARE_DEFAULTS = ("ALKEM", "TATASTEEL")  # requirements doc §4.3 defaults


def sector_distribution(summary: dict) -> list:
    """Donut segments: number of distinct stocks traded per sector."""
    stocks: dict = {}
    for t in summary["trades"]:
        stocks.setdefault(t.get("sector") or "Unclassified", set()).add(t.get("symbol"))
    ranked = sorted(stocks.items(), key=lambda kv: -len(kv[1]))
    return [
        {"label": sector, "value": len(syms), "color": _SECTOR_PALETTE[i % len(_SECTOR_PALETTE)]}
        for i, (sector, syms) in enumerate(ranked)
    ]


def compare_assets(summary: dict, mode: str = "stock", asset_1: str | None = None,
                   asset_2: str | None = None) -> dict | None:
    """Cross-compare (requirements §4.3) two stocks or two sectors traded
    under this strategy: trades, average yield, win rate. *asset_1/2* are
    user picks (case-insensitive); anything unset or not traded falls back
    to ALKEM vs TATASTEEL (stock mode, when both traded), else the two
    most-traded assets. None when fewer than two assets traded."""
    key = "sector" if mode == "sector" else "symbol"
    by_asset: dict = {}
    for r in summary["rows"]:
        name = (r["trade"].get("sector") or "Unclassified") if key == "sector" else r["symbol"]
        by_asset.setdefault(name, []).append(r["yield"])
    if len(by_asset) < 2:
        return None

    lookup = {name.upper(): name for name in by_asset}
    picks = [lookup.get((a or "").strip().upper()) for a in (asset_1, asset_2)]
    if picks[0] and picks[1] and picks[0] != picks[1]:
        picked = picks
    elif key == "symbol" and all(d in by_asset for d in _COMPARE_DEFAULTS):
        picked = list(_COMPARE_DEFAULTS)
    else:
        picked = sorted(by_asset, key=lambda k: (-len(by_asset[k]), k))[:2]
    return {
        "mode": mode,
        "rows": [
            {
                "name": n,
                "trades": len(by_asset[n]),
                "avg_yield": report_metrics.blended_yield(by_asset[n]),
                "win_rate": report_metrics.win_rate(by_asset[n]),
            }
            for n in picked
        ],
    }


def _as_date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return datetime.fromisoformat(str(value)).date()


def _resolved_dt(trade: dict) -> datetime:
    try:
        return datetime.fromisoformat(trade["resolved_at"])
    except Exception:
        return datetime.min


def _fallback_exit_price(trade: dict) -> float | None:
    """Older history (recorded before exit_price capture shipped) has no
    exit_price — approximate with the target/SL threshold value that
    actually resolved the trade rather than showing a blank yield."""
    metrics = trade.get("metrics") or {}
    resolution = trade.get("resolution")
    candidate = None
    if resolution == "all_targets_achieved":
        for m in metrics.values():
            if m.get("role") == "target" and m.get("achieved") and m.get("value") is not None:
                candidate = m["value"]
                break
    elif resolution == "stopped_out":
        for m in metrics.values():
            if m.get("role") in ("stop_loss", "trailing_exit") and m.get("value") is not None:
                candidate = m["value"]
                break
    # A target/SL metric is only a price if its formula produced one — many
    # strategies use boolean-style conditions (value 1.0 / 0.0), and treating
    # that as an exit price yielded a bogus ~-100%. Accept it only when it's
    # in a plausible band around entry; otherwise the yield is unknown.
    entry = trade.get("entry_price")
    if candidate is None or not entry or not (0.5 * entry <= candidate <= 2 * entry):
        return None
    return candidate


def _exit_price(trade: dict) -> float | None:
    price = trade.get("exit_price")
    return price if price is not None else _fallback_exit_price(trade)


def scale_out_yield(trade: dict, entry, exit_price, direction: str):
    """(yield %, booked_targets, total_targets) for a trade that achieved some
    of its targets and then did NOT reach the last one (#94): still open, or
    stopped out. The position is split equally across the targets; each
    achieved target books its share at that target's price and the rest exits
    at *exit_price* (the stop, or the last price while open). So the profit
    made on the way to those targets is no longer thrown away when the trade
    later falls back to its stop-loss.

    Returns (None, ...) when there is nothing to book — no achieved target, no
    target at all, or a target "price" that is not a price (a boolean-style
    metric) — and the caller falls back to the plain entry->exit yield."""
    targets = [m for m in (trade.get("metrics") or {}).values() if m.get("role") == "target"]
    done = [m for m in targets if m.get("achieved")]
    if not targets or not done or len(done) == len(targets) or not entry:
        return None, len(done), len(targets)
    prices = [m.get("value") for m in done]
    if any(p is None or not (0.5 * entry <= p <= 2 * entry) for p in prices):
        return None, len(done), len(targets)
    rest = len(targets) - len(done)
    parts = [report_metrics.directional_yield(entry, p, direction) for p in prices]
    tail = report_metrics.directional_yield(entry, exit_price, direction) if exit_price is not None else None
    if tail is None or any(p is None for p in parts):
        return None, len(done), len(targets)
    total = len(targets)
    return (sum(parts) + rest * tail) / total, len(done), total


def _days_true_label(trade: dict) -> str:
    try:
        entry = datetime.fromisoformat(trade["entry_time"])
        resolved = _resolved_dt(trade)
    except Exception:
        return "—"
    delta = resolved - entry
    if delta < timedelta(hours=24):
        hours = max(delta.seconds // 3600, 0)
        return f"{hours} Hr" if hours != 1 else "1 Hr"
    days = delta.days
    return f"{days} Day" if days == 1 else f"{days} Days"


def _local_resolved_trades(strategy_id: str) -> list:
    seen_ids = set()
    trades = []
    for r in state_store.get_alert_history():
        if r.get("strategy_id") != strategy_id:
            continue
        if r.get("resolution") in (None, "trade_cancelled"):
            continue
        if not r.get("resolved_at"):
            continue
        rid = r.get("id")
        if rid:
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
        trades.append(r)
    return trades


def _backend_resolved_trades(strategy_id: str, date_from: date, date_to: date) -> list:
    """Best-effort supplement from the backend's durable signal history
    (api.strategy_signals_api), for a Custom range reaching further back
    than local alert_history's ~500-record retention. Deliberately NOT
    called for every report generation (see fetch_extra_history's own
    caller in build_report_data) — a network round trip on every report
    open/refresh would make the feature feel unreliable/slow the moment
    the backend is slow or unreachable; it's only worth the round trip when
    the user explicitly asked for a range local history might not cover."""
    try:
        from api import strategy_signals_api
        from api.exceptions import ApiError, NetworkError
    except ImportError:
        return []

    start = datetime.combine(date_from, datetime.min.time()).isoformat()
    end = datetime.combine(date_to, datetime.max.time()).isoformat()
    items: list = []
    page = 1
    while page <= _MAX_BACKEND_PAGES:
        try:
            response = strategy_signals_api.list_signals(
                strategy_id=strategy_id, start_time=start, end_time=end,
                page=page, page_size=100,
            )
        except (ApiError, NetworkError):
            break
        items.extend(response.get("items", []))
        if page >= (response.get("total_pages") or 1):
            break
        page += 1

    trades = []
    for r in items:
        # The backend row's outcome field is "status" ("open" while still
        # live); local alert_history calls the same thing "resolution".
        trade = dict(r)
        trade["resolution"] = r.get("resolution") or (
            None if r.get("status") == "open" else r.get("status")
        )
        if trade["resolution"] in (None, "trade_cancelled") or not trade.get("resolved_at"):
            continue
        trades.append(trade)
    return trades


def resolved_trades_for_strategy(strategy_id: str, date_from: date | None = None,
                                  date_to: date | None = None,
                                  include_backend: bool = False) -> list:
    """Resolved (non-cancelled) trades for *strategy_id*, newest last, from
    local alert_history — plus a best-effort backend supplement when
    *include_backend* is True (build_report_data sets this only for a
    Custom-range request, see _backend_resolved_trades)."""
    trades = _local_resolved_trades(strategy_id)

    if include_backend and date_from is not None:
        seen_ids = {t.get("id") for t in trades if t.get("id")}
        for r in _backend_resolved_trades(strategy_id, date_from, date_to or date_from):
            rid = r.get("id")
            if rid and rid in seen_ids:
                continue
            if rid:
                seen_ids.add(rid)
            trades.append(r)

    if date_from is not None:
        lo = datetime.combine(date_from, datetime.min.time())
        hi = datetime.combine(date_to or date_from, datetime.max.time())
        trades = [t for t in trades if lo <= _resolved_dt(t) <= hi]

    trades.sort(key=_resolved_dt)
    return trades


def _local_open_partial_trades(strategy_id: str) -> list:
    from services.strategy_alerts.models import is_partially_achieved
    return [
        s for s in state_store.get_open_signals().values()
        if s.get("strategy_id") == strategy_id and s.get("state") == "open" and is_partially_achieved(s)
    ]


def _backend_open_partial_trades(strategy_id: str, date_from: date | None, date_to: date | None) -> list:
    """Open signals the backend holds (another device's alerts) that have hit
    some targets — best effort, like _backend_resolved_trades."""
    try:
        from api import strategy_signals_api
        from api.exceptions import ApiError, NetworkError
        from services.strategy_alerts.models import is_partially_achieved
    except ImportError:
        return []
    out, page = [], 1
    while page <= _MAX_BACKEND_PAGES:
        try:
            response = strategy_signals_api.list_signals(
                strategy_id=strategy_id, status="open", page=page, page_size=100)
        except (ApiError, NetworkError):
            break
        for item in response.get("items", []):
            signal = dict(item, state="open", resolution=None)
            if is_partially_achieved(signal):
                out.append(signal)
        if page >= (response.get("total_pages") or 1):
            break
        page += 1
    return out


def partial_open_trades(strategy_id: str, date_to: date | None, include_backend: bool = False,
                        date_from: date | None = None) -> list:
    """Open alerts of *strategy_id* that have achieved some but not all of their
    targets (#94), shaped like resolved trades so they flow through the same
    yield / table / curve code: resolution RESOLUTION_PARTIAL, resolved_at = the
    last time the signal was seen (when its current return was struck) and
    exit_price = that last price (mark-to-market), else the highest achieved
    target.

    Only for a report covering the present (date_to today or later): an alert
    that is partial NOW says nothing about a past range, and without
    point-in-time snapshots there is nothing older to reconstruct from."""
    if date_to is not None and date_to < date.today():
        return []
    signals = _local_open_partial_trades(strategy_id)
    if include_backend:
        seen = {s.get("id") for s in signals if s.get("id")}
        signals += [s for s in _backend_open_partial_trades(strategy_id, None, date_to)
                    if not (s.get("id") and s["id"] in seen)]
    trades = []
    for s in signals:
        if date_to is not None:
            try:
                if datetime.fromisoformat(s["entry_time"]).date() > date_to:
                    continue
            except (KeyError, TypeError, ValueError):
                pass
        trade = dict(s)
        trade["resolution"] = RESOLUTION_PARTIAL
        struck = s.get("last_tick_time") or datetime.now().isoformat()
        if date_from is not None:
            # keep it inside the report's window so the performance curve
            # buckets it (the last tick may predate a "today only" range)
            try:
                if datetime.fromisoformat(struck).date() < date_from:
                    struck = datetime.combine(date_from, datetime.min.time()).isoformat()
            except (TypeError, ValueError):
                pass
        trade["resolved_at"] = struck
        exit_price = s.get("last_price")
        if exit_price is None:
            achieved = [m["value"] for m in (s.get("metrics") or {}).values()
                        if m.get("role") == "target" and m.get("achieved") and m.get("value") is not None]
            if achieved:
                exit_price = max(achieved) if s.get("direction", "BUY") == "BUY" else min(achieved)
        trade["exit_price"] = exit_price
        trades.append(trade)
    return trades


def backtest_trades_for_strategy(strategy_id: str, date_from: date | None, date_to: date | None) -> tuple:
    """(trades, notes): the trades *strategy_id* would have produced over the
    range, replayed from stored end-of-day LMV data (services.strategy_backtest)
    — whether or not the strategy was active in LMV then. Cancelled/unresolved
    trades are dropped, like for recorded alerts."""
    from services import strategy_backtest
    from services.strategy_alerts import config_store as alerts_config_store

    if date_from is None or date_to is None:
        return [], ["a date range is required for a back-test"]
    strategy = next((s for s in strategy_store.load_all() if s.get("id") == strategy_id), None)
    if strategy is None:
        return [], ["the strategy was not found"]
    config = alerts_config_store.load_config(strategy_id) or {}
    trades, notes = strategy_backtest.run(strategy, config, date_from, date_to)
    lo = datetime.combine(date_from, datetime.min.time())
    hi = datetime.combine(date_to, datetime.max.time())
    kept = [t for t in trades
            if t.get("resolution") not in (None, "trade_cancelled") and t.get("resolved_at")
            and lo <= _resolved_dt(t) <= hi]
    kept.sort(key=_resolved_dt)
    return kept, notes


def _only_symbol(trades: list, stock: str | None) -> list:
    if not stock:
        return trades
    wanted = stock.strip().upper()
    return [t for t in trades if str(t.get("symbol", "")).strip().upper() == wanted]


def compute_strategy_summary(strategy_id: str, date_from: date | None, date_to: date | None,
                              include_backend: bool = False, backtest: bool = False,
                              stock: str | None = None) -> dict:
    """*stock* limits the summary to one symbol's trades (#82)."""
    notes: list = []
    if backtest:
        trades, notes = backtest_trades_for_strategy(strategy_id, date_from, date_to)
    else:
        trades = resolved_trades_for_strategy(strategy_id, date_from, date_to, include_backend=include_backend)
        partial = partial_open_trades(strategy_id, date_to, include_backend=include_backend,
                                      date_from=date_from)
        trades = sorted(trades + partial, key=_resolved_dt)
    trades = _only_symbol(trades, stock)

    rows = []
    yields = []
    resolution_counts: dict = {}
    for t in trades:
        entry = t.get("entry_price")
        exit_p = _exit_price(t)
        direction = t.get("direction", "BUY")
        y = report_metrics.directional_yield(entry, exit_p, direction)
        booked = None
        if t.get("resolution") in (RESOLUTION_PARTIAL, "stopped_out"):
            scaled, n_hit, n_total = scale_out_yield(t, entry, exit_p, direction)
            if scaled is not None:
                y, booked = scaled, (n_hit, n_total)
        yields.append(y)
        resolution_counts[t.get("resolution")] = resolution_counts.get(t.get("resolution"), 0) + 1
        label, kind = _RESOLUTION_LABELS.get(t.get("resolution"), (t.get("resolution", ""), "neutral"))
        if t.get("resolution") == RESOLUTION_PARTIAL:
            from services.strategy_alerts.models import target_progress
            done, total = target_progress(t)
            label = f"PARTIAL {done}/{total}"
            if y is not None and y < 0:
                kind = "negative"
        elif booked is not None:
            # stopped out after booking some targets: say so, and colour it by
            # the blended result (a stop after 3 of 4 targets can still be a win)
            label = f"STOP LOSS ({booked[0]}/{booked[1]} targets)"
            kind = "positive" if (y or 0) >= 0 else "negative"
        # A positional "intraday_closed" isn't inherently a win or loss —
        # recolor it by its own yield sign rather than a fixed neutral tag.
        if t.get("resolution") == "intraday_closed" and y is not None:
            kind = "positive" if y >= 0 else "negative"
        rows.append({
            "date": _resolved_dt(t),
            "symbol": t.get("symbol", ""),
            "direction": direction,
            "entry": entry,
            "exit": exit_p,
            "yield": y,
            "status_label": label,
            "status_kind": kind,
            "days_true": _days_true_label(t),
            "booked_targets": booked,
            "trade": t,
        })

    return {
        "strategy_id": strategy_id,
        "backtest": backtest, "backtest_notes": notes,
        "trades": trades,
        "rows": rows,
        "yields": yields,
        "blended_yield": report_metrics.blended_yield(yields),
        "win_rate": report_metrics.win_rate(yields),
        # "Closed" excludes the still-open partially-achieved trades, which are
        # counted (and yielded) but reported separately.
        "closed_trades": len(trades) - resolution_counts.get(RESOLUTION_PARTIAL, 0),
        "partial_trades": resolution_counts.get(RESOLUTION_PARTIAL, 0),
        "resolution_counts": resolution_counts,
        "sharpe": report_metrics.sharpe_ratio(yields),
        "sortino": report_metrics.sortino_ratio(yields),
        "calmar": report_metrics.calmar_ratio(yields),
    }


def build_report_data(strategy_a_id: str, strategy_b_id: str | None,
                       timeframe: str, date_from: date | None, date_to: date | None,
                       investment_amount: float = DEFAULT_INVESTMENT_AMOUNT,
                       include_backend: bool = False,
                       compare: dict | None = None,
                       indicator_ids: list | None = None, indicator_symbols: list | None = None,
                       indicator_days: int = 60, backtest: bool = False, stock: str | None = None) -> dict:
    """*backtest*: replay the strategies' alert rules over stored end-of-day LMV
    data instead of reading the alerts they actually recorded (see
    services.strategy_backtest). *compare*: optional {"mode": "stock"|"sector", "asset_1", "asset_2"}
    for the Cross-Compare section. *timeframe* is the CURVE'S bucketing granularity (daily/weekly/
    monthly/quarterly — how the comparative performance curve groups
    trades), independent of *date_from*/*date_to* (the lookback window
    itself, already resolved by the caller e.g. via report_metrics.
    resolve_preset_range). *include_backend* opts into the backend
    supplement fetch (see _backend_resolved_trades) — callers should only
    set this True for a Custom range reaching further back than local
    alert_history's ~500-record retention; it's False by default so a
    normal Daily/Weekly/Monthly/Quarterly report generates fast and works
    fully offline."""
    strategies_by_id = {s["id"]: s for s in strategy_store.load_all()}
    summary_a = compute_strategy_summary(strategy_a_id, date_from, date_to, include_backend, backtest, stock)
    summary_a["name"] = strategies_by_id.get(strategy_a_id, {}).get("name", "Strategy A")

    summary_b = None
    if strategy_b_id:
        summary_b = compute_strategy_summary(strategy_b_id, date_from, date_to, include_backend, backtest, stock)
        summary_b["name"] = strategies_by_id.get(strategy_b_id, {}).get("name", "Strategy B")

    curve_a = curve_b = None
    if date_from and date_to:
        bucket_keys = report_metrics.bucket_range(date_from, date_to, timeframe)
        items_a = [{"date": r["date"], "yield": r["yield"]} for r in summary_a["rows"]]
        series_a = report_metrics.bucketed_series(items_a, "date", "yield", bucket_keys, timeframe)
        curve_a = report_metrics.cumulative(series_a)
        if summary_b:
            items_b = [{"date": r["date"], "yield": r["yield"]} for r in summary_b["rows"]]
            series_b = report_metrics.bucketed_series(items_b, "date", "yield", bucket_keys, timeframe)
            curve_b = report_metrics.cumulative(series_b)
    else:
        bucket_keys = []

    investment = report_metrics.investment_simulation(investment_amount, summary_a["blended_yield"])
    indicator_charts_by_symbol = _indicator_charts(
        summary_a, indicator_ids, indicator_symbols, indicator_days, date_to)

    return {
        "backtest": backtest,
        "stock": (stock or "").strip().upper() or None,
        "indicator_charts": indicator_charts_by_symbol,
        "summary_a": summary_a,
        "summary_b": summary_b,
        "bucket_keys": bucket_keys,
        "curve_a": curve_a,
        "curve_b": curve_b,
        "investment": investment,
        "investment_amount": investment_amount,
        "timeframe": timeframe,
        "compare": compare or {},
        "date_from": date_from,
        "date_to": date_to,
    }


def backtest_result(strategy_id: str, date_from: date | None, date_to: date | None,
                    investment_amount: float = DEFAULT_INVESTMENT_AMOUNT, stock: str | None = None) -> dict:
    """The shared Back-test report's input (services.backtest_report) for an LMV
    strategy: the strategy's alert rules replayed over the stored daily LMV days
    (services.strategy_backtest), optionally for one stock (#82)."""
    from services import backtest_report

    strategies_by_id = {s["id"]: s for s in strategy_store.load_all()}
    summary = compute_strategy_summary(strategy_id, date_from, date_to, backtest=True, stock=stock)
    trades = []
    for row in summary["rows"]:
        t = row["trade"]
        try:
            entry_date = datetime.fromisoformat(t["entry_time"]).date()
        except (KeyError, TypeError, ValueError):
            continue
        trades.append({
            "symbol": row["symbol"], "sector": t.get("sector"), "direction": row["direction"],
            "entry_date": entry_date, "exit_date": row["date"].date(), "entry": row["entry"], "exit": row["exit"],
            "yield": row["yield"], "outcome": row["status_label"].title(), "kind": row["status_kind"], "extra": {},
        })
    method = (
        '<p class="fk-note">These trades are <b>simulated</b>, not recorded alerts. The strategy\'s Strategy '
        "Notifications rules are replayed over the stored end-of-day LMV data, whether or not the strategy was active "
        "in LMV at the time: a stock enters at the day's closing price when its trigger turns true, with its Stop Loss / "
        "Targets / Trailing Exit computed from that day's row; from the next day the day's High / Low decide the "
        "outcome (every target reached, or the stop-loss touched — if one day touches both, the stop-loss counts). "
        "Intraday-mode strategies are replayed as positional. Yield is the directional % from entry to exit.</p>"
    )
    return {
        "kind": "LMV", "name": strategies_by_id.get(strategy_id, {}).get("name", "Strategy"),
        "symbol": (stock or "").strip().upper() or None, "date_from": date_from, "date_to": date_to,
        "investment_amount": investment_amount, "trades": trades,
        "open_trades": 0, "notes": list(summary.get("backtest_notes") or []), "method": method,
    }


def most_traded_symbols(summary: dict, limit: int = 5) -> list:
    counts: dict = {}
    for r in summary["rows"]:
        counts[r["symbol"]] = counts.get(r["symbol"], 0) + 1
    return [sym for sym, _n in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:limit] if sym]


def _indicator_charts(summary: dict, indicator_ids, symbols, days: int, date_to) -> list:
    """[(symbol, [(title, svg), ...])] — the chosen indicators for each
    chosen stock; a stock with no synced history or chart problem is just
    skipped, never breaks the report."""
    if not indicator_ids:
        return []
    from services import indicator_charts
    chosen = [s.strip() for s in (symbols or []) if s and s.strip()] or most_traded_symbols(summary)
    end = date_to or date.today()
    out = []
    for symbol in chosen:
        try:
            sections = indicator_charts.sections_for_symbol(symbol, end, days, indicator_ids)
        except Exception:
            sections = []
        if sections:
            out.append((symbol, sections))
    return out


def _fmt_pct(value) -> str:
    return f"{value:+.2f}%" if value is not None else "—"


def _fmt_price(value) -> str:
    return f"{value:,.2f}" if value is not None else "—"


def _fmt_ratio(value) -> str:
    return f"{value:.2f}" if value is not None else "—"


def _backtest_note_block(data: dict, summaries: list) -> tuple:
    """(html, height) — says plainly that the trades are simulated, how, and
    anything that limited the run."""
    notes = []
    for summary in summaries:
        for note in summary.get("backtest_notes") or []:
            notes.append(f'{summary["name"]}: {note}')
    body = (
        '<p class="fk-note">Back-test — these trades are <b>simulated</b>, not recorded alerts. The strategy\'s '
        "Strategy Notifications rules are replayed over the stored end-of-day LMV data whether or not the strategy "
        "was active in LMV: a stock enters at the day's closing price when its trigger turns true, and from the next "
        "day the day's High/Low decide the outcome (all targets reached, or stop-loss touched; if one day touches both, "
        "the stop-loss counts). Open trades at the end of the range are not counted. Intraday-mode strategies are "
        "replayed as positional.</p>"
        + "".join(f'<p class="fk-note"><b>Note:</b> {templates.esc(n)}.</p>' for n in notes)
    )
    return templates.section("About this back-test", body), 150 + 24 * len(notes)


def build_report_pages(data: dict, columns: list | None = None) -> list:
    """Builds the report's physical pages (see services.report_engine.
    templates' docstring for why pagination is decided here, in Python, not
    left to the browser). Page 1: header/KPIs/target-achievement donut/
    comparative curve. Page 2: directional stock table, efficiency ratios,
    investment simulation — split further if the trade table is long."""
    summary_a, summary_b = data["summary_a"], data["summary_b"]
    comparing = summary_b is not None

    kpis = (
        templates.kpi_card(
            f'Blended Yield — {summary_a["name"]}', _fmt_pct(summary_a["blended_yield"]),
            kind="positive" if (summary_a["blended_yield"] or 0) >= 0 else "negative",
        )
        + templates.kpi_card("Closed Trades", str(summary_a["closed_trades"]))
        + (templates.kpi_card("Partially Achieved (open)", str(summary_a["partial_trades"]), kind="positive")
           if summary_a.get("partial_trades") else "")
        + templates.kpi_card("Win Rate", f'{summary_a["win_rate"]:.0f}%' if summary_a["win_rate"] is not None else "—")
    )
    if comparing:
        kpis += templates.kpi_card(
            f'Blended Yield — {summary_b["name"]}', _fmt_pct(summary_b["blended_yield"]),
            kind="positive" if (summary_b["blended_yield"] or 0) >= 0 else "negative",
        )

    def _donut_for(summary):
        counts = summary["resolution_counts"]
        segments = [
            {"label": "Target Hit", "value": counts.get("all_targets_achieved", 0), "color": "#16a34a"},
            {"label": "Partial Targets", "value": counts.get(RESOLUTION_PARTIAL, 0), "color": "#0d9488"},
            {"label": "Stop Loss", "value": counts.get("stopped_out", 0), "color": "#dc2626"},
            {"label": "Closed", "value": counts.get("intraday_closed", 0), "color": "#D97706"},
        ]
        headline = f'{summary["win_rate"]:.0f}%' if summary["win_rate"] is not None else "—"
        return charts.donut_chart(segments, center_label=headline, center_sublabel="Win Rate"), segments

    donut_a_svg, donut_a_segments = _donut_for(summary_a)
    achievement_html = f'<div class="chart-row"><div>{donut_a_svg}</div>{charts.donut_legend(donut_a_segments)}</div>'
    if comparing:
        donut_b_svg, donut_b_segments = _donut_for(summary_b)
        achievement_html += (
            f'<div class="chart-row"><div>{donut_b_svg}</div>{charts.donut_legend(donut_b_segments)}</div>'
        )

    curve_html = '<p style="color:#64748b;font-size:11px;">Select a date range to see the performance curve.</p>'
    if data.get("bucket_keys"):
        series = [{"label": summary_a["name"], "points": data["curve_a"], "color": "#2979FF"}]
        if comparing:
            series.append({"label": summary_b["name"], "points": data["curve_b"], "color": "#D97706", "dashed": True})
        curve_html = charts.line_chart(series, x_labels=data["bucket_keys"], y_label="Cumulative Yield %", zero_line=True)

    page1 = (
        templates.report_header(
            "LMV Based Strategy EOD Report",
            f'{summary_a["name"]}' + (f' vs {summary_b["name"]}' if comparing else "")
            + (f' — {data["stock"]}' if data.get("stock") else "")
            + (" — Back-test" if data.get("backtest") else ""),
            datetime.now(),
        )
        + f'<div class="kpi-row">{kpis}</div>'
        + templates.section("Target Achievement", achievement_html)
        + templates.section("Comparative Performance Curve" if comparing else "Performance Curve", curve_html)
    )

    sector_html = ""
    # One stock has no sector spread to show (#82).
    for summary in ([] if data.get("stock") else [summary_a] + ([summary_b] if comparing else [])):
        segments = sector_distribution(summary)
        total = sum(seg["value"] for seg in segments)
        if segments:
            sector_html += (
                (f'<p style="font-size:11px;font-weight:600;">{templates.esc(summary["name"])}</p>' if comparing else "")
                + '<div class="chart-row"><div>'
                + charts.donut_chart(segments, center_label=str(total), center_sublabel="Stocks")
                + f'</div>{charts.donut_legend(segments)}</div>'
            )
    blocks = []
    if data.get("backtest"):
        blocks.append(_backtest_note_block(data, [summary_a] + ([summary_b] if comparing else [])))
    if sector_html:
        n_donuts = 2 if comparing else 1
        blocks.append((templates.section("Sector Distribution", sector_html), 40 + 215 * n_donuts))

    all_trades = summary_a["trades"] + (summary_b["trades"] if comparing else [])
    available = report_columns.lmv_catalog(report_columns.lmv_metric_names(all_trades))
    columns = report_columns.resolve_columns(columns, available, report_columns.LMV_DEFAULT_COLUMNS)

    def _table_rows(summary):
        return [
            [report_columns.lmv_cell(c, summary["name"], r, _fmt_pct) for c in columns]
            for r in summary["rows"]
        ]

    all_rows = _table_rows(summary_a) + (_table_rows(summary_b) if comparing else [])

    cfg = data.get("compare") or {}
    cmp = None if data.get("stock") else compare_assets(
        summary_a, cfg.get("mode", "stock"), cfg.get("asset_1"), cfg.get("asset_2"))
    if cmp:
        cmp_rows = cmp["rows"]
        noun = "Sector" if cmp["mode"] == "sector" else "Stock"
        cmp_html = templates.data_table(
            [noun, "Trades", "Avg Intraday Yield", "Win Rate"],
            [[r["name"], str(r["trades"]), _fmt_pct(r["avg_yield"]),
              f'{r["win_rate"]:.0f}%' if r["win_rate"] is not None else "—"] for r in cmp_rows],
        )
        has_yields = any(r["avg_yield"] is not None for r in cmp_rows)
        if has_yields:  # a chart of unknown yields would just be empty space
            cmp_html += charts.bar_chart(
                [r["name"] for r in cmp_rows], [r["avg_yield"] or 0 for r in cmp_rows],
                color="#16a34a", negative_color="#dc2626", show_values=True,
            )
        blocks.append((templates.section(
            f'Cross-Compare — {cmp_rows[0]["name"]} vs {cmp_rows[1]["name"]}', cmp_html),
            38 + 90 + (220 if has_yields else 0)))

    ratio_cards = (
        templates.kpi_card("Sharpe Ratio", _fmt_ratio(summary_a["sharpe"]))
        + templates.kpi_card("Sortino Ratio", _fmt_ratio(summary_a["sortino"]))
        + templates.kpi_card("Calmar Ratio", _fmt_ratio(summary_a["calmar"]))
    )
    blocks.append((templates.section("Efficiency Ratios", f'<div class="kpi-row">{ratio_cards}</div>'), 38 + 78))

    inv = data["investment"]
    inv_html = (
        f'<div class="kpi-row">'
        + templates.kpi_card("Starting Investment", f'₹{inv["starting"]:,.0f}')
        + templates.kpi_card(
            "Ending Value", f'₹{inv["ending"]:,.0f}' if inv["ending"] is not None else "—",
            kind="positive" if (inv["profit"] or 0) >= 0 else "negative",
        )
        + templates.kpi_card(
            "Profit / Loss", f'₹{inv["profit"]:,.0f}' if inv["profit"] is not None else "—",
            kind="positive" if (inv["profit"] or 0) >= 0 else "negative",
        )
        + '</div><p style="color:#64748b;font-size:10px;">Hypothetical simulation only — not an actual brokerage/P&amp;L statement.</p>'
    )
    blocks.append((templates.section(
        f'₹{data["investment_amount"]:,.0f} Investment Simulation', inv_html), 38 + 78 + 24))

    for symbol, sections in data.get("indicator_charts") or []:
        for title, svg in sections:
            blocks.append((templates.section(f"{title} — {symbol}", svg), emv_report_data._section_height(svg)))

    summaries = [s for s in (summary_a, summary_b) if s]
    if any(r.get("booked_targets") or (r["trade"] or {}).get("resolution") == RESOLUTION_PARTIAL
           for s in summaries for r in s["rows"]):
        blocks.append((templates.section("Partially achieved targets", (
            '<p class="fk-note">A trade that achieved some, but not all, of its targets is counted with the profit made '
            "on the way: its position is split equally across the targets, each achieved target books its share at "
            "that target's price, and the remaining share exits at the stop-loss (stopped out) or is marked at the last "
            "price (still open — shown as <b>PARTIAL n/N</b>). The <b>Exit</b> column shows that last price / stop "
            "with the number of targets already booked, e.g. <b>4,555.00 (3/6 booked)</b>, so the Yield can be "
            "positive for a SELL even when the exit is above the entry. Trades that reached every target are "
            "unchanged.</p>")), 100))

    if not all_rows:
        blocks.append((templates.section(
            "Directional Stock Performance",
            '<p style="color:#64748b;font-size:11px;">No closed trades in the selected period'
            + (f' ({data["date_from"].strftime("%d-%b-%Y")} to {data["date_to"].strftime("%d-%b-%Y")})'
               if data.get("date_from") and data.get("date_to") else "")
            + ". Trades come from the alerts the strategy fired (Strategy Notifications) and "
              "appear once they have resolved — a target hit, stop-loss or close. A trade still "
              "open is not counted yet.</p>"), 96))

    # Page 1 (header, KPIs, donut(s), curve) is measured; the rest flows —
    # the trade table can be hundreds of rows, so it continues across pages.
    page1_used = 74 + 78 + (2 if comparing else 1) * 218 + 298
    return emv_report_data._flow_pages(
        page1, page1_used, blocks, "Directional Stock Performance", columns, all_rows, {"Status"},
    )


def build_report_html(data: dict, doc_title: str = "LMV EOD Report", columns: list | None = None) -> str:
    return templates.render_report(build_report_pages(data, columns), doc_title=doc_title)
