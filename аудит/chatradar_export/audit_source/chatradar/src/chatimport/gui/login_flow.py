"""Telegram sign-in inside the window: a modal dialog over `telegram.client.login`.

`login` is a coroutine that asks for the phone, the code and the 2FA password through plain
callables. Here they run on a worker thread with its own event loop; each callable tells the
dialog (a queued signal) which step to show and then blocks on a queue until the dialog
answers, or until the owner cancels, which unblocks it with an exception. The phone, the code
and the password live only in the dialog's own widgets and in that queue: they are never
logged, stored or echoed, and every field is cleared when the dialog closes.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import re
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from PySide6.QtCore import QObject, Qt, Signal, Slot
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLineEdit, QVBoxLayout, QWidget

from chatimport.config import ConfigError, load_config
from chatimport.control import AlreadyRunning, acquire_instance_lock
from chatimport.gui.i18n import tr
from chatimport.gui.tokens import SPACE
from chatimport.gui.widgets.base import Tone, bind_kit
from chatimport.gui.widgets.button import Button
from chatimport.gui.widgets.callout import Callout
from chatimport.gui.widgets.chip import Chip
from chatimport.gui.widgets.labels import make_label
from chatimport.gui.widgets.progress import BusyStripe

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import TelegramConfig
    from chatimport.gui.context import GuiContext
    from chatimport.gui.pages.settings_support import LoginFunc, ServiceControl, SettingsHooks

log = logging.getLogger(__name__)

DIALOG_WIDTH: Final = 460
PHONE_PATTERN: Final = re.compile(r"\+?[0-9 ()\-]{6,24}")
MIN_PHONE_DIGITS: Final = 7
STEPS: Final = ("phone", "code", "password", "done")

_FAILURES: Final[dict[str, str]] = {
    "PhoneNumberInvalidError": "invalid_phone",
    "PhoneNumberBannedError": "banned",
    "PhoneNumberFloodError": "flood",
    "PhoneNumberUnoccupiedError": "invalid_phone",
    "FloodWaitError": "flood",
    "FloodWait": "flood",
    "PhoneCodeInvalidError": "wrong_code",
    "PhoneCodeExpiredError": "wrong_code",
    "PhoneCodeEmptyError": "wrong_code",
    "PasswordHashInvalidError": "wrong_password",
    "ApiIdInvalidError": "api",
    "ApiIdPublishedFloodError": "api",
    "RuntimeError": "too_many",
    "ConnectionError": "network",
    "OSError": "network",
    "TimeoutError": "network",
    "RPCTimeoutError": "network",
    "AlreadyRunning": "busy",
    "ChatImportError": "generic",
}


class LoginCancelled(Exception):
    """The owner cancelled; raised inside the prompt so `login` unwinds and disconnects."""


@dataclass(frozen=True, slots=True)
class Failure:
    kind: str
    seconds: int | None = None


def classify_failure(error: BaseException) -> Failure:
    """Map a login failure to a message key by exception class name, following `__cause__`."""
    seen: BaseException | None = error
    while seen is not None:
        if isinstance(seen, LoginCancelled):
            return Failure("cancelled")
        for cls in type(seen).__mro__:
            kind = _FAILURES.get(cls.__name__)
            if kind is not None and cls.__name__ != "ChatImportError":
                seconds = getattr(seen, "seconds", None)
                return Failure(kind, seconds if isinstance(seconds, int) else None)
        seen = seen.__cause__
    return Failure("generic")


class LoginSession(QObject):
    """One login attempt on its own thread; talks to the dialog through signals and a queue."""

    prompted = Signal(str, int)
    finished = Signal(str, str, int)

    def __init__(
        self,
        config: TelegramConfig,
        session_path: Path,
        lock_file: Path,
        login: LoginFunc,
        phone: str,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._config = config
        self._session_path = session_path
        self._lock_file = lock_file
        self._login = login
        self._phone = phone
        self._answers: queue.Queue[str | None] = queue.Queue()
        self._attempts: dict[str, int] = {}
        self._cancelled = threading.Event()
        self._thread = threading.Thread(target=self._run, name="chatimport-login", daemon=True)

    @property
    def running(self) -> bool:
        return self._thread.is_alive()

    def start(self) -> None:
        self._thread.start()

    def answer(self, text: str) -> None:
        self._answers.put(text)

    def cancel(self) -> None:
        self._cancelled.set()
        self._answers.put(None)

    def _ask(self, kind: str) -> str:
        if kind == "phone" and self._phone:
            phone, self._phone = self._phone, ""
            return phone
        if self._cancelled.is_set():
            raise LoginCancelled
        attempt = self._attempts.get(kind, 0) + 1
        self._attempts[kind] = attempt
        self.prompted.emit(kind, attempt)
        answer = self._answers.get()
        if answer is None or self._cancelled.is_set():
            raise LoginCancelled
        return answer

    def _run(self) -> None:
        handle, failure = "", Failure("")
        try:
            lock = acquire_instance_lock(self._lock_file)
        except AlreadyRunning as error:
            self.finished.emit("", classify_failure(error).kind, 0)
            return
        try:
            handle = asyncio.run(self._login_coroutine())
        except BaseException as error:
            failure = classify_failure(error)
            if failure.kind != "cancelled":
                log.warning("sign-in failed: %s", type(error).__name__)
        finally:
            lock.release()
            self._phone = ""
        self.finished.emit(handle, failure.kind, failure.seconds or 0)

    async def _login_coroutine(self) -> str:
        return await self._login(
            self._config,
            self._session_path,
            prompt_phone=lambda: self._ask("phone"),
            prompt_code=lambda: self._ask("code"),
            prompt_password=lambda: self._ask("password"),
        )


class LoginDialog(QDialog):
    """Phone -> code -> (password) -> done. Modal; closing it mid-request cancels cleanly."""

    signed_in = Signal(str)

    def __init__(
        self,
        gui: GuiContext,
        hooks: SettingsHooks,
        control: ServiceControl | None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.gui = gui
        self._hooks = hooks
        self._control = control
        self._session: LoginSession | None = None
        self._stage = "stopping"
        self._closing = False
        self._signed_in = False
        self._was_running = control is not None and control.is_alive
        self._step = "phone"
        kit = gui.kit
        self.setModal(True)
        self.setMinimumWidth(kit.px(DIALOG_WIDTH))

        self._chips = {name: Chip(kit, "", "muted") for name in STEPS}
        self._heading = make_label("", "section", wrap=True)
        self._explain = make_label("", "muted", wrap=True)
        self._input = QLineEdit()
        self._input.returnPressed.connect(self._submit)
        self._problem = Callout(kit, "danger", "")
        self._problem.hide()
        self._busy = BusyStripe(kit)
        self._cancel = Button(kit)
        self._cancel.clicked.connect(self.reject)
        self._next = Button(kit, variant="primary", icon_name="send")
        self._next.clicked.connect(self._submit)

        chips = QHBoxLayout()
        chips.setSpacing(kit.px(SPACE[3]))
        for chip in self._chips.values():
            chips.addWidget(chip)
        chips.addStretch(1)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        buttons.addWidget(self._cancel)
        buttons.addWidget(self._next)
        column = QVBoxLayout(self)
        gap = kit.px(SPACE[6])
        column.setContentsMargins(gap, gap, gap, gap)
        column.setSpacing(gap)
        column.addLayout(chips)
        column.addWidget(self._heading)
        column.addWidget(self._explain)
        column.addWidget(self._input)
        column.addWidget(self._problem)
        column.addWidget(self._busy)
        column.addLayout(buttons)
        bind_kit(kit, language=self._retranslate)
        self._config = self._load_config()
        self._render()
        self._begin()

    @property
    def stage(self) -> str:
        return self._stage

    def _load_config(self) -> TelegramConfig:
        try:
            return load_config(self.gui.service.paths.config_file).telegram
        except ConfigError:
            return self.gui.service.config.telegram

    def _begin(self) -> None:
        if self._control is not None and self._was_running:
            self._stage = "stopping"
            self._render()
            self._control.stop_service(self._service_stopped)
        else:
            self._service_stopped()

    def _service_stopped(self) -> None:
        if self._closing:
            self._finish_closing()
            return
        self._enter("phone")

    def _enter(self, stage: str, attempt: int = 1) -> None:
        self._stage = stage
        self._step = stage
        self._input.clear()
        self._render()
        if attempt > 1:
            self._show_problem(f"settings.login.again.{stage}")
        self._input.setFocus()

    def _retranslate(self) -> None:
        self._render()

    def _render(self) -> None:
        stage = self._stage
        reached = STEPS.index(self._step)
        for index, (name, chip) in enumerate(self._chips.items()):
            chip.set_text(tr(f"settings.login.step.{name}"))
            tone: Tone = "success" if index < reached else "info" if index == reached else "muted"
            if stage == "done":
                tone = "success"
            chip.set_tone(tone)
        self.setWindowTitle(tr("settings.login.title"))
        waiting = stage in ("stopping", "working", "cancelling")
        self._heading.setText(tr(f"settings.login.heading.{stage}"))
        self._explain.setText(tr(f"settings.login.text.{stage}"))
        self._input.setVisible(stage in ("phone", "code", "password"))
        self._input.setEnabled(not waiting)
        self._input.setEchoMode(
            QLineEdit.EchoMode.Password if stage == "password" else QLineEdit.EchoMode.Normal
        )
        self._input.setPlaceholderText(tr(f"settings.login.placeholder.{stage}"))
        self._input.setAccessibleName(tr(f"settings.login.heading.{stage}"))
        self._busy.set_active(waiting)
        self._next.setVisible(stage != "done")
        self._next.setEnabled(not waiting)
        self._next.setText(tr("settings.login.next"))
        self._cancel.setText(tr("common.close") if stage == "done" else tr("common.cancel"))
        self._cancel.setEnabled(stage != "cancelling")
        if stage in ("done",):
            self._problem.hide()

    def _show_problem(self, key: str, **params: object) -> None:
        self._problem.set_body(tr(key, **params))
        self._problem.show()
        self.adjustSize()

    def _valid_phone(self, text: str) -> bool:
        digits = sum(char.isdigit() for char in text)
        return PHONE_PATTERN.fullmatch(text) is not None and digits >= MIN_PHONE_DIGITS

    def _submit(self) -> None:
        stage = self._stage
        text = self._input.text().strip()
        if stage not in ("phone", "code", "password") or not text:
            return
        self._problem.hide()
        if stage == "phone":
            if not self._valid_phone(text):
                self._show_problem("settings.login.err.phone_format")
                return
            self._start_session(text)
        elif self._session is not None:
            self._session.answer(text)
        self._stage = "working"
        self._input.clear()
        self._render()

    def _start_session(self, phone: str) -> None:
        ctx = self.gui.service
        session = LoginSession(
            self._config,
            ctx.paths.session_file,
            ctx.paths.lock_file,
            self._hooks.login,
            phone,
            self,
        )
        session.prompted.connect(self._on_prompt, Qt.ConnectionType.QueuedConnection)
        session.finished.connect(self._on_finished, Qt.ConnectionType.QueuedConnection)
        self._session = session
        session.start()

    @Slot(str, int)
    def _on_prompt(self, kind: str, attempt: int) -> None:
        if self._closing:
            return
        self._enter(kind, attempt)

    @Slot(str, str, int)
    def _on_finished(self, handle: str, failure: str, seconds: int) -> None:
        self._session = None
        self._input.clear()
        if self._closing:
            self._finish_closing()
            return
        if failure:
            self._enter("phone")
            self._show_problem(f"settings.login.err.{failure}", seconds=seconds)
            return
        self._signed_in = True
        self._enter("done")
        self._explain.setText(tr("settings.login.text.done", handle=handle))
        self.signed_in.emit(handle)
        if self._control is not None:
            self._control.start_service()

    def reject(self) -> None:
        if self._stage == "done":
            self.accept()
            return
        self._closing = True
        if self._session is not None and self._session.running:
            self._stage = "cancelling"
            self._render()
            self._session.cancel()
            return
        if self._stage == "stopping":
            self._render()
            return
        self._finish_closing()

    def _finish_closing(self) -> None:
        self._input.clear()
        if self._control is not None and self._was_running and not self._signed_in:
            self._control.start_service()
        QDialog.reject(self)

    def done(self, result: int) -> None:
        self._input.clear()
        super().done(result)
