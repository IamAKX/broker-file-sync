import re
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QProgressBar, QFileDialog, QScrollArea, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, QByteArray, QSize, Signal
from PySide6.QtGui import QFont, QIcon, QPixmap, QPainter
from PySide6.QtSvg import QSvgRenderer
from services.file_reader import (
    count_rows_sharekhan,
    count_rows_reliable,
    count_rows_nifty,
)

_BROKER_ROW_COUNTERS = {
    "Sharekhan":        count_rows_sharekhan,
    "ReliableSoftware": count_rows_reliable,
    "NiftyInvest":      count_rows_nifty,
}

ASSETS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets", "icons")

BROKERS = [
    ("Sharekhan",        "status_red",    "TradeBook export (.xlsx / .xls)",   (".xlsx", ".xls")),
    ("ReliableSoftware", "status_blue",   "Transactions export (.xlsx / .xls)", (".xlsx", ".xls")),
    ("NiftyInvest",      "status_orange", "Portfolio export (.csv)",            (".csv",)),
]


def _svg_icon(filename: str, color: str) -> QIcon:
    path = os.path.join(ASSETS_DIR, filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            svg = f.read()
    except FileNotFoundError:
        return QIcon()
    svg = re.sub(r'<rect\s+width="24"\s+height="24"[^/]*/>', '', svg)
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


class DropZone(QFrame):
    file_dropped = Signal(str)

    def __init__(self, exts: tuple = (".xlsx", ".xls"), parent=None):
        super().__init__(parent)
        self._exts = exts
        self.setObjectName("dropArea")
        self.setFixedHeight(130)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setAcceptDrops(True)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            if any(u.toLocalFile().lower().endswith(self._exts) for u in event.mimeData().urls()):
                event.acceptProposedAction()
                return
        event.ignore()

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()

    def dropEvent(self, event):
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith(self._exts):
                self.file_dropped.emit(path)
                event.acceptProposedAction()
                return


class BrokerImportCard(QFrame):
    import_done = Signal(str, int)  # broker name, row count
    import_reset = Signal(str)      # broker name when file is deleted

    def __init__(self, broker: str, color_token: str, hint: str, theme,
                 exts: tuple = (".xlsx", ".xls"), parent=None):
        super().__init__(parent)
        self._theme = theme
        self._broker = broker
        self._exts = exts
        self._selected_file = None
        self._row_count = 0
        self._progress_value = 0
        self.setObjectName("brokerPanel")
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self._build(color_token, hint)

    def _build(self, color_token: str, hint: str):
        t = self._theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 14, 16, 14)
        layout.setSpacing(10)

        # Header row: dot + name + status badge
        header = QHBoxLayout()
        dot = QLabel("●")
        dot.setStyleSheet(f"color: {t.get(color_token)}; font-size: 11px;")
        dot.setFixedWidth(16)
        name_lbl = QLabel(self._broker)
        name_lbl.setFont(QFont("", 13, QFont.Weight.Bold))
        self._status_lbl = QLabel("Awaiting")
        self._status_lbl.setFont(QFont("", 11))
        self._status_lbl.setStyleSheet(
            f"color: {t.get('text_secondary')}; border: 1px solid {t.get('text_secondary')};"
            "border-radius: 4px; padding: 1px 8px;"
        )
        header.addWidget(dot)
        header.addWidget(name_lbl)
        header.addStretch()
        header.addWidget(self._status_lbl)
        layout.addLayout(header)

        # Drop zone
        drop = DropZone(self._exts)
        drop_layout = QVBoxLayout(drop)
        drop_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        drop_layout.setSpacing(6)

        upload_icon = QLabel()
        upload_icon.setFixedSize(32, 32)
        upload_icon.setPixmap(_svg_icon("import.svg", t.get("text_secondary")).pixmap(QSize(32, 32)))
        upload_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_main = QLabel("Drop file or click to browse")
        drop_main.setFont(QFont("", 12))
        drop_main.setStyleSheet(f"color: {t.get('text_secondary')};")
        drop_main.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_hint = QLabel(hint)
        drop_hint.setFont(QFont("", 10))
        drop_hint.setStyleSheet(f"color: {t.get('text_secondary')};")
        drop_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)

        drop_layout.addWidget(upload_icon, alignment=Qt.AlignmentFlag.AlignCenter)
        drop_layout.addWidget(drop_main)
        drop_layout.addWidget(drop_hint)
        drop.mousePressEvent = lambda _: self._browse()
        drop.file_dropped.connect(self._on_file_dropped)
        layout.addWidget(drop)

        # Progress bar + percentage label
        progress_row = QHBoxLayout()
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(6)
        self._progress.setTextVisible(False)
        self._progress.setVisible(False)
        self._pct_lbl = QLabel("")
        self._pct_lbl.setFixedWidth(36)
        self._pct_lbl.setFont(QFont("", 10))
        self._pct_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._pct_lbl.setVisible(False)
        progress_row.addWidget(self._progress)
        progress_row.addWidget(self._pct_lbl)
        layout.addLayout(progress_row)

        # Bottom row: file label + delete button
        bottom_row = QHBoxLayout()
        self._file_lbl = QLabel("No files imported yet")
        self._file_lbl.setFont(QFont("", 10))
        self._file_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._file_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._delete_btn = QPushButton("✕ Remove")
        self._delete_btn.setFont(QFont("", 10))
        self._delete_btn.setFixedHeight(24)
        self._delete_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._delete_btn.setStyleSheet(
            f"color: {t.get('status_red')}; background: transparent; border: none;"
        )
        self._delete_btn.setVisible(False)
        self._delete_btn.clicked.connect(self._reset)

        bottom_row.addWidget(self._file_lbl, 1)
        bottom_row.addWidget(self._delete_btn)
        layout.addLayout(bottom_row)

    def _on_file_dropped(self, path: str):
        self._selected_file = path
        counter = _BROKER_ROW_COUNTERS.get(self._broker, count_rows_sharekhan)
        self._row_count = counter(path)
        self._file_lbl.setText(f"Selected: {os.path.basename(path)}")
        self._file_lbl.setStyleSheet(f"color: {self._theme.get('accent')};")
        self._start_import()

    def _browse(self):
        if self._exts == (".csv",):
            file_filter = "CSV Files (*.csv)"
        elif ".csv" in self._exts:
            file_filter = "Supported Files (*.xlsx *.xls *.csv)"
        else:
            file_filter = "Excel Files (*.xlsx *.xls)"
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {self._broker} File", "", file_filter
        )
        if path:
            self._on_file_dropped(path)

    def _start_import(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self._progress_value = 0
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._pct_lbl.setText("0%")
        self._pct_lbl.setVisible(True)
        self._delete_btn.setVisible(False)
        self._status_lbl.setText("Importing...")
        self._status_lbl.setStyleSheet(
            f"color: {self._theme.get('accent')}; border: 1px solid {self._theme.get('accent')};"
            "border-radius: 4px; padding: 1px 8px;"
        )
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(40)

    def _tick(self):
        self._progress_value += 2
        self._progress.setValue(self._progress_value)
        self._pct_lbl.setText(f"{self._progress_value}%")
        if self._progress_value >= 100:
            self._timer.stop()
            self._progress.setVisible(False)
            self._pct_lbl.setVisible(False)
            self._status_lbl.setText("Imported")
            self._status_lbl.setStyleSheet(
                f"color: {self._theme.get('accent')}; border: 1px solid {self._theme.get('accent')};"
                "border-radius: 4px; padding: 1px 8px;"
            )
            rows = self._row_count
            self._file_lbl.setText(f"1 file imported · {rows:,} rows")
            self._file_lbl.setStyleSheet(f"color: {self._theme.get('accent')};")
            self._delete_btn.setVisible(True)
            self.import_done.emit(self._broker, rows)

    def _reset(self):
        if hasattr(self, "_timer") and self._timer.isActive():
            self._timer.stop()
        self._selected_file = None
        self._row_count = 0
        self._progress.setValue(0)
        self._progress.setVisible(False)
        self._pct_lbl.setVisible(False)
        self._delete_btn.setVisible(False)
        self._status_lbl.setText("Awaiting")
        self._status_lbl.setStyleSheet(
            f"color: {self._theme.get('text_secondary')}; border: 1px solid {self._theme.get('text_secondary')};"
            "border-radius: 4px; padding: 1px 8px;"
        )
        self._file_lbl.setText("No files imported yet")
        self._file_lbl.setStyleSheet(f"color: {self._theme.get('text_secondary')};")
        self.import_reset.emit(self._broker)


class DataImportScreen(QWidget):
    broker_imported    = Signal(str, int)   # broker name, row count
    broker_reset       = Signal(str)
    lmv_headers_ready  = Signal(list)       # emitted when LMV loads headers
    _TOTAL_BROKERS = len(BROKERS)

    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._imported_brokers: set[str] = set()
        self._watcher_btn: QPushButton = None
        self._live_viewer = None
        self._dot_bright = True
        self._pulse_timer = QTimer()
        self._pulse_timer.setInterval(700)
        self._pulse_timer.timeout.connect(self._pulse_dot)
        self._build()
        # Keep button state in sync with watcher lifecycle
        self._controller.watcher.started.connect(self._on_watcher_started)
        self._controller.watcher.stopped.connect(self._on_watcher_stopped)

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Data Import")
        title.setFont(QFont("", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Upload Excel exports from your broker platforms. Multiple files per broker are supported.")
        subtitle.setFont(QFont("", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        subtitle.setWordWrap(True)
        layout.addWidget(subtitle)

        # 3-column broker cards
        cards_row = QHBoxLayout()
        cards_row.setSpacing(16)
        self._cards: dict[str, BrokerImportCard] = {}
        for broker, color_token, hint, exts in BROKERS:
            card = BrokerImportCard(broker, color_token, hint, t, exts)
            card.import_done.connect(self.broker_imported)
            card.import_reset.connect(self.broker_reset)
            card.import_done.connect(self._on_card_imported)
            card.import_reset.connect(self._on_card_reset)
            self._cards[broker] = card
            cards_row.addWidget(card)
        layout.addLayout(cards_row)

        # Bottom button row — Run Watcher
        gen_row = QHBoxLayout()
        gen_row.addStretch()

        self._watcher_btn = QPushButton("  Run Watcher")
        self._watcher_btn.setFixedHeight(40)
        self._watcher_btn.setFont(QFont("", 12, QFont.Weight.Bold))
        self._watcher_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._watcher_btn.setEnabled(False)
        self._watcher_btn.clicked.connect(self._run_watcher)
        self._update_watcher_btn()
        gen_row.addWidget(self._watcher_btn)

        layout.addLayout(gen_row)

        layout.addStretch()

    def _on_card_imported(self, broker: str, rows: int):
        self._imported_brokers.add(broker)
        self._update_watcher_btn()

    def _on_card_reset(self, broker: str):
        self._imported_brokers.discard(broker)
        self._update_watcher_btn()

    def _on_watcher_started(self):
        self._pulse_timer.start()
        self._dot_bright = True
        self._apply_watcher_running_style(bright=True)

    def _on_watcher_stopped(self):
        self._pulse_timer.stop()
        self._update_watcher_btn()

    def _pulse_dot(self):
        self._dot_bright = not self._dot_bright
        self._apply_watcher_running_style(bright=self._dot_bright)

    def _apply_watcher_running_style(self, bright: bool):
        if self._watcher_btn is None:
            return
        dot_color = "#39d353" if bright else "#1a5c28"
        self._watcher_btn.setText(f"  ● Watcher Running")
        self._watcher_btn.setEnabled(False)
        self._watcher_btn.setStyleSheet(
            f"QPushButton {{ background: transparent;"
            f"color: {dot_color};"
            f"border: 1px solid {dot_color};"
            "border-radius: 4px; padding: 0 20px; }"
        )

    def _update_watcher_btn(self):
        if self._watcher_btn is None:
            return
        t        = self._controller.theme
        all_done = len(self._imported_brokers) == self._TOTAL_BROKERS
        if all_done:
            self._watcher_btn.setText("  Run Watcher")
            self._watcher_btn.setEnabled(True)
            self._watcher_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {t.get('accent')};"
                f"border: 1px solid {t.get('accent')}; border-radius: 4px; padding: 0 20px; }}"
                f"QPushButton:hover {{ background: {t.get('accent')}22; }}"
            )
        else:
            self._watcher_btn.setText("  Run Watcher")
            self._watcher_btn.setEnabled(False)
            self._watcher_btn.setStyleSheet(
                "QPushButton { background: transparent; color: #555e68;"
                "border: 1px solid #555e68; border-radius: 4px; padding: 0 20px; }"
            )

    def _run_watcher(self):
        from config_defaults import SCRIPT_NAME_DATA
        from screens.live_viewer import LiveViewerWindow

        sharekhan_path = self._cards["Sharekhan"]._selected_file
        reliable_path  = self._cards["ReliableSoftware"]._selected_file
        nifty_path     = self._cards["NiftyInvest"]._selected_file
        # Reuse existing window if already open
        if self._live_viewer is not None and not self._live_viewer.isHidden():
            self._live_viewer.raise_()
            self._live_viewer.activateWindow()
            return

        self._live_viewer = LiveViewerWindow(
            sharekhan_path, reliable_path, nifty_path,
            SCRIPT_NAME_DATA,
            theme=self._controller.theme,
            controller=self._controller,
        )
        self._live_viewer.show()
        # Share LMV column headers with strategy builder
        if self._live_viewer._headers:
            self.lmv_headers_ready.emit(list(self._live_viewer._headers))
        # Notify the rest of the UI that the watcher is now active
        self._controller.watcher.started.emit()

