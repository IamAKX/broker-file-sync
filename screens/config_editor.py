from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTabWidget, QTableWidget, QTableWidgetItem, QMessageBox, QHeaderView
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont


COLUMN_MAPPING_DATA = [
    ("Date",          "trade_date"),
    ("Symbol",        "scrip_symbol"),
    ("Quantity",      "trade_qty"),
    ("Price",         "trade_price"),
    ("Transaction",   "txn_type"),
]

SCRIPT_MAPPING_DATA = [
    ("SCR001", "NSE_EQ_PROCESSOR",    "Sharekhan"),
    ("SCR002", "BSE_EQ_PROCESSOR",    "ReliableSoftware"),
    ("SCR003", "FNO_PROCESSOR",       "NiftyInvest"),
    ("SCR004", "COMMODITY_PROCESSOR", "Sharekhan"),
]


class ConfigEditorScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._build()

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Config Editor")
        title.setFont(QFont("Courier New", 24, QFont.Weight.Bold))
        layout.addWidget(title)

        subtitle = QLabel("Manage column and script name mappings")
        subtitle.setFont(QFont("Courier New", 12))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(subtitle)

        tabs = QTabWidget()
        tabs.setFont(QFont("Courier New", 12))

        # Tab 1: Column Name Mapping
        col_tab = QWidget()
        col_layout = QVBoxLayout(col_tab)
        col_layout.setContentsMargins(16, 16, 16, 16)

        col_table = QTableWidget(len(COLUMN_MAPPING_DATA), 2)
        col_table.setHorizontalHeaderLabels(["SOURCE COLUMN", "TARGET COLUMN"])
        col_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        col_table.verticalHeader().setVisible(False)
        col_table.setFont(QFont("Courier New", 12))
        for row, (src, tgt) in enumerate(COLUMN_MAPPING_DATA):
            col_table.setItem(row, 0, QTableWidgetItem(src))
            col_table.setItem(row, 1, QTableWidgetItem(tgt))
        col_layout.addWidget(col_table)
        tabs.addTab(col_tab, "Column Name Mapping")

        # Tab 2: Script Name Mapping
        scr_tab = QWidget()
        scr_layout = QVBoxLayout(scr_tab)
        scr_layout.setContentsMargins(16, 16, 16, 16)

        scr_table = QTableWidget(len(SCRIPT_MAPPING_DATA), 3)
        scr_table.setHorizontalHeaderLabels(["SCRIPT ID", "SCRIPT NAME", "BROKER"])
        scr_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        scr_table.verticalHeader().setVisible(False)
        scr_table.setFont(QFont("Courier New", 12))
        for row, (sid, name, broker) in enumerate(SCRIPT_MAPPING_DATA):
            scr_table.setItem(row, 0, QTableWidgetItem(sid))
            scr_table.setItem(row, 1, QTableWidgetItem(name))
            scr_table.setItem(row, 2, QTableWidgetItem(broker))
        scr_layout.addWidget(scr_table)
        tabs.addTab(scr_tab, "Script Name Mapping")

        layout.addWidget(tabs)

        save_btn = QPushButton("💾  Save Configuration")
        save_btn.setFixedHeight(40)
        save_btn.setFont(QFont("Courier New", 12, QFont.Weight.Bold))
        save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        save_btn.setStyleSheet(
            f"background: {t.get('accent')}; color: {t.get('background')};"
            "border: none; border-radius: 4px; padding: 0 20px;"
        )
        save_btn.clicked.connect(self._on_save)
        layout.addWidget(save_btn, alignment=Qt.AlignmentFlag.AlignLeft)
        layout.addStretch()

    def _on_save(self):
        QMessageBox.information(self, "Saved", "Configuration saved successfully.")
