"""Keeps a positioned popup (a button-anchored dropdown, or a "view more"
info popup) fully on screen. Every screens/*.py caller positions its own
popup with a hand-written mapToGlobal() + move() pair, and none of them
account for the screen's own bottom/right edge — so a popup opened from a
button near the bottom or right of a window (e.g. the "Strategies" bar at
the bottom of a short screen like Inception's View by Date) can render
partially or entirely off-screen: unusable, since a frameless
Qt.WindowType.Popup can't be dragged back into view. See GitHub issue #51's
screenshot report for the concrete case this fixes.
"""
from PySide6.QtCore import QPoint
from PySide6.QtWidgets import QApplication, QWidget


def clamp_to_screen(popup: QWidget, preferred_top_left: QPoint) -> QPoint:
    """*popup* must already be sized (call adjustSize()/resize() first —
    this reads popup.size(), which is only accurate afterward). Returns
    the closest on-screen position to *preferred_top_left*: shifted left/
    up just enough to keep the popup's full rect within whichever
    screen's available geometry *preferred_top_left* falls in (falling
    back to the primary screen if that point isn't on any screen — e.g. a
    monitor that was just disconnected), and never shifted past that
    screen's own top-left corner either — a popup taller/wider than the
    whole screen still renders at the screen's origin, the least-bad
    option, rather than an even more negative position."""
    screen = QApplication.screenAt(preferred_top_left) or QApplication.primaryScreen()
    avail = screen.availableGeometry()
    size = popup.size()
    x = min(preferred_top_left.x(), avail.right() - size.width() + 1)
    y = min(preferred_top_left.y(), avail.bottom() - size.height() + 1)
    x = max(x, avail.left())
    y = max(y, avail.top())
    return QPoint(x, y)
