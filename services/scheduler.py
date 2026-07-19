"""
Background scheduler: polls every 30s and fires each enabled trigger's job at
most once per calendar day, once its configured time has passed.

The `now_provider` is injectable (mirrors the `clock=time.monotonic` DI
pattern in services.live_merge.LiveDataReader) so this is unit-testable by
calling `_tick()` directly against a fake clock, without any real waiting.
"""

from datetime import datetime

from PySide6.QtCore import QObject, QTimer, Signal

from services import trigger_config


class Scheduler(QObject):
    fired = Signal(str)   # trigger id — for observability/tests

    def __init__(self, jobs: dict, now_provider=datetime.now,
                 poll_interval_ms: int = 30_000, parent=None):
        super().__init__(parent)
        self._jobs = jobs
        self._now = now_provider
        self._last_fired: dict = trigger_config.load_last_fired()
        self._timer = QTimer(self)
        self._timer.setInterval(poll_interval_ms)
        self._timer.timeout.connect(self._tick)

    def start(self):
        self._timer.start()
        self._tick()

    def stop(self):
        self._timer.stop()

    def _tick(self):
        now = self._now()
        today_str = now.date().isoformat()
        for cfg in trigger_config.load_trigger_configs():
            if not cfg.system_enabled:
                continue
            if self._last_fired.get(cfg.id) == today_str:
                continue
            if now.time() >= cfg.time:
                self._last_fired[cfg.id] = today_str
                trigger_config.save_last_fired(self._last_fired)
                job = self._jobs.get(cfg.id)
                if job is not None:
                    job()
                self.fired.emit(cfg.id)
