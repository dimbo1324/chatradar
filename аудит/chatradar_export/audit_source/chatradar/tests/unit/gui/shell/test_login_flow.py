# pyright: reportPrivateUsage=false, reportUnknownLambdaType=false, reportUnknownArgumentType=false
from __future__ import annotations

import gc
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from chatimport.control import AlreadyRunning, acquire_instance_lock
from chatimport.gui.login_flow import (
    Failure,
    LoginCancelled,
    LoginDialog,
    LoginSession,
    classify_failure,
)
from chatimport.gui.pages.settings_support import SettingsHooks
from chatimport.ports import ChatImportError

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterator

    from PySide6.QtWidgets import QApplication

    from chatimport.context import ServiceContext
    from chatimport.gui.context import GuiContext

PHONE = "+1 555 010 0000"

type Prompt = Callable[[], str]


@pytest.fixture(autouse=True)
def join_login_threads() -> Iterator[None]:
    gc.collect()
    gc.disable()
    yield
    gc.enable()
    for thread in threading.enumerate():
        if thread.name == "chatimport-login":
            thread.join(5)
            assert not thread.is_alive()


def named(name: str, base: type[BaseException] = Exception) -> type[BaseException]:
    return type(name, (base,), {})


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("PhoneNumberInvalidError", "invalid_phone"),
        ("PhoneCodeExpiredError", "wrong_code"),
        ("PasswordHashInvalidError", "wrong_password"),
        ("ApiIdInvalidError", "api"),
        ("TimeoutError", "network"),
        ("AlreadyRunning", "busy"),
    ],
)
def test_classify_by_class_name(name: str, kind: str) -> None:
    assert classify_failure(named(name)("x")) == Failure(kind)


def test_classify_special_cases() -> None:
    flood = named("FloodWaitError")("x")
    flood.seconds = 30  # type: ignore[attr-defined]
    assert classify_failure(flood) == Failure("flood", 30)
    odd = named("FloodWaitError")("x")
    odd.seconds = "soon"  # type: ignore[attr-defined]
    assert classify_failure(odd) == Failure("flood", None)
    assert classify_failure(LoginCancelled()).kind == "cancelled"
    assert classify_failure(named("Mine", RuntimeError)("x")).kind == "too_many"
    assert classify_failure(ChatImportError("x")).kind == "generic"
    assert classify_failure(ValueError("x")).kind == "generic"
    wrapped = ChatImportError("outer")
    wrapped.__cause__ = named("PhoneNumberBannedError")("inner")
    assert classify_failure(wrapped).kind == "banned"
    cancelled = ValueError("outer")
    cancelled.__cause__ = LoginCancelled()
    assert classify_failure(cancelled).kind == "cancelled"


def make_session(
    ctx: ServiceContext,
    login: Callable[..., Awaitable[str]],
    phone: str = PHONE,
) -> LoginSession:
    return LoginSession(
        ctx.config.telegram, ctx.paths.session_file, ctx.paths.lock_file, login, phone
    )


def run_session(session: LoginSession, qapp: QApplication) -> list[tuple[str, str, int]]:
    finished: list[tuple[str, str, int]] = []
    session.finished.connect(lambda h, f, s: finished.append((h, f, s)))
    session.start()
    session._thread.join(5)
    assert not session.running
    qapp.processEvents()
    return finished


def test_session_success_with_queued_answers(
    service_context: ServiceContext, qapp: QApplication
) -> None:
    seen: list[tuple[str, str, str]] = []

    async def login(
        config: Any,
        path: Any,
        *,
        prompt_phone: Prompt,
        prompt_code: Prompt,
        prompt_password: Prompt,
    ) -> str:
        seen.append((prompt_phone(), prompt_code(), prompt_password()))
        return "@someone"

    session = make_session(service_context, login)
    prompts: list[tuple[str, int]] = []
    session.prompted.connect(lambda kind, attempt: prompts.append((kind, attempt)))
    session.answer("111")
    session.answer("secret")
    assert run_session(session, qapp) == [("@someone", "", 0)]
    assert seen == [(PHONE, "111", "secret")]
    assert prompts == [("code", 1), ("password", 1)]


