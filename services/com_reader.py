"""
COM-based live data reader for TradeTiger's Snap to Excel feature.

TradeTiger pushes live price data into an open Excel workbook via DDE.
The .xls file on disk is never updated continuously — data lives in the
open Excel instance's memory. This module reads it directly via COM.

Windows only. On macOS/Linux returns None gracefully.
"""

import os
import platform

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
            for w in excel.Workbooks:
                if os.path.basename(w.FullName).lower() == target_name:
                    self._wb_cache[target_name] = w
                    return w
        except Exception:
            # Stale Excel handle — drop everything and let the next call retry.
            self._invalidate()
        return None

    # ── Public read ───────────────────────────────────────────────────────────

    def read_workbook_sheet(self, workbook_path: str, col_indices: list,
                            header_row_idx: int) -> tuple[list, list[list]] | None:
        """
        Read the first sheet of *workbook_path* from the cached Excel instance.

        Mirrors the module-level :func:`read_workbook_sheet` but reuses the
        cached Excel/Workbook handles.  Returns (headers, rows) or None.
        """
        if not _WIN32COM_AVAILABLE:
            return None
        target_name = os.path.basename(workbook_path).lower()
        wb = self._get_workbook(target_name)
        if wb is None:
            return None
        try:
            sheet = wb.Sheets(1)
        except Exception:
            # Workbook handle went stale between lookup and use.
            self._wb_cache.pop(target_name, None)
            self._excel = None
            return None
        try:
            return _read_sheet_cells(sheet, col_indices, header_row_idx)
        except Exception:
            self._invalidate()
            return None


def _read_sheet_cells(sheet, col_indices: list,
                      header_row_idx: int) -> tuple[list, list[list]] | None:
    """
    Read a worksheet via COM using absolute row/col indices matching the
    same conventions as file_reader.py.

    Reads from cell A1 so that header_row_idx and col_indices are the
    same 0-based values used when reading from disk.
    """
    try:
        used = sheet.UsedRange
        last_row = used.Row + used.Rows.Count - 1
        last_col = max(used.Column + used.Columns.Count - 1,
                       max(col_indices) + 1)
        rng  = sheet.Range(sheet.Cells(1, 1), sheet.Cells(last_row, last_col))
        raw  = rng.Value
        if not raw:
            return None
        # COM returns a tuple-of-tuples; normalise to list-of-lists.
        if not isinstance(raw[0], (tuple, list)):
            raw = (raw,)
        rows = [list(r) for r in raw]
        if len(rows) <= header_row_idx:
            return None
        ncols = len(rows[header_row_idx])
        headers = [
            str(rows[header_row_idx][i]) if i < ncols and rows[header_row_idx][i] is not None else ""
            for i in col_indices
        ]
        data = [
            [row[i] if i < len(row) else None for i in col_indices]
            for row in rows[header_row_idx + 1:]
        ]
        return headers, data
    except Exception:
        return None


def read_workbook_sheet(workbook_path: str, col_indices: list,
                        header_row_idx: int) -> tuple[list, list[list]] | None:
    """
    Read the specified workbook from the running Excel instance.

    Matches by filename so Sharekhan's live DDE data (which is never
    flushed back to disk) is read directly from Excel's memory.
    Returns (headers, rows) on success, None if Excel is not running or
    the workbook is not open.
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

        return _read_sheet_cells(sheet, col_indices, header_row_idx)

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
