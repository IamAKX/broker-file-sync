from PySide6.QtWidgets import QMessageBox

from api.exceptions import ApiError, NetworkError


def show_api_error(theme, parent, exc: Exception) -> None:
    """Show a themed critical popup for an API/network failure.

    Centralizes error presentation so every screen shows the same look —
    change the styling or wording here, not at each call site.
    """
    if isinstance(exc, ApiError):
        title = "Request Failed"
        message = exc.detail
    elif isinstance(exc, NetworkError):
        title = "Connection Error"
        message = str(exc)
    else:
        title = "Unexpected Error"
        message = str(exc)

    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    box.setStyleSheet(
        f"QMessageBox {{ background: {theme.get('background')}; color: {theme.get('text_primary')}; }}"
    )
    box.exec()
