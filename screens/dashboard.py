from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


class StatCard(QFrame):
    def __init__(self, label: str, value: str, icon: str, theme):
        super().__init__()
        t = theme
        self.setObjectName("statCard")
        self.setStyleSheet(
            f"QFrame#statCard {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(120)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFont(QFont("Courier New", 9))
        lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        icon_lbl = QLabel(icon)
        icon_lbl.setFont(QFont("Courier New", 16))
        icon_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        top_row.addWidget(lbl)
        top_row.addStretch()
        top_row.addWidget(icon_lbl)
        layout.addLayout(top_row)

        val_lbl = QLabel(value)
        val_lbl.setFont(QFont("Courier New", 36, QFont.Weight.Bold))
        val_lbl.setStyleSheet(f"color: {t.get('text_primary')};")
        layout.addWidget(val_lbl)


class DashboardScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        # Header
        title = QLabel("Dashboard")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("File import overview and processing activity")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Stat cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        stats = [
            ("TOTAL FILES IMPORTED",  "0",   "📄"),
            ("TOTAL ROWS PROCESSED",  "0",   "⊞"),
            ("IMPORT ERRORS",         "0",   "⚠"),
            ("BROKER SOURCES ACTIVE", "0/3", "⬡"),
        ]
        for label, value, icon in stats:
            cards_row.addWidget(StatCard(label, value, icon, t))
        layout.addLayout(cards_row)

        # Two-column section
        two_col = QHBoxLayout()
        two_col.setSpacing(16)

        # Broker Sources
        broker_panel = QFrame()
        broker_panel.setObjectName("brokerPanel")
        broker_panel.setStyleSheet(
            f"QFrame#brokerPanel {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        bp_layout = QVBoxLayout(broker_panel)
        bp_layout.setContentsMargins(16, 16, 16, 16)
        bp_layout.setSpacing(12)

        bp_title = QLabel("BROKER SOURCES")
        bp_title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        bp_layout.addWidget(bp_title)

        brokers = [
            ("Sharekhan",        t.get("status_red")),
            ("ReliableSoftware", t.get("status_blue")),
            ("NiftyInvest",      t.get("status_orange")),
        ]
        for name, color in brokers:
            row = QHBoxLayout()
            dot = QLabel("●")
            dot.setFixedWidth(16)
            dot.setStyleSheet(f"color: {color};")
            name_lbl = QLabel(name)
            name_lbl.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
            stats_lbl = QLabel("0 files – 0 imported")
            stats_lbl.setFont(QFont("Courier New", 11))
            stats_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            status_lbl = QLabel("Awaiting")
            status_lbl.setFont(QFont("Courier New", 11))
            status_lbl.setStyleSheet(f"color: {t.get('status_blue')};")
            row.addWidget(dot)
            row.addWidget(name_lbl)
            row.addWidget(stats_lbl)
            row.addStretch()
            row.addWidget(status_lbl)
            bp_layout.addLayout(row)

        bp_layout.addStretch()
        two_col.addWidget(broker_panel, 1)

        # Recent File Activity
        activity_panel = QFrame()
        activity_panel.setObjectName("activityPanel")
        activity_panel.setStyleSheet(
            f"QFrame#activityPanel {{ background: {t.get('card_bg')};"
            f"border: 1px solid {t.get('border')}; border-radius: 8px; }}"
        )
        ap_layout = QVBoxLayout(activity_panel)
        ap_layout.setContentsMargins(16, 16, 16, 16)
        ap_layout.setSpacing(12)

        ap_header = QHBoxLayout()
        ap_title = QLabel("RECENT FILE ACTIVITY")
        ap_title.setFont(QFont("Courier New", 11, QFont.Weight.Bold))
        total_lbl = QLabel("0 total")
        total_lbl.setFont(QFont("Courier New", 10))
        total_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        ap_header.addWidget(ap_title)
        ap_header.addStretch()
        ap_header.addWidget(total_lbl)
        ap_layout.addLayout(ap_header)

        ap_layout.addStretch()
        folder_icon = QLabel("📁")
        folder_icon.setFont(QFont("Courier New", 32))
        folder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        folder_icon.setStyleSheet(f"color: {t.get('text_secondary')};")
        ap_layout.addWidget(folder_icon)

        empty_msg = QLabel("No files imported yet.")
        empty_msg.setFont(QFont("Courier New", 14))
        empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(empty_msg)

        go_import_btn = QPushButton("Go to Data Import to upload broker files.")
        go_import_btn.setFlat(True)
        go_import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        go_import_btn.setFont(QFont("Courier New", 12))
        go_import_btn.setStyleSheet(
            f"color: {t.get('status_blue')}; background: transparent; border: none;"
        )
        go_import_btn.clicked.connect(
            lambda: self._controller.navigate("data_import")
        )
        ap_layout.addWidget(go_import_btn, alignment=Qt.AlignmentFlag.AlignCenter)
        ap_layout.addStretch()
        two_col.addWidget(activity_panel, 1)

        layout.addLayout(two_col)

        # Info banner
        banner = QFrame()
        banner.setObjectName("infoBanner")
        banner.setStyleSheet(
            f"QFrame#infoBanner {{ background: {t.get('info_banner_bg')};"
            f"border-left: 4px solid {t.get('accent')}; border-radius: 4px; }}"
        )
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        info_icon = QLabel("ℹ")
        info_icon.setFont(QFont("Courier New", 16))
        info_icon.setStyleSheet(f"color: {t.get('accent')};")
        info_icon.setFixedWidth(24)
        banner_text = QLabel(
            "Before importing, verify your column mappings in "
            "<b>Config Editor → Column Name Mapping</b> and script names in "
            "<b>Script Name Mapping</b>."
        )
        banner_text.setFont(QFont("Courier New", 11))
        banner_text.setWordWrap(True)
        banner_layout.addWidget(info_icon)
        banner_layout.addWidget(banner_text)
        layout.addWidget(banner)

        layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)