def test_session_asks_phone_when_none_given(
    service_context: ServiceContext, qapp: QApplication
) -> None:
    async def login(config: Any, path: Any, *, prompt_phone: Prompt, **_: Prompt) -> str:
        return prompt_phone()

    session = make_session(service_context, login, phone="")
    session.answer(PHONE)
    assert run_session(session, qapp) == [(PHONE, "", 0)]


def test_session_cancel_before_prompt(service_context: ServiceContext, qapp: QApplication) -> None:
    async def login(config: Any, path: Any, *, prompt_code: Prompt, **_: Prompt) -> str:
        return prompt_code()

    session = make_session(service_context, login)
    session.cancel()
    assert run_session(session, qapp) == [("", "cancelled", 0)]


def test_session_cancel_while_waiting(service_context: ServiceContext, qapp: QApplication) -> None:
    waiting = threading.Event()

    async def login(config: Any, path: Any, *, prompt_code: Prompt, **_: Prompt) -> str:
        return prompt_code()

    session = make_session(service_context, login)
    session.prompted.connect(lambda kind, attempt: waiting.set())
    finished: list[tuple[str, str, int]] = []
    session.finished.connect(lambda h, f, s: finished.append((h, f, s)))
    session.start()
    pump(qapp, waiting.is_set)
    session.cancel()
    session._thread.join(5)
    qapp.processEvents()
    assert finished == [("", "cancelled", 0)]


def test_session_failure_is_classified(
    service_context: ServiceContext, qapp: QApplication, caplog: pytest.LogCaptureFixture
) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        error = named("FloodWaitError")("never logged")
        error.seconds = 42  # type: ignore[attr-defined]
        raise error

    session = make_session(service_context, login)
    assert run_session(session, qapp) == [("", "flood", 42)]
    assert "never logged" not in caplog.text
    assert "FloodWaitError" in caplog.text


def test_session_refused_while_service_holds_the_lock(
    service_context: ServiceContext, qapp: QApplication
) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    held = acquire_instance_lock(service_context.paths.lock_file)
    try:
        session = make_session(service_context, login)
        assert run_session(session, qapp) == [("", "busy", 0)]
    finally:
        held.release()
    assert issubclass(AlreadyRunning, ChatImportError)


class FakeControl:
    def __init__(self, context: ServiceContext, alive: bool) -> None:
        self.context = context
        self.is_alive = alive
        self.started = 0
        self.callback: Callable[[], None] | None = None

    def start_service(self) -> bool:
        self.started += 1
        return True

    def stop_service(self, on_stopped: Callable[[], None] | None = None) -> None:
        self.callback = on_stopped

    def restart(self) -> None:
        return None


