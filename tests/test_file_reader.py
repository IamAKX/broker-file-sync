"""Tests for services.file_reader — historic-upload sheet reading."""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.file_reader import _drop_blank_scripname_rows, read_historic_sheet


def test_drop_blank_scripname_rows_removes_blank_rows():
    headers = ["ScripName", "Open"]
    data = [["INFY", 100], ["", 0], ["TCS", 200], [None, 0]]
    row_dates = [None, None, None, None]
    kept_data, kept_dates = _drop_blank_scripname_rows(headers, data, row_dates)
    assert kept_data == [["INFY", 100], ["TCS", 200]]
    assert len(kept_dates) == 2


def test_drop_blank_scripname_rows_noop_when_no_scripname_column():
    headers = ["Symbol", "Open"]
    data = [["INFY", 100], ["", 0]]
    row_dates = [None, None]
    kept_data, kept_dates = _drop_blank_scripname_rows(headers, data, row_dates)
    assert kept_data == data
    assert kept_dates == row_dates


def test_read_historic_sheet_xlsx_drops_trailing_blank_rows(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DataTime", "ScripName", "Open"])
    ws.append([46149, "INFY", 100])
    ws.append([46149, "TCS", 200])
    # Trailing rows with a blank ScripName but a stray leftover value —
    # mirrors the real-world Excel quirk this fix targets.
    ws.append(["", "", ""])
    ws.append(["", "", 5749])
    path = str(tmp_path / "historic.xlsx")
    wb.save(path)

    headers, rows, row_dates = read_historic_sheet(path)

    assert headers == ["DataTime", "ScripName", "Open"]
    assert len(rows) == 2
    assert len(row_dates) == 2
    assert [r[1] for r in rows] == ["INFY", "TCS"]
