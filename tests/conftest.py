import pytest


@pytest.fixture(autouse=True)
def _isolate_disk_stores(tmp_path, monkeypatch):
    """Redirect every JSON-backed store to a per-test tmp path.

    Without this, a test that doesn't remember to patch these itself can
    read/write the real config_data.json / strategies.json at the repo
    root — which has actually happened (a header-reorder code path wrote a
    stray "main_column_order" entry into a real, in-use config file during
    a full-suite run). Applying it globally means no individual test can
    forget it.
    """
    from services import config_store, strategy_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "config_data.json"))
    monkeypatch.setattr(strategy_store, "_STORE_FILE", str(tmp_path / "strategies.json"))
