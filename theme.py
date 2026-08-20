import os
import re
import tempfile
from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QComboBox, QFrame
import font_scale

_CHECK_ICON = os.path.join(os.path.dirname(__file__), "assets", "icons", "check.svg").replace("\\", "/")
_ICONS_DIR = os.path.join(os.path.dirname(__file__), "assets", "icons")


def _recolored_icon_path(filename: str, color: str) -> str:
    """Recolor an assets/icons/*.svg (all committed as fill="#000000"
    placeholders — see screens/strategy_builder.py's _svg_icon docstring for
    the same convention) to *color* and cache it as a real file in the OS
    temp dir, returning its path for use in QSS `image: url(...)` — QSS's
    url() needs an actual file, unlike QIcon's in-memory QPixmap route
    _svg_icon uses for QPushButton icons elsewhere in the app.

    A raw (still-black) SVG referenced directly, like _CHECK_ICON above, is
    only safe when whatever sits behind it is guaranteed light (an accent-
    colored checked checkbox square) — a subcontrol like QDateEdit's
    drop-down arrow sits on the theme's own dark input background in dark
    mode, so it needs the same per-theme recoloring _svg_icon does.
    """
    cache_path = os.path.join(
        tempfile.gettempdir(), f"brokersync_icon_{filename.rsplit('.', 1)[0]}_{color.lstrip('#')}.svg",
    )
    # Always (re)written rather than reused-if-present: this is called at
    # most a few times per app session (startup, theme toggle), so the
    # write cost is negligible, and it avoids a stale/broken cached file
    # from an earlier buggy version of this function ever silently
    # surviving in the OS temp dir across app restarts.
    try:
        with open(os.path.join(_ICONS_DIR, filename), "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return ""
    # Unlike _svg_icon's tag-restricted version, this matches fill/stroke
    # wherever they appear — down.svg (and possibly others) declares
    # fill="#000000" on the root <svg> element itself rather than on the
    # inner <path>, which a tag-restricted pattern silently never touches
    # (the file comes back byte-for-byte unchanged, still black).
    svg = re.sub(r'\bfill="(?!none)[^"]*"', f'fill="{color}"', svg)
    svg = re.sub(r'\bstroke="(?!none)[^"]*"', f'stroke="{color}"', svg)
    with open(cache_path, "w", encoding="utf-8") as f:
        f.write(svg)
    return cache_path.replace("\\", "/")


def _patch_combo_popup_frame():
    """QComboBox's popup is backed by a QListView that draws its own native
    frame by default, on top of this module's QSS border on the same
    QAbstractItemView selector — the combination reads as a doubled/"extra"
    border around every dropdown (most visible before the QPalette below is
    applied, when the native frame falls back to plain white and the seam
    against the QSS-styled list looks like a second border). Clearing the
    view's own frame here, once, for every QComboBox in the app — present
    and future — leaves exactly the one QSS-declared border.

    Patched at import time (not per-instance) so no call site needs to
    remember to opt in; guarded so re-importing this module doesn't wrap
    showPopup twice.
    """
    if getattr(QComboBox.showPopup, "_no_frame_patched", False):
        return
    original_show_popup = QComboBox.showPopup

    def _show_popup_no_frame(self):
        self.view().setFrameShape(QFrame.Shape.NoFrame)
        original_show_popup(self)

    _show_popup_no_frame._no_frame_patched = True
    QComboBox.showPopup = _show_popup_no_frame


_patch_combo_popup_frame()

DARK = {
    "background":    "#0d1117",
    "sidebar_bg":    "#161b22",
    "card_bg":       "#1c2128",
    "border":        "#30363d",
    "accent":        "#39d353",
    "accent_hover":  "#2ea043",
    "text_primary":  "#e6edf3",
    "text_secondary":"#8b949e",
    "status_red":    "#f85149",
    "status_blue":   "#58a6ff",
    "status_orange": "#e3b341",
    "status_amber":  "#d29922",
    "status_purple": "#a371f7",
    "status_pink":   "#f778ba",
    "info_banner_bg":"#2d1f00",
    "info_banner_border":"#d97706",
    "info_banner_text":"#fcd34d",
    "watcher_banner_bg":"#0d2116",
    "watcher_banner_border":"#39d353",
    "divider":        "#2a2f36",
    "input_bg":      "#0d1117",
    "button_bg":     "#21262d",
    "destructive":   "#da3633",
}

LIGHT = {
    "background":    "#ffffff",
    "sidebar_bg":    "#f6f8fa",
    "card_bg":       "#f6f8fa",
    "border":        "#d0d7de",
    "accent":        "#1a7f37",
    "accent_hover":  "#116329",
    "text_primary":  "#1f2328",
    "text_secondary":"#656d76",
    "status_red":    "#cf222e",
    "status_blue":   "#0969da",
    "status_orange": "#9a6700",
    "status_amber":  "#bf8700",
    "status_purple": "#8250df",
    "status_pink":   "#bf3989",
    "info_banner_bg":"#fffbeb",
    "info_banner_border":"#d97706",
    "info_banner_text":"#78350f",
    "watcher_banner_bg":"#f0fdf4",
    "watcher_banner_border":"#1a7f37",
    "divider":        "#e5e7eb",
    "input_bg":      "#ffffff",
    "button_bg":     "#eaecef",
    "destructive":   "#cf222e",
}

PALETTES = {"dark": DARK, "light": LIGHT}


class ThemeManager:
    def __init__(self, app: QApplication):
        from services import config_store
        self._app = app
        self._mode = config_store.load_theme()
        # apply() is deferred — called explicitly from AppController.start()
        # so that setStyleSheet runs only after the event loop is ready

    @property
    def current_mode(self) -> str:
        return self._mode

    def get(self, token: str) -> str:
        return PALETTES[self._mode][token]

    def toggle(self):
        from services import config_store
        self._mode = "light" if self._mode == "dark" else "dark"
        config_store.save_theme(self._mode)
        self.apply()

    def sync_from_server(self) -> bool:
        """Pulls the logged-in user's theme from the server and re-applies
        it if it differs from what __init__ already showed from the local
        cache. Call once, right after a successful login (fresh or via a
        persisted token) — see app.py::AppController.show_main_window.
        Returns whether the mode actually changed."""
        from services import config_store
        server_mode = config_store.sync_theme_from_server()
        if server_mode is not None and server_mode != self._mode:
            self._mode = server_mode
            self.apply()
            return True
        return False

    def _build_palette(self, p: dict) -> QPalette:
        """Explicit QPalette to go alongside the QSS stylesheet below.

        Fusion-style popups that spawn their own top-level window — a
        QComboBox dropdown, a QMenu, a tooltip — paint their surrounding
        frame from the application's ambient QPalette before any QSS on the
        inner view is applied. Without this, only the *stylesheet's* colors
        show (e.g. QComboBox QAbstractItemView's background) while the
        popup's own frame stays whatever QPalette.Base/Window defaulted to —
        white, on macOS — regardless of dark/light mode. Setting the palette
        here keeps every native-ish popup in sync with the theme instead of
        just the widgets QSS selectors happen to reach directly.
        """
        palette = QPalette()
        window = QColor(p["background"])
        base = QColor(p["input_bg"])
        alt_base = QColor(p["card_bg"])
        text = QColor(p["text_primary"])
        button = QColor(p["button_bg"])
        highlight = QColor(p["accent"])
        highlighted_text = QColor(p["background"])
        disabled_text = QColor(p["text_secondary"])

        palette.setColor(QPalette.ColorRole.Window, window)
        palette.setColor(QPalette.ColorRole.WindowText, text)
        palette.setColor(QPalette.ColorRole.Base, base)
        palette.setColor(QPalette.ColorRole.AlternateBase, alt_base)
        palette.setColor(QPalette.ColorRole.ToolTipBase, alt_base)
        palette.setColor(QPalette.ColorRole.ToolTipText, text)
        palette.setColor(QPalette.ColorRole.Text, text)
        palette.setColor(QPalette.ColorRole.Button, button)
        palette.setColor(QPalette.ColorRole.ButtonText, text)
        palette.setColor(QPalette.ColorRole.Highlight, highlight)
        palette.setColor(QPalette.ColorRole.HighlightedText, highlighted_text)
        palette.setColor(QPalette.ColorRole.Link, highlight)

        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, disabled_text)
        palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, disabled_text)

        return palette

    def apply(self):
        p = PALETTES[self._mode]
        date_arrow_icon = _recolored_icon_path("down.svg", p["text_primary"])

        self._app.setPalette(self._build_palette(p))
        self._app.setStyleSheet(f"""
            QWidget {{
                background-color: {p['background']};
                color: {p['text_primary']};
                font-size: {font_scale.MEDIUM}pt;
            }}
            QLabel {{
                background-color: transparent;
            }}
            QLabel#statValue {{
                font-size: {font_scale.DISPLAY_LG}pt;
                font-weight: bold;
            }}
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox,
            QDateTimeEdit, QDateEdit, QTimeEdit {{
                background-color: {p['input_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
            QDateTimeEdit::drop-down, QDateEdit::drop-down {{
                border: none;
                width: 20px;
            }}
            QDateTimeEdit::down-arrow, QDateEdit::down-arrow {{
                image: url("{date_arrow_icon}");
                width: 10px;
                height: 10px;
            }}
            QDateTimeEdit QCalendarWidget, QDateEdit QCalendarWidget {{
                background-color: {p['card_bg']};
                color: {p['text_primary']};
            }}
            QCalendarWidget QAbstractItemView {{
                background-color: {p['card_bg']};
                color: {p['text_primary']};
                selection-background-color: {p['accent']};
                selection-color: {p['background']};
            }}
            QCalendarWidget QToolButton {{
                background-color: {p['button_bg']};
                color: {p['text_primary']};
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {p['button_bg']};
                border: 1px solid {p['border']};
                width: 16px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {p['accent']};
            }}
            QComboBox::drop-down {{
                border: none;
                width: 20px;
            }}
            QComboBox QAbstractItemView {{
                background-color: {p['card_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                outline: none;
                selection-background-color: {p['accent']};
                selection-color: {p['background']};
            }}
            QLineEdit:focus, QPlainTextEdit:focus, QSpinBox:focus {{
                border: 1px solid {p['accent']};
            }}
            QPushButton {{
                background-color: {p['button_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 4px;
                padding: 6px 14px;
            }}
            QPushButton:hover {{
                border-color: {p['accent']};
                color: {p['accent']};
            }}
            QTabWidget::pane {{
                border: 1px solid {p['border']};
                background: {p['card_bg']};
            }}
            QTabBar::tab {{
                background: {p['button_bg']};
                color: {p['text_secondary']};
                padding: 6px 16px;
                border: 1px solid {p['border']};
            }}
            QTabBar::tab:selected {{
                background: {p['card_bg']};
                color: {p['accent']};
                border-bottom: 2px solid {p['accent']};
            }}
            QScrollBar:vertical {{
                background: {p['sidebar_bg']};
                width: 8px;
            }}
            QScrollBar::handle:vertical {{
                background: {p['border']};
                border-radius: 4px;
            }}
            QTableWidget {{
                background: {p['card_bg']};
                color: {p['text_primary']};
                gridline-color: {p['border']};
                border: 1px solid {p['border']};
            }}
            QHeaderView::section {{
                background: {p['button_bg']};
                color: {p['text_secondary']};
                border: 1px solid {p['border']};
                padding: 4px 8px;
                font-size: {font_scale.SMALL}pt;
            }}
            QMenuBar {{
                background-color: {p['sidebar_bg']};
                color: {p['text_primary']};
                font-size: {font_scale.MEDIUM}pt;
            }}
            QMenuBar::item:selected {{
                background: {p['button_bg']};
            }}
            QMenu {{
                background-color: {p['card_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
            }}
            QMenu::item:selected {{
                background: {p['accent']};
                color: {p['background']};
            }}
            QProgressBar {{
                border: 1px solid {p['border']};
                border-radius: 4px;
                background: {p['card_bg']};
                text-align: center;
                color: {p['text_primary']};
            }}
            QProgressBar::chunk {{
                background: {p['accent']};
                border-radius: 3px;
            }}
            QCheckBox {{
                color: {p['text_primary']};
                spacing: 8px;
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 15px;
                height: 15px;
                border: 1px solid {p['text_secondary']};
                border-radius: 3px;
                background: transparent;
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid {p['accent']};
            }}
            QCheckBox::indicator:checked {{
                background: {p['accent']};
                border: 1px solid {p['accent']};
                image: url("{_CHECK_ICON}");
            }}
            QDialog {{
                background: {p['background']};
            }}
            QMessageBox {{
                background: {p['background']};
                color: {p['text_primary']};
            }}
            QFrame#statCard, QFrame#brokerPanel, QFrame#activityPanel,
            QFrame#infoCard, QFrame#prefCard, QFrame#notifItem,
            QFrame#dropArea {{
                background: {p['card_bg']};
                border: 1px solid {p['border']};
                border-radius: 8px;
            }}
            QFrame#watcherBanner {{
                background: {p['watcher_banner_bg']};
                border: 1px solid {p['watcher_banner_border']};
                border-radius: 8px;
            }}
            QFrame#infoBanner {{
                background: {p['info_banner_bg']};
                border-left: 4px solid {p['info_banner_border']};
                border-top: 1px solid {p['info_banner_border']};
                border-right: 1px solid {p['info_banner_border']};
                border-bottom: 1px solid {p['info_banner_border']};
                border-radius: 4px;
            }}
            QLabel#bannerText {{
                color: {p['info_banner_text']};
            }}
        """)
