"""ExcelLiveReader recovers from a stale COM handle on fresh handles, and
LMV bridges a brief COM failure with the last good live read (not the slow,
stale on-disk file)."""
from services import com_reader
from services.com_reader import ExcelLiveReader


class _Sheet:
    def __init__(self, fail):
        self.fail = fail


class _Wb:
    def __init__(self, sheet):
        self._sheet = sheet

    def Sheets(self, _i):
        return self._sheet


def _reader(monkeypatch, sheets):
    monkeypatch.setattr(com_reader, "_WIN32COM_AVAILABLE", True)
    r = ExcelLiveReader()
    queue = list(sheets)

    def get_workbook(name):
        return _Wb(queue.pop(0))
    monkeypatch.setattr(r, "_get_workbook", get_workbook)

    def read(sheet, cols, hdr):
        if sheet.fail:
            raise RuntimeError("Member not found")
        return (list(cols), [[1]]), ""
    monkeypatch.setattr(com_reader, "_read_sheet_cells_ex", read)
    return r


def test_retry_uses_a_fresh_sheet_handle(monkeypatch):
    r = _reader(monkeypatch, [_Sheet(True), _Sheet(False)])
    assert r.read_workbook_sheet("C:/x/Snap.xls", ["A"], 0) == (["A"], [[1]])


def test_two_failures_return_none_and_last_good_bridges(monkeypatch):
    r = _reader(monkeypatch, [_Sheet(False), _Sheet(True), _Sheet(True)])
    assert r.read_workbook_sheet("Snap.xls", ["A"], 0) is not None
    assert r.read_workbook_sheet("Snap.xls", ["A"], 0) is None
    assert "Member not found" in r.last_failure
    assert r.last_good("Snap.xls", 20) == (["A"], [[1]])
    assert r.last_good("Snap.xls", -1) is None
    assert r.last_good("Other.xls", 20) is None
