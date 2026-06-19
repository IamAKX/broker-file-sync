from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel


class NotificationsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Notifications — coming in next task"))
