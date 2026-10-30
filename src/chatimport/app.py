"""Application wiring (spec §8.1): runs the service, follows the library and executes commands."""

from __future__ import annotations

import asyncio
import contextlib
import functools
import logging
import os
from dataclasses import replace
from typing import TYPE_CHECKING, Any, Final

from chatimport.commands import CommandResult, Handler, ServiceCommands, finish
from chatimport.config import load_config
from chatimport.config_edit import set_output_root
from chatimport.context import ServiceContext, build_gateway, load_context
from chatimport.control import COMMANDS, ControlServer, acquire_instance_lock
from chatimport.library import Library, LibraryChange, LibraryError, LibraryWatcher, load_library
from chatimport.paths import ROOT_ENV, normalize_root
from chatimport.ports import ChatImportError, SessionRevoked
from chatimport.resolution import (
    LIBRARY_ERROR,
    ActiveChats,
    ErrorBook,
    ResolvedEntry,
    resolve_entries,
    resolve_library,
    select_for_once,
    tracked_chat,
)
from chatimport.runtime import BackfillSlots, Level, SystemClock, SystemDiskUsage
from chatimport.service_runtime import ServiceRuntime, make_worker
from chatimport.setroot import move_root, validate_new_root
from chatimport.supervisor import Supervisor

if TYPE_CHECKING:
    from collections.abc import Iterable
    from pathlib import Path

    from chatimport.commands import SetRootArgs
    from chatimport.library import ChatEntry
    from chatimport.ports import ChatEvent, Clock, DiskUsage, TelegramGateway
    from chatimport.runtime import Notifier

__all__ = [
    "ChatImportApp",
    "ServiceContext",
    "build_gateway",
    "load_context",
    "resolve_entries",
    "resolve_library",
    "tracked_chat",
]

log = logging.getLogger(__name__)

_RETRY_UNRESOLVED_SECONDS: Final = 600


