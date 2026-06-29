import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    return config_store


def test_load_tab_returns_default_when_unsaved(store):
    default = [("A", "B"), ("C", "D")]
    rows = store.load_tab("sector_stock", default)
    assert rows == [["A", "B"], ["C", "D"]]


def test_save_then_load_roundtrip(store):
    store.save_tab("script_name", [("X", "1"), ("Y", "2")])
    assert store.load_tab("script_name", []) == [["X", "1"], ["Y", "2"]]


def test_save_tab_is_isolated_per_key(store):
    store.save_tab("sector_stock", [("S", "T")])
    store.save_tab("script_name", [("U", "V")])
    assert store.load_tab("sector_stock", []) == [["S", "T"]]
    assert store.load_tab("script_name", []) == [["U", "V"]]


def test_get_rename_map_only_includes_renamed(store):
    store.save_tab("main_column_name", [
        ("Current", "LTP"),       # renamed
        ("High", "High"),         # unchanged → excluded
        ("Low", ""),              # blank → excluded
        ("Open", "Open Price"),   # renamed
    ])
    assert store.get_rename_map() == {"Current": "LTP", "Open": "Open Price"}


def test_get_rename_map_empty_when_all_defaults(store):
    # Defaults map every column to itself, so no overrides.
    assert store.get_rename_map() == {}
