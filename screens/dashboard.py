import font_scale
import re
import os
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QByteArray, QSize, QTimer
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^>]*></rect>', '', svg)
    # Replace fill on root <svg> element
    svg = re.sub(r'(<svg\b[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect|g)[^>]*)\bfill="(?!none)[^"]*"', rf'\1fill="{color}"', svg)
    svg = re.sub(r'(<(?:path|circle|ellipse|polygon|polyline|line|rect)[^>]*)\bstroke="(?!none)[^"]*"', rf'\1stroke="{color}"', svg)
    renderer = QSvgRenderer(QByteArray(svg.encode("utf-8")))
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    renderer.render(painter)
    painter.end()
    return QIcon(pixmap)


class StatCard(QFrame):
    def __init__(self, label: str, value: str, icon_file: str, theme):
        super().__init__()
        t = theme
        self.setObjectName("statCard")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.setFixedHeight(140)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(4)

        top_row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFont(font_scale.font(font_scale.SMALL, False))
        lbl.setStyleSheet(f"color: {t.get('text_secondary')};")

        icon_lbl = QLabel()
        icon_lbl.setFixedSize(22, 22)
        icon_lbl.setPixmap(_svg_icon(icon_file, t.get("text_secondary")).pixmap(QSize(22, 22)))

        top_row.addWidget(lbl)
        top_row.addStretch()
        top_row.addWidget(icon_lbl)
        layout.addLayout(top_row)

        self._val_lbl = QLabel(value)
        self._val_lbl.setStyleSheet("font-size: 36pt; font-weight: bold;")
        layout.addWidget(self._val_lbl)

    def set_value(self, value: str):
        self._val_lbl.setText(value)


BROKER_COLORS = [
    ("Sharekhan",        "status_red"),
    ("ReliableSoftware", "status_blue"),
    ("NiftyInvest",      "status_orange"),
    ("ExternalImport",   "status_purple"),
    ("MarketProfile",    "status_pink"),
]


class DashboardScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._broker_widgets: dict[str, tuple[QLabel, QLabel]] = {}
        self._stat_cards: list[StatCard] = []
        self._imported_count = 0
        self._broker_rows: dict[str, int] = {}
        self._dot_state = True   # for pulsing animation
        self._build()
        self._wire_watcher()

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
        title.setFont(font_scale.font(font_scale.DISPLAY_MD, True))
        layout.addWidget(title)

        subtitle = QLabel("File import overview and processing activity")
        subtitle.setFont(font_scale.font(font_scale.MEDIUM, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Stat cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        stats = [
            ("TOTAL FILES IMPORTED",  "0",   "file.svg"),
            ("TOTAL ROWS PROCESSED",  "0",   "database.svg"),
            ("IMPORT ERRORS",         "0",   "error.svg"),
            ("BROKER SOURCES ACTIVE", f"0/{len(BROKER_COLORS)}", "folder.svg"),
        ]
        for label, value, icon in stats:
            card = StatCard(label, value, icon, t)
            self._stat_cards.append(card)
            cards_row.addWidget(card)
        layout.addLayout(cards_row)

        # Two-column section
        two_col = QHBoxLayout()
        two_col.setSpacing(16)

        # Broker Sources
        broker_panel = QFrame()
        broker_panel.setObjectName("brokerPanel")
        bp_layout = QVBoxLayout(broker_panel)
        bp_layout.setContentsMargins(16, 16, 16, 16)
        bp_layout.setSpacing(12)

        bp_title = QLabel("BROKER SOURCES")
        bp_title.setFont(font_scale.font(font_scale.SMALL, True))
        bp_title.setStyleSheet(f"color: {t.get('text_secondary')};")
        bp_layout.addWidget(bp_title)

        sep0 = QWidget(); sep0.setFixedHeight(1)
        sep0.setStyleSheet(f"background-color: {t.get('divider')};")
        bp_layout.addWidget(sep0)

        for i, (name, color_token) in enumerate(BROKER_COLORS):
            color = t.get(color_token)
            row = QHBoxLayout()
            row.setContentsMargins(0, 8, 0, 8)
            row.setSpacing(10)

            dot = QLabel("●")
            dot.setFixedWidth(14)
            dot.setStyleSheet(f"color: {color}; font-size: 12pt;")

            info = QVBoxLayout()
            info.setSpacing(2)
            name_lbl = QLabel(name)
            name_lbl.setFont(font_scale.font(font_scale.MEDIUM, True))
            stats_lbl = QLabel("0 files – 0 imported")
            stats_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            stats_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
            info.addWidget(name_lbl)
            info.addWidget(stats_lbl)

            status_lbl = QLabel("Awaiting")
            status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
            status_lbl.setStyleSheet(
                f"color: {t.get('text_secondary')}; border: 1px solid {t.get('text_secondary')};"
                "border-radius: 4px; padding: 2px 8px;"
            )

            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addLayout(info, 1)
            row.addWidget(status_lbl, 0, Qt.AlignmentFlag.AlignVCenter)
            bp_layout.addLayout(row)

            self._broker_widgets[name] = (stats_lbl, status_lbl)

            if i < len(BROKER_COLORS) - 1:
                sep = QWidget(); sep.setFixedHeight(1)
                sep.setStyleSheet(f"background-color: {t.get('divider')};")
                bp_layout.addWidget(sep)
        two_col.addWidget(broker_panel, 1)

        # Recent File Activity
        activity_panel = QFrame()
        activity_panel.setObjectName("activityPanel")
        ap_layout = QVBoxLayout(activity_panel)
        ap_layout.setContentsMargins(16, 16, 16, 16)
        ap_layout.setSpacing(12)

        ap_header = QHBoxLayout()
        ap_title = QLabel("RECENT FILE ACTIVITY")
        ap_title.setFont(font_scale.font(font_scale.SMALL, True))
        self._total_lbl = QLabel("0 total")
        self._total_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._total_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        ap_header.addWidget(ap_title)
        ap_header.addStretch()
        ap_header.addWidget(self._total_lbl)
        ap_layout.addLayout(ap_header)

        ap_layout.addStretch()

        folder_icon = QLabel()
        folder_icon.setFixedSize(48, 48)
        folder_icon.setPixmap(_svg_icon("folder.svg", t.get("text_secondary")).pixmap(QSize(48, 48)))
        folder_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ap_layout.addWidget(folder_icon, alignment=Qt.AlignmentFlag.AlignCenter)

        empty_msg = QLabel("No files imported yet.\nGo to Data Import to upload broker files.")
        empty_msg.setFont(font_scale.font(font_scale.MEDIUM, False))
        empty_msg.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_msg.setStyleSheet(f"color: {t.get('text_secondary')};")
        empty_msg.setCursor(Qt.CursorShape.PointingHandCursor)
        empty_msg.mousePressEvent = lambda _: self._controller.navigate("data_import")
        ap_layout.addWidget(empty_msg, alignment=Qt.AlignmentFlag.AlignCenter)

        ap_layout.addStretch()
        two_col.addWidget(activity_panel, 1)

        layout.addLayout(two_col)

        # Watcher banner (hidden until watcher starts)
        self._watcher_banner = QFrame()
        self._watcher_banner.setObjectName("watcherBanner")
        wb_layout = QHBoxLayout(self._watcher_banner)
        wb_layout.setContentsMargins(16, 12, 16, 12)
        wb_layout.setSpacing(12)

        self._watcher_dot = QLabel("●")
        self._watcher_dot.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._watcher_dot.setFixedWidth(18)

        self._watcher_info = QLabel()
        self._watcher_info.setFont(font_scale.font(font_scale.SMALL, False))

        self._watcher_sync_lbl = QLabel()
        self._watcher_sync_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._watcher_sync_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")

        stop_btn = QPushButton("Stop Watcher")
        stop_btn.setFixedHeight(30)
        stop_btn.setFont(font_scale.font(font_scale.SMALL, False))
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {t.get('status_red')};"
            f"border: 1px solid {t.get('status_red')}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ background: {t.get('status_red')}; color: #ffffff; }}"
        )
        stop_btn.clicked.connect(self._controller.watcher.stop)

        wb_layout.addWidget(self._watcher_dot)
        wb_layout.addWidget(self._watcher_info, 1)
        wb_layout.addWidget(self._watcher_sync_lbl)
        wb_layout.addWidget(stop_btn)

        self._watcher_banner.setVisible(False)
        layout.addWidget(self._watcher_banner)

        # Pulsing dot timer
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(800)
        self._pulse_timer.timeout.connect(self._pulse_dot)

        # Info banner
        banner = QFrame()
        banner.setObjectName("infoBanner")
        banner_layout = QHBoxLayout(banner)
        banner_layout.setContentsMargins(16, 12, 16, 12)
        amber = "#d97706"
        info_icon = QLabel()
        info_icon.setFixedSize(20, 20)
        info_icon.setPixmap(_svg_icon("info.svg", amber).pixmap(QSize(20, 20)))
        banner_text = QLabel(
            "Before importing, verify your column mappings in "
            "<b>Config Editor → Column Name Mapping</b> and script names in "
            "<b>Script Name Mapping</b>."
        )
        banner_text.setFont(font_scale.font(font_scale.SMALL, False))
        banner_text.setObjectName("bannerText")
        banner_text.setWordWrap(True)
        banner_layout.addWidget(info_icon)
        banner_layout.addWidget(banner_text)
        layout.addWidget(banner)

        layout.addStretch()

        scroll.setWidget(container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

    def on_broker_imported(self, broker: str, rows: int):
        t = self._controller.theme
        self._imported_count += 1
        self._broker_rows[broker] = rows
        if broker in self._broker_widgets:
            stats_lbl, status_lbl = self._broker_widgets[broker]
            stats_lbl.setText(f"1 file – {rows:,} rows imported")
            status_lbl.setText("Imported")
            status_lbl.setStyleSheet(
                f"color: {t.get('accent')}; border: 1px solid {t.get('accent')};"
                "border-radius: 4px; padding: 2px 8px;"
            )
        self._refresh_stat_cards()

    def on_broker_reset(self, broker: str):
        t = self._controller.theme
        self._imported_count = max(0, self._imported_count - 1)
        self._broker_rows.pop(broker, None)
        if broker in self._broker_widgets:
            stats_lbl, status_lbl = self._broker_widgets[broker]
            stats_lbl.setText("0 files – 0 imported")
            status_lbl.setText("Awaiting")
            status_lbl.setStyleSheet(
                f"color: {t.get('text_secondary')}; border: 1px solid {t.get('text_secondary')};"
                "border-radius: 4px; padding: 2px 8px;"
            )
        self._refresh_stat_cards()

    def _wire_watcher(self):
        w = self._controller.watcher
        w.started.connect(self._on_watcher_started)
        w.stopped.connect(self._on_watcher_stopped)
        w.synced.connect(self._on_watcher_synced)
        w.sync_failed.connect(self._on_watcher_failed)

    def _on_watcher_started(self):
        t = self._controller.theme
        w = self._controller.watcher
        self._watcher_info.setText(f"Watching  <b>{w.watched_filename}</b>  · real-time")
        self._watcher_dot.setStyleSheet(f"color: {t.get('accent')};")
        self._watcher_sync_lbl.setText("Waiting for first change…")
        self._watcher_banner.setVisible(True)
        self._pulse_timer.start()

    def _on_watcher_stopped(self):
        t = self._controller.theme
        self._watcher_dot.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._watcher_info.setText("Watcher stopped")
        self._pulse_timer.stop()
        # hide banner after 3 seconds
        QTimer.singleShot(3000, lambda: self._watcher_banner.setVisible(False))

    def _on_watcher_synced(self, timestamp: str):
        t = self._controller.theme
        self._watcher_dot.setStyleSheet(f"color: {t.get('accent')};")
        self._watcher_sync_lbl.setText(f"Last synced: {timestamp}")

    def _on_watcher_failed(self, msg: str):
        t = self._controller.theme
        self._watcher_dot.setStyleSheet(f"color: {t.get('status_red')};")
        self._watcher_sync_lbl.setText(f"Sync failed: {msg[:60]}")

    def _pulse_dot(self):
        if not self._controller.watcher.is_active:
            return
        t = self._controller.theme
        self._dot_state = not self._dot_state
        color = t.get("accent") if self._dot_state else t.get("text_secondary")
        self._watcher_dot.setStyleSheet(f"color: {color};")

    def _refresh_stat_cards(self):
        total_files = self._imported_count
        total_rows = sum(self._broker_rows.values())
        self._stat_cards[0].set_value(str(total_files))
        self._stat_cards[1].set_value(f"{total_rows:,}")
        self._stat_cards[2].set_value("0")
        self._stat_cards[3].set_value(f"{total_files}/{len(BROKER_COLORS)}")
        self._total_lbl.setText(f"{total_files} total")
