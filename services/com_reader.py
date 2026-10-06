"""
COM-based live data reader for TradeTiger's Snap to Excel feature.

TradeTiger pushes live price data into an open Excel workbook via DDE.
The .xls file on disk is never updated continuously — data lives in the
open Excel instance's memory. This module reads it directly via COM.

Windows only. On macOS/Linux returns None gracefully.
"""

import os
import platform
import time

_WIN32COM_AVAILABLE = False

if platform.system() == "Windows":
    try:
        import win32com.client
        import pythoncom
        _WIN32COM_AVAILABLE = True
    except ImportError:
        pass


# Sheet name TradeTiger uses for Snap to Excel
_SNAP_SHEET = "Streaming_Stock_Watch"
# Partial workbook name match
_SNAP_WB    = "Snap"


def _norm_header(h) -> str:
    """Header-cell text normalised for matching: collapses runs of whitespace
    (incl. NBSP/newlines that DDE-fed header cells sometimes carry) and
    ignores case, so a cosmetically different header still resolves."""
    return " ".join(str(h).replace("\xa0", " ").split()).lower() if h is not None else ""


def is_available() -> bool:
    """True if COM automation is available (Windows + pywin32 installed)."""
    return _WIN32COM_AVAILABLE


def _get_excel() -> object | None:
    """Return the running Excel.Application COM object, or None."""
    if not _WIN32COM_AVAILABLE:
        return None
    try:
        pythoncom.CoInitialize()
        return win32com.client.GetActiveObject("Excel.Application")
    except Exception:
        return None


class ExcelLiveReader:
    """
    Stateful COM reader that caches the running Excel.Application handle and
    the per-workbook COM objects across reads.

    Re-acquiring the Excel handle (GetActiveObject) and re-enumerating
    Workbooks on every tick is the dominant cross-process COM cost.  Holding
    the handles between ticks lets each read be a single marshalled
    ``Range.Value`` call.  Any COM error invalidates the cache so the next
    read transparently re-acquires — covering Excel restarts or workbook
    close/reopen.

    Intended to live on a worker thread: call :meth:`init_thread` once on that
    thread before the first read and :meth:`close` when finished so COM is
    initialised/uninitialised on the correct thread.
    """

    def __init__(self):
        self._excel = None
        self._wb_cache: dict[str, object] = {}   # basename(lower) → Workbook COM obj
        self._com_inited = False
        # Why the most recent read_workbook_sheet() returned None ("" after a
        # success). Callers silently fall back to the stale on-disk file on
        # None, so this is the only trail explaining a "prices frozen" report.
        self.last_failure = ""

    # ── Thread lifecycle ────────────────────────────────────────────────────

    def init_thread(self) -> None:
        """Initialise COM on the calling thread (idempotent)."""
        if _WIN32COM_AVAILABLE and not self._com_inited:
            try:
                pythoncom.CoInitialize()
                self._com_inited = True
            except Exception:
                pass

    def close(self) -> None:
        """Release cached handles and uninitialise COM on the calling thread."""
        self._invalidate()
        if _WIN32COM_AVAILABLE and self._com_inited:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass
            self._com_inited = False

    # ── Internals ─────────────────────────────────────────────────────────────

    def _invalidate(self) -> None:
        self._excel = None
        self._wb_cache.clear()

    def _ensure_excel(self) -> object | None:
        if self._excel is not None:
            return self._excel
        if not _WIN32COM_AVAILABLE:
            return None
        try:
            self._excel = win32com.client.GetActiveObject("Excel.Application")
        except Exception:
            self._excel = None
            self._wb_cache.clear()
        return self._excel

    def _get_workbook(self, target_name: str) -> object | None:
        """Return the cached Workbook COM object for *target_name*, or find it."""
        wb = self._wb_cache.get(target_name)
        if wb is not None:
            # Touch a cheap property to confirm the handle is still alive.
            try:
                _ = wb.Name
                return wb
            except Exception:
                self._wb_cache.pop(target_name, None)

        excel = self._ensure_excel()
        if excel is None:
            return None
        try:
            open_names = []
            for w in excel.Workbooks:
                name = os.path.basename(w.FullName).lower()
                if name == target_name:
                    self._wb_cache[target_name] = w
                    return w
                open_names.append(name)
            self.last_failure = (
                f"workbook '{target_name}' is not open in the Excel instance this app "
                f"attached to (open there: {', '.join(open_names) or 'none'})"
            )
        except Exception as exc:
            # Stale Excel handle — drop everything and let the next call retry.
            self.last_failure = f"Excel Workbooks enumeration failed: {exc!r}"
            self._invalidate()
        return None

    # ── Public read ───────────────────────────────────────────────────────────

    def read_workbook_sheet(self, workbook_path: str, col_names: list,
                            header_row_idx: int) -> tuple[list, list[list]] | None:
        """
        Read the first sheet of *workbook_path* from the cached Excel instance.

        Mirrors the module-level :func:`read_workbook_sheet` but reuses the
        cached Excel/Workbook handles.  Returns (headers, rows) or None.
        """
        if not _WIN32COM_AVAILABLE:
            return None
        self.last_failure = ""
        target_name = os.path.basename(workbook_path).lower()
        wb = self._get_workbook(target_name)
        if wb is None:
            if self._excel is None and not self.last_failure:
                self.last_failure = "no running Excel instance found (GetActiveObject failed)"
            return None
        try:
            sheet = wb.Sheets(1)
        except Exception as exc:
            # Workbook handle went stale between lookup and use.
            self.last_failure = f"could not open sheet 1: {exc!r}"
            self._wb_cache.pop(target_name, None)
            self._excel = None
            return None
        # Excel rejects COM calls while a cell is being edited or a dialog is
        # open — transient, so retry once before dropping to the stale disk copy.
        for attempt in (1, 2):
            try:
                result, reason = _read_sheet_cells_ex(sheet, col_names, header_row_idx)
            except Exception as exc:
                result, reason = None, f"COM read raised {exc!r}"
                self._invalidate()
                if attempt == 1:
                    time.sleep(0.05)
                    continue
            if result is None:
                self.last_failure = reason
            return result
        return None


