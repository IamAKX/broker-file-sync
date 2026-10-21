"""Back-test of an Inception (EMV) strategy over the locally synced daily bars
(issue #83), producing the trades for the shared Back-test report
(services.backtest_report).

The rules come from services.inception_backtest_config: a direction (BUY/SELL),
an ENTRY condition, an EXIT condition and optional informational metrics. There
is deliberately no target / stop-loss / trailing exit.

How a stock is walked, one trading day at a time (each stock independently):

  * the day's row is the same one EMV View by Date shows — raw OHLCV, Group A/B
    values, the Formula Builder columns (MT, WT, DT, ...) as of that day, then
    the strategy's own columns, with the same look-back history View by Date
    builds (VALUE_DAYS_AGO / VALUE_ON_DATE / AVG_DAYS / VALUE_BEFORE_CHANGE ...)
    resolved from the bars up to THAT day, so a back-test day sees exactly what
    the EMV table showed on it;
  * a stock is IN the strategy that day when it passes the strategy's row filter
    (no filter = always); it ENTERS at that day's closing price when it is in the
    strategy and the entry condition is true (no entry condition: being in the
    strategy is the entry);
  * from the next day on it EXITS at a day's closing price when the exit condition
    is true (no exit condition: once the entry no longer holds);
  * after an exit the entry condition must turn false at least once before the
    stock can enter again — the same "don't re-fire the same continuous move" rule
    the LMV alert engine uses;
  * a trade still open at the end of the range is not counted (reported as open).

Informational metrics are evaluated on the entry day's row and shown in the
trade ledger. Limits, reported in the report itself: a formula that compares a
stock with the whole universe (the *_ALL aggregates / "[X of OtherStock]") reads
blank because stocks are walked one by one, and a look-back into a Group A/B
column (VALUE_DAYS_AGO([52WH], ...)) is not resolved.
"""

from datetime import date

from services import (
    emv_report_data, inception_backtest_config, inception_bars_store, inception_compute_service,
    inception_day_history, inception_formula_builder_columns, inception_formula_variable_store,
    inception_sector, inception_settings, inception_value_before_change,
)
from services.formula_engine import FORMULA_CODES
from services.report_metrics import directional_yield
from services.strategy_engine import apply_strategies, evaluate, evaluate_condition

SYMBOL_KEY = "Scrip Name"        # the key evaluate()'s day_history lookup reads by default


class _Bundle:
    """Which look-back resolvers a strategy's formulas need — worked out once
    per back-test, then applied per stock and day."""

    def __init__(self, strategy: dict, config: dict):
        columns = list(strategy.get("columns", []))
        for name, tokens in (("__entry", config.get("entry_condition")), ("__exit", config.get("exit_condition")),
                             ("__filter", strategy.get("row_filter"))):
            if tokens:
                columns.append({"name": name, "formula": tokens})
        columns += [{"name": m["name"], "formula": m.get("formula") or []} for m in config.get("metrics", [])]
        pseudo = [{"id": strategy.get("id"), "columns": columns, "row_filter": []}]

        store = inception_formula_variable_store
        self.specs = inception_day_history.raw_day_specs(pseudo)
        self.extreme_specs = inception_day_history.raw_extreme_specs(pseudo)
        vbc = inception_value_before_change.specs_for_strategies(pseudo)
        self.vbc_fb = [(c, m) for c, m in vbc if c in FORMULA_CODES]
        vbc_other = [(c, m) for c, m in vbc if c not in FORMULA_CODES]
        vbc_n = inception_value_before_change.n_specs_for_strategies(pseudo)
        self.vbc_n_fb = [(c, n) for c, n in vbc_n if c in FORMULA_CODES]
        vbc_n_other = [(c, n) for c, n in vbc_n if c not in FORMULA_CODES]
        derived = inception_day_history.derived_day_specs(pseudo)
        self.derived_fb = [s for s in derived if s[1] in FORMULA_CODES]
        derived_group = [s for s in derived if s[1] not in FORMULA_CODES]
        all_extreme = inception_day_history.extreme_specs_for_strategies(pseudo)
        extra = (inception_day_history.extreme_needed_pairs(all_extreme)
                 - inception_day_history.extreme_needed_pairs(self.extreme_specs))
        self.extra_raw, self.extra_fb, extra_group = inception_day_history.split_extreme_pairs_by_kind(extra)
        self.strategy_columns = inception_day_history.strategy_column_specs(pseudo, store)
        # Group A/B look-backs need a whole-universe range pass per day — not supported.
        self.unsupported = bool(vbc_other or vbc_n_other or derived_group or extra_group)
        self.needed = bool(self.specs or self.extreme_specs or self.vbc_fb or self.vbc_n_fb or self.derived_fb
                           or self.extra_raw or self.extra_fb or self.strategy_columns)

    def history(self, symbol: str, bars: list) -> dict:
        """The day_history View by Date would build for *symbol* as of bars[-1]."""
        if not self.needed:
            return {}
        merge = inception_day_history.merge_into
        out: dict = {}
        store = inception_formula_variable_store
        if self.strategy_columns:
            merge(out, inception_day_history.resolve_strategy_columns(self.strategy_columns, symbol, bars, store))
        if self.specs:
            merge(out, inception_day_history.build(self.specs, symbol, bars))
        if self.extreme_specs:
            merge(out, inception_day_history.build_extreme(self.extreme_specs, symbol, bars))
        if self.vbc_fb:
            merge(out, inception_value_before_change.resolve_formula_builder(self.vbc_fb, symbol, bars))
        if self.vbc_n_fb:
            merge(out, inception_value_before_change.resolve_formula_builder_n(self.vbc_n_fb, symbol, bars))
        if self.extra_raw:
            merge(out, inception_day_history.build_extreme_for_pairs(self.extra_raw, symbol, bars))
        if self.derived_fb:
            merge(out, inception_day_history.resolve_formula_builder_day(self.derived_fb, symbol, bars))
        if self.extra_fb:
            merge(out, inception_day_history.resolve_formula_builder_extreme(self.extra_fb, symbol, bars))
        return out


