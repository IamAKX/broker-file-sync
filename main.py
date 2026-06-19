import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QFont
from app import AppController


def main():
    app = QApplication(sys.argv)
    app.setFont(QFont("Courier New", 13))
    controller = AppController(app)
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
