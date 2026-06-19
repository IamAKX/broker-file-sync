from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class DataImportScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Data Import — coming in next task"))
