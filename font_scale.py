import sys
from PySide6.QtGui import QFont

# Windows renders pt sizes larger due to 96 DPI baseline vs macOS 72 DPI.
# Segoe UI is the correct modern Windows font; San Francisco is default on Mac.
if sys.platform == "win32":
    _FAMILY   = "Segoe UI"
    _SCALE    = 0.80          # scale down all sizes on Windows
else:
    _FAMILY   = ""            # use system default (SF on Mac)
    _SCALE    = 1.0

def _s(size: int) -> int:
    return max(8, round(size * _SCALE))

SMALL      = _s(10)
MEDIUM     = _s(12)
LARGE      = _s(14)
DISPLAY_SM = _s(22)
DISPLAY_MD = _s(28)
DISPLAY_LG = _s(36)


def font(size: int, bold: bool = False) -> QFont:
    w = QFont.Weight.Bold if bold else QFont.Weight.Normal
    f = QFont(_FAMILY, size, w)
    if sys.platform == "win32":
        f.setHintingPreference(QFont.HintingPreference.PreferFullHinting)
    return f


F_SMALL      = lambda bold=False: font(SMALL,      bold)
F_MEDIUM     = lambda bold=False: font(MEDIUM,     bold)
F_LARGE      = lambda bold=False: font(LARGE,      bold)
F_DISPLAY_SM = lambda bold=False: font(DISPLAY_SM, bold)
F_DISPLAY_MD = lambda bold=False: font(DISPLAY_MD, bold)
F_DISPLAY_LG = lambda bold=False: font(DISPLAY_LG, bold)