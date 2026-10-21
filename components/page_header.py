"""The title + subtitle block at the top of each main screen, with the
Fuku Lens header logo pinned to its top-right corner (#91)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QHBoxLayout, QVBoxLayout

import branding


def page_header(title, subtitle=None, trailing=None) -> QHBoxLayout:
    """*title*/*subtitle* are already-styled QLabels. *trailing* (optional)
    is a widget placed between the text and the logo (e.g. a Save button)."""
    row = QHBoxLayout()
    row.setSpacing(16)
    col = QVBoxLayout()
    col.setSpacing(4)
    col.addWidget(title)
    if subtitle is not None:
        col.addWidget(subtitle)
    row.addLayout(col, 1)
    if trailing is not None:
        row.addWidget(trailing, alignment=Qt.AlignmentFlag.AlignVCenter)
    logo = branding.make_header_logo()
    if logo is not None:
        row.addWidget(logo, alignment=Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
    return row
