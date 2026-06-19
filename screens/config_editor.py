from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class ConfigEditorScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Config Editor — coming in next task"))
