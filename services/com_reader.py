"""
COM-based live data reader for TradeTiger's Snap to Excel feature.

TradeTiger pushes live price data into an open Excel workbook via DDE.
The .xls file on disk is never updated continuously — data lives in the
open Excel instance's memory. This module reads it directly via COM.

Windows only. On macOS/Linux returns None gracefully.
"""

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
