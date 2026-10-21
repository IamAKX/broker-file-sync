"""Excel-style "Filter by Colour" for the grids whose cells are filled by
conditional formatting (LMV live grid, EMV View by Date popup, HMV) — #99.

Right-click a column header -> *Filter by colour* lists the fills actually
present in that column (plus "No fill"); picking one hides every row whose
cell in that column doesn't have it. One colour per column; filters on
several columns combine (AND). The caller owns row hiding: it asks
``row_passes(row)`` from its own row-visibility pass and passes *on_changed*
to be re-run whenever the choice changes, so this composes with the
sector/search filters instead of fighting them.

What counts as a colour is the cell's actual fill, whatever painted it — a
conditional-format rule or the "changed since last time" highlight — exactly
as Excel's cell-colour filter does. *base_colors* are fills that mean "no
fill" for this table (LMV paints every cell with its card background).
"""
from PySide6.QtCore import QObject, Qt
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QMenu

NO_FILL = "__no_fill__"


def _icon(color: str) -> QIcon:
    pm = QPixmap(14, 14)
    pm.fill(QColor(color))
    return QIcon(pm)


def fill_color(brush, base_colors=()):
    """"#rrggbb" of a cell's fill, or None when it has none — no brush, a
    translucent tint, or one of *base_colors* (the table's plain background)."""
    if brush is None or brush.style() == Qt.BrushStyle.NoBrush:
        return None
    color = brush.color()
    if color.alpha() < 255:
        return None
    name = color.name()
    return None if name in base_colors else name


class ColorColumnFilter(QObject):
    def __init__(self, table, header_name_fn, on_changed, base_colors=None, cell_color_fn=None,
                 extra_headers=()):
        """*header_name_fn(col)* -> the column's stable name (survives column
        reordering / re-population). *cell_color_fn(row, col)* -> "#rrggbb"
        or None, default reads the item's background brush. *extra_headers*:
        other QHeaderViews (e.g. a frozen overlay's) that get the same menu."""
        super().__init__(table)
        self._table = table
        self._name = header_name_fn
        self._on_changed = on_changed
        self._base = base_colors if callable(base_colors) else (lambda b=set(base_colors or ()): b)
        self._cell_color_fn = cell_color_fn or self._item_color
        self._filters: dict[str, str] = {}      # column name -> colour hex or NO_FILL
        for hdr in (table.horizontalHeader(), *extra_headers):
            hdr.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            hdr.customContextMenuRequested.connect(lambda pos, h=hdr: self._on_menu(h, pos))

    # ── colour of a cell ─────────────────────────────────────────────────
    def _item_color(self, row: int, col: int):
        item = self._table.item(row, col)
        if item is None:
            return None
        return fill_color(item.background(), self._base())

    def color_of(self, row: int, col: int) -> str:
        return self._cell_color_fn(row, col) or NO_FILL

    def colors_in_column(self, col: int) -> list:
        """Distinct fills in *col* (most frequent first), NO_FILL last."""
        counts: dict = {}
        for r in range(self._table.rowCount()):
            c = self.color_of(r, col)
            counts[c] = counts.get(c, 0) + 1
        coloured = sorted((c for c in counts if c != NO_FILL), key=lambda c: (-counts[c], c))
        return coloured + ([NO_FILL] if NO_FILL in counts else [])

    # ── filtering ────────────────────────────────────────────────────────
    @property
    def active(self) -> bool:
        return bool(self._filters)

    def filters(self) -> dict:
        return dict(self._filters)

    def row_passes(self, row: int) -> bool:
        if not self._filters:
            return True
        for col in range(self._table.columnCount()):
            want = self._filters.get(self._name(col))
            if want is not None and self.color_of(row, col) != want:
                return False
        return True

    def set_filter(self, column_name: str, color: str | None):
        if color is None:
            self._filters.pop(column_name, None)
        else:
            self._filters[column_name] = color
        self._on_changed()

    def clear(self, notify: bool = True):
        if self._filters:
            self._filters.clear()
            if notify:
                self._on_changed()

    def summary(self) -> str:
        """Short text for a status label, "" when no colour filter is on."""
        if not self._filters:
            return ""
        return "colour filter: " + ", ".join(self._filters)

    # ── menu ─────────────────────────────────────────────────────────────
    def _on_menu(self, header, pos):
        col = header.logicalIndexAt(pos)
        if col < 0 or col >= self._table.columnCount():
            return
        self.build_menu(col).exec(header.mapToGlobal(pos))

    def build_menu(self, col: int) -> QMenu:
        name = self._name(col)
        current = self._filters.get(name)
        menu = QMenu(self._table)
        sub = menu.addMenu("Filter by colour")
        menu._submenu = sub        # keep the Python wrapper alive with the menu (PySide would delete the C++ submenu)
        colors = self.colors_in_column(col)
        if not [c for c in colors if c != NO_FILL]:
            sub.addAction("No coloured cells in this column").setEnabled(False)
        for c in colors:
            action = sub.addAction("No fill" if c == NO_FILL else c.upper())
            if c != NO_FILL:
                action.setIcon(_icon(c))
            action.setCheckable(True)
            action.setChecked(current == c)
            action.triggered.connect(lambda _=False, color=c: self.set_filter(name, color))
        sub.addSeparator()
        clear_col = sub.addAction("Clear filter on this column")
        clear_col.setEnabled(current is not None)
        clear_col.triggered.connect(lambda: self.set_filter(name, None))
        clear_all = menu.addAction("Clear all colour filters")
        clear_all.setEnabled(self.active)
        clear_all.triggered.connect(lambda: self.clear())
        return menu
