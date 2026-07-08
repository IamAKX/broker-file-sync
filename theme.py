import os
from PySide6.QtWidgets import QApplication
import font_scale

_CHECK_ICON = os.path.join(os.path.dirname(__file__), "assets", "icons", "check.svg").replace("\\", "/")

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

    def apply(self):
        p = PALETTES[self._mode]

        self._app.setStyleSheet(f"""
            QWidget {{
                background-color: {p['background']};
                color: {p['text_primary']};
                font-size: {font_scale.MEDIUM}pt;
            }}
            QLabel {{
                background-color: transparent;
            }}
            QLineEdit, QPlainTextEdit, QTextEdit, QComboBox, QSpinBox {{
                background-color: {p['input_bg']};
                color: {p['text_primary']};
                border: 1px solid {p['border']};
                border-radius: 4px;
                padding: 6px 10px;
            }}
            QSpinBox::up-button, QSpinBox::down-button {{
                background: {p['button_bg']};
                border: 1px solid {p['border']};
                width: 16px;
            }}
            QSpinBox::up-button:hover, QSpinBox::down-button:hover {{
                background: {p['accent']};
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
                image: url({_CHECK_ICON});
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
