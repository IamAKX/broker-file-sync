"""
Read broker export files and extract the configured columns.

Column specs (0-based indices):
  Sharekhan       (.xlsx/.xls): header at row 8 (idx 7), data from row 9
                  cols C,D,E,F,I,J,K,L,M,N,O,P,Z,AA,AB
  ReliableSoftware(.xlsx/.xls): header at row 1 (idx 0), data from row 2
                  cols B,E,F,K,L
  NiftyInvest     (.csv):       header at row 1 (idx 0), data from row 2
                  cols A,C
  MarketProfile   (.csv/.xlsx): header at row 1 (idx 0), data from row 2
                  cols B(stock key),G(VAH),H(POC),I(VAL)
"""

_SHAREKHAN_COLS  = [2, 3, 4, 5, 8, 9, 10, 11, 12, 13, 14, 15, 25, 26, 27]
_RELIABLE_COLS   = [1, 4, 5, 10, 11]
_NIFTY_COLS      = [0, 2]
_MARKET_PROFILE_COLS = [1, 6, 7, 8]   # B=stock(key), G=VAH, H=POC, I=VAL

# Row index (0-based) of the header row for each broker
_SHAREKHAN_HEADER_ROW  = 7   # row 8
_RELIABLE_HEADER_ROW   = 0   # row 1
_NIFTY_HEADER_ROW      = 0   # row 1
_MARKET_PROFILE_HEADER_ROW = 0   # row 1


def count_rows(path: str, data_start_row: int = 1) -> int:
    """Return number of data rows. data_start_row is 0-based index of first data row."""
    try:
        if path.lower().endswith(".xlsx"):
            import openpyxl
            wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
            ws = wb.active
            count = ws.max_row - data_start_row
            wb.close()
            return max(0, count)
        elif path.lower().endswith(".xls"):
            import xlrd
            wb = xlrd.open_workbook(path)
            ws = wb.sheet_by_index(0)
            return max(0, ws.nrows - data_start_row)
        elif path.lower().endswith(".csv"):
            with open(path, "r", encoding="utf-8", errors="replace") as f:
                return max(0, sum(1 for _ in f) - data_start_row)
    except Exception:
        pass
    return 0


def count_rows_sharekhan(path: str) -> int:
    return count_rows(path, data_start_row=_SHAREKHAN_HEADER_ROW + 1)


def count_rows_reliable(path: str) -> int:
    return count_rows(path, data_start_row=_RELIABLE_HEADER_ROW + 1)


def count_rows_nifty(path: str) -> int:
    return count_rows(path, data_start_row=_NIFTY_HEADER_ROW + 1)


def count_rows_market_profile(path: str) -> int:
    return count_rows(path, data_start_row=_MARKET_PROFILE_HEADER_ROW + 1)


def _extract_cols(row: tuple | list, col_indices: list, ncols: int) -> list:
    return [row[i] if i < ncols else None for i in col_indices]


def _read_xlsx(path: str, col_indices: list, header_row_idx: int) -> tuple[list, list]:
    import openpyxl
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if len(rows) <= header_row_idx:
        return [], []
    ncols = len(rows[header_row_idx]) if rows[header_row_idx] else 0
    headers = _extract_cols(rows[header_row_idx], col_indices, ncols)
    headers = [str(h) if h is not None else "" for h in headers]
    data = []
    for row in rows[header_row_idx + 1:]:
        nc = len(row) if row else 0
        data.append(_extract_cols(row, col_indices, nc))
    return headers, data


def _read_xls(path: str, col_indices: list, header_row_idx: int) -> tuple[list, list]:
    import xlrd
    wb = xlrd.open_workbook(path)
    ws = wb.sheet_by_index(0)
    if ws.nrows <= header_row_idx:
        return [], []
    headers = [str(ws.cell_value(header_row_idx, i)) if i < ws.ncols else ""
               for i in col_indices]
    data = []
    for r in range(header_row_idx + 1, ws.nrows):
        data.append([ws.cell_value(r, i) if i < ws.ncols else None for i in col_indices])
    return headers, data


def _read_csv(path: str, col_indices: list, header_row_idx: int) -> tuple[list, list]:
    import csv
    with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
        rows = list(csv.reader(f))
    if len(rows) <= header_row_idx:
        return [], []
    ncols = len(rows[header_row_idx])
    headers = _extract_cols(rows[header_row_idx], col_indices, ncols)
    headers = [str(h) if h is not None else "" for h in headers]
    data = []
    for row in rows[header_row_idx + 1:]:
        nc = len(row)
        data.append(_extract_cols(row, col_indices, nc))
    return headers, data


def _read_file(path: str, col_indices: list, header_row_idx: int) -> tuple[list, list]:
    if path.lower().endswith(".xlsx"):
        return _read_xlsx(path, col_indices, header_row_idx)
    elif path.lower().endswith(".xls"):
        return _read_xls(path, col_indices, header_row_idx)
    elif path.lower().endswith(".csv"):
        return _read_csv(path, col_indices, header_row_idx)
    raise ValueError(f"Unsupported file type: {path}")


def read_sharekhan(path: str) -> tuple[list, list]:
    return _read_file(path, _SHAREKHAN_COLS, _SHAREKHAN_HEADER_ROW)


def read_reliable_software(path: str) -> tuple[list, list]:
    return _read_file(path, _RELIABLE_COLS, _RELIABLE_HEADER_ROW)


def read_nifty_invest(path: str) -> tuple[list, list]:
    return _read_file(path, _NIFTY_COLS, _NIFTY_HEADER_ROW)


def read_market_profile(path: str) -> tuple[list, list]:
    return _read_file(path, _MARKET_PROFILE_COLS, _MARKET_PROFILE_HEADER_ROW)


def read_external_import(path: str) -> tuple[list, list]:
    """Read all columns from an external file (xlsx/xls/csv). Header at row 1."""
    if path.lower().endswith(".xlsx"):
        import openpyxl
        wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
        ws = wb.active
        rows = list(ws.iter_rows(values_only=True))
        wb.close()
        if not rows:
            return [], []
        headers = [str(h) if h is not None else "" for h in rows[0]]
        data = [list(r) for r in rows[1:]]
        return headers, data
    elif path.lower().endswith(".xls"):
        import xlrd
        wb = xlrd.open_workbook(path)
        ws = wb.sheet_by_index(0)
        if ws.nrows == 0:
            return [], []
        headers = [str(ws.cell_value(0, c)) for c in range(ws.ncols)]
        data = [[ws.cell_value(r, c) for c in range(ws.ncols)] for r in range(1, ws.nrows)]
        return headers, data
    elif path.lower().endswith(".csv"):
        import csv
        with open(path, "r", encoding="utf-8", errors="replace", newline="") as f:
            rows = list(csv.reader(f))
        if not rows:
            return [], []
        return rows[0], [list(r) for r in rows[1:]]
    raise ValueError(f"Unsupported file type: {path}")


def count_rows_external(path: str) -> int:
    return count_rows(path, data_start_row=1)


def read_historic_upload(path: str) -> tuple[list, list]:
    """Read all columns from a historic-upload file (xlsx/xls/csv), no fixed template."""
    return read_external_import(path)
