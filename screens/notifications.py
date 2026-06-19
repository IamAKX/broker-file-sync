from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


NOTIFICATIONS = [
    ("info",    "Import Ready",    "Sharekhan files are queued for import.",                  "2026-06-19  11:30"),
    ("success", "Import Complete", "ReliableSoftware batch processed: 0 rows.",               "2026-06-19  10:15"),
    ("warning", "Config Warning",  "Script SCR003 mapping not found for NiftyInvest.",        "2026-06-18  17:42"),
    ("error",   "Import Failed",   "Failed to read header row in sharekhan_june.xlsx.",       "2026-06-18  09:05"),
    ("info",    "System Update",   "Broker File Sync v2.4.1 is available.",                   "2026-06-17  08:00"),
]

ICONS = {"info": ("ℹ", "status_blue"), "success": ("✔", "accent"),
         "warning": ("⚠", "status_orange"), "error": ("✖", "status_red")}


class NotificationsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._icon_labels = []
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Header row
        header_row = QHBoxLayout()
        title = QLabel("Notifications")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        mark_btn = QPushButton("Mark All as Read")
        mark_btn.setFixedHeight(34)
        mark_btn.setFont(QFont("Courier New", 11))
        mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mark_btn.clicked.connect(self._mark_all_read)
        header_row.addWidget(title)
        header_row.addStretch()
        header_row.addWidget(mark_btn)
        layout.addLayout(header_row)

        # Scroll area
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        container = QWidget()
        c_layout = QVBoxLayout(container)
        c_layout.setContentsMargins(0, 0, 0, 0)
        c_layout.setSpacing(10)

        for kind, title_text, body, ts in NOTIFICATIONS:
            item = QFrame()
            item.setObjectName("notifItem")
            item.setStyleSheet(
                f"QFrame#notifItem {{ background: {t.get('card_bg')};"
                f"border: 1px solid {t.get('border')}; border-radius: 6px; }}"
            )
            item_layout = QHBoxLayout(item)
            item_layout.setContentsMargins(16, 12, 16, 12)
            item_layout.setSpacing(14)

            icon_char, color_token = ICONS[kind]
            icon_lbl = QLabel(icon_char)
            icon_lbl.setFont(QFont("Courier New", 18))
            icon_lbl.setFixedWidth(24)
            icon_lbl.setAlignment(Qt.AlignmentFlag.AlignTop)
            icon_lbl.setStyleSheet(f"color: {t.get(color_token)};")
            self._icon_labels.append(icon_lbl)

            text_col = QVBoxLayout()
            text_col.setSpacing(2)
            t_title = QLabel(title_text)
            t_title.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
            t_body = QLabel(body)
            t_body.setFont(QFont("Courier New", 11))
            t_body.setStyleSheet(f"color: {t.get('text_secondary')};")
            text_col.addWidget(t_title)
            text_col.addWidget(t_body)

            ts_lbl = QLabel(ts)
            ts_lbl.setFont(QFont("Courier New", 10))
            ts_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            ts_lbl.setAlignment(Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)

            item_layout.addWidget(icon_lbl)
            item_layout.addLayout(text_col, 1)
            item_layout.addWidget(ts_lbl)
            c_layout.addWidget(item)

        c_layout.addStretch()
        scroll.setWidget(container)
        layout.addWidget(scroll)

    def _mark_all_read(self):
        t = self._controller.theme
        for lbl in self._icon_labels:
            lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
