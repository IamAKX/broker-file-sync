from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class ProfileScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("My Profile — coming in next task"))