def pump(qapp: QApplication, condition: Callable[[], bool], timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        qapp.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("condition not reached")
        time.sleep(0.002)


def settle() -> None:
    for thread in threading.enumerate():
        if thread.name == "chatimport-login":
            thread.join(5)


def make_dialog(
    gui: GuiContext,
    login: Callable[..., Awaitable[str]],
    control: FakeControl | None = None,
) -> LoginDialog:
    hooks = SettingsHooks(login=login)
    return LoginDialog(gui, hooks, control)  # type: ignore[arg-type]


def type_and_submit(dialog: LoginDialog, text: str) -> None:
    dialog._input.setText(text)
    dialog._submit()


def test_dialog_full_flow_with_retry_and_password(gui: GuiContext, qapp: QApplication) -> None:
    async def login(
        config: Any,
        path: Any,
        *,
        prompt_phone: Prompt,
        prompt_code: Prompt,
        prompt_password: Prompt,
    ) -> str:
        prompt_phone()
        prompt_code()
        prompt_code()
        prompt_password()
        return "@someone"

    control = FakeControl(gui.service, alive=False)
    dialog = make_dialog(gui, login, control)
    signed: list[str] = []
    dialog.signed_in.connect(signed.append)
    assert dialog.stage == "phone"
    type_and_submit(dialog, "")
    type_and_submit(dialog, "abc")
    assert not dialog._problem.isHidden()
    assert dialog.stage == "phone"
    type_and_submit(dialog, PHONE)
    assert dialog.stage == "working"
    pump(qapp, lambda: dialog.stage == "code")
    type_and_submit(dialog, "1")
    pump(qapp, lambda: dialog._problem.isHidden() is False and dialog.stage == "code")
    type_and_submit(dialog, "2")
    pump(qapp, lambda: dialog.stage == "password")
    type_and_submit(dialog, "pw")
    pump(qapp, lambda: dialog.stage == "done")
    settle()
    assert signed == ["@someone"]
    assert control.started == 1
    assert dialog._input.text() == ""
    gui.language.set_language("ru")
    dialog.reject()
    assert dialog.result() == 1
    settle()


def test_dialog_failure_returns_to_phone(gui: GuiContext, qapp: QApplication) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        raise named("PhoneNumberBannedError")("x")

    dialog = make_dialog(gui, login)
    type_and_submit(dialog, PHONE)
    pump(qapp, lambda: dialog.stage == "phone" and not dialog._problem.isHidden())
    assert dialog._session is None
    settle()


def test_dialog_cancel_mid_request(gui: GuiContext, qapp: QApplication) -> None:
    async def login(config: Any, path: Any, *, prompt_code: Prompt, **_: Prompt) -> str:
        return prompt_code()

    dialog = make_dialog(gui, login)
    rejected: list[bool] = []
    dialog.rejected.connect(lambda: rejected.append(True))
    type_and_submit(dialog, PHONE)
    pump(qapp, lambda: dialog.stage == "code")
    dialog.reject()
    assert dialog.stage == "cancelling"
    pump(qapp, lambda: rejected == [True])
    dialog._on_prompt("code", 1)
    settle()


def test_dialog_cancel_when_idle_and_when_done(gui: GuiContext) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    idle = make_dialog(gui, login)
    rejected: list[bool] = []
    idle.rejected.connect(lambda: rejected.append(True))
    idle.reject()
    assert rejected == [True]
    done = make_dialog(gui, login)
    done._enter("done")
    accepted: list[bool] = []
    done.accepted.connect(lambda: accepted.append(True))
    done.reject()
    assert accepted == [True]
    done.done(0)


def test_dialog_waits_for_service_to_stop(gui: GuiContext, qapp: QApplication) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    control = FakeControl(gui.service, alive=True)
    dialog = make_dialog(gui, login, control)
    assert dialog.stage == "stopping"
    type_and_submit(dialog, PHONE)
    assert dialog.stage == "stopping"
    assert control.callback is not None
    control.callback()
    assert dialog.stage == "phone"

    closing = FakeControl(gui.service, alive=True)
    second = make_dialog(gui, login, closing)
    second.reject()
    assert second.stage == "stopping"
    assert closing.callback is not None
    closing.callback()
    assert closing.started == 1


def test_dialog_close_without_session_restarts_nothing_after_sign_in(gui: GuiContext) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    control = FakeControl(gui.service, alive=True)
    dialog = make_dialog(gui, login, control)
    assert control.callback is not None
    control.callback()
    dialog._signed_in = True
    dialog.reject()
    assert control.started == 0


def test_dialog_unstarted_session_does_not_block_close(gui: GuiContext) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    dialog = make_dialog(gui, login)
    dialog._session = make_session(gui.service, login)
    dialog._stage = "code"
    type_and_submit(dialog, "123")
    assert dialog.stage == "working"
    dialog.reject()
    assert dialog.result() == 0


def test_dialog_ignores_bad_config(gui: GuiContext) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    gui.service.paths.config_file.parent.mkdir(parents=True, exist_ok=True)
    gui.service.paths.config_file.write_text("[telegram\nbroken", encoding="utf-8")
    dialog = make_dialog(gui, login)
    assert dialog._config == gui.service.config.telegram


@pytest.mark.parametrize(
    ("text", "valid"),
    [(PHONE, True), ("+12", False), ("12345678", True), ("abc 1234567", False)],
)
def test_phone_validation(gui: GuiContext, text: str, valid: bool) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "x"

    assert make_dialog(gui, login)._valid_phone(text) is valid


def test_dialog_success_without_control_and_stray_answer(
    gui: GuiContext, qapp: QApplication
) -> None:
    async def login(config: Any, path: Any, **_: Prompt) -> str:
        return "@someone"

    dialog = make_dialog(gui, login)
    dialog._enter("code")
    type_and_submit(dialog, "123")
    assert dialog.stage == "working"
    dialog._enter("phone")
    type_and_submit(dialog, PHONE)
    pump(qapp, lambda: dialog.stage == "done")
    settle()
