"""The service's commands: one registry for the control folder and the tray, a typed argument
object per command, and the handlers themselves."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import TYPE_CHECKING, Any, Final, Protocol, Self

from chatimport.integrity import ERROR, INFO, WARNING, check_folder
from chatimport.offline import lower_floor_state, resolve_chat_selector
from chatimport.ports import ChatImportError
from chatimport.status import format_status_lines
from chatimport.storage.layout import iter_chat_folders
from chatimport.storage.state import StateUnreadable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Mapping
    from contextlib import AbstractAsyncContextManager

    from chatimport.context import ServiceContext
    from chatimport.integrity import CheckIssue
    from chatimport.ports import Clock
    from chatimport.runtime import ChatController
    from chatimport.service_runtime import ServiceRuntime

log = logging.getLogger(__name__)

_SEVERITY_RANK: Final = {ERROR: 0, WARNING: 1, INFO: 2}


@dataclass(frozen=True, slots=True)
class CommandResult:
    ok: bool
    message: str = ""
    data: dict[str, Any] = field(default_factory=dict[str, Any])


type Handler = Callable[[dict[str, Any]], Awaitable[CommandResult]]
type ChatSelector = int | str | None


async def finish[T](task: asyncio.Future[T]) -> T:
    """Await `task`; if the caller is cancelled, wait for `task` to finish first and then
    re-raise. Work in a thread cannot be stopped, so locks and restarts must wait for it."""
    cancelled = False
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError:
            cancelled = True
    if cancelled:
        if not task.cancelled():
            task.exception()
        raise asyncio.CancelledError
    return task.result()


async def in_thread[**P, T](func: Callable[P, T], *args: P.args, **kwargs: P.kwargs) -> T:
    return await finish(asyncio.ensure_future(asyncio.to_thread(func, *args, **kwargs)))


def _whole_number(args: Mapping[str, Any], name: str) -> int | None:
    value = args.get(name)
    if value is None:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(value, str):
        with contextlib.suppress(ValueError):
            return int(value.strip())
    raise ChatImportError(f"{name} must be a whole number")


def _chat(args: Mapping[str, Any]) -> ChatSelector:
    value = args.get("chat")
    if value is None or value == "":
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    return str(value)


@dataclass(frozen=True, slots=True)
class NoArgs:
    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Self:
        return cls()


@dataclass(frozen=True, slots=True)
class ChatArgs:
    chat: ChatSelector = None

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Self:
        return cls(_chat(args))


@dataclass(frozen=True, slots=True)
class TrimArgs:
    pct: int
    chat: ChatSelector = None

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Self:
        pct = _whole_number(args, "pct")
        if pct is None:
            raise ChatImportError("pct is required")
        return cls(pct, _chat(args))


@dataclass(frozen=True, slots=True)
class RecheckArgs:
    days: int | None = None
    chat: ChatSelector = None

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Self:
        days = _whole_number(args, "days")
        if days is not None and days < 1:
            raise ChatImportError("days must be at least 1")
        return cls(days, _chat(args))


@dataclass(frozen=True, slots=True)
class CheckArgs:
    repair: bool = False

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Self:
        return cls(bool(args.get("repair", False)))


@dataclass(frozen=True, slots=True)
class SetRootArgs:
    path: str
    move: bool = False

    @classmethod
    def parse(cls, args: Mapping[str, Any]) -> Self:
        raw = args.get("path")
        if not isinstance(raw, str) or not raw.strip():
            raise ChatImportError("path is required")
        return cls(raw.strip(), bool(args.get("move", False)))


class ServiceHost(Protocol):
    """What the commands need from the running application."""

    @property
    def ctx(self) -> ServiceContext: ...

    @property
    def clock(self) -> Clock: ...

    def runtime(self) -> ServiceRuntime: ...

    def reload_config(self) -> None: ...

    def request_shutdown(self) -> None: ...

    async def change_root(self, args: SetRootArgs) -> CommandResult: ...


type _Method[A] = Callable[[ServiceCommands, A], Awaitable[CommandResult]]
type _Runner = Callable[[ServiceCommands, Mapping[str, Any]], Awaitable[CommandResult]]

_REGISTRY: dict[str, _Runner] = {}


def _command[A](
    name: str, parse: Callable[[Mapping[str, Any]], A]
) -> Callable[[_Method[A]], _Method[A]]:
    def register(method: _Method[A]) -> _Method[A]:
        async def run(commands: ServiceCommands, raw: Mapping[str, Any]) -> CommandResult:
            return await method(commands, parse(raw))

        _REGISTRY[name] = run
        return method

    return register


def _no_lock() -> AbstractAsyncContextManager[None]:
    return contextlib.nullcontext()


class ServiceCommands:
    def __init__(self, host: ServiceHost) -> None:
        self._host = host

    async def execute(self, name: str, args: Mapping[str, Any]) -> CommandResult:
        runner = _REGISTRY.get(name)
        if runner is None:
            return CommandResult(False, f"unknown command: {name!r}")
        try:
            return await runner(self, args)
        except Exception as error:
            log.exception("command %s failed", name)
            return CommandResult(False, f"{type(error).__name__}: {error}")

    def _chat_id(self, chat: ChatSelector) -> int | None:
        if chat is None or isinstance(chat, int):
            return chat
        return resolve_chat_selector(self._host.ctx, chat)

    def _targets(self, chat: ChatSelector) -> list[ChatController]:
        rt = self._host.runtime()
        chat_id = self._chat_id(chat)
        if chat_id is None:
            return rt.registry.all()
        controller = rt.registry.get(chat_id)
        if controller is None:
            raise ChatImportError("that chat is not tracked by the running service")
        return [controller]

    @_command("trim", TrimArgs.parse)
    async def trim(self, args: TrimArgs) -> CommandResult:
        rt = self._host.runtime()
        report = await rt.trimmer.trim_percent(args.pct, self._chat_id(args.chat))
        return CommandResult(
            True,
            f"trimmed {report.trimmed_records} records, freed {report.freed_bytes} bytes, "
            f"deleted {len(report.deleted_parts)} parts",
            {
                "records": report.trimmed_records,
                "bytes": report.freed_bytes,
                "parts": len(report.deleted_parts),
                "per_chat": {str(chat): count for chat, count in report.per_chat.items()},
            },
        )

    @_command("pause", ChatArgs.parse)
    async def pause(self, args: ChatArgs) -> CommandResult:
        targets = self._targets(args.chat)
        for controller in targets:
            controller.pause()
        return CommandResult(True, f"paused {len(targets)} chats")

    @_command("resume", ChatArgs.parse)
    async def resume(self, args: ChatArgs) -> CommandResult:
        targets = self._targets(args.chat)
        for controller in targets:
            controller.resume()
        return CommandResult(True, f"resumed {len(targets)} chats")

    @_command("recheck", RecheckArgs.parse)
    async def recheck(self, args: RecheckArgs) -> CommandResult:
        rt = self._host.runtime()
        count = await rt.scheduler.trigger_now(args.days, self._chat_id(args.chat))
        return CommandResult(True, f"recheck requested for {count} chats", {"chats": count})

    @_command("status", NoArgs.parse)
    async def status(self, args: NoArgs) -> CommandResult:
        data = self._host.runtime().status.build()
        return CommandResult(True, format_status_lines(data)[0], data)

    @_command("reload_config", NoArgs.parse)
    async def reload_config(self, args: NoArgs) -> CommandResult:
        self._host.reload_config()
        return CommandResult(True, "config reloaded; new chats use it, a restart applies the rest")

    @_command("set_root", SetRootArgs.parse)
    async def set_root(self, args: SetRootArgs) -> CommandResult:
        return await self._host.change_root(args)

    @_command("shutdown", NoArgs.parse)
    async def shutdown(self, args: NoArgs) -> CommandResult:
        self._host.request_shutdown()
        return CommandResult(True, "shutting down")

    @_command("refetch", ChatArgs.parse)
    async def refetch(self, args: ChatArgs) -> CommandResult:
        targets = self._targets(args.chat)
        for controller in targets:
            controller.request_refetch()
        return CommandResult(True, f"refetch requested for {len(targets)} chats")

    @_command("deeper", ChatArgs.parse)
    async def deeper(self, args: ChatArgs) -> CommandResult:
        targets = self._targets(args.chat)
        now = self._host.clock.now()
        lowered = 0
        for controller in targets:
            async with controller.lock:
                try:
                    if await in_thread(lower_floor_state, controller.folder, now):
                        lowered += 1
                except StateUnreadable:
                    log.warning(
                        "state unreadable; floor kept", extra={"chat_id": controller.chat_id}
                    )
            controller.resume_backfill()
        return CommandResult(True, f"lowered the floor of {lowered} chats", {"chats": lowered})

    @_command("check", CheckArgs.parse)
    async def check(self, args: CheckArgs) -> CommandResult:
        rt = self._host.runtime()
        by_folder = {controller.folder.name: controller for controller in rt.registry.all()}
        now = self._host.clock.now()
        issues: list[CheckIssue] = []
        for folder in list(iter_chat_folders(rt.root)):
            controller = by_folder.get(folder.name)
            async with controller.lock if controller is not None else _no_lock():
                found = await in_thread(check_folder, folder, repair=args.repair, now=now)
            issues.extend(sorted(found, key=lambda issue: _SEVERITY_RANK.get(issue.severity, 3)))
        rows = [
            {
                "chat_id": issue.chat_id,
                "folder": issue.folder,
                "severity": issue.severity,
                "message": issue.message,
            }
            for issue in issues
        ]
        lines = [f"{row['severity']} {row['folder']}: {row['message']}" for row in rows]
        summary = f"{len(rows)} issue(s) found" if rows else "no issues found"
        return CommandResult(
            True, "\n".join([summary, *lines]), {"count": len(rows), "issues": rows}
        )


COMMANDS: Final = MappingProxyType(_REGISTRY)
COMMAND_NAMES: Final = tuple(_REGISTRY)
