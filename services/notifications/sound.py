"""
Loud alert sound played alongside every notification, regardless of channel.
Uses QSoundEffect (QtMultimedia) rather than QApplication.beep() so both the
sound itself and its volume are ours to control instead of whatever quiet
default beep the OS provides.
"""

import os

from PySide6.QtCore import QUrl
from PySide6.QtMultimedia import QSoundEffect

_ASSET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "sounds", "notification_alert.wav",
)


class AlertSound:
    def __init__(self, volume: float = 1.0):
        self._effect = QSoundEffect()
        self._effect.setSource(QUrl.fromLocalFile(_ASSET_PATH))
        self._effect.setVolume(volume)   # 1.0 = loudest QSoundEffect allows

    def play(self) -> None:
        self._effect.play()
