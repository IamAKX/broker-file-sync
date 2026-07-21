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
