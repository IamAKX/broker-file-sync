"""services.com_reader._read_sheet_cells — column resolution by header
name (issue: a differently-laid-out Sharekhan/TradeTiger live sheet could
silently read the wrong column's live numbers under the right header when
this read by fixed column letter; see services.file_reader.read_sharekhan's
own docstring for the on-disk half of the same fix).

Windows-only module (win32com), but _read_sheet_cells itself takes a plain
COM-shaped object and does no platform check, so it's testable anywhere
with a fake `sheet`.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.com_reader import _read_sheet_cells


class _Counted:
    def __init__(self, count):
        self.Count = count


class _FakeUsedRange:
    def __init__(self, nrows, ncols):
        self.Row = 1
        self.Column = 1
        self.Rows = _Counted(nrows)
        self.Columns = _Counted(ncols)


class _FakeRange:
    def __init__(self, value):
        self.Value = value


class _FakeSheet:
    """*grid* is the full used range, row 0 = header row idx 0 for this
    test's purposes (matches how live_merge/file_reader both pass
    header_row_idx=7 against a full 0-based grid)."""

    def __init__(self, grid):
        self._grid = grid
        ncols = len(grid[0]) if grid else 0
        self.UsedRange = _FakeUsedRange(len(grid), ncols)

    def Cells(self, row, col):
        return (row, col)

    def Range(self, start, end):
        return _FakeRange(tuple(tuple(r) for r in self._grid))


def test_reads_columns_by_header_name_in_standard_order():
    grid = [
        ["Scrip Name", "Current", "Open"],
        ["RELIANCE", 2500, 2490],
    ]
    headers, rows = _read_sheet_cells(_FakeSheet(grid), ["Scrip Name", "Current", "Open"], 0)
    assert headers == ["Scrip Name", "Current", "Open"]
    assert rows == [["RELIANCE", 2500, 2490]]


def test_reads_columns_correctly_when_sheet_columns_are_rearranged():
    """The actual live-feed bug: same headers, different order — must not
    silently swap Current and Open's values."""
    grid = [
        ["Open", "Scrip Name", "Current"],
        [2490, "RELIANCE", 2500],
    ]
    headers, rows = _read_sheet_cells(_FakeSheet(grid), ["Scrip Name", "Current", "Open"], 0)
    assert headers == ["Scrip Name", "Current", "Open"]
    assert rows == [["RELIANCE", 2500, 2490]]


def test_returns_none_when_an_expected_header_is_missing():
    grid = [["Scrip Name", "Current"], ["RELIANCE", 2500]]
    assert _read_sheet_cells(_FakeSheet(grid), ["Scrip Name", "Current", "Open"], 0) is None


def test_returns_none_when_sheet_is_empty():
    assert _read_sheet_cells(_FakeSheet([]), ["Scrip Name"], 0) is None