def _read_sheet_cells_ex(sheet, col_names: list,
                         header_row_idx: int) -> tuple[tuple | None, str]:
    """
    Read a worksheet via COM, then locate each of *col_names* by matching
    it against the sheet's own header row (row header_row_idx) — same
    by-name resolution services.file_reader.read_sharekhan uses for the
    on-disk fallback, and for the identical reason: TradeTiger's live Snap
    to Excel feed doesn't guarantee the same column ORDER across accounts,
    only the header text, so a fixed column-letter read can silently read
    the wrong column's live numbers under the right header.

    Reads from cell A1 so header_row_idx is the same 0-based row used when
    reading from disk. Returns (result, "") on success, or (None, reason)
    when a header in *col_names* can't be found in the live sheet etc. —
    callers treat None as "fall back to the on-disk reader" and surface
    *reason* so that fallback is never silent. Raises on a COM error.
    """
    used = sheet.UsedRange
    last_row = used.Row + used.Rows.Count - 1
    last_col = used.Column + used.Columns.Count - 1
    rng  = sheet.Range(sheet.Cells(1, 1), sheet.Cells(last_row, last_col))
    raw  = rng.Value
    if not raw:
        return None, "live sheet returned no cells"
    # COM returns a tuple-of-tuples; normalise to list-of-lists.
    if not isinstance(raw[0], (tuple, list)):
        raw = (raw,)
    rows = [list(r) for r in raw]
    if len(rows) <= header_row_idx:
        return None, f"live sheet has {len(rows)} rows, header expected on row {header_row_idx + 1}"
    header_row = [_norm_header(h) for h in rows[header_row_idx]]
    missing = [n for n in col_names if _norm_header(n) not in header_row]
    if missing:
        return None, (f"header(s) {missing} not found on row {header_row_idx + 1} of the live sheet "
                      f"(found: {[h for h in header_row if h]})")
    indices = [header_row.index(_norm_header(name)) for name in col_names]
    data = [
        [row[i] if i < len(row) else None for i in indices]
        for row in rows[header_row_idx + 1:]
    ]
    return (list(col_names), data), ""


def _read_sheet_cells(sheet, col_names: list,
                      header_row_idx: int) -> tuple[list, list[list]] | None:
    """Result-only wrapper over :func:`_read_sheet_cells_ex` (swallows COM
    errors as None, like every other failure here)."""
    try:
        return _read_sheet_cells_ex(sheet, col_names, header_row_idx)[0]
    except Exception:
        return None


def read_workbook_sheet(workbook_path: str, col_names: list,
                        header_row_idx: int) -> tuple[list, list[list]] | None:
    """
    Read the specified workbook from the running Excel instance.

    Matches by filename so Sharekhan's live DDE data (which is never
    flushed back to disk) is read directly from Excel's memory. Columns
    are located by header name — see _read_sheet_cells. Returns (headers,
    rows) on success, None if Excel is not running, the workbook is not
    open, or an expected header isn't found in the live sheet.
    """
    if not _WIN32COM_AVAILABLE:
        return None

    import os
    target_name = os.path.basename(workbook_path).lower()

    excel = _get_excel()
    if excel is None:
        return None

    try:
        wb = None
        for w in excel.Workbooks:
            if os.path.basename(w.FullName).lower() == target_name:
                wb = w
                break
        if wb is None:
            return None

        try:
            sheet = wb.Sheets(1)
        except Exception:
            return None

        return _read_sheet_cells(sheet, col_names, header_row_idx)

    except Exception:
        return None
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


def read_snap_sheet() -> tuple[list, list[list]] | None:
    """
    Read TradeTiger's Snap sheet from the running Excel instance.
    Returns (headers, rows), or None if not found.
    """
    if not _WIN32COM_AVAILABLE:
        return None

    excel = _get_excel()
    if excel is None:
        return None

    try:
        snap_wb = None
        for wb in excel.Workbooks:
            if _SNAP_WB.lower() in wb.Name.lower():
                snap_wb = wb
                break
        if snap_wb is None:
            return None

        try:
            sheet = snap_wb.Sheets(_SNAP_SHEET)
        except Exception:
            try:
                sheet = snap_wb.Sheets(1)
            except Exception:
                return None

        used = sheet.UsedRange
        raw  = used.Value
        if not raw:
            return None

        rows = [list(r) for r in raw]
        if not rows:
            return None

        headers = [str(h) if h is not None else "" for h in rows[0]]
        return headers, [list(r) for r in rows[1:]]

    except Exception:
        return None
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
