"""
Loud alert sound played alongside every notification, regardless of channel.
Uses QSoundEffect (QtMultimedia) rather than QApplication.beep() so both the
sound itself and its volume are ours to control instead of whatever quiet
default beep the OS provides.
"""

import os

from PySide6.QtCore import QUrl

try:
    # On Linux, importing this binding loads Qt's multimedia backend, which
    # dynamically links against the platform's audio stack (e.g. PulseAudio)
    # — on a headless CI runner without that installed, the import itself
    # raises ImportError, not just QSoundEffect() construction. Degrading to
    # a no-op keeps every other notification channel (and anything that
    # merely imports this module, like services.notifications.manager)
    # working on machines with no audio device instead of crashing at import
    # time.
    from PySide6.QtMultimedia import QSoundEffect
except ImportError:
    QSoundEffect = None

_ASSET_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
    "assets", "sounds", "notification_alert.wav",
)


class AlertSound:
    def __init__(self, volume: float = 1.0):
        self._effect = None
        if QSoundEffect is None:
            return
        try:
            self._effect = QSoundEffect()
            self._effect.setSource(QUrl.fromLocalFile(_ASSET_PATH))
            self._effect.setVolume(volume)   # 1.0 = loudest QSoundEffect allows
        except Exception:
            self._effect = None

    def play(self) -> None:
        if self._effect is not None:
            self._effect.play()
