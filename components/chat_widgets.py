"""Building blocks for the AI assistant screen (screens/chat.py).

All animation is QPainter/QTimer driven (no image assets), so it follows the
active theme and costs nothing when hidden — every timer is stopped while its
widget is not visible.
"""

import math

import font_scale
from PySide6.QtCore import QEasingCurve, QPropertyAnimation, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPen
from PySide6.QtWidgets import (
    QAbstractButton, QFrame, QGraphicsOpacityEffect, QHBoxLayout, QLabel, QPushButton, QSizePolicy,
    QTableWidget, QTableWidgetItem, QVBoxLayout, QWidget,
)

# (event stage key from the backend, label shown while it is active)
STAGES = [
    ("understanding", "Understanding your question"),
    ("generating_query", "Building the query"),
    ("running_query", "Searching Fuku Lens data"),
    ("writing_answer", "Writing the answer"),
]
_FRAME_MS = 33


class ThinkingIndicator(QWidget):
    """Bouncing dots + a pulsing stage label + a four-step progress bar whose
    active segment has a light sweeping across it. Driven by set_stage()."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._stage = 0
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setFixedHeight(64)
        self.setMinimumWidth(380)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def set_stage(self, key: str) -> None:
        for i, (stage_key, _label) in enumerate(STAGES):
            if stage_key == key:
                self._stage = i
                self.update()
                return

    def stage_index(self) -> int:
        return self._stage

    def showEvent(self, event):
        self._timer.start(_FRAME_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._t += 1.0
        self.update()

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        accent = QColor(self._theme.get("accent"))
        dim = QColor(self._theme.get("border"))
        text = QColor(self._theme.get("text_secondary"))

        # bouncing dots
        for i in range(3):
            phase = self._t * 0.18 - i * 0.7
            lift = max(0.0, math.sin(phase)) * 7
            c = QColor(accent)
            c.setAlphaF(0.45 + 0.55 * (0.5 + 0.5 * math.sin(phase)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(c)
            p.drawEllipse(QRectF(4 + i * 15, 16 - lift, 9, 9))

        # pulsing stage label
        label_color = QColor(text)
        label_color.setAlphaF(0.65 + 0.35 * (0.5 + 0.5 * math.sin(self._t * 0.12)))
        p.setPen(label_color)
        f = font_scale.font(font_scale.SMALL, True)
        p.setFont(f)
        dots = "." * (int(self._t / 8) % 4)
        p.drawText(QRectF(58, 6, self.width() - 62, 24), Qt.AlignmentFlag.AlignVCenter, STAGES[self._stage][1] + dots)

        # progress segments
        n = len(STAGES)
        gap = 6
        seg_w = (self.width() - 8 - gap * (n - 1)) / n
        y = 42
        for i in range(n):
            rect = QRectF(4 + i * (seg_w + gap), y, seg_w, 5)
            p.setPen(Qt.PenStyle.NoPen)
            if i < self._stage:
                p.setBrush(accent)
                p.drawRoundedRect(rect, 2.5, 2.5)
            else:
                p.setBrush(dim)
                p.drawRoundedRect(rect, 2.5, 2.5)
                if i == self._stage:
                    sweep = ((self._t * 0.035) % 1.4) - 0.2
                    x0 = rect.left() + sweep * rect.width()
                    grad = QLinearGradient(x0 - 30, 0, x0 + 30, 0)
                    transparent = QColor(accent)
                    transparent.setAlpha(0)
                    grad.setColorAt(0.0, transparent)
                    grad.setColorAt(0.5, accent)
                    grad.setColorAt(1.0, transparent)
                    p.save()
                    p.setClipRect(rect)
                    p.setBrush(grad)
                    p.drawRoundedRect(rect, 2.5, 2.5)
                    p.restore()
        p.end()


class TypewriterLabel(QLabel):
    """Markdown label that reveals streamed text a few characters per frame, so
    bursty network chunks still read as smooth typing. finish() flushes the rest."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextFormat(Qt.TextFormat.MarkdownText)
        self.setWordWrap(True)
        self.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum)
        self._shown = ""
        self._pending = ""
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._step)

    def push(self, text: str) -> None:
        self._pending += text
        if not self._timer.isActive():
            self._timer.start(_FRAME_MS)

    def finish(self) -> None:
        self._timer.stop()
        self._shown += self._pending
        self._pending = ""
        self._render()

    def full_text(self) -> str:
        return self._shown + self._pending

    def _step(self):
        if not self._pending:
            self._timer.stop()
            return
        n = max(2, len(self._pending) // 10)
        self._shown += self._pending[:n]
        self._pending = self._pending[n:]
        self._render()

    def _render(self):
        self.setText(self._shown)


class MessageBubble(QFrame):
    """One chat message. Assistant bubbles can also carry a collapsible
    'data' section (a preview of the result rows; never the SQL)."""

    def __init__(self, theme, role: str, text: str = "", parent=None):
        super().__init__(parent)
        self._theme = theme
        self.role = role
        is_user = role == "user"
        bg = theme.get("accent") if is_user else theme.get("card_bg")
        fg = "#ffffff" if is_user else theme.get("text_primary")
        border = theme.get("accent") if is_user else theme.get("border")
        self.setObjectName("chatBubble")
        self.setStyleSheet(
            f"#chatBubble {{ background: {bg}; border: 1px solid {border}; border-radius: 12px; }}"
            f"#chatBubble QLabel {{ color: {fg}; background: transparent; border: none; }}"
        )
        self.setMaximumWidth(760)
        if not is_user:
            self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 10, 14, 10)
        layout.setSpacing(8)

        self.indicator: ThinkingIndicator | None = None
        self.body = TypewriterLabel()
        self.body.setFont(font_scale.font(font_scale.SMALL, False))
        if text:
            self.body.push(text)
            self.body.finish()
            if is_user:
                # A word-wrapped QLabel in a stretch row otherwise collapses to a
                # sliver; ask for the text's natural width (wraps at the bubble max).
                natural = self.body.fontMetrics().horizontalAdvance(text) + 12
                self.body.setMinimumWidth(min(700, natural))
        elif not is_user:
            self.body.hide()
        layout.addWidget(self.body)

        self._details: QWidget | None = None
        self._details_btn: QPushButton | None = None

    # ── thinking state ───────────────────────────────────────────────────
    def start_thinking(self) -> None:
        self.indicator = ThinkingIndicator(self._theme)
        self.layout().insertWidget(0, self.indicator)

    def stop_thinking(self) -> None:
        if self.indicator is not None:
            self.indicator.hide()
            self.indicator.deleteLater()
            self.indicator = None
        self.body.show()

    def set_stage(self, key: str) -> None:
        if self.indicator is not None:
            self.indicator.set_stage(key)

    # ── answer ───────────────────────────────────────────────────────────
    def add_text(self, text: str) -> None:
        self.stop_thinking()
        self.body.push(text)

    def finish(self) -> None:
        self.stop_thinking()
        self.body.finish()

    def set_error(self, message: str) -> None:
        self.stop_thinking()
        self.body.setStyleSheet(f"color: {self._theme.get('destructive')};")
        self.body.push(message)
        self.body.finish()

    # ── query & data details ─────────────────────────────────────────────
    def set_details(self, columns: list, rows: list, row_count: int, truncated: bool) -> None:
        t = self._theme
        self._details_btn = QPushButton("Show data")
        self._details_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._details_btn.setFlat(True)
        self._details_btn.setStyleSheet(
            f"QPushButton {{ color: {t.get('accent')}; text-align: left; padding: 0; border: none; }}"
            f"QPushButton:hover {{ text-decoration: underline; }}"
        )
        self._details_btn.setFont(font_scale.font(font_scale.SMALL, False))
        self._details_btn.clicked.connect(self._toggle_details)
        self.layout().addWidget(self._details_btn)

        box = QWidget()
        v = QVBoxLayout(box)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        table = QTableWidget(len(rows), len(columns))
        table.setHorizontalHeaderLabels([str(c) for c in columns])
        table.verticalHeader().setVisible(False)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.setFont(font_scale.font(font_scale.SMALL, False))
        for r, row in enumerate(rows):
            for c, val in enumerate(row):
                item = QTableWidgetItem("" if val is None else str(val))
                if isinstance(val, (int, float)):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
                table.setItem(r, c, item)
        table.resizeColumnsToContents()
        table.setMaximumHeight(min(260, 34 + 26 * max(1, len(rows))))
        table.setStyleSheet(f"background: {t.get('input_bg')}; color: {t.get('text_primary')};")
        v.addWidget(table)

        note = f"{row_count} row(s)" + (" — preview truncated" if truncated else "")
        caption = QLabel(note)
        caption.setFont(font_scale.font(font_scale.SMALL, False))
        caption.setStyleSheet(f"color: {t.get('text_secondary')};")
        v.addWidget(caption)

        box.setVisible(False)
        self._details = box
        self.layout().addWidget(box)

    def _toggle_details(self) -> None:
        if self._details is None or self._details_btn is None:
            return
        show = self._details.isHidden()
        self._details.setVisible(show)
        self._details_btn.setText("Hide data" if show else "Show data")

    def details_visible(self) -> bool:
        return self._details is not None and not self._details.isHidden()

    # ── entrance animation ───────────────────────────────────────────────
    def fade_in(self) -> None:
        effect = QGraphicsOpacityEffect(self)
        self.setGraphicsEffect(effect)
        anim = QPropertyAnimation(effect, b"opacity", self)
        anim.setDuration(260)
        anim.setStartValue(0.0)
        anim.setEndValue(1.0)
        anim.setEasingCurve(QEasingCurve.Type.OutCubic)
        # The effect forces an offscreen render on every repaint, which is wasted
        # work (and blurs streaming text) once the fade is over — drop it.
        anim.finished.connect(lambda: self.setGraphicsEffect(None))
        anim.start(QPropertyAnimation.DeletionPolicy.DeleteWhenStopped)


