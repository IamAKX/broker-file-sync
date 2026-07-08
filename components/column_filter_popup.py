import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QLineEdit, QScrollArea, QCheckBox
)
from PySide6.QtCore import Qt, Signal


class ColumnFilterPopup(QWidget):
    """Floating popup for toggling column visibility."""

    columns_changed = Signal(set)   # emits set of visible column indices

    def __init__(self, headers: list, visible: set, theme=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._headers  = headers
        self._visible  = set(visible)
        self._theme    = theme
        self._checks: list[QCheckBox] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg     = t.get("card_bg")        if t else "#1c2128"
        win_bg = t.get("background")    if t else "#0d1117"
        border = t.get("border")        if t else "#30363d"
        txt    = t.get("text_primary")  if t else "#e6edf3"
        txt_s  = t.get("text_secondary")if t else "#8b949e"
        accent = t.get("accent")        if t else "#39d353"
        inp_bg = t.get("input_bg")      if t else "#0d1117"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(280)
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border};"
            "border-radius: 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        hdr_row = QHBoxLayout()
        title = QLabel("Columns")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color: {txt}; border: none;")

        self._sel_lbl = QLabel()
        self._sel_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._sel_lbl.setStyleSheet(f"color: {txt_s}; border: none;")

        hdr_row.addWidget(title)
        hdr_row.addStretch()
        hdr_row.addWidget(self._sel_lbl)
        card_layout.addLayout(hdr_row)

        self._search = QLineEdit()
        self._search.setPlaceholderText("Search columns…")
        self._search.setFixedHeight(34)
        self._search.setFont(font_scale.font(font_scale.SMALL, False))
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {inp_bg}; color: {txt};"
            f"border: 1px solid {border}; border-radius: 6px; padding: 0 10px; }}"
        )
        self._search.textChanged.connect(self._filter)
        card_layout.addWidget(self._search)

        action_row = QHBoxLayout()
        for label, slot in [("Select All", self._select_all), ("Clear All", self._clear_all)]:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setFont(font_scale.font(font_scale.SMALL, False))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {accent};"
                f"border: 1px solid {accent}22; border-radius: 4px; padding: 0 10px; }}"
                f"QPushButton:hover {{ background: {accent}18; }}"
            )
            btn.clicked.connect(slot)
            action_row.addWidget(btn)
        action_row.addStretch()
        card_layout.addLayout(action_row)

        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {border}; border: none;")
        card_layout.addWidget(div)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(min(len(self._headers) * 36 + 8, 320))
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.verticalScrollBar().setStyleSheet(
            f"QScrollBar:vertical {{ width: 4px; background: transparent; }}"
            f"QScrollBar::handle:vertical {{ background: {border}; border-radius: 2px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 4, 0, 4)
        list_layout.setSpacing(2)

        for i, header in enumerate(self._headers):
            cb = QCheckBox(header)
            cb.setChecked(i in self._visible)
            cb.setFont(font_scale.font(font_scale.SMALL, False))
            cb.setFixedHeight(32)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {txt}; background: transparent; border: none;"
                "padding: 0 4px; border-radius: 4px; spacing: 8px; }"
                f"QCheckBox:hover {{ background: {accent}12; }}"
                f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;"
                f"border: 1.5px solid {border}; background: {inp_bg}; }}"
                f"QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent};"
                "image: none; }}"
            )
            cb.stateChanged.connect(self._on_state_changed)
            list_layout.addWidget(cb)
            self._checks.append(cb)

        list_layout.addStretch()
        scroll.setWidget(list_widget)
        card_layout.addWidget(scroll)

        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(34)
        apply_btn.setFont(font_scale.font(font_scale.SMALL, True))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: {win_bg};"
            "border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {accent}dd; }}"
        )
        apply_btn.clicked.connect(self._apply)
        card_layout.addWidget(apply_btn)

        outer.addWidget(card)
        self._update_sel_label()

    def _filter(self, text: str):
        q = text.strip().lower()
        for cb in self._checks:
            cb.setVisible(not q or q in cb.text().lower())

    def _on_state_changed(self):
        self._update_sel_label()

    def _select_all(self):
        for cb in self._checks:
            if cb.isVisible():
                cb.setChecked(True)

    def _clear_all(self):
        for cb in self._checks:
            if cb.isVisible():
                cb.setChecked(False)

    def _update_sel_label(self):
        checked = sum(1 for cb in self._checks if cb.isChecked())
        total   = len(self._checks)
        self._sel_lbl.setText(f"{checked}/{total}")

    def _apply(self):
        visible = {i for i, cb in enumerate(self._checks) if cb.isChecked()}
        self.columns_changed.emit(visible)
        self.close()
