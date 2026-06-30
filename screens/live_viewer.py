import font_scale
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFrame,
    QLineEdit, QScrollArea, QCheckBox, QSizePolicy, QComboBox
)
from PySide6.QtCore import (
    Qt, QTimer, QFileSystemWatcher, Signal, QObject, QThread
)
from PySide6.QtGui import QColor, QBrush


_DEBOUNCE_MS   = 300    # ms to wait after file event before re-reading
_COM_POLL_MS   = 200    # active COM polling interval — near-real-time live sync
_COM_IDLE_MS   = 1000   # relaxed interval after a quiet spell (adaptive backoff)
_IDLE_TICKS    = 15     # consecutive no-change ticks before backing off (~3s)
_HIGHLIGHT_MS  = 4000   # how long a changed cell stays amber
_SWEEP_MS      = 500    # how often expired highlights are cleared
_FILE_SETTLE_S = 0.2    # brief wait so disk writes finish before re-reading


# ── Off-thread reader worker ────────────────────────────────────────────────

class _LiveDataWorker(QObject):
    """
    Runs the read+merge on a worker thread so a slow COM/disk read never
    freezes the UI.  Owns a :class:`services.live_merge.LiveDataReader`; the
    reader's COM handles are created and used entirely on this thread.
    """

    result = Signal(list, list)   # headers, data
    failed = Signal(str)          # error message

    def __init__(self, reader):
        super().__init__()
        self._reader  = reader
        self._started = False

    def do_read(self, force_slow: bool, settle_s: float) -> None:
        if not self._started:
            try:
                self._reader.start()
            except Exception:
                pass
            self._started = True
        # Settle delay runs here on the worker thread, never blocking the UI.
        if settle_s > 0:
            time.sleep(settle_s)
        try:
            headers, data = self._reader.read_merged(force_slow=force_slow)
        except Exception as exc:
            self.failed.emit(str(exc)[:120])
            return
        self.result.emit(headers, data)

    def shutdown(self) -> None:
        if self._started:
            try:
                self._reader.stop()
            except Exception:
                pass
            self._started = False


# ── Strategy selector popup ────────────────────────────────────────────────

