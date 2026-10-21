"""Click-a-header-to-sort for the Inception QTableWidget grids (EMV View by
Date popup, HMV) — the same ascending/descending toggle LMV's live grid has.

Cells are stored as display text, so Qt's default sort would order "9.5"
after "10.2". SortableItem compares numerically when both cells parse as
numbers (text otherwise) and always keeps blank cells last, in either
direction. Rows are physically reordered (QTableWidget.sortItems), which
the FrozenColumns overlay follows because it shares the model.
"""
from PySide6.QtCore import QObject, Qt
from PySide6.QtWidgets import QTableWidgetItem


def _sort_key(text: str):
    """(is_blank, number_or_None, lowercase_text)."""
    s = (text or "").strip()
    if not s:
        return (True, None, "")
    try:
        return (False, float(s.replace(",", "").rstrip("%")), s.lower())
    except ValueError:
        return (False, None, s.lower())


class SortableItem(QTableWidgetItem):
    def __init__(self, text: str = ""):
        super().__init__(text)
        self._key = _sort_key(text)

    def __lt__(self, other):
        if not isinstance(other, SortableItem):
            return super().__lt__(other)
        a, b = self._key, other._key
        table = self.tableWidget()
        desc = bool(table.property("_sort_desc")) if table is not None else False
        # Qt sorts descending by swapping the operands, so "blank last" in
        # either direction means blank must compare as the greatest value
        # when ascending and as the least when descending.
        if a[0] or b[0]:
            if a[0] and b[0]:
                return False
            return desc if a[0] else not desc
        if a[1] is not None and b[1] is not None:
            return a[1] < b[1]
        if a[1] is not None:      # numbers before text
            return True
        if b[1] is not None:
            return False
        return a[2] < b[2]


class HeaderSorter(QObject):
    """Wires header clicks on *table* (and the frozen overlay's header, if
    *freeze* is given) to a sort. First click on a column sorts ascending,
    clicking it again toggles descending. *on_sorted* runs after every sort
    (e.g. to re-apply row-hidden state, which doesn't follow the rows)."""

    def __init__(self, table, freeze=None, on_sorted=None):
        super().__init__(table)
        self._table = table
        self._freeze = freeze
        self._on_sorted = on_sorted
        self._col_name: str | None = None
        self._desc = False
        hdr = table.horizontalHeader()
        hdr.setSectionsClickable(True)
        hdr.setSortIndicatorShown(True)
        hdr.sectionClicked.connect(self._on_clicked)
        if freeze is not None:
            fhdr = freeze.overlay_header()
            fhdr.setSectionsClickable(True)
            fhdr.setSortIndicatorShown(True)
            fhdr.sectionClicked.connect(self._on_clicked)

    @property
    def column_name(self):
        return self._col_name

    @property
    def descending(self) -> bool:
        return self._desc

    def _header_text(self, col: int) -> str:
        item = self._table.horizontalHeaderItem(col)
        return item.text() if item is not None else ""

    def _on_clicked(self, col: int):
        if col < 0 or col >= self._table.columnCount():
            return
        name = self._header_text(col)
        if self._col_name == name:
            self._desc = not self._desc
        else:
            self._col_name, self._desc = name, False
        self._apply(col)

    def _apply(self, col: int):
        order = Qt.SortOrder.DescendingOrder if self._desc else Qt.SortOrder.AscendingOrder
        self._table.setProperty("_sort_desc", self._desc)
        self._table.sortItems(col, order)
        self._table.horizontalHeader().setSortIndicator(col, order)
        if self._freeze is not None:
            self._freeze.overlay_header().setSortIndicator(col, order)
            self._freeze._sync_row_heights()
        if self._on_sorted is not None:
            self._on_sorted()

    def reapply(self):
        """Call after the table is repopulated: sort the fresh rows by the
        column the user last sorted on (matched by header text); if it's
        gone, drop the sort indicator."""
        if self._col_name is None:
            return
        for c in range(self._table.columnCount()):
            if self._header_text(c) == self._col_name:
                self._apply(c)
                return
        self._col_name = None
        self._table.horizontalHeader().setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
