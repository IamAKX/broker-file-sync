import sys
import pytest
from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication(sys.argv)


@pytest.fixture(autouse=True)
def isolated_store(tmp_path, monkeypatch):
    from services import config_store
    monkeypatch.setattr(config_store, "_STORE_FILE", str(tmp_path / "c.json"))


@pytest.fixture
def screen(qapp):
    from app import AppController
    from screens.formula_builder import FormulaBuilderScreen
    return FormulaBuilderScreen(AppController(qapp))


def test_formula_builder_creates(screen):
    assert screen is not None


def test_prefeeds_all_56_formulas(screen):
    assert len(screen._formulas) == 56


def test_formulas_have_real_expressions_not_free_text(screen):
    from services import formula_tokens as ft
    for formula in screen._formulas:
        assert isinstance(formula["tokens"], list)
        assert len(formula["tokens"]) > 0
        # every token is one of the known kinds — not a plain description string
        for tok in formula["tokens"]:
            assert tok.get("type") in {"field", "num", "op", "paren", "func"}


def test_formula_cards_show_real_expression(screen):
    from PySide6.QtWidgets import QLabel
    from screens.formula_builder import FormulaCard
    from services import formula_tokens as ft
    cmh = next(f for f in screen._formulas if f["code"] == "CMH")
    card = FormulaCard(cmh, screen._theme)
    labels = [w.text() for w in card.findChildren(QLabel)]
    assert "MAX_OF([HIGH], CURRENT_MONTH)" in labels


def test_has_add_formula_button(screen):
    from PySide6.QtWidgets import QPushButton
    btns = [b.text() for b in screen.findChildren(QPushButton)]
    assert any("Add Formula" in t for t in btns)


def test_add_formula_appends_and_opens_editor(screen):
    before = len(screen._formulas)
    screen._add_formula()
    assert len(screen._formulas) == before + 1
    assert screen._active_editor is not None


def test_delete_formula_removes_it(qapp, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    target_id = screen._formulas[0]["id"]
    screen._delete_formula(target_id)
    assert all(f["id"] != target_id for f in screen._formulas)


def test_editing_formula_persists_via_editor_panel(qapp, screen):
    from screens.formula_builder import FormulaEditorPanel
    formula = screen._formulas[0]
    editor = FormulaEditorPanel(formula, screen._theme)
    editor._name_edit.setText("Renamed")
    saved = {}
    editor.set_on_saved(lambda updated: saved.update(updated))
    editor._save()
    assert saved["name"] == "Renamed"


def test_open_formula_field_editor_updates_preview(qapp, screen, monkeypatch):
    from screens.formula_builder import FormulaEditorPanel
    from screens.formula_field_editor import FormulaFieldEditorDialog
    from PySide6.QtWidgets import QDialog

    formula = dict(screen._formulas[0])
    editor = FormulaEditorPanel(formula, screen._theme)

    new_tokens = [{"type": "field", "value": "CLOSE"}]

    class _FakeDialog:
        def __init__(self, *a, **k):
            pass
        def exec(self):
            return QDialog.DialogCode.Accepted
        def get_tokens(self):
            return new_tokens

    monkeypatch.setattr("screens.formula_builder.FormulaFieldEditorDialog", _FakeDialog)
    editor._open_formula_editor()
    assert editor._formula["tokens"] == new_tokens


def test_reset_to_defaults_restores_56(qapp, screen, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "exec", lambda self: QMessageBox.StandardButton.Yes)
    screen._add_formula()
    assert len(screen._formulas) == 57
    screen._reset_to_defaults()
    assert len(screen._formulas) == 56


def test_persists_across_screen_instances(qapp):
    from app import AppController
    from screens.formula_builder import FormulaBuilderScreen

    screen = FormulaBuilderScreen(AppController(qapp))
    formula = screen._formulas[0]
    formula["name"] = "Changed Name"
    screen._on_formula_saved(formula["id"], formula)

    reloaded = FormulaBuilderScreen(AppController(qapp))
    changed = next(f for f in reloaded._formulas if f["id"] == formula["id"])
    assert changed["name"] == "Changed Name"


def test_edit_menu_has_formula_builder(qapp):
    from theme import ThemeManager
    from components.topbar import TopBar
    from PySide6.QtWidgets import QPushButton
    tm = ThemeManager(qapp)
    topbar = TopBar(tm)
    found = False
    for btn in topbar.findChildren(QPushButton):
        menu = btn.menu()
        if menu is not None:
            for action in menu.actions():
                if action.text() == "Formula Builder":
                    found = True
    assert found
