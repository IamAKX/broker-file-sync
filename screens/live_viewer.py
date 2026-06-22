import font_scale
import os
import sys
import time
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QFrame,
    QLineEdit, QScrollArea, QCheckBox, QSizePolicy
)
from PySide6.QtCore import Qt, QTimer, QFileSystemWatcher, Signal
from PySide6.QtGui import QFont, QColor, QBrush


_DEBOUNCE_MS  = 300    # ms to wait after file event before re-reading
_COM_POLL_MS  = 1000   # COM polling interval — 1s for live trading data


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


class LiveViewerWindow(QWidget):
    """
    Standalone window showing the merged master table in real-time.
    Uses QFileSystemWatcher (OS-level events) — no polling interval.
    Changed rows are highlighted amber for 4 seconds.
    """

    def __init__(self, sharekhan_path: str, reliable_path: str,
                 nifty_path: str, script_name_data: list,
                 theme=None, controller=None, parent=None):
        super().__init__(parent)
        self._sharekhan_path   = sharekhan_path
        self._reliable_path    = reliable_path
        self._nifty_path       = nifty_path
        self._script_name_data = script_name_data
        self._theme            = theme
        self._controller       = controller

        self._headers: list      = []
        self._data: list[list]   = []
        self._row_key_index: int = 0
        self._dot_state          = True
        self._visible_cols: set  = set()   # populated after first load
        self._strategies: list   = []      # injected by DataImportScreen

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

        self._col_btn = QPushButton("⊞  Columns")
        self._col_btn.setFixedHeight(30)
        self._col_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._col_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._col_btn.setStyleSheet(
            f"QPushButton {{ background: transparent; color: {text_s};"
            f"border: 1px solid {divclr}; border-radius: 4px; padding: 0 12px; }}"
            f"QPushButton:hover {{ border-color: {accent}; color: {accent}; }}"
        )
        self._col_btn.clicked.connect(self._show_col_filter)

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
        top.addWidget(self._col_btn)
        top.addSpacing(8)
        top.addWidget(self._strat_btn)
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
        self._use_com = com_available()

        if self._use_com:
            # Windows + pywin32: poll Excel COM object directly.
            # TradeTiger updates Excel via DDE (in-memory) so the file on
            # disk never changes — QFileSystemWatcher would never fire.
            self._com_timer = QTimer(self)
            self._com_timer.setInterval(_COM_POLL_MS)
            self._com_timer.timeout.connect(self._refresh)
            self._com_timer.start()
            # Keep fs_watcher as a no-op fallback so _stop() doesn't error
            self._fs_watcher = QFileSystemWatcher(self)
            self._debounce   = QTimer(self)
        else:
            # macOS / Linux: fall back to QFileSystemWatcher + debounce
            self._fs_watcher = QFileSystemWatcher(self)
            self._fs_watcher.addPath(self._sharekhan_path)
            self._fs_watcher.fileChanged.connect(self._on_file_changed)
            self._debounce = QTimer(self)
            self._debounce.setSingleShot(True)
            self._debounce.setInterval(_DEBOUNCE_MS)
            self._debounce.timeout.connect(self._refresh)

    def _on_file_changed(self, path: str):
        # Re-add watch if the app briefly removed the file on save
        if path not in self._fs_watcher.files():
            if os.path.exists(path):
                self._fs_watcher.addPath(path)
        self._debounce.start()

    # ── Data ─────────────────────────────────────────────────────────────────

    def _merge(self) -> tuple[list, list[list]]:
        from services.master_generator import (
            _build_script_name_lookup, _normalise,
            _RS_DATA_INDICES, _NI_DATA_INDICES,
            _SK_PK_IDX, _RS_FK_IDX, _NI_FK_IDX,
        )
        from services.file_reader import read_sharekhan, read_reliable_software, read_nifty_invest

        sk_headers, sk_rows = read_sharekhan(self._sharekhan_path)
        rs_headers, rs_rows = read_reliable_software(self._reliable_path)
        ni_headers, ni_rows = read_nifty_invest(self._nifty_path)

        name_to_symbol = _build_script_name_lookup(self._script_name_data)

        rs_lookup = {}
        for row in rs_rows:
            sym = name_to_symbol.get(_normalise(row[_RS_FK_IDX]).lower())
            if sym:
                rs_lookup[_normalise(sym).upper()] = row

        ni_lookup = {}
        for row in ni_rows:
            ni_lookup[_normalise(row[_NI_FK_IDX]).upper()] = row

        out_headers = list(sk_headers)
        for i in _RS_DATA_INDICES:
            out_headers.append(rs_headers[i] if i < len(rs_headers) else "")
        for i in _NI_DATA_INDICES:
            out_headers.append(ni_headers[i] if i < len(ni_headers) else "")

        merged = []
        for sk_row in sk_rows:
            pk = _normalise(sk_row[_SK_PK_IDX]).upper()
            out_row = list(sk_row)
            rs_row = rs_lookup.get(pk)
            for i in _RS_DATA_INDICES:
                out_row.append(rs_row[i] if rs_row and i < len(rs_row) else None)
            ni_row = ni_lookup.get(pk)
            for i in _NI_DATA_INDICES:
                out_row.append(ni_row[i] if ni_row and i < len(ni_row) else None)
            merged.append(out_row)

        return out_headers, merged

    def _load_initial(self):
        try:
            headers, data = self._merge()
        except Exception as exc:
            self._status_lbl.setText(f"Error loading: {exc}")
            return
        self._headers = headers
        self._data    = data
        # All columns visible by default
        self._visible_cols = set(range(len(headers)))
        self._populate_table(data, changed_keys=set())
        self._update_col_btn_label()

    def _refresh(self):
        from datetime import datetime

        if getattr(self, "_use_com", False):
            # Windows: read live data directly from open Excel via COM
            from services.com_reader import read_snap_sheet
            result = read_snap_sheet()
            if result is None:
                self._status_lbl.setText("Waiting for Snap.xls in Excel…")
                return
            headers, new_data = result
        else:
            # macOS / Linux: re-read and merge from disk files
            time.sleep(0.2)
            try:
                headers, new_data = self._merge()
            except Exception as exc:
                self._status_lbl.setText(f"Read error: {str(exc)[:80]}")
                return

        self._data    = new_data
        self._headers = headers
        self._populate_table(new_data, set())
        self._status_lbl.setText(f"Updated: {datetime.now().strftime('%H:%M:%S')}")


    # ── Table rendering ───────────────────────────────────────────────────────

    def _populate_table(self, data: list[list], changed_keys: set):
        from services.strategy_engine import apply_strategies, get_cell_color

        # Apply active strategies — may extend headers and data
        active_strategies = [s for s in self._strategies if s.get("active")]
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

        self.setStyleSheet(f"background: {win_bg};")
        self._table.setStyleSheet(
            f"QTableWidget {{ background: {norm_bg.name()}; color: {norm_txt.name()}; }}"
            f"QTableWidget QHeaderView::section {{ background: {hdr_bg}; color: {norm_txt.name()}; }}"
        )

        self._table.setColumnCount(len(disp_headers))
        self._table.setHorizontalHeaderLabels(disp_headers)
        self._table.setRowCount(len(disp_data))

        # Build per-column info for strategy columns (for conditional formatting)
        strat_col_defs = []   # list of col_def dicts for strategy cols in order
        for s in active_strategies:
            for col in s.get("columns", []):
                strat_col_defs.append(col)

        all_dicts = [dict(zip(disp_headers, row)) for row in disp_data]

        bold_font = font_scale.font(font_scale.SMALL, True)
        for r, row in enumerate(disp_data):
            row_dict = dict(zip(disp_headers, row))
            for c, val in enumerate(row):
                if isinstance(val, float):
                    display = f"{val:.2f}"
                elif val is None:
                    display = ""
                else:
                    display = str(val)
                item = QTableWidgetItem(display)
                item.setForeground(QBrush(norm_txt))
                item.setBackground(QBrush(norm_bg))
                item.setTextAlignment(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft)
                if c == 0:
                    item.setFont(bold_font)

                # Strategy column: tinted background + conditional formatting
                strat_idx = c - base_col_count
                if strat_idx >= 0 and strat_idx < len(strat_col_defs):
                    col_def = strat_col_defs[strat_idx]
                    cell_color = get_cell_color(col_def, val, row_dict, all_dicts)
                    if cell_color:
                        item.setBackground(QBrush(QColor(cell_color)))
                        # Choose readable text color based on background brightness
                        qc = QColor(cell_color)
                        lum = 0.299 * qc.red() + 0.587 * qc.green() + 0.114 * qc.blue()
                        item.setForeground(QBrush(QColor("#000000" if lum > 128 else "#ffffff")))
                    else:
                        item.setBackground(QBrush(QColor(strat_hdr)))

                self._table.setItem(r, c, item)

        # Strategy header columns: tinted section header
        for c in range(base_col_count, len(disp_headers)):
            self._table.horizontalHeaderItem(c)

        # Ensure visible_cols covers strategy columns too
        if len(disp_headers) > len(self._headers):
            for c in range(len(self._headers), len(disp_headers)):
                self._visible_cols.add(c)

        # Apply column visibility
        for c in range(len(disp_headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)

        self._table.resizeColumnsToContents()
        self._update_strat_btn_label()

    # ── Strategy picker ───────────────────────────────────────────────────────

    def set_strategies(self, strategies: list):
        """Inject strategies from StrategyBuilderScreen."""
        self._strategies = [dict(s) for s in strategies]
        self._update_strat_btn_label()
        self._populate_table(self._data, set())

    def _show_strategy_picker(self):
        popup = StrategyPickerPopup(self._strategies, self._theme, self)
        popup.applied.connect(self._on_strategies_applied)
        btn_pos = self._strat_btn.mapToGlobal(self._strat_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _on_strategies_applied(self, updated: list):
        self._strategies = updated
        # Persist toggle state back to store
        from services import strategy_store as store
        for s in updated:
            store.save_strategy(s)
        # Reset visible_cols to base headers so new strategy cols get added
        self._visible_cols = set(range(len(self._headers)))
        self._populate_table(self._data, set())

    def _update_strat_btn_label(self):
        active = sum(1 for s in self._strategies if s.get("active"))
        total  = len(self._strategies)
        if total == 0:
            self._strat_btn.setText("⚡  Strategies")
        elif active == 0:
            self._strat_btn.setText("⚡  Strategies  off")
        else:
            self._strat_btn.setText(f"⚡  Strategies  {active}/{total}")

    # ── Column filter ─────────────────────────────────────────────────────────

    def _show_col_filter(self):
        if not self._headers:
            return
        popup = ColumnFilterPopup(self._headers, self._visible_cols, self._theme, self)
        popup.columns_changed.connect(self._apply_col_filter)
        # Position below the Columns button
        btn_pos = self._col_btn.mapToGlobal(self._col_btn.rect().bottomLeft())
        popup.adjustSize()
        popup.move(btn_pos.x(), btn_pos.y() + 4)
        popup.show()

    def _apply_col_filter(self, visible: set):
        # Always keep column 0 (Scrip Name) visible
        visible.add(0)
        self._visible_cols = visible
        for c in range(len(self._headers)):
            self._table.setColumnHidden(c, c not in self._visible_cols)
        self._update_col_btn_label()

    def _update_col_btn_label(self):
        total   = len(self._headers)
        visible = len(self._visible_cols)
        if total == 0:
            return
        if visible == total:
            self._col_btn.setText("⊞  Columns")
        else:
            self._col_btn.setText(f"⊞  Columns  {visible}/{total}")

    # ── Controls ─────────────────────────────────────────────────────────────

    def _stop(self):
        self._fs_watcher.removePaths(self._fs_watcher.files())
        self._debounce.stop()
        if hasattr(self, "_com_timer"):
            self._com_timer.stop()
        self._pulse_timer.stop()
        t   = self._theme
        red = t.get("status_red") if t else "#f85149"
        self._dot.setStyleSheet(f"color: {red};")
        self._status_lbl.setText("Stopped")

    def _pulse(self):
        t      = self._theme
        accent = t.get("accent")         if t else "#39d353"
        muted  = t.get("text_secondary") if t else "#8b949e"
        self._dot_state = not self._dot_state
        self._dot.setStyleSheet(f"color: {accent if self._dot_state else muted};")

    def refresh_theme(self):
        """Re-render table and window chrome with the current theme."""
        self._populate_table(self._data, set())

    def closeEvent(self, event):
        self._stop()
        if self._controller is not None:
            # Emit stopped regardless of whether configure() was called
            self._controller.watcher.stopped.emit()
        super().closeEvent(event)
