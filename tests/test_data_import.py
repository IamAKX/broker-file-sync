import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.data_import import DataImportScreen
    return DataImportScreen(AppController(qapp))


def test_data_import_creates(screen):
    assert screen is not None


def test_has_watcher_button(screen):
    from PySide6.QtWidgets import QPushButton
    buttons = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Watcher" in t for t in buttons)


def test_has_five_broker_cards(screen):
    assert len(screen._cards) == 5
    # Each card exposes a Browse button and a remove button.
    from PySide6.QtWidgets import QPushButton
    for card in screen._cards.values():
        labels = [b.text() for b in card.findChildren(QPushButton)]
        assert "Browse" in labels


def test_watcher_button_initially_disabled(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b for b in screen.findChildren(QPushButton) if "Watcher" in b.text()]
    assert btns and not btns[0].isEnabled()


# ── ReliableSoftware date check ──────────────────────────────────────────────

def test_reliable_software_rejects_mismatched_date(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from datetime import date, timedelta
    import services.file_reader as file_reader

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    wrong_date = date.today() - timedelta(days=30)
    monkeypatch.setattr(file_reader, "read_reliable_software_date", lambda path: wrong_date)

    card = screen._cards["ReliableSoftware"]
    fake_path = str(tmp_path / "reliable.xls")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file is None


def test_reliable_software_rejects_unreadable_date(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    import services.file_reader as file_reader

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(file_reader, "read_reliable_software_date", lambda path: None)

    card = screen._cards["ReliableSoftware"]
    fake_path = str(tmp_path / "reliable.xls")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file is None


def test_reliable_software_accepts_matching_day_month_any_year(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from datetime import date
    import services.file_reader as file_reader

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    today = date.today()
    # Same day/month, different year — year is deliberately not compared yet.
    same_day_month_last_year = date(today.year - 1, today.month, today.day)
    monkeypatch.setattr(file_reader, "read_reliable_software_date", lambda path: same_day_month_last_year)

    card = screen._cards["ReliableSoftware"]
    fake_path = str(tmp_path / "reliable.xls")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file == fake_path


def test_other_broker_cards_skip_reliable_date_check(screen, monkeypatch, tmp_path):
    """The date check is ReliableSoftware-specific — Sharekhan et al. must
    not call read_reliable_software_date at all."""
    import services.file_reader as file_reader

    def _boom(path):
        raise AssertionError("read_reliable_software_date should not be called")
    monkeypatch.setattr(file_reader, "read_reliable_software_date", _boom)

    card = screen._cards["Sharekhan"]
    fake_path = str(tmp_path / "sharekhan.xls")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file == fake_path


# ── MarketProfile date check ─────────────────────────────────────────────────

def test_market_profile_rejects_mismatched_date(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from datetime import date, timedelta
    import services.file_reader as file_reader

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    wrong_date = date.today() - timedelta(days=30)
    monkeypatch.setattr(file_reader, "read_market_profile_date", lambda path: wrong_date)

    card = screen._cards["MarketProfile"]
    fake_path = str(tmp_path / "marketprofile.csv")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file is None


def test_market_profile_rejects_unreadable_date(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    import services.file_reader as file_reader

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    monkeypatch.setattr(file_reader, "read_market_profile_date", lambda path: None)

    card = screen._cards["MarketProfile"]
    fake_path = str(tmp_path / "marketprofile.csv")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file is None


def test_market_profile_accepts_matching_day_month_any_year(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    from datetime import date
    import services.file_reader as file_reader

    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))
    today = date.today()
    same_day_month_last_year = date(today.year - 1, today.month, today.day)
    monkeypatch.setattr(file_reader, "read_market_profile_date", lambda path: same_day_month_last_year)

    card = screen._cards["MarketProfile"]
    fake_path = str(tmp_path / "marketprofile.csv")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file == fake_path


def test_other_broker_cards_skip_market_profile_date_check(screen, monkeypatch, tmp_path):
    """The date check is MarketProfile-specific — Sharekhan et al. must not
    call read_market_profile_date at all."""
    import services.file_reader as file_reader

    def _boom(path):
        raise AssertionError("read_market_profile_date should not be called")
    monkeypatch.setattr(file_reader, "read_market_profile_date", _boom)

    card = screen._cards["Sharekhan"]
    fake_path = str(tmp_path / "sharekhan.xls")
    open(fake_path, "wb").close()
    card._on_file_dropped(fake_path)

    assert card._selected_file == fake_path


# ── NiftyInvest: multiple files, header-name column detection ──────────────────

def _nifty_csv(tmp_path, name, header_row, rows):
    path = tmp_path / name
    lines = [",".join(header_row)] + [",".join(str(c) for c in r) for r in rows]
    path.write_text("\n".join(lines) + "\n")
    return str(path)


def test_nifty_invest_card_is_multi_file(screen):
    assert screen._cards["NiftyInvest"]._show_multi_file is True


def test_other_cards_are_not_multi_file(screen):
    for broker in ["Sharekhan", "ReliableSoftware", "ExternalImport", "MarketProfile"]:
        assert screen._cards[broker]._show_multi_file is False


def test_browse_getopenfilenames_used_for_nifty_invest(screen, monkeypatch, tmp_path):
    """Multi-select dialog, not the single-file one, for NiftyInvest only."""
    from PySide6.QtWidgets import QFileDialog

    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    f2 = _nifty_csv(tmp_path, "b.csv", ["Symbol", "Max Pain"], [["TCS", 3500]])
    monkeypatch.setattr(QFileDialog, "getOpenFileNames", staticmethod(lambda *a, **k: ([f1, f2], "")))

    def _boom(*a, **k):
        raise AssertionError("getOpenFileName (singular) should not be used for NiftyInvest")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(_boom))

    screen._cards["NiftyInvest"]._browse()
    assert screen._cards["NiftyInvest"]._selected_files == [f1, f2]


def test_on_files_dropped_populates_selected_files(screen, tmp_path):
    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    f2 = _nifty_csv(tmp_path, "b.csv", ["Max Pain", "Symbol"], [[3500, "TCS"]])
    card = screen._cards["NiftyInvest"]
    card._on_files_dropped([f1, f2])
    assert card._selected_files == [f1, f2]
    assert "2 files imported" not in card._file_lbl.text()  # import still animating, not done yet


def test_browse_replaces_previous_selection(screen, tmp_path):
    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    f2 = _nifty_csv(tmp_path, "b.csv", ["Symbol", "Max Pain"], [["TCS", 3500]])
    card = screen._cards["NiftyInvest"]
    card._on_files_dropped([f1], replace=True)
    assert card._selected_files == [f1]
    card._on_files_dropped([f2], replace=True)
    assert card._selected_files == [f2]


def test_drop_appends_and_dedupes_existing_selection(screen, tmp_path):
    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    f2 = _nifty_csv(tmp_path, "b.csv", ["Symbol", "Max Pain"], [["TCS", 3500]])
    card = screen._cards["NiftyInvest"]
    card._on_files_dropped([f1], replace=True)
    card._on_files_dropped([f1, f2], replace=False)
    assert card._selected_files == [f1, f2]   # f1 not duplicated


def test_invalid_nifty_file_rejected_valid_files_kept(screen, monkeypatch, tmp_path):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "critical", staticmethod(lambda *a, **k: None))

    good = _nifty_csv(tmp_path, "good.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    bad = _nifty_csv(tmp_path, "bad.csv", ["Symbol", "SomethingElse"], [["TCS", 3500]])
    card = screen._cards["NiftyInvest"]
    card._on_files_dropped([good, bad], replace=True)
    assert card._selected_files == [good]


def test_nifty_invest_import_completes_with_multi_file_label(screen, tmp_path):
    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    f2 = _nifty_csv(tmp_path, "b.csv", ["Symbol", "Max Pain"], [["TCS", 3500]])
    card = screen._cards["NiftyInvest"]
    card._on_files_dropped([f1, f2], replace=True)
    card._tick()
    while card._timer.isActive():
        card._tick()
    assert "2 files imported" in card._file_lbl.text()


def test_nifty_invest_reset_clears_selected_files(screen, tmp_path):
    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    card = screen._cards["NiftyInvest"]
    card._on_files_dropped([f1], replace=True)
    card._reset()
    assert card._selected_files == []


def test_run_watcher_passes_nifty_file_list(screen, monkeypatch, tmp_path):
    f1 = _nifty_csv(tmp_path, "a.csv", ["Symbol", "Max Pain"], [["INFY", 1800]])
    f2 = _nifty_csv(tmp_path, "b.csv", ["Symbol", "Max Pain"], [["TCS", 3500]])
    screen._cards["NiftyInvest"]._selected_files = [f1, f2]

    captured = {}

    class _FakeSignal:
        def connect(self, *a, **k):
            pass

    class _FakeLiveViewer:
        def __init__(self, sharekhan_path, reliable_path, nifty_paths, *a, **k):
            captured["nifty_paths"] = nifty_paths
            self._headers = []
            self._data = []
            self.data_updated = _FakeSignal()
        def show(self):
            pass

    # _run_watcher does a local `from screens.live_viewer import
    # LiveViewerWindow` — patch it at its defining module, not on data_import.
    monkeypatch.setattr("screens.live_viewer.LiveViewerWindow", _FakeLiveViewer)
    screen._run_watcher()

    assert captured["nifty_paths"] == [f1, f2]
