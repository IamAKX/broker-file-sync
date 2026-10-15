"""
Per-date history of an Inception *strategy column* (issue #61) — e.g. the RSC
strategy's "RSC" column, ``(CLOSE / PMC) / (NIFTY CLOSE / NIFTY PMC) * 100``.

A strategy column normally exists only as of the latest day (it's computed
across the live/EOD universe by services.strategy_engine.apply_strategies),
so there was no way to plot it over a period — and strategies like RSC can't
be rebuilt as Formula Builder fields because they use *row references*
("CLOSE of NIFTY": another stock's value in the same row set).

This module recomputes the column for each past trading day:

1. For every day in the window, rebuild the stock's row from its own bars the
   same way the EOD universe snapshot does (Group A/B values + Formula
   Builder values as of that day).
2. Do the same for every stock the strategy refers to ("of" tokens, e.g.
   NIFTY), so a row reference resolves against THAT day's value of the other
   stock.
3. Run the strategy over that small per-day set of rows — row filter ignored,
   we want the column's value for the stock whether or not it "qualifies" —
   and read the column.

Limitation (same as the strategy-report "Days True"): a formula that
aggregates over the WHOLE universe (an ``_ALL`` function) or reads live
day-history is evaluated over just these few rows / blank, so such a column's
history will be wrong or blank; row references and the stock's own fields are
exact.
"""

from datetime import date

from services import emv_report_data, inception_bars_store, inception_strategy_store
from services.inception_formula_builder_columns import compute_for_bars
from services.strategy_engine import apply_strategies

_HISTORY_BARS_FOR_FORMULAS = 300   # bars handed to compute_for_bars per day (covers its lookbacks)


def field_code(strategy: dict, column_name: str) -> str:
    """The code a strategy column is offered under in field pickers."""
    return f'{column_name} [{strategy.get("name", "")}]'


def strategy_field_codes() -> list:
    """One code per named column of every Inception strategy."""
    out = []
    for strategy in inception_strategy_store.load_all():
        for column in strategy.get("columns", []):
            if column.get("name"):
                out.append(field_code(strategy, column["name"]))
    return out


def looks_like_strategy_field(code: str) -> bool:
    return bool(code) and code.endswith("]") and " [" in code


def resolve_field(code: str) -> tuple | None:
    """(strategy, column_name) for a code from strategy_field_codes(), else
    None. Cheap-rejects anything that isn't shaped like one before touching
    the strategy store."""
    if not looks_like_strategy_field(code):
        return None
    for strategy in inception_strategy_store.load_all():
        for column in strategy.get("columns", []):
            if column.get("name") and field_code(strategy, column["name"]) == code:
                return strategy, column["name"]
    return None


def _walk_tokens(tokens):
    for tok in tokens or []:
        if isinstance(tok, dict):
            yield tok
            for key in ("formula", "args", "tokens"):
                if isinstance(tok.get(key), list):
                    yield from _walk_tokens(tok[key])


def referenced_symbols(strategy: dict) -> list:
    """Symbols the strategy's column formulas read through row references
    ("of" tokens), first-seen order, deduplicated case-insensitively."""
    seen, out = set(), []
    for column in strategy.get("columns", []):
        for tok in _walk_tokens(column.get("formula")):
            ref = tok.get("of")
            if ref and str(ref).strip().upper() not in seen:
                seen.add(str(ref).strip().upper())
                out.append(str(ref).strip())
    return out


def _rows_by_date(raw_symbol: str, bars: list, dates: set) -> dict:
    """{trade_date: row values} for *raw_symbol* on each of *dates* (where it
    has a bar), built the way the EOD universe snapshot builds a row."""
    from services import inception_compute_service, inception_settings

    targets = [b for b in bars if b["trade_date"] in dates]
    if not targets:
        return {}
    derived = inception_compute_service._compute_rows_for_days(bars, inception_settings.load(), targets)
    index_of = {b["trade_date"]: i for i, b in enumerate(bars)}
    display = emv_report_data._display_symbol(raw_symbol)
    out = {}
    for bar in targets:
        i = index_of[bar["trade_date"]]
        values = dict(derived.get(bar["trade_date"], {}))
        values.update(compute_for_bars(raw_symbol, bars[max(0, i - _HISTORY_BARS_FOR_FORMULAS): i + 1]))
        values["Symbol"] = display
        out[bar["trade_date"]] = values
    return out


def column_series(symbol: str, strategy: dict, column_name: str, date_from: date, date_to: date) -> list:
    """[{"date", "value", "close"}] — the strategy column's value for *symbol*
    on each trading day in [date_from, date_to] (same shape as
    inception_historical_field_series.historical_field_series). A day the
    formula can't be evaluated (a referenced stock has no bar, a missing
    field) has value None — never 0."""
    from services import inception_formula_variable_store

    raw = emv_report_data.resolve_symbol(symbol)
    bars = inception_bars_store.bars_for_symbol(raw, date_to=date_to)
    window = [b for b in bars if b["trade_date"] >= date_from]
    if not window:
        return []
    dates = {b["trade_date"] for b in window}

    own_rows = _rows_by_date(raw, bars, dates)
    known = set(inception_bars_store.available_symbols())
    ref_rows = {}
    for ref in referenced_symbols(strategy):
        raw_ref = emv_report_data.resolve_symbol(ref)
        if raw_ref in known and raw_ref != raw:
            ref_rows[raw_ref] = _rows_by_date(raw_ref, inception_bars_store.bars_for_symbol(raw_ref, date_to=date_to), dates)

    runnable = dict(strategy, active=True, row_filter=[])
    own_display = emv_report_data._display_symbol(raw)
    series = []
    for bar in window:
        d = bar["trade_date"]
        rows = [own_rows[d]] if d in own_rows else []
        rows += [r[d] for r in ref_rows.values() if d in r]
        value = None
        if rows:
            headers = ["Symbol"] + sorted({k for r in rows for k in r} - {"Symbol"})
            new_headers, new_data = apply_strategies(
                [runnable], headers, [[r.get(h) for h in headers] for r in rows], day_history={},
                include_streak_columns=False, symbol_col="Symbol", variable_store=inception_formula_variable_store,
            )
            if column_name in new_headers:
                sym_idx, col_idx = new_headers.index("Symbol"), new_headers.index(column_name)
                row = next((r for r in new_data if r[sym_idx] == own_display), None)
                value = _num(row[col_idx]) if row is not None else None
        series.append({"date": d, "value": value, "close": bar.get("close")})
    return series


def _num(value):
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
