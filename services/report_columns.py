"""
Column catalogues for the report tables' dynamic column picker (LMV §
"Customize Strategy View Columns" / EMV "dynamic column selector"): which
columns a report table can show, which it shows by default, and how to turn
a selected column name into a cell value. A report's chosen, ordered list
lives in report["columns"] (services.report_store); an empty list means
"use the type's default columns".

LMV scope note: closed-trade rows carry what the signal itself recorded
(prices, high/low, score, target/stop-loss metric values) — the full LMV
column row at entry time is not stored, so those columns can't be offered.
"""

from datetime import datetime

from services.report_engine import templates

LMV_DEFAULT_COLUMNS = ["Strategy", "Ticker", "Direction", "Entry", "Exit", "Yield", "Days True", "Status"]
LMV_EXTRA_COLUMNS = ["Sector", "Entry Time", "Exit Time", "High", "Low", "Score"]

EMV_DEFAULT_COLUMNS = ["Stock", "Sector", "Fuku Score"]
EMV_FIXED_COLUMNS = ["Stock", "Sector", "Fuku Score"]


def resolve_columns(selected: list | None, available: list, default: list) -> list:
    """*selected* in its own order, minus anything not in *available*; the
    default list when nothing valid is selected."""
    chosen = [c for c in (selected or []) if c in available]
    return chosen or [c for c in default if c in available] or list(default)


def _fmt_price(value) -> str:
    return f"{value:,.2f}" if value is not None else "—"


def _fmt_dt(value) -> str:
    if not value:
        return "—"
    try:
        return datetime.fromisoformat(value).strftime("%d-%b-%Y %H:%M")
    except (TypeError, ValueError):
        return str(value)


# ── LMV ──────────────────────────────────────────────────────────────────

def lmv_catalog(metric_names: list | None = None) -> list:
    """Every column a LMV trade table can show: defaults, signal extras,
    then the strategy's own target/stop-loss metric names."""
    out = list(LMV_DEFAULT_COLUMNS) + LMV_EXTRA_COLUMNS
    out += [n for n in (metric_names or []) if n and n not in out]
    return out


def lmv_metric_names(trades: list) -> list:
    names = []
    for t in trades:
        for m in (t.get("metrics") or {}).values():
            n = m.get("name")
            if n and n not in names:
                names.append(n)
    return names


def lmv_cell(column: str, strategy_name: str, row: dict, fmt_pct) -> str:
    """Cell text for *column*; the Status column is pre-rendered HTML (see
    lmv_html_columns)."""
    trade = row.get("trade") or {}
    if column == "Strategy":
        return strategy_name
    if column == "Ticker":
        return row["symbol"]
    if column == "Direction":
        return row["direction"]
    if column == "Entry":
        return _fmt_price(row["entry"])
    if column == "Exit":
        return _fmt_price(row["exit"])
    if column == "Yield":
        return fmt_pct(row["yield"])
    if column == "Days True":
        return row["days_true"]
    if column == "Status":
        return templates.status_pill(row["status_label"], row["status_kind"])
    if column == "Sector":
        return trade.get("sector") or "—"
    if column == "Entry Time":
        return _fmt_dt(trade.get("entry_time"))
    if column == "Exit Time":
        return _fmt_dt(trade.get("resolved_at"))
    if column == "High":
        return _fmt_price(trade.get("running_high"))
    if column == "Low":
        return _fmt_price(trade.get("running_low"))
    if column == "Score":
        return _fmt_price(trade.get("score"))
    for m in (trade.get("metrics") or {}).values():
        if m.get("name") == column:
            return _fmt_price(m.get("value"))
    return "—"


# ── EMV (strategy-based) ─────────────────────────────────────────────────

def emv_catalog(field_codes: list | None = None) -> list:
    return list(EMV_FIXED_COLUMNS) + [c for c in (field_codes or []) if c not in EMV_FIXED_COLUMNS]


def emv_cell(column: str, row: dict) -> str:
    if column == "Stock":
        return row["symbol"]
    if column == "Sector":
        return row["sector"]
    if column == "Fuku Score":
        return f'{row["score"]["score"]:.0f} / {row["score"]["max_score"]:.0f}'
    value = (row.get("values") or {}).get(column)
    if value is None:
        return "—"
    return f"{value:,.2f}" if isinstance(value, float) else str(value)