class ToggleSwitch(QAbstractButton):
    """A painted on/off pill (voice mode). Checkable; emits toggled(bool)."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self.setCheckable(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(40, 22)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        track = QColor(self._theme.get("accent" if self.isChecked() else "border"))
        if not self.isEnabled():
            track.setAlphaF(0.4)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(track)
        p.drawRoundedRect(QRectF(0, 0, self.width(), self.height()), self.height() / 2, self.height() / 2)
        d = self.height() - 6
        x = self.width() - d - 3 if self.isChecked() else 3
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QRectF(x, 3, d, d))
        p.end()


class VoiceStatusBar(QFrame):
    """The strip above the input while voice mode is on: an animated glyph for
    what Fuku is doing (live microphone level while listening, a wave while
    speaking, a slow pulse otherwise) and one line of status text."""

    def __init__(self, theme, parent=None):
        super().__init__(parent)
        self._theme = theme
        self._state = "off"
        self._level = 0.0
        self._t = 0.0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self.setObjectName("voiceBar")
        self.setStyleSheet(
            f"#voiceBar {{ background: {theme.get('card_bg')}; border: 1px solid {theme.get('border')}; "
            f"border-radius: 8px; }}"
        )
        self.setFixedHeight(40)
        row = QHBoxLayout(self)
        row.setContentsMargins(64, 0, 12, 0)   # the glyph is painted in the left 64px
        self._label = QLabel("")
        self._label.setFont(font_scale.font(font_scale.SMALL, False))
        self._label.setStyleSheet(f"color: {theme.get('text_secondary')}; background: transparent; border: none;")
        row.addWidget(self._label, 1)

    def set_state(self, state: str, text: str) -> None:
        self._state = state
        self._label.setText(text)
        self.update()

    def set_level(self, level: float) -> None:
        self._level = max(level, self._level * 0.7)   # fast attack, soft decay
        self.update()

    def text(self) -> str:
        return self._label.text()

    def showEvent(self, event):
        self._timer.start(_FRAME_MS)
        super().showEvent(event)

    def hideEvent(self, event):
        self._timer.stop()
        super().hideEvent(event)

    def _tick(self):
        self._t += 1.0
        self._level *= 0.92
        self.update()

    def paintEvent(self, event):
        super().paintEvent(event)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        listening = self._state in ("listening", "hearing")
        color = QColor(self._theme.get("accent" if self._state in ("listening", "hearing", "speaking")
                                       else "text_secondary"))
        p.setPen(Qt.PenStyle.NoPen)
        mid = self.height() / 2
        for i in range(5):
            if listening:
                shape = (0.45, 0.75, 1.0, 0.75, 0.45)[i]
                h = 4 + 20 * min(1.0, self._level * 1.6) * shape
            elif self._state == "speaking":
                h = 6 + 14 * (0.5 + 0.5 * math.sin(self._t * 0.22 + i * 0.9))
            else:
                h = 5 + 5 * (0.5 + 0.5 * math.sin(self._t * 0.1 + i * 0.6))
            c = QColor(color)
            c.setAlphaF(0.55 + 0.45 * (h / 24))
            p.setBrush(c)
            p.drawRoundedRect(QRectF(16 + i * 8, mid - h / 2, 4, h), 2, 2)
        p.end()
