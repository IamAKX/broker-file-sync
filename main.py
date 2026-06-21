import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from app import AppController
import font_scale


def main():
    # Must be set before QApplication is created for Windows DPI awareness
    os.environ.setdefault("QT_AUTO_SCREEN_SCALE_FACTOR", "1")
    os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setFont(font_scale.F_MEDIUM())

    controller = AppController(app)
    controller.start()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