class ChatImportApp:
    def __init__(
        self,
        ctx: ServiceContext,
        *,
        notifier: Notifier,
        gateway: TelegramGateway | None = None,
        clock: Clock | None = None,
        disk: DiskUsage | None = None,
    ) -> None:
        self._ctx = ctx
        self._config = ctx.config
        self._notifier = notifier
        self._clock: Clock = clock or SystemClock()
        self._disk: DiskUsage = disk or SystemDiskUsage()
        self._gateway = gateway
        self._service_state = "stopped"
        self._shutdown = asyncio.Event()
        self._early_shutdown = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._rt: ServiceRuntime | None = None
        self._core_watch: asyncio.Task[None] | None = None
        self._watcher = LibraryWatcher(ctx.library_file)
        self._errors = ErrorBook()
        self._chats = ActiveChats(self._errors)
        self._reconfig = asyncio.Lock()
        self._commands = ServiceCommands(self)

    @property
    def ctx(self) -> ServiceContext:
        return self._ctx

    @property
    def clock(self) -> Clock:
        return self._clock

    def runtime(self) -> ServiceRuntime:
        if self._rt is None:
            raise ChatImportError("the service is not running or is restarting")
        return self._rt

    def _runtime(self) -> ServiceRuntime:
        return self.runtime()

    def reload_config(self) -> None:
        config = load_config(self._ctx.paths.config_file)
        self._config = config
        self._ctx = replace(self._ctx, config=config)
        if self._rt is not None:
            self._rt.config = config

    def request_shutdown(self) -> None:
        self._early_shutdown = True
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._shutdown.set)

    def build_handlers(self) -> dict[str, Handler]:
        return {name: functools.partial(self.execute, name) for name in COMMANDS}

    async def execute(self, command: str, args: dict[str, Any]) -> CommandResult:
        return await self._commands.execute(command, args)

    async def run(self) -> None:
        lock = acquire_instance_lock(self._ctx.paths.lock_file)
        try:
            await self._serve()
        finally:
            lock.release()

    async def run_once(self, chat: str | None = None) -> None:
        gateway = self._gateway or build_gateway(self._ctx, self._clock)
        lock = acquire_instance_lock(self._ctx.paths.lock_file)
        try:
            await gateway.connect()
            library = load_library(self._ctx.library_file)
            if chat is None:
                results = await resolve_library(gateway, library)
            else:
                results = await select_for_once(gateway, library, chat)
            await self._sync_each(gateway, results)
        finally:
            with contextlib.suppress(Exception):
                await gateway.disconnect()
            lock.release()

    async def _sync_each(self, gateway: TelegramGateway, results: list[ResolvedEntry]) -> None:
        """Sync every resolved chat in turn; one failing chat does not stop the others."""
        slots = BackfillSlots(self._config.backfill.max_parallel_chats)
        failed: list[int] = []
        first = True
        for item in results:
            if not item.found:
                log.warning("library entry not resolved: %s", item.resolved.status.value)
                continue
            if not first:
                await self._clock.sleep(self._config.backfill.pause_between_chats_sec)
            first = False
            worker = make_worker(
                tracked_chat(*item),
                root=self._ctx.root,
                gateway=gateway,
                config=self._config,
                clock=self._clock,
                notifier=self._notifier,
                slots=slots,
            )
            try:
                await worker.sync_once()
            except SessionRevoked:
                raise
            except Exception:
                log.exception("chat sync failed", extra={"chat_id": worker.chat_id})
                failed.append(worker.chat_id)
        if failed:
            raise ChatImportError(f"sync failed for chats {', '.join(map(str, failed))}")

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._early_shutdown:
            self._shutdown.set()
        gateway = self._gateway or build_gateway(self._ctx, self._clock)
        self._gateway = gateway
        core = Supervisor(self._clock, self._notifier)
        self._service_state = "starting"
        try:
            await gateway.connect()
            gateway.add_event_handler(self._on_event)
            library = self._load_initial_library()
            self._absorb(await resolve_library(gateway, library))
            self._service_state = "running"
            self._start_runtime(self._ctx.root, gateway)
            server = ControlServer(
                self._ctx.paths.control_dir, self.build_handlers(), clock=self._clock
            )
            core.spawn("control", server.run)
            core.spawn("library", self._library_loop)
            self._core_watch = asyncio.create_task(self._watch_fatal(core))
            log.info("service running", extra={"chats": len(self._chats)})
            await self._shutdown.wait()
        finally:
            await self._teardown(core)
            with contextlib.suppress(Exception):
                await gateway.disconnect()

    async def _teardown(self, core: Supervisor) -> None:
        self._service_state = "stopping"
        await core.stop_all()
        if self._core_watch is not None:
            self._core_watch.cancel()
        rt = await self._stop_runtime()
        self._service_state = "stopped"
        if rt is not None:
            with contextlib.suppress(OSError):
                await rt.status.write()
        log.info("service stopped")

    async def _watch_fatal(self, supervisor: Supervisor) -> None:
        await supervisor.wait_fatal()
        log.error("fatal task failure, shutting down")
        self._shutdown.set()

    async def _on_event(self, event: ChatEvent) -> None:
        rt = self._rt
        if rt is not None:
            await rt.router.handle(event)

    def _load_initial_library(self) -> Library:
        try:
            return self._watcher.load_initial()
        except LibraryError as error:
            self._errors.set(LIBRARY_ERROR, str(error))
            self._notifier.notify(Level.ERROR, "Library", "chats.toml is invalid; fix the file")
            return Library()

    def _absorb(self, results: list[ResolvedEntry]) -> list[ResolvedEntry]:
        absorbed = self._chats.absorb(results)
        if absorbed.failed:
            self._notifier.notify(
                Level.WARNING,
                "Library",
                f"{absorbed.failed} of {absorbed.total} chats could not be resolved",
            )
        return absorbed.found

    def _start_runtime(self, root: Path, gateway: TelegramGateway) -> None:
        rt = ServiceRuntime(
            root,
            config=self._config,
            gateway=gateway,
            clock=self._clock,
            notifier=self._notifier,
            disk=self._disk,
            errors=self._errors,
            service_state=lambda: self._service_state,
        )
        self._rt = rt
        rt.start(self._chats.entries(), on_fatal=self._shutdown.set)

    async def _stop_runtime(self) -> ServiceRuntime | None:
        rt = self._rt
        if rt is None:
            return None
        self._rt = None
        await rt.stop()
        return rt

    async def _library_loop(self) -> None:
        interval = self._config.library.reload_check_seconds
        waited = 0
        while True:
            await self._clock.sleep(interval)
            waited += interval
            change = self._watcher.check()
            if self._watcher.last_error is not None:
                self._errors.set(LIBRARY_ERROR, self._watcher.last_error)
            else:
                self._errors.clear(LIBRARY_ERROR)
            async with self._reconfig:
                rt = self.runtime()
                if change is not None:
                    await self._apply_change(rt, change)
                if waited >= _RETRY_UNRESOLVED_SECONDS and self._chats.has_unresolved:
                    waited = 0
                    await self._start_entries(
                        rt, self._chats.retry_candidates(self._watcher.current)
                    )

    async def _apply_change(self, rt: ServiceRuntime, change: LibraryChange) -> None:
        for entry in (*change.removed, *change.disabled):
            chat_id = self._chats.release(entry)
            if chat_id is not None:
                await rt.remove(chat_id)
        await self._start_entries(rt, (*change.added, *change.enabled))
        log.info(
            "library change applied",
            extra={
                "added": len(change.added),
                "removed": len(change.removed),
                "disabled": len(change.disabled),
                "enabled": len(change.enabled),
            },
        )

    async def _start_entries(self, rt: ServiceRuntime, entries: Iterable[ChatEntry]) -> None:
        pending = tuple(entries)
        if not pending:
            return
        rt.add(self._absorb(await resolve_entries(rt.gateway, pending)))

    async def change_root(self, args: SetRootArgs) -> CommandResult:
        new = normalize_root(args.path)
        async with self._reconfig:
            gateway = self.runtime().gateway
            old = self._ctx.root
            if new == old:
                return CommandResult(True, "the folder is unchanged")
            warnings = await asyncio.to_thread(
                validate_new_root, new, old, app_base=self._ctx.paths.base, move=args.move
            )
            await self._stop_runtime()
            moving = asyncio.ensure_future(move_root(old, new, move=args.move))
            try:
                await finish(moving)
            except asyncio.CancelledError:
                if not moving.cancelled() and moving.exception() is None:
                    self._remember_root_on_stop(new)
                raise
            except Exception:
                self._start_runtime(old, gateway)
                raise
            try:
                set_output_root(self._ctx.paths.config_file, new)
            except (OSError, ValueError) as error:
                self._adopt_root(new, gateway)
                raise ChatImportError(
                    f"data is now in {new} but config.toml was not updated: {error}"
                ) from error
            self._adopt_root(new, gateway)
        if os.environ.get(ROOT_ENV):
            warnings.append(f"{ROOT_ENV} is set and overrides the saved folder on restart")
        if not args.move:
            warnings.append("the data was not moved; chats are fetched again into the new folder")
        return CommandResult(
            True, "; ".join([f"output folder is now {new}", *warnings]), {"path": str(new)}
        )

    def _remember_root_on_stop(self, new: Path) -> None:
        """The service is stopping, but the move finished: keep the data findable."""
        self._ctx = replace(self._ctx, root=new)
        try:
            set_output_root(self._ctx.paths.config_file, new)
        except OSError, ValueError:
            log.exception("config.toml was not updated after the data folder moved")

    def _adopt_root(self, new: Path, gateway: TelegramGateway) -> None:
        self._ctx = replace(self._ctx, root=new)
        self._start_runtime(new, gateway)
