from PySide6.QtGui import QFont

SMALL  = 10
MEDIUM = 12
LARGE  = 16

# Display sizes (titles, headings) — proportionally scaled
DISPLAY_SM = 22   # section headings
DISPLAY_MD = 28   # screen titles  (was ~27)
DISPLAY_LG = 36   # login/signup title (was ~33-35)


def font(size: int, bold: bool = False) -> QFont:
    w = QFont.Weight.Bold if bold else QFont.Weight.Normal
    return QFont("", size, w)


F_SMALL      = lambda bold=False: font(SMALL,      bold)
F_MEDIUM     = lambda bold=False: font(MEDIUM,     bold)
F_LARGE      = lambda bold=False: font(LARGE,      bold)
F_DISPLAY_SM = lambda bold=False: font(DISPLAY_SM, bold)
F_DISPLAY_MD = lambda bold=False: font(DISPLAY_MD, bold)
F_DISPLAY_LG = lambda bold=False: font(DISPLAY_LG, bold)
