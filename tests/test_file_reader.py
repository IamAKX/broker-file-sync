"""Tests for services.file_reader — historic-upload sheet reading."""
import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

from services.file_reader import (
    _drop_blank_scripname_rows,
    read_historic_sheet,
    read_market_profile_date,
    read_reliable_software_date,
)


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


def test_read_reliable_software_date_reads_first_data_row_column_a(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DataTime", "ScripName", "DiffPcnt"])
    ws.append([datetime.datetime(2026, 6, 18), "INFY.rolling.12D", 1.5])
    ws.append([datetime.datetime(2026, 6, 18), "TCS.rolling.12D", 2.0])
    path = str(tmp_path / "reliable.xlsx")
    wb.save(path)

    assert read_reliable_software_date(path) == datetime.date(2026, 6, 18)


def test_read_reliable_software_date_returns_none_when_column_a_blank(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DataTime", "ScripName", "DiffPcnt"])
    ws.append([None, "INFY.rolling.12D", 1.5])
    path = str(tmp_path / "reliable.xlsx")
    wb.save(path)

    assert read_reliable_software_date(path) is None


def test_read_reliable_software_date_returns_none_when_no_data_rows(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["DataTime", "ScripName", "DiffPcnt"])
    path = str(tmp_path / "reliable.xlsx")
    wb.save(path)

    assert read_reliable_software_date(path) is None


def test_read_market_profile_date_reads_iso_string_from_csv(tmp_path):
    path = tmp_path / "marketprofile.csv"
    path.write_text(
        "Date,stock,Open,High,Low,VAH,POC,VAL\n"
        "2026-06-29,360ONE,1079.8,1097.0,1070.4,1094.0,1088.0,1086.0\n"
        "2026-06-29,ABB,7000.0,7268.0,6887.5,7117.5,7007.5,6967.5\n"
    )
    assert read_market_profile_date(str(path)) == datetime.date(2026, 6, 29)


def test_read_market_profile_date_returns_none_when_blank_csv(tmp_path):
    path = tmp_path / "marketprofile.csv"
    path.write_text("Date,stock,Open\n,360ONE,1079.8\n")
    assert read_market_profile_date(str(path)) is None


def test_read_market_profile_date_returns_none_when_no_data_rows_csv(tmp_path):
    path = tmp_path / "marketprofile.csv"
    path.write_text("Date,stock,Open\n")
    assert read_market_profile_date(str(path)) is None


def test_read_market_profile_date_reads_typed_date_from_xlsx(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Date", "stock", "Open"])
    ws.append([datetime.datetime(2026, 6, 29), "360ONE", 1079.8])
    path = str(tmp_path / "marketprofile.xlsx")
    wb.save(path)

    assert read_market_profile_date(path) == datetime.date(2026, 6, 29)


def test_read_market_profile_date_reads_iso_string_from_xlsx(tmp_path):
    import openpyxl
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Date", "stock", "Open"])
    ws.append(["2026-06-29", "360ONE", 1079.8])
    path = str(tmp_path / "marketprofile.xlsx")
    wb.save(path)

    assert read_market_profile_date(path) == datetime.date(2026, 6, 29)