class StrategyPickerPopup(QWidget):
    """Floating popup to enable/disable individual strategies on the LMV."""

    applied = Signal(list)   # emits updated strategy list

    def __init__(self, strategies: list, theme=None, parent=None):
        super().__init__(parent,
                         Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._strategies = [dict(s) for s in strategies]
        self._theme      = theme
        self._checks: list[QCheckBox] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg        = t.get("card_bg")        if t else "#1c2128"
        win_bg    = t.get("background")    if t else "#0d1117"
        bd        = t.get("border")        if t else "#30363d"
        txt       = t.get("text_primary")  if t else "#e6edf3"
        txts      = t.get("text_secondary")if t else "#8b949e"
        accent    = t.get("accent")        if t else "#39d353"
        inp_bg    = t.get("input_bg")      if t else "#0d1117"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(260)
        card.setStyleSheet(
            f"QFrame{{background:{bg};border:1px solid {bd};border-radius:10px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(14, 14, 14, 14)
        lay.setSpacing(10)

        # Title
        hdr_row = QHBoxLayout()
        title = QLabel("Strategies")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color:{txt};border:none;")
        hdr_row.addWidget(title)
        hdr_row.addStretch()
        lay.addLayout(hdr_row)

        if not self._strategies:
            empty = QLabel("No strategies defined yet.\nGo to Strategy Builder.")
            empty.setFont(font_scale.font(font_scale.SMALL, False))
            empty.setStyleSheet(f"color:{txts};border:none;")
            empty.setWordWrap(True)
            lay.addWidget(empty)
        else:
            # Checkbox per strategy
            for strat in self._strategies:
                cb = QCheckBox(strat.get("name", "Unnamed"))
                cb.setChecked(strat.get("active", True))
                cb.setFont(font_scale.font(font_scale.SMALL, False))
                cb.setFixedHeight(30)
                cb.setStyleSheet(
                    f"QCheckBox{{color:{txt};background:transparent;border:none;"
                    "padding:0 4px;border-radius:4px;spacing:8px;}"
                    f"QCheckBox:hover{{background:{accent}12;}}"
                    f"QCheckBox::indicator{{width:16px;height:16px;border-radius:4px;"
                    f"border:1.5px solid {bd};background:{inp_bg};}}"
                    f"QCheckBox::indicator:checked{{background:{accent};"
                    f"border-color:{accent};}}"
                )
                self._checks.append(cb)
                lay.addWidget(cb)

        # Divider
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background:{bd};border:none;")
        lay.addWidget(div)

        # Apply button
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(32)
        apply_btn.setFont(font_scale.font(font_scale.SMALL, True))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton{{background:{accent};color:{win_bg};"
            "border:none;border-radius:6px;}}"
            f"QPushButton:hover{{background:{accent}dd;}}"
        )
        apply_btn.clicked.connect(self._apply)
        lay.addWidget(apply_btn)

        outer.addWidget(card)

    def _apply(self):
        for i, cb in enumerate(self._checks):
            if i < len(self._strategies):
                self._strategies[i]["active"] = cb.isChecked()
        self.applied.emit(self._strategies)
        self.close()


class ColumnFilterPopup(QWidget):
    """Floating popup for toggling column visibility in the Live Master View."""

    columns_changed = Signal(set)   # emits set of visible column indices

    def __init__(self, headers: list, visible: set, theme=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._headers  = headers
        self._visible  = set(visible)
        self._theme    = theme
        self._checks: list[QCheckBox] = []
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg     = t.get("card_bg")        if t else "#1c2128"
        win_bg = t.get("background")    if t else "#0d1117"
        border = t.get("border")        if t else "#30363d"
        txt    = t.get("text_primary")  if t else "#e6edf3"
        txt_s  = t.get("text_secondary")if t else "#8b949e"
        accent = t.get("accent")        if t else "#39d353"
        inp_bg = t.get("input_bg")      if t else "#0d1117"

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(280)
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border};"
            "border-radius: 10px; }}"
        )
        card_layout = QVBoxLayout(card)
        card_layout.setContentsMargins(14, 14, 14, 14)
        card_layout.setSpacing(10)

        # ── Header ──────────────────────────────────────────────────────────
        hdr_row = QHBoxLayout()
        title = QLabel("Columns")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color: {txt}; border: none;")

        self._sel_lbl = QLabel()
        self._sel_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._sel_lbl.setStyleSheet(f"color: {txt_s}; border: none;")

        hdr_row.addWidget(title)
        hdr_row.addStretch()
        hdr_row.addWidget(self._sel_lbl)
        card_layout.addLayout(hdr_row)

        # ── Search box ──────────────────────────────────────────────────────
        self._search = QLineEdit()
        self._search.setPlaceholderText("Search columns…")
        self._search.setFixedHeight(34)
        self._search.setFont(font_scale.font(font_scale.SMALL, False))
        self._search.setStyleSheet(
            f"QLineEdit {{ background: {inp_bg}; color: {txt};"
            f"border: 1px solid {border}; border-radius: 6px; padding: 0 10px; }}"
        )
        self._search.textChanged.connect(self._filter)
        card_layout.addWidget(self._search)

        # ── Select all / none ───────────────────────────────────────────────
        action_row = QHBoxLayout()
        for label, slot in [("Select All", self._select_all), ("Clear All", self._clear_all)]:
            btn = QPushButton(label)
            btn.setFixedHeight(26)
            btn.setFont(font_scale.font(font_scale.SMALL, False))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {accent};"
                f"border: 1px solid {accent}22; border-radius: 4px; padding: 0 10px; }}"
                f"QPushButton:hover {{ background: {accent}18; }}"
            )
            btn.clicked.connect(slot)
            action_row.addWidget(btn)
        action_row.addStretch()
        card_layout.addLayout(action_row)

        # ── Divider ─────────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {border}; border: none;")
        card_layout.addWidget(div)

        # ── Scrollable checkbox list ─────────────────────────────────────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setFixedHeight(min(len(self._headers) * 36 + 8, 320))
        scroll.setStyleSheet("background: transparent; border: none;")
        scroll.verticalScrollBar().setStyleSheet(
            f"QScrollBar:vertical {{ width: 4px; background: transparent; }}"
            f"QScrollBar::handle:vertical {{ background: {border}; border-radius: 2px; }}"
            f"QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}"
        )

        list_widget = QWidget()
        list_widget.setStyleSheet("background: transparent;")
        list_layout = QVBoxLayout(list_widget)
        list_layout.setContentsMargins(0, 4, 0, 4)
        list_layout.setSpacing(2)

        for i, header in enumerate(self._headers):
            cb = QCheckBox(header)
            cb.setChecked(i in self._visible)
            cb.setFont(font_scale.font(font_scale.SMALL, False))
            cb.setFixedHeight(32)
            cb.setStyleSheet(
                f"QCheckBox {{ color: {txt}; background: transparent; border: none;"
                "padding: 0 4px; border-radius: 4px; spacing: 8px; }"
                f"QCheckBox:hover {{ background: {accent}12; }}"
                f"QCheckBox::indicator {{ width: 16px; height: 16px; border-radius: 4px;"
                f"border: 1.5px solid {border}; background: {inp_bg}; }}"
                f"QCheckBox::indicator:checked {{ background: {accent}; border-color: {accent};"
                "image: none; }}"
            )
            cb.stateChanged.connect(self._on_state_changed)
            list_layout.addWidget(cb)
            self._checks.append(cb)

        list_layout.addStretch()
        scroll.setWidget(list_widget)
        card_layout.addWidget(scroll)

        # ── Apply button ────────────────────────────────────────────────────
        apply_btn = QPushButton("Apply")
        apply_btn.setFixedHeight(34)
        apply_btn.setFont(font_scale.font(font_scale.SMALL, True))
        apply_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        apply_btn.setStyleSheet(
            f"QPushButton {{ background: {accent}; color: {win_bg};"
            "border: none; border-radius: 6px; }}"
            f"QPushButton:hover {{ background: {accent}dd; }}"
        )
        apply_btn.clicked.connect(self._apply)
        card_layout.addWidget(apply_btn)

        outer.addWidget(card)
        self._update_sel_label()

    def _filter(self, text: str):
        q = text.strip().lower()
        for cb in self._checks:
            cb.setVisible(not q or q in cb.text().lower())

    def _on_state_changed(self):
        self._update_sel_label()

    def _select_all(self):
        for cb in self._checks:
            if cb.isVisible():
                cb.setChecked(True)

    def _clear_all(self):
        for cb in self._checks:
            if cb.isVisible():
                cb.setChecked(False)

    def _update_sel_label(self):
        checked = sum(1 for cb in self._checks if cb.isChecked())
        total   = len(self._checks)
        self._sel_lbl.setText(f"{checked}/{total}")

    def _apply(self):
        visible = {i for i, cb in enumerate(self._checks) if cb.isChecked()}
        self.columns_changed.emit(visible)
        self.close()


class FilterPanelPopup(QWidget):
    """Unified floating filter panel — columns, category, and sector in one place."""

    columns_requested = Signal()
    category_changed  = Signal(str)
    sector_changed    = Signal(str)
    cleared           = Signal()

    def __init__(self, current_category: str, current_sector: str,
                 sectors: list, col_visible: int, col_total: int,
                 theme=None, parent=None):
        super().__init__(parent, Qt.WindowType.Popup | Qt.WindowType.FramelessWindowHint)
        self._current_category = current_category
        self._current_sector   = current_sector
        self._sectors          = sectors
        self._col_visible      = col_visible
        self._col_total        = col_total
        self._theme            = theme
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._build()

    def _build(self):
        t      = self._theme
        bg     = t.get("card_bg")        if t else "#1c2128"
        border = t.get("border")         if t else "#30363d"
        txt    = t.get("text_primary")   if t else "#e6edf3"
        txt_s  = t.get("text_secondary") if t else "#8b949e"
        accent = t.get("accent")         if t else "#39d353"
        inp_bg = t.get("input_bg")       if t else "#0d1117"
        red    = t.get("status_red")     if t else "#f85149"

        any_active = (self._current_category != "All"
                      or self._current_sector != "All"
                      or self._col_visible < self._col_total)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)

        card = QFrame()
        card.setFixedWidth(300)
        card.setStyleSheet(
            f"QFrame {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 14, 16, 14)
        lay.setSpacing(8)

        # ── Header ───────────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        title = QLabel("Filters")
        title.setFont(font_scale.font(font_scale.MEDIUM, True))
        title.setStyleSheet(f"color: {txt}; border: none;")
        hdr.addWidget(title)
        hdr.addStretch()
        if any_active:
            clear_btn = QPushButton("Clear all")
            clear_btn.setFixedHeight(24)
            clear_btn.setFont(font_scale.font(font_scale.SMALL, False))
            clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            clear_btn.setStyleSheet(
                f"QPushButton {{ background: transparent; color: {txt_s};"
                f"border: 1px solid {border}; border-radius: 4px; padding: 0 8px; }}"
                f"QPushButton:hover {{ color: {red}; border-color: {red}; }}"
            )
            clear_btn.clicked.connect(self._on_clear)
            hdr.addWidget(clear_btn)
        lay.addLayout(hdr)

        # ── Divider ───────────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {border}; border: none;")
        lay.addWidget(div)

        combo_ss = (
            f"QComboBox {{ background: {inp_bg}; color: {txt};"
            f"border: 1px solid {border}; border-radius: 6px; padding: 0 10px; }}"
            f"QComboBox:hover {{ border-color: {accent}; }}"
            f"QComboBox::drop-down {{ border: none; width: 24px; }}"
        )

        def _row(label_text, widget):
            row = QHBoxLayout()
            row.setSpacing(12)
            lbl = QLabel(label_text)
            lbl.setFixedWidth(72)
            lbl.setFont(font_scale.font(font_scale.SMALL, False))
            lbl.setStyleSheet(f"color: {txt_s}; border: none;")
            row.addWidget(lbl)
            row.addWidget(widget, 1)
            return row

        # ── Columns row ───────────────────────────────────────────────────────
        col_label = ("All visible" if self._col_visible == self._col_total
                     else f"{self._col_visible} / {self._col_total} visible")
        col_btn = QPushButton(f"⊞  {col_label}")
        col_btn.setFixedHeight(32)
        col_btn.setFont(font_scale.font(font_scale.SMALL, False))
        col_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        col_color = accent if self._col_visible < self._col_total else txt
        col_btn.setStyleSheet(
            f"QPushButton {{ background: {inp_bg}; color: {col_color};"
            f"border: 1px solid {border}; border-radius: 6px; padding: 0 10px; text-align: left; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        col_btn.clicked.connect(self._on_columns_clicked)
        lay.addLayout(_row("Columns", col_btn))

        # ── Category row ──────────────────────────────────────────────────────
        cat_combo = QComboBox()
        cat_combo.addItems(["All", "Daily", "Weekly", "Monthly"])
        cat_combo.setCurrentText(self._current_category)
        cat_combo.setFixedHeight(32)
        cat_combo.setFont(font_scale.font(font_scale.SMALL, False))
        cat_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        cat_combo.setStyleSheet(combo_ss)
        cat_combo.currentTextChanged.connect(self.category_changed)
        lay.addLayout(_row("Category", cat_combo))

        # ── Sector row ────────────────────────────────────────────────────────
        sec_combo = QComboBox()
        sec_combo.addItem("All")
        for s in self._sectors:
            sec_combo.addItem(s)
        sec_combo.setCurrentText(self._current_sector)
        sec_combo.setFixedHeight(32)
        sec_combo.setFont(font_scale.font(font_scale.SMALL, False))
        sec_combo.setCursor(Qt.CursorShape.PointingHandCursor)
        sec_combo.setStyleSheet(combo_ss)
        sec_combo.currentTextChanged.connect(self.sector_changed)
        lay.addLayout(_row("Sector", sec_combo))

        outer.addWidget(card)

    def _on_columns_clicked(self):
        self.close()
        self.columns_requested.emit()

    def _on_clear(self):
        self.cleared.emit()
        self.close()


class LiveViewerWindow(QWidget):
    """
    Standalone window showing the merged master table in real-time.

    Two update drivers:
      * QFileSystemWatcher (OS-level events) for disk-based broker exports.
      * On Windows, a fast COM poll for the in-memory DDE values Sharekhan
        never flushes to disk (the only driver for its live prices).

    Reads/merges run on a worker thread so a slow read never freezes the UI.
    Changed cells are highlighted amber for ~4 seconds.
    """

    # Emitted from the GUI thread to drive work on the worker thread.
    _request_read     = Signal(bool, float)   # force_slow, settle_seconds
    _request_shutdown = Signal()              # release COM on the worker thread
    data_updated      = Signal(list, list)    # headers, data — for downstream consumers

    def __init__(self, sharekhan_path: str, reliable_path: str,
                 nifty_path: str, script_name_data: list,
                 expiry_date=None, external_path=None,
                 market_profile_path=None,
                 theme=None, controller=None, parent=None):
        super().__init__(parent)
        self._sharekhan_path   = sharekhan_path
        self._reliable_path    = reliable_path
        self._nifty_path       = nifty_path
        self._external_path    = external_path
        self._market_profile_path = market_profile_path
        self._script_name_data = script_name_data
        self._expiry_date      = expiry_date
        self._theme            = theme
        self._controller       = controller

        self._headers: list      = []
        self._data: list[list]   = []
        self._row_key_index: int = 0
        self._dot_state          = True
        self._visible_cols: set  = set()   # populated after first load
        self._strategies: list   = []      # injected by DataImportScreen
        self._selected_category: str = "All"

        # Build sector lookup from config defaults once at init
        from config_defaults import SECTOR_STOCK_DATA
        self._sector_map: dict = {stock: sector for sector, stock in SECTOR_STOCK_DATA}

        # Live-update bookkeeping
        self._render_sig         = None    # signature of last full rebuild
        self._sized_cols         = set()   # columns already auto-sized once
        self._prev_disp: list[list] = []   # last displayed values (for diffing)
        self._highlights: dict   = {}      # (r, c) → expiry tick count
        self._idle_count         = 0       # consecutive no-change ticks
        self._worker             = None
        self._worker_thread      = None

        self.setWindowTitle("Live Master View")
        self.resize(1300, 700)
        self._build()
        self._setup_watcher()
        self._load_initial()

    # ── Build UI ──────────────────────────────────────────────────────────────

    def _build(self):
        t      = self._theme
        accent = t.get("accent")        if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        red    = t.get("status_red")    if t else "#f85149"
        divclr = t.get("divider")       if t else "#30363d"

        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        # ── Top bar ───────────────────────────────────────────────────────────
        top = QHBoxLayout()

        title = QLabel("Live Master View")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        top.addWidget(title)
        top.addStretch()

        self._dot = QLabel("●")
        self._dot.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._dot.setStyleSheet(f"color: {accent};")

        self._status_lbl = QLabel("Watching for changes…")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {text_s};")

        # Hidden combos — keep as instance attrs so existing logic / tests can
        # read their current selection without touching the toolbar layout.
        self._cat_combo = QComboBox(self)
        self._cat_combo.addItems(["All", "Daily", "Weekly", "Monthly"])
        self._cat_combo.setCurrentText("All")
        self._cat_combo.hide()
        self._cat_combo.currentTextChanged.connect(self._on_category_changed)

        self._sector_combo = QComboBox(self)
        self._sector_combo.addItem("All")
        for s in sorted(set(self._sector_map.values())):
            self._sector_combo.addItem(s)
        self._sector_combo.setCurrentText("All")
        self._sector_combo.hide()
        self._sector_combo.currentTextChanged.connect(self._apply_sector_filter)

        self._filter_btn = QPushButton("⊞  Filters")
        self._filter_btn.setFixedHeight(30)
        self._filter_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._filter_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._filter_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._filter_btn.clicked.connect(self._show_filter_panel)

        self._strat_btn = QPushButton("⚡  Strategies")
        self._strat_btn.setFixedHeight(30)
        self._strat_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._strat_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._strat_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._strat_btn.clicked.connect(self._show_strategy_picker)

        self._export_btn = QPushButton("⭳  Export")
        self._export_btn.setFixedHeight(30)
        self._export_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._export_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._export_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._export_btn.clicked.connect(self._export)

        stop_btn = QPushButton("Stop")
        stop_btn.setFixedHeight(30)
        stop_btn.setFont(font_scale.font(font_scale.SMALL, False))
        stop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        stop_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {red};"
            f"border: 1px solid {red}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ background: {red}; color: #ffffff; }}"
        )
        stop_btn.clicked.connect(self._stop)

        top.addWidget(self._dot)
        top.addSpacing(4)
        top.addWidget(self._status_lbl)
        top.addSpacing(12)
        top.addWidget(self._filter_btn)
        top.addSpacing(8)
        top.addWidget(self._strat_btn)
        top.addSpacing(8)
        top.addWidget(self._export_btn)
        top.addSpacing(8)
        top.addWidget(stop_btn)
        root.addLayout(top)

        # ── Divider ───────────────────────────────────────────────────────────
        div = QFrame()
        div.setFixedHeight(1)
        div.setStyleSheet(f"background: {divclr};")
        root.addWidget(div)

        # ── Table ─────────────────────────────────────────────────────────────
        self._table = QTableWidget()
        self._table.setFont(font_scale.font(font_scale.SMALL, False))
        self._table.verticalHeader().setVisible(False)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setAlternatingRowColors(False)
        self._table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._table.horizontalHeader().setStretchLastSection(True)
        self._table.setShowGrid(True)
        root.addWidget(self._table, 1)

        # ── Pulse timer ───────────────────────────────────────────────────────
        self._pulse_timer = QTimer(self)
        self._pulse_timer.setInterval(800)
        self._pulse_timer.timeout.connect(self._pulse)
        self._pulse_timer.start()

    # ── File watching / COM polling ───────────────────────────────────────────

    def _setup_watcher(self):
        from services.com_reader import is_available as com_available
        from services.live_merge import LiveDataReader

        self._use_com    = com_available()
        self._refreshing = False   # re-entrancy guard so fast ticks don't pile up

        # Stateful reader: caches COM handles + slow sources (Reliable/Nifty).
        # Shared by the synchronous initial load and the worker thread; only
        # one of them touches it at a time (initial load completes before the
        # worker thread starts polling).
        self._reader = LiveDataReader(
            self._sharekhan_path, self._reliable_path, self._nifty_path,
            self._script_name_data, expiry_date=self._expiry_date,
            use_com=self._use_com, external_path=self._external_path,
            market_profile_path=self._market_profile_path,
        )

        # Worker thread: all polled reads/merges run here so a slow read never
        # blocks the UI.  Requests go out via _request_read; results come back
        # via queued signals (thread-safe).
        self._worker_thread = QThread(self)
        self._worker        = _LiveDataWorker(self._reader)
        self._worker.moveToThread(self._worker_thread)
        self._request_read.connect(self._worker.do_read)
        self._request_shutdown.connect(self._worker.shutdown)
        self._worker.result.connect(self._on_data_ready)
        self._worker.failed.connect(self._on_read_failed)
        self._worker_thread.start()

        # Safety net for teardown that bypasses closeEvent (e.g. the widget is
        # garbage-collected directly).  Qt emits destroyed() before deleting
        # child objects, so the thread is still alive here and can be stopped.
        # Capture the thread only — never self, which is mid-destruction.
        _t = self._worker_thread
        self.destroyed.connect(lambda: (_t.quit(), _t.wait(2000)))

        # Always watch the Sharekhan file on disk — covers saves from any broker software.
        self._fs_watcher = QFileSystemWatcher(self)
        self._fs_watcher.addPath(self._sharekhan_path)
        self._fs_watcher.fileChanged.connect(self._on_file_changed)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(_DEBOUNCE_MS)
        # Disk path: data may still be mid-write, so let it settle first.
        self._debounce.timeout.connect(self._refresh_from_disk)

        if self._use_com:
            # Windows + pywin32: poll COM for the in-memory DDE values (Sharekhan
            # live prices + TradeTiger Snap) that are never flushed to disk.  This
            # is the only driver for Sharekhan's live updates, so it polls fast.
            # COM reads Excel's in-memory state, which is always consistent — no
            # settle delay needed, keeping the LMV in lock-step with the sheet.
            self._com_timer = QTimer(self)
            self._com_timer.setInterval(_COM_POLL_MS)
            self._com_timer.timeout.connect(self._refresh_live)
            self._com_timer.start()

        # Highlight sweep: revert expired amber cells back to normal.
        self._sweep_timer = QTimer(self)
        self._sweep_timer.setInterval(_SWEEP_MS)
        self._sweep_timer.timeout.connect(self._sweep_highlights)
        self._sweep_timer.start()

    def _on_file_changed(self, path: str):
        # Re-add watch if the app briefly removed the file on save
        if path not in self._fs_watcher.files():
            if os.path.exists(path):
                self._fs_watcher.addPath(path)
        self._debounce.start()

    # ── Data ─────────────────────────────────────────────────────────────────

    def _load_initial(self):
        # Synchronous first read so callers (DataImportScreen) can read
        # _headers immediately after construction.  Runs on the GUI thread,
        # so it does NOT start COM here — COM is initialised and used solely on
        # the worker thread (COM apartment affinity).  This first read therefore
        # uses the disk fallback; the worker's COM reads take over thereafter.
        try:
            headers, data = self._reader.read_merged(force_slow=True)
        except Exception as exc:
            self._status_lbl.setText(f"Error loading: {exc}")
            return
        headers, data = self._inject_sector(headers, data)
        self._headers = headers
        self._data    = data
        # All columns visible by default
        self._visible_cols = set(range(len(headers)))
        self._populate_table(data, changed_keys=set())
        self._apply_sector_filter()
        self._update_filter_btn_label()

    def _inject_sector(self, headers: list, data: list) -> tuple:
        """Prepend a Sector column to headers and every data row."""
        scrip_idx = headers.index("Scrip Name") if "Scrip Name" in headers else -1
        new_headers = ["Sector"] + list(headers)
        new_data = []
        for row in data:
            scrip = row[scrip_idx] if scrip_idx >= 0 and scrip_idx < len(row) else ""
            sector = self._sector_map.get(str(scrip).strip().upper(), "—")
            new_data.append([sector] + list(row))
        return new_headers, new_data

    def _refresh_from_disk(self):
        # Disk-based saves (e.g. Sharekhan export on macOS) may still be
        # flushing — let the worker settle briefly before reading.
        self._request_refresh(settle=_FILE_SETTLE_S)

    def _refresh_live(self):
        # COM reads Excel's in-memory state, which is always consistent — no
        # settle delay, keeping the LMV in lock-step with the sheet.
        self._request_refresh(settle=0.0)

    def _request_refresh(self, settle: float):
        # Skip if a previous read is still in flight, so fast ticks collapse
        # instead of queueing up and lagging behind.
        if self._refreshing or self._worker is None:
            return
        self._refreshing = True
        self._request_read.emit(False, settle)

    def _on_read_failed(self, msg: str):
        self._refreshing = False
        self._status_lbl.setText(f"Read error: {msg}")

    def _on_data_ready(self, headers: list, new_data: list):
        from datetime import datetime
        try:
            headers, new_data = self._inject_sector(headers, new_data)
            self._data    = new_data
            self._headers = headers
            self._populate_table(new_data, changed_keys=None)  # diff internally
            self._apply_sector_filter()
            self._status_lbl.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")
            self._adapt_poll_rate(getattr(self, "_last_change_count", 0))
            self.data_updated.emit(self._headers, self._data)
        finally:
            self._refreshing = False

    def _adapt_poll_rate(self, changed: int):
        """
        Back off the COM poll when the data is quiet, and snap back to the fast
        rate the instant something changes.  Reduces idle COM load (e.g. when
        the market is closed) without ever adding lag to live ticks.
        """
        if not hasattr(self, "_com_timer"):
            return
        if changed > 0:
            self._idle_count = 0
            if self._com_timer.interval() != _COM_POLL_MS:
                self._com_timer.setInterval(_COM_POLL_MS)
        else:
            self._idle_count += 1
            if (self._idle_count >= _IDLE_TICKS
                    and self._com_timer.interval() != _COM_IDLE_MS):
                self._com_timer.setInterval(_COM_IDLE_MS)


    # ── Table rendering ───────────────────────────────────────────────────────

    @staticmethod
    def _fmt_cell(val) -> str:
        if isinstance(val, float):
            return f"{val:.2f}"
        if val is None:
            return ""
        return str(val)

    def _populate_table(self, data: list[list], changed_keys=set()):
        """
        Render *data* into the table.

        ``changed_keys=None`` marks a live-data tick: cells whose displayed
        value changed are diffed against the table's current contents and
        flashed amber.  A real set (incl. the empty set) marks a structural
        re-render (theme/strategy/category change) where no highlight is wanted.
        """
        from services.strategy_engine import apply_strategies, get_cell_color

        highlight = changed_keys is None
        self._last_change_count = 0

        # Apply active strategies — may extend headers and data
        active_strategies = [s for s in self._filtered_strategies() if s.get("active")]
        if active_strategies:
            disp_headers, disp_data = apply_strategies(
                active_strategies, self._headers, data
            )
        else:
            disp_headers, disp_data = self._headers, data

        base_col_count = len(self._headers)

        # Read theme at render time so light/dark toggle is always current
        t = self._theme
        norm_bg  = QColor(t.get("card_bg")      if t else "#1c2128")
        norm_txt = QColor(t.get("text_primary")  if t else "#e6edf3")
        win_bg   = t.get("background")           if t else "#0d1117"
        hdr_bg   = t.get("button_bg")            if t else "#21262d"
        strat_hdr = t.get("accent") + "22"       if t else "#39d35322"
        # theme.get() raises KeyError on a missing token, so fall back rather
        # than assume the key exists (covers older/partial palettes).
        try:
            amber = t.get("status_amber") if t else "#d29922"
        except KeyError:
            amber = "#d29922"
        self._amber_bg  = QBrush(QColor(amber))
        self._amber_txt = QBrush(QColor("#000000"))

        # Build per-column info for strategy columns (for conditional formatting)
        strat_col_defs = []   # list of col_def dicts for strategy cols in order
        for s in active_strategies:
            for col in s.get("columns", []):
                strat_col_defs.append(col)

        all_dicts = [dict(zip(disp_headers, row)) for row in disp_data]

        # ── Fast path ───────────────────────────────────────────────────────
        # When only cell values changed (same headers, same row count, same
        # theme) — the common live-tick case — update existing items in place.
        # This skips item recreation, header relabelling, stylesheet resets and
        # the costly resizeColumnsToContents(), keeping the LMV in lock-step
        # with the source sheet.
        sig = (tuple(disp_headers), len(disp_data),
               id(t), norm_bg.name(), norm_txt.name())
        fast = (
            getattr(self, "_render_sig", None) == sig
            and self._table.rowCount() == len(disp_data)
            and self._table.columnCount() == len(disp_headers)
        )
        if fast:
            self._update_cells_in_place(
                disp_data, all_dicts, strat_col_defs,
                base_col_count, norm_bg, norm_txt, strat_hdr, get_cell_color,
                highlight,
            )
            self._update_strat_btn_label()
            return

        # ── Full rebuild ────────────────────────────────────────────────────
        # Items are recreated, so any pending highlights no longer map to live
        # items — drop them.
        self._highlights.clear()

        self.setStyleSheet(f"background: {win_bg};")
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {norm_bg.name()}; color: {norm_txt.name()}; }}"
            f"QTableWidget QHeaderView::section {{ background: {hdr_bg}; color: {norm_txt.name()}; }}"
        )

        self._table.setColumnCount(len(disp_headers))
        self._table.setHorizontalHeaderLabels(disp_headers)
        self._table.setRowCount(len(disp_data))

        bold_font   = font_scale.font(font_scale.SMALL, True)
        scrip_col   = disp_headers.index("Scrip Name") if "Scrip Name" in disp_headers else -1
        for r, row in enumerate(disp_data):
            row_dict = all_dicts[r]
            for c, val in enumerate(row):
                item = QTableWidgetItem(self._fmt_cell(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                if c == scrip_col:
                    item.setFont(bold_font)
                self._apply_cell_style(
                    item, c, val, row_dict, all_dicts, strat_col_defs,
                    base_col_count, norm_bg, norm_txt, strat_hdr, get_cell_color,
                )
                self._table.setItem(r, c, item)

        # Ensure visible_cols covers strategy columns too
        if len(disp_headers) > len(self._headers):
            for c in range(len(self._headers), len(disp_headers)):
                self._visible_cols.add(c)

        # Apply column visibility
        for c in range(len(disp_headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)

        # Auto-size columns only the first time we see this header layout, so
        # user-adjusted widths survive theme/strategy/category re-renders.
        if getattr(self, "_sized_headers", None) != tuple(disp_headers):
            self._table.resizeColumnsToContents()
            self._sized_headers = tuple(disp_headers)

        self._render_sig = sig
        self._update_strat_btn_label()

    def _apply_cell_style(self, item, c, val, row_dict, all_dicts,
                          strat_col_defs, base_col_count,
                          norm_bg, norm_txt, strat_hdr, get_cell_color):
        """Set foreground/background for one cell, incl. strategy formatting."""
        item.setForeground(QBrush(norm_txt))
        item.setBackground(QBrush(norm_bg))
        strat_idx = c - base_col_count
        if 0 <= strat_idx < len(strat_col_defs):
            col_def = strat_col_defs[strat_idx]
            cell_color = get_cell_color(col_def, val, row_dict, all_dicts)
            if cell_color:
                item.setBackground(QBrush(QColor(cell_color)))
                qc = QColor(cell_color)
                lum = 0.299 * qc.red() + 0.587 * qc.green() + 0.114 * qc.blue()
                item.setForeground(QBrush(QColor("#000000" if lum > 128 else "#ffffff")))
            else:
                item.setBackground(QBrush(QColor(strat_hdr)))

    def _update_cells_in_place(self, disp_data, all_dicts,
                               strat_col_defs, base_col_count,
                               norm_bg, norm_txt, strat_hdr, get_cell_color,
                               highlight):
        """
        Update existing QTableWidgetItems in place (no recreation).

        When *highlight* is set, cells whose displayed value changed are
        flashed amber; the steady-state brushes are stashed so the sweep timer
        can restore them after the highlight window.
        """
        import time as _time
        now = _time.monotonic()
        changed = 0
        for r, row in enumerate(disp_data):
            row_dict = all_dicts[r]
            for c, val in enumerate(row):
                item = self._table.item(r, c)
                if item is None:
                    item = QTableWidgetItem()
                    item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                    self._table.setItem(r, c, item)
                    old_text = None
                else:
                    old_text = item.text()
                new_text = self._fmt_cell(val)
                item.setText(new_text)

                # Recompute the steady-state ("base") style every tick so the
                # restored colour reflects current strategy formatting.
                self._apply_cell_style(
                    item, c, val, row_dict, all_dicts, strat_col_defs,
                    base_col_count, norm_bg, norm_txt, strat_hdr, get_cell_color,
                )

                if not highlight:
                    continue

                key = (r, c)
                cell_changed = old_text is not None and new_text != old_text
                if cell_changed:
                    changed += 1
                    self._highlights[key] = (
                        now + _HIGHLIGHT_MS / 1000.0,
                        item.background(), item.foreground(),
                    )
                    item.setBackground(self._amber_bg)
                    item.setForeground(self._amber_txt)
                elif key in self._highlights:
                    # Still within the highlight window: keep amber, but refresh
                    # the stashed base brushes to the latest computed values.
                    exp, _, _ = self._highlights[key]
                    self._highlights[key] = (exp, item.background(), item.foreground())
                    item.setBackground(self._amber_bg)
                    item.setForeground(self._amber_txt)

        self._last_change_count = changed

    def _sweep_highlights(self):
        """Revert amber cells whose highlight window has expired."""
        if not self._highlights:
            return
        import time as _time
        now = _time.monotonic()
        expired = [k for k, (exp, _, _) in self._highlights.items() if now >= exp]
        for key in expired:
            _, base_bg, base_fg = self._highlights.pop(key)
            r, c = key
            item = self._table.item(r, c)
            if item is not None:
                item.setBackground(base_bg)
                item.setForeground(base_fg)

    # ── Strategy picker ───────────────────────────────────────────────────────

    def set_strategies(self, strategies: list):
        """Inject strategies from StrategyBuilderScreen."""
        self._strategies = [dict(s) for s in strategies]
        self._update_strat_btn_label()
        self._populate_table(self._data, set())
        self._apply_sector_filter()

    def _filtered_strategies(self) -> list:
        if self._selected_category == "All":
            return self._strategies
        return [s for s in self._strategies if s.get("category", "Daily") == self._selected_category]

    def _on_category_changed(self, text: str):
        self._selected_category = text
        self._update_strat_btn_label()
        self._visible_cols = set(range(len(self._headers)))
        self._populate_table(self._data, set())
        self._apply_sector_filter()
        self._update_filter_btn_label()

    def _show_strategy_picker(self):
        popup = StrategyPickerPopup(self._filtered_strategies(), self._theme, self)
        popup.applied.connect(self._on_strategies_applied)
        btn_pos = self._strat_btn.mapToGlobal(self._strat_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _on_strategies_applied(self, updated: list):
        # Merge updated strategies back by ID so strategies outside the current
        # category filter are not overwritten.
        updated_by_id = {s["id"]: s for s in updated}
        self._strategies = [updated_by_id.get(s["id"], s) for s in self._strategies]
        from services import strategy_store as store
        for s in updated:
            store.save_strategy(s)
        self._visible_cols = set(range(len(self._headers)))
        self._populate_table(self._data, set())
        self._apply_sector_filter()

    def _update_strat_btn_label(self):
        filtered = self._filtered_strategies()
        active = sum(1 for s in filtered if s.get("active"))
        total  = len(filtered)
        if total == 0:
            self._strat_btn.setText("⚡  Strategies")
        elif active == 0:
            self._strat_btn.setText("⚡  Strategies  off")
        else:
            self._strat_btn.setText(f"⚡  Strategies  {active}/{total}")

    # ── Filter panel ──────────────────────────────────────────────────────────

    def _show_filter_panel(self):
        sectors = sorted(set(self._sector_map.values()))
        col_total   = len(self._headers)
        col_visible = len(self._visible_cols)
        popup = FilterPanelPopup(
            current_category=self._cat_combo.currentText(),
            current_sector=self._sector_combo.currentText(),
            sectors=sectors,
            col_visible=col_visible,
            col_total=col_total,
            theme=self._theme,
            parent=self,
        )
        popup.columns_requested.connect(self._show_col_filter)
        popup.category_changed.connect(self._cat_combo.setCurrentText)
        popup.sector_changed.connect(self._sector_combo.setCurrentText)
        popup.cleared.connect(self._clear_all_filters)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _clear_all_filters(self):
        self._cat_combo.setCurrentText("All")
        self._sector_combo.setCurrentText("All")
        if self._headers:
            self._visible_cols = set(range(len(self._headers)))
            for c in range(len(self._headers)):
                self._table.setColumnHidden(c, False)
        self._update_filter_btn_label()

    def _show_col_filter(self):
        if not self._headers:
            return
        popup = ColumnFilterPopup(self._headers, self._visible_cols, self._theme, self)
        popup.columns_changed.connect(self._apply_col_filter)
        btn_pos = self._filter_btn.mapToGlobal(self._filter_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _apply_col_filter(self, visible: set):
        # Always keep Scrip Name visible regardless of user selection
        if "Scrip Name" in self._headers:
            visible.add(self._headers.index("Scrip Name"))
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        self._update_filter_btn_label()

    def _update_col_btn_label(self):
        self._update_filter_btn_label()

    def _update_filter_btn_label(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        text_s = t.get("text_secondary") if t else "#8b949e"
        divclr = t.get("divider")        if t else "#30363d"

        active = 0
        if self._cat_combo.currentText() != "All":
            active += 1
        if self._sector_combo.currentText() != "All":
            active += 1
        total   = len(self._headers)
        visible = len(self._visible_cols)
        if total > 0 and visible < total:
            active += 1

        if active:
            label = f"⊞  Filters · {active}"
            color = accent
            border = accent
        else:
            label = "⊞  Filters"
            color = text_s
            border = divclr

        self._filter_btn.setText(label)
        self._filter_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {color};"
            f"border: 1px solid {border}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )

    def _repopulate_sector_combo(self):
        """Rebuild sector combo items from the current sector map."""
        sectors = sorted(set(self._sector_map.values()))
        self._sector_combo.blockSignals(True)
        current = self._sector_combo.currentText()
        self._sector_combo.clear()
        self._sector_combo.addItem("All")
        for s in sectors:
            self._sector_combo.addItem(s)
        # Restore previous selection if still valid
        idx = self._sector_combo.findText(current)
        self._sector_combo.setCurrentIndex(idx if idx >= 0 else 0)
        self._sector_combo.blockSignals(False)

    def _visible_table_data(self) -> tuple:
        """
        Scrape the table for exactly what's on screen: visible columns and
        visible (non-filtered) rows, in display order. Returns (headers, rows).
        """
        cols = [c for c in range(self._table.columnCount())
                if not self._table.isColumnHidden(c)]
        headers = []
        for c in cols:
            hdr = self._table.horizontalHeaderItem(c)
            headers.append(hdr.text() if hdr else "")

        rows = []
        for r in range(self._table.rowCount()):
            if self._table.isRowHidden(r):
                continue
            row = []
            for c in cols:
                item = self._table.item(r, c)
                row.append(item.text() if item else "")
            rows.append(row)
        return headers, rows

    def _export(self):
        """Export the currently displayed table to an .xlsx file, applying the
        'Main Column Name' rename overrides to the headers."""
        from PySide6.QtWidgets import QFileDialog, QMessageBox
        from services.lmv_export import export_xlsx

        headers, rows = self._visible_table_data()
        if not headers:
            QMessageBox.information(self, "Export", "Nothing to export yet.")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Live Master View", "lmv_export.xlsx",
            "Excel Workbook (*.xlsx)",
        )
        if not path:
            return
        if not path.lower().endswith(".xlsx"):
            path += ".xlsx"
        try:
            export_xlsx(path, headers, rows)
        except Exception as exc:
            QMessageBox.warning(self, "Export Failed", f"Could not export:\n\n{exc}")
            return
        QMessageBox.information(self, "Export",
                               f"Exported {len(rows)} rows to:\n{path}")

    def _apply_sector_filter(self):
        """Show/hide rows based on the selected sector. No table re-render."""
        selected = self._sector_combo.currentText()
        for r in range(self._table.rowCount()):
            if selected == "All":
                self._table.setRowHidden(r, False)
            else:
                item = self._table.item(r, 0)   # Sector is always col 0
                self._table.setRowHidden(r, item is None or item.text() != selected)
        self._update_filter_btn_label()

    # ── Controls ─────────────────────────────────────────────────────────────

    def _stop(self):
        self._fs_watcher.removePaths(self._fs_watcher.files())
        self._debounce.stop()
        if hasattr(self, "_com_timer"):
            self._com_timer.stop()
        if hasattr(self, "_sweep_timer"):
            self._sweep_timer.stop()
        self._pulse_timer.stop()
        self._shutdown_worker()
        t   = self._theme
        red = t.get("status_red") if t else "#f85149"
        self._dot.setStyleSheet(f"color: {red};")
        self._status_lbl.setText("Stopped")

    def _shutdown_worker(self):
        """Tear down the reader worker thread and release its COM handles."""
        if self._worker_thread is None:
            return
        # Release COM on the worker thread (queued), then stop its event loop.
        if self._worker is not None:
            self._request_shutdown.emit()
        self._worker_thread.quit()
        self._worker_thread.wait(2000)
        self._worker        = None
        self._worker_thread = None

    def _pulse(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        muted  = t.get("text_secondary") if t else "#8b949e"
        self._dot_state = not self._dot_state
        self._dot.setStyleSheet(f"color: {accent if self._dot_state else muted};")

    def refresh_theme(self):
        """Re-render table and window chrome with the current theme."""
        self._populate_table(self._data, set())
        self._apply_sector_filter()

    def closeEvent(self, event):
        self._stop()
        if self._controller is not None:
            # Emit stopped regardless of whether configure() was called
            self._controller.watcher.stopped.emit()
        super().closeEvent(event)
