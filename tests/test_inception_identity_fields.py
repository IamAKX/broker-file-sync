"""Issue #53: Sector/Symbol selectable (and usable) in Inception conditional
formatting, like LMV's Sector/Scrip Name."""
from services import strategy_engine as se


def _cond(field, value):
    return [{"type": "col", "value": field}, {"type": "op", "value": "=="},
            {"type": "num", "value": f'"{value}"'}]


def test_text_condition_on_sector_and_symbol_evaluates():
    row = {"Sector": "CG", "Symbol": "ABB", "CLOSE": 10}
    all_data = [row]
    assert se.evaluate(_cond("Sector", "CG"), row, all_data, symbol_col="Symbol") is True
    assert se.evaluate(_cond("Symbol", "ABB"), row, all_data, symbol_col="Symbol") is True
    assert se.evaluate(_cond("Sector", "POWER"), row, all_data, symbol_col="Symbol") is False


def test_builder_field_list_offers_sector_and_symbol_first(monkeypatch):
    import sys
    from PySide6.QtWidgets import QApplication
    app = QApplication.instance() or QApplication(sys.argv)
    from screens import inception_strategy_builder as isb
    assert isb.INCEPTION_IDENTITY_FIELDS == ["Sector", "Symbol"]
    # _reload_all's field assembly, exercised without constructing the screen
    class _Stub:
        _fields = []
    monkeypatch.setattr(isb.store, "load_all", lambda: [])
    stub = _Stub()
    stub._refresh_list = lambda: None
    isb.InceptionStrategyBuilderScreen._reload_all(stub)
    assert stub._fields[:2] == ["Sector", "Symbol"]
    assert stub._fields.count("Sector") == 1 and stub._fields.count("Symbol") == 1
