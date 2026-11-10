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
from PySide6.QtWidgets import QInputDialog, QMenu

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


def parse_number(text) -> float | None:
    """Number in a cell's text ("1,234.50", "-2.5%", "3"), None if it isn't one."""
    if text is None:
        return None
    t = str(text).strip().replace(",", "").replace("%", "").replace("₹", "").strip()
    if not t:
        return None
    try:
        v = float(t)
    except ValueError:
        return None
    return v if v == v else None   # NaN -> None


class ColorColumnFilter(QObject):
    """Header right-click filters for a grid: Filter by colour (#99) and
    Show top / bottom N by this column (#110).

    Top/bottom N keeps only the N rows with the highest (top) or lowest
    (bottom) value in one column, *among the rows every other filter already
    lets through* — so "strategy gives 50 stocks, show the top 25 by DAY TO"
    works. Rows with no number in that column are dropped. One column at a
    time. The caller owns row hiding: after its own filters it calls
    ``limit_rows(visible_rows)`` and hides whatever isn't returned.
    *sort_fn(column_name, descending)* (optional) is asked to sort the grid by
    the column when a top/bottom N is picked, so the kept rows read best-first.
    """

    def __init__(self, table, header_name_fn, on_changed, base_colors=None, cell_color_fn=None,
                 extra_headers=(), sort_fn=None, value_fn=None):
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
        self._sort_fn = sort_fn
        self._value_fn = value_fn or self._item_value
        self._topn: tuple[str, int, str] | None = None   # (column name, n, "top" | "bottom")
        self._last_n = 25
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
        return bool(self._filters) or self._topn is not None

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
        if self._filters or self._topn is not None:
            self._filters.clear()
            self._topn = None
            if notify:
                self._on_changed()

    def summary(self) -> str:
        """Short text for a status label, "" when no filter from here is on."""
        parts = []
        if self._filters:
            parts.append("colour filter: " + ", ".join(self._filters))
        if self._topn is not None:
            name, n, mode = self._topn
            parts.append(f"{mode} {n} by {name}")
        return "  ·  ".join(parts)

    # ── top / bottom N ───────────────────────────────────────────────────
    def _item_value(self, row: int, col: int):
        item = self._table.item(row, col)
        return parse_number(item.text()) if item is not None else None

    def topn(self):
        return self._topn

    def _column_of(self, name: str):
        for c in range(self._table.columnCount()):
            if self._name(c) == name:
                return c
        return None

    def set_topn(self, column_name: str, n: int, mode: str):
        """mode: "top" (highest first) or "bottom" (lowest first)."""
        self._last_n = n
        self._topn = (column_name, int(n), mode)
        if self._sort_fn is not None:
            self._sort_fn(column_name, mode == "top")
        self._on_changed()

    def clear_topn(self):
        if self._topn is not None:
            self._topn = None
            self._on_changed()

    def limit_rows(self, rows) -> set:
        """Of *rows* (the row numbers the other filters let through), the ones
        to keep for the active top/bottom N; all of them when none is active."""
        rows = list(rows)
        if self._topn is None:
            return set(rows)
        name, n, mode = self._topn
        col = self._column_of(name)
        if col is None:                      # column gone (reset / different view) -> no limit
            return set(rows)
        scored = []
        for r in rows:
            v = self._value_fn(r, col)
            if v is not None:
                scored.append((v, r))
        scored.sort(key=lambda t: (-t[0] if mode == "top" else t[0], t[1]))
        return {r for _, r in scored[:n]}

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
        clear_all.setEnabled(bool(self._filters))
        clear_all.triggered.connect(lambda: self.clear_colours())
        menu.addSeparator()
        cur = self._topn[1:] if self._topn and self._topn[0] == name else None
        top = menu.addAction("Show top N…" if not cur or cur[1] != "top" else f"Show top N… (now {cur[0]})")
        top.triggered.connect(lambda: self._ask_topn(name, "top"))
        bottom = menu.addAction("Show bottom N…" if not cur or cur[1] != "bottom" else f"Show bottom N… (now {cur[0]})")
        bottom.triggered.connect(lambda: self._ask_topn(name, "bottom"))
        clear_n = menu.addAction("Clear top / bottom N")
        clear_n.setEnabled(self._topn is not None)
        clear_n.triggered.connect(self.clear_topn)
        return menu

    def clear_colours(self):
        if self._filters:
            self._filters.clear()
            self._on_changed()

    def _ask_topn(self, name: str, mode: str):
        word = "highest" if mode == "top" else "lowest"
        n, ok = QInputDialog.getInt(
            self._table, f"Show {mode} N", f"Show the {word} N stocks by “{name}”.\nHow many?",
            self._last_n, 1, 100000)
        if ok:
            self.set_topn(name, n, mode)
