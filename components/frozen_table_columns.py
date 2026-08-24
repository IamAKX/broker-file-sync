"""Pins the first N logical columns of a QTableWidget (a small overlay
QTableView sharing the same item model) in place while the rest of the
table scrolls horizontally underneath — the same "frozen column" pattern
screens.live_viewer uses to pin LMV's Scrip Name column (see that module's
_setup_frozen_column/_configure_frozen_column/_update_frozen_geometry: a
QTableView(parent=table), same model, geometry re-laid-out over the real
column(s) it's covering), generalized here to pin MORE THAN ONE column
together (Inception's Sector + Symbol) and packaged as a standalone,
reusable component instead of being duplicated per screen.

Usage::

    freeze = FrozenColumns(table)
    ...
    freeze.configure(headers, ["Sector", "Symbol"], style_sheet)
    # call again after every table rebuild (new headers/rows) — cheap even
    # when the frozen columns haven't changed. Pass [] to unfreeze.

Column names are looked up by their CURRENT text in *headers* at
configure()-time (not tracked across renames), matching how live_viewer
re-resolves "Scrip Name"'s logical index fresh on every render rather than
caching it once.

Deliberately NOT wired into screens.live_viewer itself — LMV's existing
single-column freeze already works and ships; this is a separate, additive
component for Inception's grids (screens.inception_hmv, the HistoricDataViewer
popup screens.inception_view_by_date uses) so as not to risk regressing it.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QAbstractItemView, QFrame, QHeaderView, QTableView


class FrozenColumns(QObject):
    def __init__(self, table, parent=None):
        super().__init__(parent or table)
        self._table = table
        self._frozen_cols: list[int] = []
        self._guarding = False

        self._overlay = QTableView(table)
        ov = self._overlay
        ov.setModel(table.model())
        ov.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        ov.setFont(table.font())
        ov.verticalHeader().setVisible(False)
        ov.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        ov.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        ov.setAlternatingRowColors(False)
        ov.setShowGrid(True)
        ov.setFrameShape(QFrame.Shape.NoFrame)
        ov.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        ov.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        fhdr = ov.horizontalHeader()
        fhdr.setSectionResizeMode(QHeaderView.ResizeMode.Fixed)
        fhdr.setSectionsMovable(False)
        fhdr.setSectionsClickable(False)
        ov.hide()

        # The two views are otherwise fully independent even though they
        # share a model — keep vertical scrolling in lock-step by hand.
        table.verticalScrollBar().valueChanged.connect(ov.verticalScrollBar().setValue)
        ov.verticalScrollBar().valueChanged.connect(table.verticalScrollBar().setValue)
        table.horizontalHeader().sectionResized.connect(self._on_section_resized)
        table.horizontalHeader().sectionMoved.connect(self._on_section_moved)
        table.installEventFilter(self)

    # ── Qt event filter (resize/show of the real table) ─────────────────────

    def eventFilter(self, obj, event):
        if obj is self._table and event.type() in (QEvent.Type.Resize, QEvent.Type.Show):
            self._update_geometry()
        return False

    def _on_section_resized(self, logical: int, old_size: int, new_size: int):
        if logical in self._frozen_cols:
            self._update_geometry()

    def _on_section_moved(self, logical: int, old_visual: int, new_visual: int):
        """Undo any drag (of a frozen column, or of another column across
        one) that would break the "frozen columns occupy visual 0..N-1, in
        order" invariant — without re-entering this slot for the corrective
        move itself."""
        if self._guarding or not self._frozen_cols:
            return
        hdr = self._table.horizontalHeader()
        current = [hdr.logicalIndex(v) for v in range(len(self._frozen_cols))]
        if current != self._frozen_cols:
            self._pin_order()
            self._update_geometry()

    # ── configure ────────────────────────────────────────────────────────────

    def configure(self, headers: list, frozen_headers: list, style_sheet: str = ""):
        """*headers*: this table's full current header-text list (same
        order as its logical column indices). *frozen_headers*: the subset
        (and left-to-right order) to pin — [] / None to unfreeze."""
        cols = [headers.index(h) for h in (frozen_headers or []) if h in headers]
        self._frozen_cols = cols
        if not cols:
            self._overlay.hide()
            return
        for c in range(self._table.model().columnCount()):
            self._overlay.setColumnHidden(c, c not in cols)
        if style_sheet:
            self._overlay.setStyleSheet(style_sheet)
        self._pin_order()
        self._update_geometry()
        # Re-assert one event-loop turn later too, in case anything here
        # (setStyleSheet's repolish, column auto-sizing) settles its final
        # layout asynchronously rather than within this call — same
        # belt-and-suspenders live_viewer's own _configure_frozen_column uses.
        QTimer.singleShot(0, self._update_geometry)

    def _pin_order(self):
        hdr = self._table.horizontalHeader()
        self._guarding = True
        try:
            for target_visual, logical in enumerate(self._frozen_cols):
                visual = hdr.visualIndex(logical)
                if visual != target_visual:
                    hdr.moveSection(visual, target_visual)
        finally:
            self._guarding = False

    def _update_geometry(self):
        if not self._frozen_cols or any(self._table.isColumnHidden(c) for c in self._frozen_cols):
            self._overlay.hide()
            return
        hdr = self._table.horizontalHeader()
        vh = self._table.verticalHeader()
        vh_width = vh.width() if vh.isVisible() else 0
        x = vh_width + self._table.frameWidth()
        y = self._table.frameWidth()
        width = 0
        for c in self._frozen_cols:
            w = self._table.columnWidth(c)
            self._overlay.setColumnWidth(c, w)
            width += w
        height = self._table.viewport().height() + hdr.height()
        self._overlay.setGeometry(x, y, width, height)
        self._overlay.verticalScrollBar().setValue(self._table.verticalScrollBar().value())
        self._overlay.show()
        self._overlay.raise_()
