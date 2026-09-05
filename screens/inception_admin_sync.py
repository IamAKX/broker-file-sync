"""Admin Controls > Inception Sync — client side of Admin Controls >
Inception Sync (see components/topbar.py's own gating comment for why this
menu only ever appears for one account). Triggers POST /inception/admin/
sync-lmv-metrics (api.inception_api.sync_admin_lmv_metrics), which copies
hari_dss.LmvDailySnapshot's turnover/average-traded-price metrics (Avg
Rate, PATP, PWATP, PMATP, CWATP, CMATP, DAY TO, PDTO, CWTO, PWTO), the
options-OI/max-pain sheet columns (callstrikehighestoi, Max Pain, ...), and
Market Profile (VAH/POC/VAL) — plus OR.High/OR.Low, sourced from the
separate hari_dss.OpeningRangeCapture table — into public.EodBar's own
columns of the same name — see app/services/inception_admin_sync_service.py
in the broker-sync-api repo for the actual sync/matching logic; this screen
only calls it and shows the result (the results table below is a generic
render of whatever "metrics" rows the response carries, so it needs no
changes when the backend's own column set grows).

Runs on a QThread — mirrors screens.inception_settings' own
_VendorSyncWorker (same shape: one POST, generous timeout, no progress
fraction to report mid-request, so an indeterminate progress bar is what's
shown while it runs).

After a successful server-side sync, auto-follows with the same local
"Sync Now" pull screens.inception_settings' own vendor-fetch success
handler triggers — explicitly mirroring that convention, so a click here
is a true one-step "sync centrally AND pull it down to this device"
action rather than needing a second manual step on the Data & Settings
screen.
"""
import font_scale
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QFrame,
    QProgressBar, QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
)
from PySide6.QtCore import Qt, QThread, Signal

from api.exceptions import ApiError, NetworkError


class _AdminSyncWorker(QThread):
    succeeded = Signal(dict)
    failed = Signal(str)

    def run(self):
        from api import inception_api
        try:
            result = inception_api.sync_admin_lmv_metrics()
        except (ApiError, NetworkError) as exc:
            self.failed.emit(str(exc))
            return
        except Exception as exc:  # never let an unexpected error kill the worker thread silently
            self.failed.emit(f"Unexpected error: {exc}")
            return
        self.succeeded.emit(result)


