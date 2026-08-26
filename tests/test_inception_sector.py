"""Tests for services.inception_sector — in particular the punctuation
normalization (_normalize) that lets a sector lookup match a symbol
regardless of whether it's spelled LMV's way (SECTOR_STOCK_DATA, e.g.
"BAJAJ-AUTO", "M&M", "NAM-INDIA") or the historical/Inception feed's
underscore-only way (e.g. "BAJAJ_AUTO", "M_M", "NAM_INDIA")."""
from collections import defaultdict

from config_defaults import SECTOR_STOCK_DATA
from services import inception_sector


def test_bajaj_auto_hyphen_vs_underscore():
    assert inception_sector.sector_for("BAJAJ-AUTO") == inception_sector.sector_for("BAJAJ_AUTO")
    assert inception_sector.sector_for("BAJAJ_AUTO") != "—"


def test_m_and_m_ampersand_vs_underscore():
    assert inception_sector.sector_for("M&M") == inception_sector.sector_for("M_M")
    assert inception_sector.sector_for("M_M") != "—"


def test_nam_india_hyphen_vs_underscore():
    assert inception_sector.sector_for("NAM-INDIA") == inception_sector.sector_for("NAM_INDIA")
    assert inception_sector.sector_for("NAM_INDIA") != "—"


def test_unmapped_symbol_falls_back_to_dash():
    assert inception_sector.sector_for("NOT_A_REAL_SYMBOL") == "—"


def test_case_and_whitespace_insensitive():
    assert inception_sector.sector_for("  bajaj_auto  ") == inception_sector.sector_for("BAJAJ-AUTO")


def test_normalized_keys_collision_free():
    """Guards the assumption _normalize's docstring relies on: stripping all
    punctuation from every SECTOR_STOCK_DATA symbol must not make two
    different stocks collide onto the same lookup key — if it ever does,
    _normalize needs to stop being a blanket strip and this test should fail
    loudly rather than let two unrelated stocks silently share a sector."""
    groups = defaultdict(list)
    for sector, stock in SECTOR_STOCK_DATA:
        groups[inception_sector._normalize(stock)].append(stock)
    collisions = {k: v for k, v in groups.items() if len(v) > 1}
    assert collisions == {}


def test_refresh_picks_up_config_editor_rename(monkeypatch):
    """A stock renamed in Config Editor's Sector Stock tab (e.g. LTIM -> LTM
    to match a vendor feed's own spelling) must take effect after refresh()
    — previously _MAP was built once from config_defaults.SECTOR_STOCK_DATA
    only, so a Config Editor save had no effect here even though it looked
    saved (services.config_store's "sector_stock" tab key was never read by
    this module at all)."""
    from services import config_store

    renamed = [
        (sector, "LTM" if stock == "LTIM" else stock)
        for sector, stock in SECTOR_STOCK_DATA
    ]
    monkeypatch.setattr(config_store, "load_tab", lambda key, default: renamed)
    original_map = dict(inception_sector._MAP)
    try:
        inception_sector.refresh()
        assert inception_sector.sector_for("LTM") == "TECHNOLOGY"
        assert inception_sector.sector_for("LTIM") == "—"
    finally:
        inception_sector._MAP = original_map
