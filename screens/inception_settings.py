"""Inception > Data & Settings — where the local raw-bar sync
(services.inception_sync_service/inception_bars_store) and the Group A/B
formula parameters (services.inception_settings, read by services.
inception_formula_engine) live, now that both moved entirely to this
client. View by Date and HMV both depend on a sync having run at least
once; this screen is where that first sync (and any later "Sync Now") gets
triggered.

Sync runs on a worker QThread (mirrors components.update_dialog's
_ApplyWorker pattern) so a multi-minute first backfill (~500K rows across
~213 instruments — see services.inception_sync_service's module docstring)
never freezes the UI. A QProgressBar tracks it: determinate (a real %) for
a chunked full backfill, indeterminate/busy for a single-request
incremental delta (nothing to report a fraction of — see
inception_sync_service.incremental_sync). The colored dot + headline above
the status line is the "is my data synced at all" answer at a glance;
the sentence below it has the specifics (as-of date, row count).

The three formula parameters (gap threshold %, 52-week window length, gap
FIFO depth) are the full extent of "editable formula" for Group A/B — see
services.inception_formula_engine's module docstring for why: these
columns aren't row-level expressions, so a numeric parameter is the only
thing there is to edit. Saving here takes effect on the NEXT View by
Date/HMV load (values aren't cached, so no explicit recompute step is
needed — see services.inception_compute_service).
"""

import font_scale

from PySide6.QtCore import QThread, Signal, QTimer
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDoubleSpinBox,
    QSpinBox, QFrame, QMessageBox, QProgressBar,
)

from services import (
    inception_bars_store, inception_compute_service, inception_formula_builder_columns,
    inception_settings, inception_sync_service,
)


class _SyncWorker(QThread):
    progress = Signal(str, object)   # message, fraction (float | None)
    succeeded = Signal(int)          # total rows synced
    failed = Signal(str)

    def __init__(self, full: bool, parent=None):
        super().__init__(parent)
        self._full = full

    def run(self):
        try:
            fn = inception_sync_service.full_backfill if self._full else inception_sync_service.incremental_sync
            total = fn(progress_cb=lambda msg, frac: self.progress.emit(msg, frac))
        except inception_sync_service.SyncError as exc:
            self.failed.emit(str(exc))
            return
        self.succeeded.emit(total)


class InceptionSettingsScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._worker: _SyncWorker | None = None
        self._build()
        QTimer.singleShot(0, self._refresh_sync_status)

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(20)

        title = QLabel("Inception — Data & Settings")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        # ── sync section ─────────────────────────────────────────────────────
        sync_card = self._section("Local Data Sync", t)
        layout.addWidget(sync_card)
        sync_lay = sync_card.layout()

        # Status: a colored dot + a plain-language "synced / not synced yet"
        # line — the thing most people want to know at a glance before
        # digging into the exact date/row-count line below it.
        status_row = QHBoxLayout()
        self._sync_dot = QLabel("●")
        self._sync_dot.setFixedWidth(14)
        self._sync_dot.setStyleSheet(f"color: {t.get('text_secondary')}; background: transparent;")
        status_row.addWidget(self._sync_dot)
        self._sync_headline_lbl = QLabel("Checking…")
        self._sync_headline_lbl.setFont(font_scale.font(font_scale.SMALL, True))
        status_row.addWidget(self._sync_headline_lbl)
        status_row.addStretch()
        sync_lay.addLayout(status_row)

        self._sync_status_lbl = QLabel("")
        self._sync_status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._sync_status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._sync_status_lbl.setWordWrap(True)
        sync_lay.addWidget(self._sync_status_lbl)

        self._sync_progress_bar = QProgressBar()
        self._sync_progress_bar.setRange(0, 100)
        self._sync_progress_bar.setFixedHeight(18)
        self._sync_progress_bar.setVisible(False)
        sync_lay.addWidget(self._sync_progress_bar)

        self._sync_progress_lbl = QLabel("")
        self._sync_progress_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._sync_progress_lbl.setStyleSheet(f"color: {t.get('accent')};")
        self._sync_progress_lbl.setWordWrap(True)
        sync_lay.addWidget(self._sync_progress_lbl)

        sync_btn_row = QHBoxLayout()
        self._sync_now_btn = QPushButton("Sync Now")
        self._sync_now_btn.setFixedHeight(32)
        self._sync_now_btn.setToolTip(
            "Fetches only the trading days added since your last sync — fast, and "
            "safe to click any time. Use this for normal, day-to-day updates."
        )
        self._sync_now_btn.clicked.connect(lambda: self._start_sync(full=False))
        self._resync_btn = QPushButton("Full Resync")
        self._resync_btn.setFixedHeight(32)
        self._resync_btn.setToolTip(
            "Re-downloads the ENTIRE historical dataset from scratch (back to 2000) — "
            "slow, several minutes. Only use this if the local data looks wrong or "
            "you suspect it's corrupted; Sync Now is enough otherwise."
        )
        self._resync_btn.clicked.connect(self._confirm_full_resync)
        sync_btn_row.addWidget(self._sync_now_btn)
        sync_btn_row.addWidget(self._resync_btn)
        sync_btn_row.addStretch()
        sync_lay.addLayout(sync_btn_row)

        sync_hint = QLabel(
            "Sync Now — grabs just the new trading days since last time (quick, use "
            "this normally). Full Resync — wipes the local copy and re-downloads "
            "everything from scratch (slow; only needed if the data looks wrong)."
        )
        sync_hint.setFont(font_scale.font(font_scale.SMALL, False))
        sync_hint.setStyleSheet(f"color: {t.get('text_secondary')};")
        sync_hint.setWordWrap(True)
        sync_lay.addWidget(sync_hint)

        # ── formula parameters section ──────────────────────────────────────
        params_card = self._section("Group A/B Formula Parameters", t)
        layout.addWidget(params_card)
        params_lay = params_card.layout()

        hint = QLabel(
            "These are the only user-editable parts of the Group A/B "
            "computation (52-week high/low, gap tracking, …) — the "
            "algorithms themselves aren't row-level formulas, so a formula "
            "field wouldn't apply to them. Changes apply the next time you "
            "load View by Date or HMV."
        )
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color: {t.get('text_secondary')};")
        hint.setWordWrap(True)
        params_lay.addWidget(hint)

        self._threshold_spin = self._labeled_double_spin(
            params_lay, "Gap threshold (%):",
            "A day's open counts as a gap only when it moves more than this % from the previous close.",
            0.01, 50.0, 2,
        )
        self._window_spin = self._labeled_int_spin(
            params_lay, "52-week window (days):",
            "Calendar-day window 52WH/52WL roll over — 364 is the standard \"52 weeks\".",
            7, 3650,
        )
        self._fifo_spin = self._labeled_int_spin(
            params_lay, "Gap FIFO depth:",
            "How many recent gap areas per bucket (e.g. \"DAY UF GUP\") are kept/shown — 3 gives ranks 1-3.",
            1, 10,
        )

        save_row = QHBoxLayout()
        save_btn = QPushButton("Save Parameters")
        save_btn.setFixedHeight(32)
        save_btn.clicked.connect(self._save_params)
        save_row.addWidget(save_btn)
        save_row.addStretch()
        params_lay.addLayout(save_row)

        layout.addStretch()
        self._load_params()

    def _section(self, title: str, t) -> QFrame:
        card = QFrame()
        # Scoped to #inceptionSectionCard (not a bare "QFrame{...}" type
        # selector) — QLabel IS a QFrame subclass, so a bare-type selector
        # here would cascade its border onto every label nested inside this
        # card too, which is exactly the "every label has a border" bug this
        # avoids.
        card.setObjectName("inceptionSectionCard")
        card.setStyleSheet(
            f"QFrame#inceptionSectionCard{{background:{t.get('card_bg')};"
            f"border:1px solid {t.get('border')};border-radius:8px;}}"
        )
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)
        hdr = QLabel(title)
        hdr.setFont(font_scale.font(font_scale.MEDIUM, True))
        lay.addWidget(hdr)
        return card

    def _labeled_double_spin(self, layout, label, tooltip, lo, hi, decimals):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(180)
        spin = QDoubleSpinBox()
        spin.setRange(lo, hi)
        spin.setDecimals(decimals)
        spin.setToolTip(tooltip)
        spin.setFixedWidth(120)
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    def _labeled_int_spin(self, layout, label, tooltip, lo, hi):
        row = QHBoxLayout()
        lbl = QLabel(label)
        lbl.setFixedWidth(180)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setToolTip(tooltip)
        spin.setFixedWidth(120)
        row.addWidget(lbl)
        row.addWidget(spin)
        row.addStretch()
        layout.addLayout(row)
        return spin

    # ── formula parameters ──────────────────────────────────────────────────

    def _load_params(self):
        saved = inception_settings.load()
        self._threshold_spin.setValue(saved["gap_threshold_pct"])
        self._window_spin.setValue(saved["week_window_days"])
        self._fifo_spin.setValue(saved["fifo_cap"])

    def _save_params(self):
        inception_settings.save(
            self._threshold_spin.value(), self._window_spin.value(), self._fifo_spin.value(),
        )
        # Not required for correctness — inception_compute_service's row
        # cache keys on these settings too, so it self-invalidates on next
        # read — just tidies up entries computed under the old settings
        # that would otherwise sit unused in memory until the app restarts.
        inception_compute_service.clear_cache()
        t = self._controller.theme
        self._sync_progress_lbl.setStyleSheet(f"color: {t.get('accent')};")
        self._sync_progress_lbl.setText(
            "Parameters saved — they'll apply next time you load View by Date or HMV."
        )

    # ── sync ─────────────────────────────────────────────────────────────────

    def _refresh_sync_status(self):
        t = self._controller.theme
        last = inception_bars_store.last_synced_date()
        count = inception_bars_store.row_count()
        if last is None:
            self._sync_dot.setStyleSheet(f"color: {t.get('status_red')}; background: transparent;")
            self._sync_headline_lbl.setText("Not synced")
            self._sync_status_lbl.setText(
                "No data synced to this device yet. Click Sync Now to download historical "
                "data (may take a few minutes on first run)."
            )
        else:
            self._sync_dot.setStyleSheet(f"color: {t.get('accent')}; background: transparent;")
            self._sync_headline_lbl.setText("Synced")
            self._sync_status_lbl.setText(f"Synced through {last.isoformat()} — {count:,} bar rows stored locally.")

    def _confirm_full_resync(self):
        msg = QMessageBox(self)
        msg.setWindowTitle("Full Resync")
        msg.setText(
            "This re-downloads the full historical dataset from scratch — may take a few "
            "minutes. Continue?"
        )
        msg.setStandardButtons(QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
        msg.setDefaultButton(QMessageBox.StandardButton.No)
        if msg.exec() == QMessageBox.StandardButton.Yes:
            self._start_sync(full=True)

    def _start_sync(self, full: bool):
        if self._worker is not None and self._worker.isRunning():
            return
        t = self._controller.theme
        self._sync_now_btn.setEnabled(False)
        self._resync_btn.setEnabled(False)
        self._sync_progress_lbl.setStyleSheet(f"color: {t.get('accent')};")
        self._sync_progress_lbl.setText("Starting sync…")

        self._sync_progress_bar.setVisible(True)
        # Chunked (full backfill, or an empty-store "Sync Now" — see
        # inception_sync_service.incremental_sync) reports a real fraction
        # per chunk, so the bar is determinate; a small incremental delta is
        # one request with nothing to report a fraction of, so the bar runs
        # busy/indeterminate (Qt's range(0, 0) convention) until it resolves.
        self._sync_progress_bar.setRange(0, 100)
        self._sync_progress_bar.setValue(0)

        self._worker = _SyncWorker(full=full, parent=self)
        self._worker.progress.connect(self._on_sync_progress)
        self._worker.succeeded.connect(self._on_sync_succeeded)
        self._worker.failed.connect(self._on_sync_failed)
        self._worker.start()

    def _on_sync_progress(self, message: str, fraction):
        if fraction is not None:
            self._sync_progress_bar.setRange(0, 100)
            self._sync_progress_bar.setValue(int(fraction * 100))
            self._sync_progress_lbl.setText(f"{message} ({fraction * 100:.0f}%)")
        else:
            self._sync_progress_bar.setRange(0, 0)   # indeterminate/busy
            self._sync_progress_lbl.setText(message)

    def _on_sync_succeeded(self, total_rows: int):
        t = self._controller.theme
        self._sync_now_btn.setEnabled(True)
        self._resync_btn.setEnabled(True)
        self._sync_progress_bar.setRange(0, 100)
        self._sync_progress_bar.setValue(100)
        self._sync_progress_bar.setVisible(False)
        self._sync_progress_lbl.setStyleSheet(f"color: {t.get('accent')};")
        self._sync_progress_lbl.setText(f"Sync complete — {total_rows:,} rows written.")
        # New/changed bars already self-invalidate inception_compute_
        # service's row cache (the fingerprint includes bar count + last
        # date) — this just frees the now-unused pre-sync entries rather
        # than letting them sit in memory until the app restarts. Same for
        # the HMV-only Formula Builder column cache (services.
        # inception_formula_builder_columns), keyed the same way.
        inception_compute_service.clear_cache()
        inception_formula_builder_columns.clear_cache()
        self._refresh_sync_status()

    def _on_sync_failed(self, message: str):
        t = self._controller.theme
        self._sync_now_btn.setEnabled(True)
        self._resync_btn.setEnabled(True)
        self._sync_progress_bar.setVisible(False)
        self._sync_progress_lbl.setStyleSheet(f"color: {t.get('status_red')};")
        self._sync_progress_lbl.setText(f"Sync failed: {message}")

    # ── theme ────────────────────────────────────────────────────────────────

    def refresh_theme(self):
        self._refresh_sync_status()
