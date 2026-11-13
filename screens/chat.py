"""
AI assistant screen (sidebar > Ask Fuku).

A chat over the user's Fuku Lens data: the backend (broker-sync-api /chat/ask)
turns the question into a guarded read-only SQL query, runs it, and streams
back the answer. This screen animates each pipeline stage while it works
(components.chat_widgets.ThinkingIndicator), types the answer out as it
arrives, and lets the user expand the rows behind any answer (the generated SQL is never shown).

Voice mode (the switch in the header) makes it hands-free: the question is
spoken, transcribed on this machine and asked like a typed one; the answer is
read aloud while it also appears in the transcript (services/voice_io.py).

Live questions ("what is Reliance trading at now?") are answered from the
running Live Master View: every question carries the LMV grid, or the reason
it isn't available (services/lmv_chat_context.py), and the line under the
input shows which of the two it is.

Every finished answer has a small options button (⋯): "Save chat as PDF"
exports the whole transcript, data tables included (services/chat_export.py),
and "Translate to Tamil" / "Translate to Tanglish" / "Show in English" switches
that one answer's language - Tanglish is Tamil typed in English letters (the
server translates; names, symbols and numbers stay as they are).

Scope is enforced server-side (prompt + SQL validator) —
see docs/chatbot.md. Nothing is stored locally: the conversation lives in
memory for the session and the last few turns are sent along so follow-up
questions work.
"""

import threading

import font_scale
import shiboken6
from PySide6.QtCore import QTimer, Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QMessageBox, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

from api import chat_api
from api.exceptions import ApiError, NetworkError
from components.chat_widgets import MessageBubble, ToggleSwitch, VoiceStatusBar
from components.page_header import page_header
from services import chat_export, lmv_chat_context, voice_io

_HISTORY_TURNS_SENT = 6


