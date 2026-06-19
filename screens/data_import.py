from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QFrame, QComboBox, QProgressBar, QPlainTextEdit, QFileDialog, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from datetime import datetime


class DataImportScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._selected_file = None
        self._progress_value = 0
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Data Import")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Upload broker Excel files for processing")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        # Broker selector
        row = QHBoxLayout()
        row.setSpacing(12)
        broker_lbl = QLabel("SELECT BROKER")
        broker_lbl.setFont(QFont("Courier New", 10))
        broker_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._broker_combo = QComboBox()
        self._broker_combo.addItems(["Sharekhan", "ReliableSoftware", "NiftyInvest"])
        self._broker_combo.setFixedHeight(36)
        self._broker_combo.setMinimumWidth(220)
        row.addWidget(broker_lbl, alignment=Qt.AlignmentFlag.AlignVCenter)
        row.addWidget(self._broker_combo)
        row.addStretch()
        layout.addLayout(row)

        # Drop area
        self._drop_area = QFrame()
        self._drop_area.setObjectName("dropArea")
        self._drop_area.setFixedHeight(130)
        self._drop_area.setStyleSheet(
            f"QFrame#dropArea {{ background: {t.get('card_bg')};"
            f"border: 2px dashed {t.get('border')}; border-radius: 8px; }}"
        )
        self._drop_area.setCursor(Qt.CursorShape.PointingHandCursor)
        drop_layout = QVBoxLayout(self._drop_area)
        self._drop_label = QLabel("Drop Excel files here or click to browse")
        self._drop_label.setFont(QFont("Courier New", 13))
        self._drop_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._drop_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        drop_layout.addWidget(self._drop_label)
        self._drop_area.mousePressEvent = lambda _: self._browse_file()
        layout.addWidget(self._drop_area)

        self._file_name_lbl = QLabel("")
        self._file_name_lbl.setFont(QFont("Courier New", 11))
        self._file_name_lbl.setStyleSheet(f"color: {t.get('accent')};")
        layout.addWidget(self._file_name_lbl)

        # Import button
        import_btn = QPushButton("⬆  Import Files")
        import_btn.setFixedHeight(42)
        import_btn.setFont(QFont("Courier New", 13, QFont.Weight.Bold))
        import_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        import_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px;"
        )
        import_btn.clicked.connect(self._start_import)
        layout.addWidget(import_btn, alignment=Qt.AlignmentFlag.AlignLeft)

        # Progress bar
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(10)
        self._progress.setVisible(False)
        layout.addWidget(self._progress)

        # Log area
        log_lbl = QLabel("IMPORT LOG")
        log_lbl.setFont(QFont("Courier New", 10))
        log_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(log_lbl)

        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Courier New", 11))
        self._log.setMinimumHeight(160)
        self._log.setStyleSheet(
            f"background: {t.get('card_bg')}; border: 1px solid {t.get('border')};"
            "border-radius: 4px;"
        )
        layout.addWidget(self._log)
        layout.addStretch()

    def _browse_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select Excel File", "", "Excel Files (*.xlsx *.xls)"
        )
        if path:
            self._selected_file = path
            filename = path.split("/")[-1]
            self._file_name_lbl.setText(f"Selected: {filename}")

    def _start_import(self):
        self._progress.setValue(0)
        self._progress.setVisible(True)
        self._progress_value = 0
        self._log.appendPlainText(
            f"[{datetime.now().strftime('%H:%M:%S')}] Starting import for "
            f"{self._broker_combo.currentText()}..."
        )
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick_progress)
        self._timer.start(40)

    def _tick_progress(self):
        self._progress_value += 2
        self._progress.setValue(self._progress_value)
        if self._progress_value >= 100:
            self._timer.stop()
            ts = datetime.now().strftime("%H:%M:%S")
            self._log.appendPlainText(f"[{ts}] Reading file headers...")
            self._log.appendPlainText(f"[{ts}] Validating column mappings...")
            self._log.appendPlainText(f"[{ts}] Processing rows...")
            self._log.appendPlainText(f"[{ts}] Import complete! 0 rows processed.")