def _to_float(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _holds(tokens: list, row: dict, history: dict) -> bool:
    return bool(evaluate_condition(tokens, row, [row], day_history=history,
                                   variable_store=inception_formula_variable_store))


def _walk_symbol(strategy: dict, config: dict, bundle: _Bundle, symbol: str, bars: list, settings: dict,
                 date_from: date, date_to: date) -> tuple:
    """(trades, still_open) for one stock."""
    in_range = [b for b in bars if date_from <= b["trade_date"] <= date_to]
    if not in_range:
        return [], False
    display = emv_report_data._display_symbol(symbol)
    sector = inception_sector.sector_for(display)
    ab_rows = inception_compute_service._compute_rows_for_days(bars, settings, in_range)
    position_in_bars = {b["trade_date"]: i for i, b in enumerate(bars)}

    entry_tokens = config.get("entry_condition") or []
    exit_tokens = config.get("exit_condition") or []
    filter_tokens = strategy.get("row_filter") or []
    own = dict(strategy, active=True, row_filter=[])
    direction = config.get("direction") or "BUY"
    metrics = config.get("metrics") or []

    headers = None
    trades, position, armed = [], None, True
    for bar in in_range:
        close = _to_float(bar.get("close"))
        if close is None:
            continue
        upto = bars[: position_in_bars[bar["trade_date"]] + 1]
        values = dict(ab_rows.get(bar["trade_date"]) or {})
        values.update(inception_formula_builder_columns.compute_for_bars(symbol, upto))
        history = bundle.history(display, upto)

        keys = ["Sector", "Symbol"] + sorted(values)
        row_values = {"Sector": sector, "Symbol": display, **values}
        if headers is None or len(keys) != len(headers):
            headers = keys
        new_headers, new_rows = apply_strategies(
            [own], headers, [[row_values.get(h) for h in headers]], day_history=history,
            include_streak_columns=False, symbol_col="Symbol", variable_store=inception_formula_variable_store)
        if not new_rows:
            continue
        row = dict(zip(new_headers, new_rows[0]))
        row[SYMBOL_KEY] = display

        member = (not filter_tokens) or _holds(filter_tokens, row, history)
        entry_true = member and (_holds(entry_tokens, row, history) if entry_tokens else True)
        exit_true = _holds(exit_tokens, row, history) if exit_tokens else not entry_true

        if position is None:
            if entry_true and armed:
                position = {
                    "symbol": display, "sector": sector, "direction": direction,
                    "entry_date": bar["trade_date"], "entry": close,
                    "extra": {m["name"]: _to_float(evaluate(m.get("formula") or [], row, [row], day_history=history,
                                                           variable_store=inception_formula_variable_store))
                              for m in metrics},
                }
            elif not entry_true:
                armed = True
        elif exit_true and bar["trade_date"] > position["entry_date"]:
            position.update(exit_date=bar["trade_date"], exit=close,
                            **{"yield": directional_yield(position["entry"], close, direction)})
            trades.append(position)
            position, armed = None, not entry_true
    return trades, position is not None


def run(strategy: dict, config: dict, date_from: date, date_to: date, stock: str | None = None,
        progress_cb=None) -> dict:
    """{"trades": [...], "open_trades": n, "notes": [...], "symbols": n}."""
    notes: list = []
    if not (config.get("entry_condition") or config.get("exit_condition")):
        notes.append("this strategy has no entry / exit condition yet — the strategy's row filter is used as the entry "
                     "and the trade closes once it no longer holds")
    bundle = _Bundle(strategy, config)
    if bundle.unsupported:
        notes.append("a look-back into a Group A/B column (e.g. VALUE_DAYS_AGO([52WH], n)) is not resolved in a "
                     "back-test and reads blank")
    settings = inception_settings.load()
    if stock:
        symbols = [emv_report_data.resolve_symbol(stock)]
    else:
        symbols = inception_bars_store.available_symbols()

    trades, open_trades, with_data = [], 0, 0
    for i, symbol in enumerate(symbols):
        bars = inception_bars_store.bars_for_symbol(symbol, date_to=date_to)
        if bars:
            done, still_open = _walk_symbol(strategy, config, bundle, symbol, bars, settings, date_from, date_to)
            if any(date_from <= b["trade_date"] <= date_to for b in bars):
                with_data += 1
            trades.extend(done)
            open_trades += 1 if still_open else 0
        if progress_cb:
            progress_cb(i + 1, len(symbols))
    if stock and not with_data:
        notes.append(f"no synced price history for {stock.upper()} in this period")
    first = inception_bars_store.first_synced_date()
    if first and first > date_from:
        notes.append(f"synced history only starts on {first.strftime('%d-%b-%Y')}; earlier days are not covered")
    trades.sort(key=lambda t: (t["exit_date"], t["entry_date"], t["symbol"]))
    return {"trades": trades, "open_trades": open_trades, "notes": notes, "symbols": with_data}


def _describe(tokens: list) -> str:
    return " ".join(str(t.get("value", "")).strip() for t in (tokens or [])) or "—"


def backtest_result(strategy_id: str, date_from: date, date_to: date, investment_amount: float = 5000.0,
                    stock: str | None = None, progress_cb=None) -> dict:
    """The shared Back-test report's input (services.backtest_report) for an EMV
    strategy — whole universe, or one stock (#83)."""
    from services import inception_strategy_store

    strategy = next((s for s in inception_strategy_store.load_all() if s.get("id") == strategy_id), None)
    if strategy is None:
        return {"kind": "EMV", "name": "Unknown strategy", "symbol": (stock or "").upper() or None,
                "date_from": date_from, "date_to": date_to, "investment_amount": investment_amount,
                "trades": [], "notes": ["the strategy was not found"], "method": ""}
    config = inception_backtest_config.load_config(strategy_id)
    result = run(strategy, config, date_from, date_to, stock, progress_cb)

    trades = []
    for t in result["trades"]:
        y = t["yield"]
        trades.append(dict(t, outcome="Exit signal", kind="neutral" if y is None else ("positive" if y >= 0 else "negative")))
    method = (
        '<p class="fk-note">These trades are <b>simulated</b> from the synced daily price history. '
        f'Direction: <b>{config["direction"]}</b>. A stock enters at the day\'s closing price when it is in the strategy '
        f'(row filter: {templates_esc(_describe(strategy.get("row_filter")))}) and the entry condition '
        f'<b>{templates_esc(_describe(config.get("entry_condition")))}</b> is true; it exits at a later day\'s closing price when '
        f'the exit condition <b>{templates_esc(_describe(config.get("exit_condition")))}</b> is true. After an exit the entry '
        "condition must turn false once before the stock can enter again. There are no targets or stop-loss. Yield is the "
        "directional % from entry to exit. Each day uses exactly the values EMV View by Date shows for that day.</p>"
    )
    return {
        "kind": "EMV", "name": strategy.get("name", "Strategy"), "symbol": (stock or "").strip().upper() or None,
        "date_from": date_from, "date_to": date_to, "investment_amount": investment_amount, "trades": trades,
        "open_trades": result["open_trades"], "notes": result["notes"], "method": method,
        "extra_columns": [m["name"] for m in config.get("metrics", [])],
    }


def templates_esc(text: str) -> str:
    from services.report_engine import templates
    return templates.esc(text)