class ChatScreen(QWidget):
    # (conversation token, event name, payload) — emitted from the streaming
    # thread, delivered on the GUI thread. The token drops events from a
    # conversation that was cleared or superseded while it was in flight.
    _event = Signal(int, str, object)

    def __init__(self, controller):
        super().__init__()
        self._controller = controller
        self._token = 0
        self._busy = False
        self._cancel = threading.Event()
        self._history: list[dict] = []
        self._current: MessageBubble | None = None
        self._current_text = ""
        self._status_loaded = False
        self._suggestions: list[str] = []
        self._event.connect(self._on_event)
        self._voice = self._make_voice()
        self._voice.state_changed.connect(self._on_voice_state)
        self._voice.level.connect(lambda level: self._voice_bar.set_level(level))
        self._voice.question.connect(self.ask)
        self._voice.failed.connect(self._on_voice_failed)
        self._build()

    def _make_voice(self) -> voice_io.VoiceConversation:
        return voice_io.VoiceConversation(self)

    # ── build ────────────────────────────────────────────────────────────

    def _build(self):
        t = self._controller.theme
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 24, 24, 16)
        outer.setSpacing(12)

        title = QLabel("Ask Fuku")
        title.setFont(font_scale.font(font_scale.LARGE, True))
        subtitle = QLabel("Ask about stocks, markets and your Fuku Lens data. Answers come from your own data.")
        subtitle.setFont(font_scale.font(font_scale.SMALL, False))
        subtitle.setStyleSheet(f"color: {t.get('text_secondary')};")
        self._clear_btn = QPushButton("New chat")
        self._clear_btn.clicked.connect(self.clear_chat)
        self._voice_switch = ToggleSwitch(t)
        self._voice_switch.setToolTip(
            "Voice mode: speak your question and hear the answer. Your speech is turned into text on this computer."
        )
        self._voice_switch.toggled.connect(self._on_voice_toggled)
        voice_label = QLabel("Voice mode")
        voice_label.setFont(font_scale.font(font_scale.SMALL, False))
        voice_label.setStyleSheet(f"color: {t.get('text_secondary')};")
        trailing = QWidget()
        trailing_row = QHBoxLayout(trailing)
        trailing_row.setContentsMargins(0, 0, 0, 0)
        trailing_row.setSpacing(8)
        trailing_row.addWidget(voice_label)
        trailing_row.addWidget(self._voice_switch)
        trailing_row.addSpacing(12)
        trailing_row.addWidget(self._clear_btn)
        outer.addLayout(page_header(title, subtitle, trailing=trailing))

        self._banner = QLabel("")
        self._banner.setWordWrap(True)
        self._banner.setStyleSheet(
            f"background: {t.get('info_banner_bg')}; color: {t.get('info_banner_text')}; "
            f"border: 1px solid {t.get('info_banner_border')}; border-radius: 8px; padding: 8px 12px;"
        )
        self._banner.hide()
        outer.addWidget(self._banner)

        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFrameShape(QFrame.Shape.NoFrame)
        self._messages = QWidget()
        self._messages_layout = QVBoxLayout(self._messages)
        self._messages_layout.setContentsMargins(0, 0, 8, 0)
        self._messages_layout.setSpacing(10)
        self._messages_layout.addStretch(1)
        self._scroll.setWidget(self._messages)
        outer.addWidget(self._scroll, 1)
        # Follow the newest content, unless the user scrolled up to read.
        self._stick_to_bottom = True
        bar = self._scroll.verticalScrollBar()
        bar.rangeChanged.connect(lambda _lo, hi: self._stick_to_bottom and bar.setValue(hi))
        bar.valueChanged.connect(lambda v: setattr(self, "_stick_to_bottom", v >= bar.maximum() - 24))

        self._welcome = self._build_welcome()
        self._messages_layout.insertWidget(0, self._welcome)

        self._voice_notice = QLabel("")
        self._voice_notice.setWordWrap(True)
        self._voice_notice.setStyleSheet(self._banner.styleSheet())
        self._voice_notice.hide()
        outer.addWidget(self._voice_notice)
        self._voice_bar = VoiceStatusBar(t)
        self._voice_bar.hide()
        outer.addWidget(self._voice_bar)

        row = QHBoxLayout()
        row.setSpacing(8)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Ask a question, e.g. “Which stocks fell the most on the latest trading day?”")
        self._input.setFont(font_scale.font(font_scale.MEDIUM, False))
        self._input.setMinimumHeight(38)
        self._input.setMaxLength(1000)
        self._input.returnPressed.connect(self._send)
        self._send_btn = QPushButton("Send")
        self._send_btn.setMinimumHeight(38)
        self._send_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get('accent')}; color: #ffffff; border: none; "
            f"border-radius: 6px; padding: 0 20px; font-weight: bold; }}"
            f"QPushButton:hover {{ background: {t.get('accent_hover')}; }}"
            f"QPushButton:disabled {{ background: {t.get('button_bg')}; color: {t.get('text_secondary')}; }}"
        )
        self._send_btn.clicked.connect(self._on_send_clicked)
        row.addWidget(self._input, 1)
        row.addWidget(self._send_btn)
        outer.addLayout(row)

        self._live_lbl = QLabel("")
        self._live_lbl.setFont(font_scale.font(font_scale.SMALL, False))
        self._live_lbl.setWordWrap(True)
        outer.addWidget(self._live_lbl)
        self._live_timer = QTimer(self)
        self._live_timer.setInterval(5000)
        self._live_timer.timeout.connect(self._refresh_live_status)
        self._refresh_live_status()

        disclaimer = QLabel("Answers are generated from Fuku Lens data and may contain mistakes. Not investment advice.")
        disclaimer.setFont(font_scale.font(font_scale.SMALL, False))
        disclaimer.setStyleSheet(f"color: {t.get('text_secondary')};")
        outer.addWidget(disclaimer)

    def _build_welcome(self) -> QWidget:
        t = self._controller.theme
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 24, 0, 0)
        v.setSpacing(10)
        hello = QLabel("What would you like to know?")
        hello.setFont(font_scale.font(font_scale.LARGE, True))
        hello.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint = QLabel("Try one of these, or type your own question.")
        hint.setFont(font_scale.font(font_scale.SMALL, False))
        hint.setStyleSheet(f"color: {t.get('text_secondary')};")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        v.addWidget(hello)
        v.addWidget(hint)
        self._chips_grid = QGridLayout()
        self._chips_grid.setSpacing(8)
        v.addLayout(self._chips_grid)
        self._fill_chips(chat_api_default_suggestions())
        return w

    def _fill_chips(self, questions: list[str]) -> None:
        t = self._controller.theme
        while self._chips_grid.count():
            item = self._chips_grid.takeAt(0)
            if item.widget() is not None:
                item.widget().deleteLater()
        for i, q in enumerate(questions[:8]):
            chip = QPushButton(q)
            chip.setCursor(Qt.CursorShape.PointingHandCursor)
            chip.setFont(font_scale.font(font_scale.SMALL, False))
            chip.setStyleSheet(
                f"QPushButton {{ background: {t.get('card_bg')}; color: {t.get('text_primary')}; "
                f"border: 1px solid {t.get('border')}; border-radius: 14px; padding: 8px 14px; text-align: left; }}"
                f"QPushButton:hover {{ border-color: {t.get('accent')}; color: {t.get('accent')}; }}"
            )
            chip.clicked.connect(lambda _=False, text=q: self.ask(text))
            self._chips_grid.addWidget(chip, i // 2, i % 2)

    # ── lifecycle ────────────────────────────────────────────────────────

    def showEvent(self, event):
        super().showEvent(event)
        if not self._status_loaded:
            self._status_loaded = True
            threading.Thread(target=self._load_status, name="chat-status", daemon=True).start()
        self._input.setFocus()
        self._refresh_live_status()
        self._live_timer.start()

    def hideEvent(self, event):
        # The microphone must not stay open behind another screen (or in the tray).
        self._voice.stop()
        self._live_timer.stop()
        super().hideEvent(event)

    # ── live market data (the running LMV) ───────────────────────────────

    def _live_context(self, include_rows: bool = True) -> dict | None:
        """The Live Master View block for a question; None if it can't be built
        (the question is then asked exactly as before this feature existed)."""
        try:
            return self._controller.get_lmv_chat_context(include_rows)
        except Exception:
            return None

    def _refresh_live_status(self, block: dict | None = None):
        t = self._controller.theme
        block = block if block is not None else self._live_context(include_rows=False)
        if block is None:
            self._live_lbl.hide()
            return
        connected, text = lmv_chat_context.summary(block)
        color = t.get("accent") if connected and not block.get("warning") else t.get("text_secondary")
        self._live_lbl.setStyleSheet(f"color: {color};")
        self._live_lbl.setText(("● " if connected else "○ ") + text)
        self._live_lbl.show()

    def _load_status(self):
        try:
            status = chat_api.get_status()
        except (ApiError, NetworkError):
            return  # leave the defaults; /chat/ask reports the real problem if there is one
        self._event.emit(self._token, "_status", status)

    def refresh_theme(self):
        # Inline-styled widgets bake in theme colors at construction (same
        # convention as screens/reports.py), so rebuild around the transcript.
        if self._busy:
            # The in-flight bubble is about to be destroyed; abandon that turn
            # (its events are dropped by the token bump) rather than leave the
            # screen stuck on "busy" with nothing to update.
            self._token += 1
            self._cancel.set()
            self._busy = False
            self._voice.interrupt()
            if self._history and self._history[-1]["role"] == "user":
                self._history.pop()
        history, suggestions = list(self._history), list(self._suggestions)
        # The data rows behind each recorded answer, so a theme switch doesn't drop
        # the "Show data" tables (and with them the tables in a saved PDF).
        details = [
            b.details_data for b in self._bubbles()
            if b.role == "assistant" and not b.is_error and b is not self._current and b.body.full_text().strip()
        ]
        if len(details) != sum(1 for turn in history if turn["role"] == "assistant"):
            details = []
        voice_text = self._voice_bar.text()
        old_layout = self.layout()
        if old_layout is not None:
            QWidget().setLayout(old_layout)  # orphan the old layout + children so they are freed
        self._current = None
        self._build()
        self._history = history
        if suggestions:
            self._fill_chips(suggestions)
        for turn in history:
            bubble = MessageBubble(self._controller.theme, turn["role"], turn["text"])
            if turn["role"] == "assistant" and details:
                kept = details.pop(0)
                if kept:
                    bubble.set_details(kept["columns"], kept["rows"], kept["row_count"], kept["truncated"])
            self._append_bubble(bubble, animate=False)
        if history:
            self._welcome.hide()
        if self._voice.is_on():   # the rebuilt switch and status strip pick the session back up
            self._voice.state_changed.emit(self._voice.state, voice_text)

    # ── voice mode ───────────────────────────────────────────────────────

    def _on_voice_toggled(self, on: bool):
        if on:
            self._voice_notice.hide()
            self._voice.start()
        else:
            self._voice.stop()

    def _on_voice_state(self, state: str, text: str):
        on = state != voice_io.OFF
        self._voice_bar.set_state(state, text)
        self._voice_bar.setVisible(on)
        if self._voice_switch.isChecked() != on:
            self._voice_switch.blockSignals(True)
            self._voice_switch.setChecked(on)
            self._voice_switch.blockSignals(False)
        self._sync_send_btn()

    def _on_voice_failed(self, message: str):
        self._on_voice_state(voice_io.OFF, "")
        self._voice_notice.setText(f"Voice mode is off: {message}")
        self._voice_notice.show()

    def _sync_send_btn(self):
        # "Stop" cancels a running question, and cuts a spoken answer short.
        stop = self._busy or self._voice.state == voice_io.SPEAKING
        self._send_btn.setText("Stop" if stop else "Send")

    # ── asking ───────────────────────────────────────────────────────────

    def _on_send_clicked(self):
        if self._busy:
            self._cancel.set()  # the button is "Stop" while a question is running
            self._voice.interrupt()
        elif self._voice.state == voice_io.SPEAKING:
            self._voice.interrupt()
        else:
            self._send()

    def _send(self):
        text = self._input.text().strip()
        if text and not self._busy:
            self._input.clear()
            self.ask(text)

    def ask(self, question: str) -> None:
        question = question.strip()
        if not question or self._busy:
            return
        self._busy = True
        self._cancel = threading.Event()
        self._welcome.hide()
        self._voice.begin_turn()
        self._sync_send_btn()
        self._input.setEnabled(False)

        self._append_bubble(MessageBubble(self._controller.theme, "user", question))
        bubble = MessageBubble(self._controller.theme, "assistant")
        bubble.start_thinking()
        self._append_bubble(bubble)
        self._current, self._current_text = bubble, ""

        history = self._history[-(_HISTORY_TURNS_SENT * 2):]
        self._history.append({"role": "user", "text": question})
        live = self._live_context()   # snapshot of the LMV grid at the moment of asking (GUI thread)
        if live is not None:
            self._refresh_live_status(live)
        threading.Thread(
            target=self._stream, args=(self._token, question, history, self._cancel, live),
            name="chat-ask", daemon=True,
        ).start()

    def _stream(self, token: int, question: str, history: list, cancel: threading.Event, live: dict | None = None):
        try:
            for event, data in chat_api.ask(question, history, live):
                if cancel.is_set():
                    break
                self._event.emit(token, event, data)
            else:
                self._event.emit(token, "_end", {})
                return
            self._event.emit(token, "_cancelled", {})
        except ApiError as exc:
            self._event.emit(token, "error", {"message": exc.detail})
        except NetworkError as exc:
            self._event.emit(token, "error", {"message": f"Could not reach the server. {exc}"})
        except Exception as exc:  # never let the worker die silently with the UI stuck on "thinking"
            self._event.emit(token, "error", {"message": f"Something went wrong: {exc}"})

    # ── events from the stream ───────────────────────────────────────────

    def _on_event(self, token: int, event: str, data):
        if token != self._token:
            return
        if event == "_status":
            self._apply_status(data)
            return
        if event == "_translated":
            bubble, target, text, error = data
            if shiboken6.isValid(bubble):   # the bubble may be gone (theme rebuild)
                if error:
                    bubble.translation_failed(error)
                else:
                    bubble.set_translation(target, text)
            return
        bubble = self._current
        if bubble is None:
            return
        if event == "stage":
            bubble.set_stage(data.get("stage", ""))
        elif event == "rows":
            bubble.set_details(
                data.get("columns", []), data.get("rows", []),
                data.get("row_count", 0), bool(data.get("truncated")),
            )
        elif event == "token":
            self._current_text += data.get("text", "")
            bubble.add_text(data.get("text", ""))
            self._voice.answer_text(data.get("text", ""))
        elif event == "answer":
            self._current_text = data.get("text", "")
            bubble.add_text(self._current_text)
            self._voice.answer_text(self._current_text)
        elif event == "error":
            bubble.set_error(data.get("message", "Something went wrong."))
            self._voice.answer_text(data.get("message", "Something went wrong."))
            self._finish_turn(record=False)
        elif event in ("_end", "_cancelled"):
            if event == "_cancelled" and not self._current_text:
                bubble.set_error("Stopped.")
                self._finish_turn(record=False)
            else:
                bubble.finish()
                self._finish_turn(record=bool(self._current_text))
        elif event == "done":
            pass  # _end follows when the stream closes

    def _finish_turn(self, record: bool):
        if record:
            self._history.append({"role": "assistant", "text": self._current_text})
        elif self._history and self._history[-1]["role"] == "user":
            self._history.pop()  # a failed question shouldn't pollute follow-ups
        self._current = None
        self._busy = False
        self._voice.answer_done()
        self._sync_send_btn()
        self._input.setEnabled(True)
        self._input.setFocus()

    def _apply_status(self, status: dict):
        self._suggestions = list(status.get("suggested_questions") or [])
        if self._suggestions:
            self._fill_chips(self._suggestions)
        if not status.get("enabled", True):
            self._banner.setText("The AI assistant is not enabled for this deployment yet.")
            self._banner.show()
            self._send_btn.setEnabled(False)
            self._input.setEnabled(False)
            self._voice.stop()
            self._voice_switch.setEnabled(False)

    # ── answer options: save as PDF / translate ──────────────────────────

    def _bubbles(self) -> list[MessageBubble]:
        """The transcript in order, top to bottom."""
        out = []
        for i in range(self._messages_layout.count()):
            row = self._messages_layout.itemAt(i).widget()
            bubble = row.findChild(MessageBubble) if row is not None and row is not self._welcome else None
            if bubble is not None:
                out.append(bubble)
        return out

    def export_turns(self) -> list[dict]:
        """What "Save chat as PDF" writes: every message as it is shown (an answer
        switched to Tamil or Tanglish is saved that way) with the data rows behind it. An
        answer still being written is left out."""
        turns = []
        for bubble in self._bubbles():
            text = bubble.body.full_text().strip()
            if bubble is self._current or not text:
                continue
            turns.append({
                "role": bubble.role, "text": text, "error": bubble.is_error,
                "details": bubble.details_data,
            })
        return turns

    def save_chat_pdf(self):
        turns = self.export_turns()
        if not turns:
            return
        path, _unused = QFileDialog.getSaveFileName(
            self, "Save chat as PDF", chat_export.default_filename(), "PDF Files (*.pdf)",
        )
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        self._export_pdf(turns, path)

    def _export_pdf(self, turns: list[dict], path: str):
        from services.report_engine import pdf_export   # QtWebEngine: only loaded when a PDF is made

        def on_done(success: bool, error: str | None):
            if not shiboken6.isValid(self):
                return
            if success:
                QMessageBox.information(self, "Chat saved", f"Saved to:\n{path}")
            else:
                QMessageBox.warning(self, "Save failed", error or "Unknown error generating the PDF.")

        pdf_export.render_to_pdf(
            chat_export.build_html(turns), path, on_done, margins_mm=chat_export.PAGE_MARGINS_MM,
        )

    def _translate_bubble(self, bubble: MessageBubble, target: str):
        text = bubble.original_text()
        threading.Thread(
            target=self._translate_worker, args=(self._token, bubble, target, text),
            name="chat-translate", daemon=True,
        ).start()

    def _translate_worker(self, token: int, bubble: MessageBubble, target: str, text: str):
        translated, error = "", ""
        try:
            translated = chat_api.translate(text, target)
            if not translated.strip():
                error = "The server sent back an empty translation."
        except ApiError as exc:
            # 404: no translate endpoint yet; 422: it doesn't know this language yet.
            error = ("Translation needs a newer server version." if exc.status_code in (404, 405, 422)
                     else exc.detail)
        except NetworkError as exc:
            error = f"Could not reach the server. {exc}"
        except Exception as exc:
            error = str(exc)
        self._event.emit(token, "_translated", (bubble, target, translated, error))

    # ── helpers ──────────────────────────────────────────────────────────

    def _append_bubble(self, bubble: MessageBubble, animate: bool = True):
        is_user = bubble.role == "user"
        if not is_user:
            bubble.save_requested.connect(self.save_chat_pdf)
            bubble.translate_requested.connect(lambda target, b=bubble: self._translate_bubble(b, target))
        row = QWidget()
        h = QHBoxLayout(row)
        h.setContentsMargins(0, 0, 0, 0)
        if is_user:
            h.addStretch(1)
            h.addWidget(bubble)
        else:
            h.addWidget(bubble)
            h.addStretch(1)
        self._messages_layout.insertWidget(self._messages_layout.count() - 1, row)
        if animate:
            bubble.fade_in()
        QTimer.singleShot(0, lambda: self._scroll.verticalScrollBar().setValue(self._scroll.verticalScrollBar().maximum()))

    def clear_chat(self):
        self._token += 1  # in-flight events from the old conversation are dropped
        self._cancel.set()
        self._history.clear()
        self._current = None
        self._busy = False
        self._voice.interrupt()
        self._sync_send_btn()
        self._input.setEnabled(not self._banner.isVisible())
        while self._messages_layout.count() > 1:
            item = self._messages_layout.takeAt(0)
            w = item.widget()
            if w is None:
                continue
            if w is self._welcome:
                w.hide()
            else:
                w.deleteLater()
        self._messages_layout.insertWidget(0, self._welcome)
        self._welcome.show()


def chat_api_default_suggestions() -> list[str]:
    """Shown until /chat/status returns the server's own list (or if it fails)."""
    return [
        "Which stocks fell the most on the latest trading day?",
        "Show the last 10 closes for RELIANCE",
        "Which of my strategy alerts are still open?",
        "What does open interest tell a trader?",
    ]
