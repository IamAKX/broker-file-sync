"""What Ask Fuku is told about the Live Master View when a question is asked.

Every question carries a small "live" block (see api.chat_api.ask and the
backend's schemas.chat.ChatLiveLmv):

* LMV running with data → the whole grid as currently shown (broker columns,
  formula columns and active strategy columns), so the backend can answer
  "right now" questions from it;
* otherwise → ``running: False`` plus a plain-language ``reason`` saying what
  is missing (which files aren't loaded, or that Run Watcher wasn't clicked),
  which the assistant shows the user instead of guessing from old data.

Everything here is read-only and must be called on the GUI thread. It never
raises: any surprise degrades to "not running" so a chat question can't fail
because of it.
"""

import math
from datetime import datetime

_BROKER_LABELS = {
    "Sharekhan": "Sharekhan",
    "ReliableSoftware": "Reliable Software",
    "NiftyInvest": "Nifty Invest",
    "ExternalImport": "External Import",
    "MarketProfile": "Market Profile",
}
_EMPTY_CELLS = {"", "-", "--", "—", "–", "n/a", "na", "nan", "none", "null"}
_STALE_AFTER_S = 300
_MAX_ROWS = 1500
_MAX_COLUMNS = 600
_ERROR_PREFIXES = ("Read error", "Render error", "Strategy error", "Live update error", "Error loading")

NOT_OPEN = ("The Live Master View is not running. Open Data Import, load today's files "
            "and click Run Watcher.")


def _cell(value):
    """A JSON-safe cell, or None for an empty one (the backend treats None as 'no value')."""
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return round(value, 4) if math.isfinite(value) else None
    text = str(value).strip()
    if text.lower() in _EMPTY_CELLS:
        return None
    return text[:120]


def missing_sources(data_import) -> list[str]:
    """Labels of the required Data Import sources that are not loaded yet."""
    missing = []
    imported = getattr(data_import, "_imported_brokers", set())
    cards = getattr(data_import, "_cards", {})
    for broker in sorted(getattr(data_import, "_REQUIRED_BROKERS", ())):
        if broker in imported:
            continue
        card = cards.get(broker)
        if card is not None and getattr(card, "_source_mode", "file") == "database":
            continue
        missing.append(_BROKER_LABELS.get(broker, broker))
    return missing


def _not_running(reason: str) -> dict:
    return {"running": False, "reason": reason}


def build(data_import, script_name_data, include_rows: bool = True, now: datetime | None = None) -> dict:
    """The "live" block for a chat question. *data_import* is the DataImportScreen
    (or None if it was never opened)."""
    try:
        return _build(data_import, script_name_data, include_rows, now or datetime.now())
    except Exception:
        from services.error_logging import error_logger
        error_logger.exception("Building the live LMV context for Ask Fuku failed")
        return _not_running("The Live Master View could not be read just now.")


def _build(data_import, script_name_data, include_rows: bool, now: datetime) -> dict:
    if data_import is None:
        return _not_running(NOT_OPEN)
    viewer = getattr(data_import, "_live_viewer", None)
    if viewer is None or viewer.isHidden() or getattr(viewer, "_chat_stopped", False):
        missing = missing_sources(data_import)
        if missing:
            return _not_running(
                "The Live Master View is not running, and these files are not loaded yet on Data Import: "
                + ", ".join(missing) + ". Load them, then click Run Watcher."
            )
        return _not_running(
            "The Live Master View is not running. All the required files are loaded — "
            "click Run Watcher on Data Import to start it."
        )

    status = viewer._status_lbl.text() if hasattr(viewer, "_status_lbl") else ""
    disp = getattr(viewer, "_chat_disp", None)
    headers, data = disp if disp else (getattr(viewer, "_headers", None) or [], getattr(viewer, "_data", None) or [])
    if not headers or not data or "Scrip Name" not in headers:
        detail = f" (status: {status})" if status else ""
        return _not_running(
            "The Live Master View is open but has no data loaded yet" + detail +
            ". Check that today's files are loaded on Data Import."
        )

    updated_at = getattr(viewer, "_chat_updated_at", None) or now
    warnings = []
    feed_warning = getattr(getattr(viewer, "_reader", None), "sharekhan_warning", "")
    if feed_warning:
        warnings.append("The live Excel feed is not readable, so prices may be the last saved ones, not live.")
    if status.startswith(_ERROR_PREFIXES):
        warnings.append(f"The Live Master View reported a problem on its last update ({status[:160]}).")
    age = (now - updated_at).total_seconds()
    if age > _STALE_AFTER_S:
        warnings.append(
            f"The grid last updated at {updated_at.strftime('%H:%M:%S')} ({int(age // 60)} min ago) — "
            "the market may be closed or the feed paused."
        )
    block = {
        "running": True,
        "reason": "",
        "warning": " ".join(warnings)[:600],
        "as_of": updated_at.strftime("%Y-%m-%d %H:%M:%S"),
        "stocks": len(data),
    }
    if include_rows:
        block["columns"], block["rows"] = _grid(headers, data, script_name_data)
    return block


def _grid(headers: list, data: list, script_name_data) -> tuple[list, list]:
    """→ (columns, rows) with each row = [symbol, display_name, sector, *values]."""
    from services.master_generator import _build_script_name_lookup, _strip_rolling_suffix

    name_to_symbol = _build_script_name_lookup(script_name_data)
    scrip_idx = headers.index("Scrip Name")
    sector_idx = headers.index("Sector") if "Sector" in headers else None
    seen, value_idx = set(), []
    for i, h in enumerate(headers):
        name = str(h).strip()
        if i in (scrip_idx, sector_idx) or not name or name in seen:
            continue
        seen.add(name)
        value_idx.append(i)
    value_idx = value_idx[:_MAX_COLUMNS]
    columns = [str(headers[i]).strip() for i in value_idx]

    rows = []
    for row in data[:_MAX_ROWS]:
        raw_name = str(row[scrip_idx]).strip() if scrip_idx < len(row) and row[scrip_idx] is not None else ""
        if not raw_name:
            continue
        display_name = _strip_rolling_suffix(raw_name) or raw_name
        symbol = name_to_symbol.get(display_name.lower()) or display_name
        sector = _cell(row[sector_idx]) if sector_idx is not None and sector_idx < len(row) else None
        rows.append([symbol, display_name, sector] + [_cell(row[i]) if i < len(row) else None for i in value_idx])
    return columns, rows


def summary(block: dict) -> tuple[bool, str]:
    """(connected?, one line for the chat screen's status label)."""
    if block.get("running"):
        time_part = (block.get("as_of") or "")[-8:]
        text = f"Live market data: on — LMV as of {time_part}, {block.get('stocks', 0)} stocks"
        if block.get("warning"):
            text += "  ⚠ " + block["warning"]
        return True, text
    return False, "Live market data: off — " + (block.get("reason") or NOT_OPEN)