class InceptionAdminSyncScreen(QWidget):
    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._worker: _AdminSyncWorker | None = None
        self._local_sync_worker = None
        self._build()

    # ── build ────────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        title = QLabel("Admin Controls — Inception Sync")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        layout.addWidget(title)

        desc = QLabel(
            "Copies Avg Rate, PATP, PWATP, PMATP, CWATP, CMATP, DAY TO, PDTO, "
            "CWTO, PWTO, callstrikehighestoi, Callstrikewithsecondhighestoi, "
            "PutStrikeWithsecondHighestOI, TodayPutHighestStrike, Max Pain, "
            "VAH, POC, VAL, OR.High and OR.Low — figures LMV's own daily grid "
            "already computes and archives — into Inception's shared historic "
            "dataset, so HMV can show them as plain columns the same way "
            "OPEN/HIGH/LOW/CLOSE already work. Safe to run any time; "
            "re-running just re-copies the current values, it never "
            "duplicates anything."
        )
        desc.setWordWrap(True)
        desc.setFont(font_scale.font(font_scale.SMALL, False))
        desc.setStyleSheet(f"color: {t.get('text_secondary')};")
        layout.addWidget(desc)

        card = QFrame()
        card.setObjectName("adminSyncCard")
        card.setStyleSheet(
            f"QFrame#adminSyncCard{{background:{t.get('card_bg')};"
            f"border:1px solid {t.get('border')};border-radius:8px;}}"
        )
        card_lay = QVBoxLayout(card)
        card_lay.setContentsMargins(16, 16, 16, 16)
        card_lay.setSpacing(10)

        self._progress_bar = QProgressBar()
        self._progress_bar.setRange(0, 0)  # indeterminate — a single request, nothing to report a fraction of
        self._progress_bar.setFixedHeight(18)
        self._progress_bar.setTextVisible(False)
        self._progress_bar.setVisible(False)
        card_lay.addWidget(self._progress_bar)

        self._status_lbl = QLabel("")
        self._status_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._status_lbl.setWordWrap(True)
        card_lay.addWidget(self._status_lbl)

        btn_row = QHBoxLayout()
        self._sync_btn = QPushButton("Sync Now")
        self._sync_btn.setFixedHeight(32)
        self._sync_btn.setToolTip(
            "Reads every Avg Rate/PATP/.../PWTO, options-OI/Max Pain, VAH/"
            "POC/VAL, and OR.High/OR.Low value LMV has archived and writes "
            "it into the matching Inception instrument/date. Only updates "
            "dates Inception already has a bar for — never invents a new "
            "row."
        )
        self._sync_btn.clicked.connect(self._start_sync)
        btn_row.addWidget(self._sync_btn)
        btn_row.addStretch()
        card_lay.addLayout(btn_row)

        layout.addWidget(card)

        # ── results table ───────────────────────────────────────────────────
        self._results_table = QTableWidget(0, 3)
        self._results_table.setHorizontalHeaderLabels(["Metric", "Candidate Rows", "Rows Updated"])
        self._results_table.verticalHeader().setVisible(False)
        self._results_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._results_table.setSelectionMode(QAbstractItemView.SelectionMode.NoSelection)
        self._results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._results_table.setVisible(False)
        layout.addWidget(self._results_table)

        layout.addStretch()

    # ── sync ─────────────────────────────────────────────────────────────────

    def _start_sync(self):
        if self._worker is not None and self._worker.isRunning():
            return
        t = self._controller.theme
        self._sync_btn.setEnabled(False)
        self._progress_bar.setVisible(True)
        self._results_table.setVisible(False)
        self._status_lbl.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._status_lbl.setText("Syncing from LMV's archive…")

        self._worker = _AdminSyncWorker(parent=self)
        self._worker.succeeded.connect(self._on_sync_succeeded)
        self._worker.failed.connect(self._on_sync_failed)
        self._worker.start()

    def _on_sync_succeeded(self, result: dict):
        t = self._controller.theme
        self._sync_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_lbl.setStyleSheet(f"color: {t.get('accent')};")

        metrics = result.get("metrics", [])
        date_from, date_to = result.get("date_from"), result.get("date_to")
        symbols = result.get("symbols_matched", 0)
        if date_from and date_to:
            self._status_lbl.setText(
                f"Synced {date_from} → {date_to} across {symbols} symbol(s). "
                f"Pulling this into this device's local cache…"
            )
        else:
            self._status_lbl.setText(
                "Nothing to sync — LMV's archive has no matching data yet."
            )

        self._results_table.setRowCount(len(metrics))
        for row, m in enumerate(metrics):
            self._results_table.setItem(row, 0, QTableWidgetItem(m.get("name", "")))
            self._results_table.setItem(row, 1, QTableWidgetItem(f"{m.get('candidate_rows', 0):,}"))
            self._results_table.setItem(row, 2, QTableWidgetItem(f"{m.get('rows_updated', 0):,}"))
        self._results_table.setVisible(bool(metrics))

        # Auto-follow with the same local "Sync Now" pull screens.
        # inception_settings' own vendor-fetch success handler triggers —
        # see this module's own docstring for why. Harmless to call even
        # when nothing changed (incremental_sync's own no-op-if-current
        # check makes it a cheap round trip).
        from services import inception_sync_service

        class _LocalPullWorker(QThread):
            done = Signal()

            def run(self):
                try:
                    inception_sync_service.incremental_sync()
                except Exception:
                    pass  # best-effort — the server-side sync above already succeeded regardless
                self.done.emit()

        self._local_sync_worker = _LocalPullWorker(parent=self)
        self._local_sync_worker.done.connect(self._on_local_pull_done)
        self._local_sync_worker.start()

    def _on_local_pull_done(self):
        t = self._controller.theme
        current = self._status_lbl.text()
        if current.endswith("local cache…"):
            self._status_lbl.setText(current[:-len("Pulling this into this device's local cache…")]
                                      + "This device's local cache is up to date.")
        self._status_lbl.setStyleSheet(f"color: {t.get('accent')};")

    def _on_sync_failed(self, message: str):
        t = self._controller.theme
        self._sync_btn.setEnabled(True)
        self._progress_bar.setVisible(False)
        self._status_lbl.setStyleSheet(f"color: {t.get('status_red')};")
        self._status_lbl.setText(f"Sync failed: {message}")
