SMALL      = 14
MEDIUM     = 16
LARGE      = 18
DISPLAY_SM = 22
DISPLAY_MD = 28
DISPLAY_LG = 36


def font(size: int, bold: bool = False):
    from PySide6.QtGui import QFont
    w = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return QFont("", size, w)


F_SMALL      = lambda bold=False: font(SMALL,      bold)
F_MEDIUM     = lambda bold=False: font(MEDIUM,     bold)
F_LARGE      = lambda bold=False: font(LARGE,      bold)
F_DISPLAY_SM = lambda bold=False: font(DISPLAY_SM, bold)
F_DISPLAY_MD = lambda bold=False: font(DISPLAY_MD, bold)
F_DISPLAY_LG = lambda bold=False: font(DISPLAY_LG, bold)
