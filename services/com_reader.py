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


def read_snap_sheet() -> tuple[list, list[list]] | None:
    """
    Connect to the open Excel instance and read TradeTiger's Snap sheet.

    Returns (headers, rows) where headers is a list of column names and
    rows is a list of lists of cell values. Returns None if Excel is not
    running, the Snap workbook is not open, or COM fails.
    """
    if not _WIN32COM_AVAILABLE:
        return None

    try:
        pythoncom.CoInitialize()
        excel = win32com.client.GetActiveObject("Excel.Application")
    except Exception:
        return None

    try:
        # Find the Snap workbook
        snap_wb = None
        for wb in excel.Workbooks:
            if _SNAP_WB.lower() in wb.Name.lower():
                snap_wb = wb
                break
        if snap_wb is None:
            return None

        # Find the sheet — try exact name first, then first sheet
        sheet = None
        try:
            sheet = snap_wb.Sheets(_SNAP_SHEET)
        except Exception:
            # Fall back to first sheet if sheet name differs by version
            try:
                sheet = snap_wb.Sheets(1)
            except Exception:
                return None

        # Read all used cells
        used = sheet.UsedRange
        raw = used.Value
        if not raw:
            return None

        rows = [list(r) for r in raw]
        if not rows:
            return None

        # First row is headers — convert None to empty string
        headers = [str(h) if h is not None else "" for h in rows[0]]
        data = []
        for row in rows[1:]:
            data.append([c for c in row])

        return headers, data

    except Exception:
        return None
    finally:
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass
