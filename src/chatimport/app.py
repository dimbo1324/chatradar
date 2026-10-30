"""Application wiring (spec §8.1): builds every component, runs the service, executes commands."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Any, Final

from chatimport.config import Config, load_config
from chatimport.config_edit import set_output_root
from chatimport.control import (
    COMMANDS,
    CommandResult,
    ControlServer,
    Handler,
    acquire_instance_lock,
)
from chatimport.guards.disk import DiskGuard
from chatimport.guards.folders import FolderWatcher
from chatimport.library import (
    ChatEntry,
    Library,
    LibraryChange,
    LibraryError,
    LibraryWatcher,
    load_library,
)
from chatimport.media import MediaDownloader
from chatimport.offline import lower_floor_state, resolve_chat_selector
from chatimport.paths import (
    ROOT_ENV,
    AppPaths,
    app_paths,
    library_path,
    normalize_root,
    resolve_root,
)
from chatimport.ports import ChatImportError, ResolvedChat, ResolveStatus, SessionRevoked
from chatimport.recheck import RecheckScheduler, compute_recheck
from chatimport.router import Router
from chatimport.runtime import (
    ChatController,
    ChatRegistry,
    Level,
    SystemClock,
    SystemDiskUsage,
    TrackedChat,
)
from chatimport.setroot import move_root, validate_new_root
from chatimport.status import StatusWriter, format_status_lines
from chatimport.storage.layout import chat_folder_name
from chatimport.storage.state import load_state
from chatimport.supervisor import Supervisor
from chatimport.telegram.client import TelethonGateway
from chatimport.trim import Trimmer
from chatimport.worker import ChatWorker

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable
    from datetime import datetime
    from pathlib import Path

    from chatimport.ports import ChatEvent, Clock, DiskUsage, TelegramGateway
    from chatimport.runtime import Notifier

log = logging.getLogger(__name__)

_MIB: Final = 1024 * 1024
_GIB: Final = 1024**3
_RETRY_UNRESOLVED_SECONDS: Final = 600
_RETRYABLE: Final = (ResolveStatus.NEED_TO_JOIN, ResolveStatus.NOT_FOUND)


@dataclass(frozen=True, slots=True)
class ServiceContext:
    config: Config
    paths: AppPaths
    root: Path
    library_file: Path


def load_context(root_override: str | None = None, base: Path | None = None) -> ServiceContext:
    paths = app_paths(base)
    config = load_config(paths.config_file)
    root = resolve_root(root_override, config.output.root_dir)
    library_file = library_path(config.library.file, paths)
    paths.ensure()
    return ServiceContext(config=config, paths=paths, root=root, library_file=library_file)


def build_gateway(ctx: ServiceContext, clock: Clock) -> TelethonGateway:
    if not ctx.config.telegram.is_configured:
        raise ChatImportError("telegram api_id and api_hash are not set in config.toml")
    return TelethonGateway(
        ctx.config.telegram,
        ctx.paths.session_file,
        include_sender_names=ctx.config.output.include_sender_names,
        include_raw=ctx.config.output.include_raw,
        clock=clock,
    )


async def resolve_entries(
    gateway: TelegramGateway, entries: Iterable[ChatEntry]
) -> list[tuple[ChatEntry, ResolvedChat]]:
    results: list[tuple[ChatEntry, ResolvedChat]] = []
    for entry in entries:
        try:
            resolved = await gateway.resolve(entry.key)
        except SessionRevoked:
            raise
        except ChatImportError as error:
            resolved = ResolvedChat(entry.key, ResolveStatus.NOT_FOUND, detail=type(error).__name__)
        results.append((entry, resolved))
    return results


async def resolve_library(
    gateway: TelegramGateway, library: Library
) -> list[tuple[ChatEntry, ResolvedChat]]:
    return await resolve_entries(gateway, library.enabled_entries())


def tracked_chat(entry: ChatEntry, resolved: ResolvedChat) -> TrackedChat:
    if resolved.chat_id is None:
        raise ChatImportError("the library entry is not resolved to a chat")
    title = resolved.title or entry.name or str(resolved.chat_id)
    return TrackedChat(
        chat_id=resolved.chat_id,
        title=title,
        username=resolved.username,
        folder_name=chat_folder_name(entry.name or title, resolved.chat_id),
    )


@dataclass(slots=True)
class _Runtime:
    root: Path
    registry: ChatRegistry
    router: Router
    trimmer: Trimmer
    status: StatusWriter
    scheduler: RecheckScheduler
    supervisor: Supervisor
    aux_tasks: list[asyncio.Task[None]] = field(default_factory=list[asyncio.Task[None]])
    fatal_watch: asyncio.Task[None] | None = None
    launches: int = 0


def _last_recheck_at(controller: ChatController) -> datetime | None:
    state = load_state(controller.folder)
    return state.last_recheck_at if state is not None else None


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
        self._rt: _Runtime | None = None
        self._core: Supervisor | None = None
        self._core_watch: asyncio.Task[None] | None = None
        self._watcher = LibraryWatcher(ctx.library_file)
        self._active: dict[str, tuple[ChatEntry, ResolvedChat]] = {}
        self._unresolved: dict[str, ChatEntry] = {}
        self._errors: dict[str, str] = {}
        self._reconfig = asyncio.Lock()
        self._commands: dict[str, Handler] = {
            "trim": self._cmd_trim,
            "pause": self._cmd_pause,
            "resume": self._cmd_resume,
            "recheck": self._cmd_recheck,
            "status": self._cmd_status,
            "reload_config": self._cmd_reload_config,
            "set_root": self._cmd_set_root,
            "shutdown": self._cmd_shutdown,
            "refetch": self._cmd_refetch,
            "deeper": self._cmd_deeper,
            "check": self._cmd_check,
        }

    @property
    def ctx(self) -> ServiceContext:
        return self._ctx

    def request_shutdown(self) -> None:
        self._early_shutdown = True
        loop = self._loop
        if loop is not None:
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._shutdown.set)

    def build_handlers(self) -> dict[str, Handler]:
        def make(name: str) -> Handler:
            async def handler(args: dict[str, Any]) -> CommandResult:
                return await self.execute(name, args)

            return handler

        return {name: make(name) for name in COMMANDS}

    async def execute(self, command: str, args: dict[str, Any]) -> CommandResult:
        handler = self._commands.get(command)
        if handler is None:
            return CommandResult(False, f"unknown command: {command!r}")
        try:
            return await handler(args)
        except Exception as error:
            log.exception("command %s failed", command)
            return CommandResult(False, f"{type(error).__name__}: {error}")

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
                results = await self._select_for_once(gateway, library, chat)
            pause = self._config.backfill.pause_between_chats_sec
            first = True
            for entry, resolved in results:
                if resolved.status is not ResolveStatus.FOUND or resolved.chat_id is None:
                    log.warning("library entry not resolved: %s", resolved.status.value)
                    continue
                if not first:
                    await self._clock.sleep(pause)
                first = False
                worker = ChatWorker(
                    tracked_chat(entry, resolved),
                    root=self._ctx.root,
                    gateway=gateway,
                    config=self._config,
                    clock=self._clock,
                    notifier=self._notifier,
                    recheck=compute_recheck,
                )
                await worker.sync_once()
        finally:
            with contextlib.suppress(Exception):
                await gateway.disconnect()
            lock.release()

    async def _select_for_once(
        self, gateway: TelegramGateway, library: Library, chat: str
    ) -> list[tuple[ChatEntry, ResolvedChat]]:
        entry = library.find(chat)
        if entry is not None:
            return await resolve_entries(gateway, [entry])
        needle = chat.strip().casefold()
        username = needle.removeprefix("@")
        matched: list[tuple[ChatEntry, ResolvedChat]] = []
        for item, resolved in await resolve_library(gateway, library):
            if str(resolved.chat_id) == needle or (
                resolved.username is not None and resolved.username.casefold() == username
            ):
                matched.append((item, resolved))
        if not matched:
            raise ChatImportError(f"no library chat matches {chat.strip()!r}")
        return matched

    async def _serve(self) -> None:
        self._loop = asyncio.get_running_loop()
        if self._early_shutdown:
            self._shutdown.set()
        gateway = self._gateway or build_gateway(self._ctx, self._clock)
        self._gateway = gateway
        core = Supervisor(self._clock, self._notifier)
        self._core = core
        self._service_state = "starting"
        try:
            await gateway.connect()
            gateway.add_event_handler(self._on_event)
            library = self._load_initial_library()
            self._absorb(await resolve_library(gateway, library))
            self._service_state = "running"
            self._start_runtime(self._ctx.root)
            server = ControlServer(
                self._ctx.paths.control_dir, self.build_handlers(), clock=self._clock
            )
            core.spawn("control", server.run)
            core.spawn("library", self._library_loop)
            self._core_watch = asyncio.create_task(self._watch_fatal(core))
            log.info("service running", extra={"chats": len(self._active)})
            await self._shutdown.wait()
        finally:
            await self._teardown()
            with contextlib.suppress(Exception):
                await gateway.disconnect()

    async def _teardown(self) -> None:
        self._service_state = "stopping"
        if self._core is not None:
            await self._core.stop_all()
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
            self._set_error("library", str(error))
            self._notifier.notify(Level.ERROR, "Library", "chats.toml is invalid; fix the file")
            return Library()

    def _absorb(self, results: list[tuple[ChatEntry, ResolvedChat]]) -> list[ChatEntry]:
        found: list[ChatEntry] = []
        failed = 0
        for entry, resolved in results:
            key = f"resolve:{entry.key}"
            if resolved.status is ResolveStatus.FOUND and resolved.chat_id is not None:
                self._clear_error(key)
                self._unresolved.pop(entry.key, None)
                self._active[entry.key] = (entry, resolved)
                found.append(entry)
                continue
            failed += 1
            detail = f" ({resolved.detail})" if resolved.detail else ""
            self._set_error(key, f"{entry.key}: {resolved.status.value}{detail}")
            if resolved.status in _RETRYABLE:
                self._unresolved[entry.key] = entry
            log.warning("library entry unresolved: %s", resolved.status.value)
        if failed:
            self._notifier.notify(
                Level.WARNING, "Library", f"{failed} of {len(results)} chats could not be resolved"
            )
        return found

    def _set_error(self, key: str, text: str) -> None:
        self._errors[key] = text
        if self._rt is not None:
            self._rt.status.add_error(key, text)

    def _clear_error(self, key: str) -> None:
        self._errors.pop(key, None)
        if self._rt is not None:
            self._rt.status.clear_error(key)

    def _build_runtime(self, root: Path) -> _Runtime:
        config = self._config
        registry = ChatRegistry()
        supervisor = Supervisor(self._clock, self._notifier)
        trimmer = Trimmer(
            root, registry, clock=self._clock, max_chunk_bytes=config.output.max_chunk_mb * _MIB
        )
        status = StatusWriter(
            root,
            registry,
            supervisor,
            clock=self._clock,
            disk=self._disk,
            low_watermark_gb=config.disk.low_watermark_gb,
            service_state=lambda: self._service_state,
        )
        for key, text in self._errors.items():
            status.add_error(key, text)
        return _Runtime(
            root=root,
            registry=registry,
            router=Router(registry, root, clock=self._clock),
            trimmer=trimmer,
            status=status,
            scheduler=RecheckScheduler(registry, config.recheck, self._clock, _last_recheck_at),
            supervisor=supervisor,
        )

    def _start_runtime(self, root: Path) -> None:
        rt = self._build_runtime(root)
        self._rt = rt
        config = self._config
        workers = [
            worker
            for entry, resolved in self._active.values()
            if (worker := self._register(rt, entry, resolved)) is not None
        ]
        self._launch(rt, workers)
        guard = DiskGuard(
            root,
            rt.registry,
            rt.trimmer,
            config.disk,
            clock=self._clock,
            disk=self._disk,
            notifier=self._notifier,
        )
        watcher = FolderWatcher(
            root, rt.registry, config.watch, clock=self._clock, notifier=self._notifier
        )
        self._spawn_aux(rt, "folder-watcher", watcher.run)
        self._spawn_aux(rt, "disk-guard", guard.run)
        self._spawn_aux(rt, "recheck", rt.scheduler.run)
        self._spawn_aux(rt, "status", rt.status.run)
        if config.media.enabled:
            downloader = MediaDownloader(
                rt.registry,
                self._require_gateway(),
                config.media,
                clock=self._clock,
                max_chunk_bytes=config.output.max_chunk_mb * _MIB,
            )
            self._spawn_aux(rt, "media", downloader.run)
            self._spawn_aux(rt, "media-guard", lambda: self._media_guard(root, downloader))
        rt.fatal_watch = asyncio.create_task(self._watch_fatal(rt.supervisor))

    async def _media_guard(self, root: Path, downloader: MediaDownloader) -> None:
        disk = self._config.disk
        while True:
            free = self._disk.free_bytes(root)
            if free < disk.low_watermark_gb * _GIB:
                downloader.pause()
            elif free >= disk.high_watermark_gb * _GIB:
                downloader.resume()
            await self._clock.sleep(disk.check_every_minutes * 60)

    @staticmethod
    def _spawn_aux(rt: _Runtime, name: str, factory: Callable[[], Awaitable[None]]) -> None:
        rt.aux_tasks.append(rt.supervisor.spawn(name, factory))

    def _require_gateway(self) -> TelegramGateway:
        if self._gateway is None:
            raise ChatImportError("the service is not connected")
        return self._gateway

    async def _stop_runtime(self) -> _Runtime | None:
        rt = self._rt
        if rt is None:
            return None
        self._rt = None
        if rt.fatal_watch is not None:
            rt.fatal_watch.cancel()
        for task in rt.aux_tasks:
            task.cancel()
        await asyncio.gather(*rt.aux_tasks, return_exceptions=True)
        results = await asyncio.gather(
            *(controller.stop() for controller in rt.registry.all()), return_exceptions=True
        )
        for result in results:
            if isinstance(result, BaseException):
                log.error("a worker did not stop cleanly: %s", type(result).__name__)
        await rt.supervisor.stop_all()
        return rt

    def _register(
        self, rt: _Runtime, entry: ChatEntry, resolved: ResolvedChat
    ) -> ChatWorker | None:
        chat_id = resolved.chat_id
        if chat_id is None or rt.registry.get(chat_id) is not None:
            return None
        worker = ChatWorker(
            tracked_chat(entry, resolved),
            root=rt.root,
            gateway=self._require_gateway(),
            config=self._config,
            clock=self._clock,
            notifier=self._notifier,
            recheck=compute_recheck,
        )
        rt.registry.add(worker)
        return worker

    def _launch(self, rt: _Runtime, workers: list[ChatWorker]) -> None:
        fresh: list[ChatWorker] = []
        for worker in workers:
            state = load_state(worker.folder)
            if state is not None and state.backfill.done:
                self._spawn_worker(rt, worker)
            else:
                fresh.append(worker)
        if fresh:
            rt.launches += 1
            rt.supervisor.spawn(
                f"launch-{rt.launches}", lambda: self._stagger(rt, fresh), restart=False
            )

    async def _stagger(self, rt: _Runtime, workers: list[ChatWorker]) -> None:
        pause = self._config.backfill.pause_between_chats_sec
        for index, worker in enumerate(workers):
            if index:
                await self._clock.sleep(pause)
            if rt.registry.get(worker.chat_id) is worker:
                self._spawn_worker(rt, worker)

    @staticmethod
    def _spawn_worker(rt: _Runtime, worker: ChatWorker) -> None:
        rt.supervisor.spawn(f"worker-{worker.chat_id}", worker.run)

    async def _library_loop(self) -> None:
        interval = self._config.library.reload_check_seconds
        waited = 0
        while True:
            await self._clock.sleep(interval)
            waited += interval
            change = self._watcher.check()
            if self._watcher.last_error is not None:
                self._set_error("library", self._watcher.last_error)
            else:
                self._clear_error("library")
            async with self._reconfig:
                if change is not None:
                    await self._apply_change(change)
                if waited >= _RETRY_UNRESOLVED_SECONDS and self._unresolved:
                    waited = 0
                    await self._retry_unresolved()

    async def _apply_change(self, change: LibraryChange) -> None:
        rt = self._rt
        if rt is None:
            return
        for entry in (*change.removed, *change.disabled):
            await self._release(rt, entry)
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

    async def _retry_unresolved(self) -> None:
        rt = self._rt
        if rt is None:
            return
        entries = [
            entry
            for entry in self._unresolved.values()
            if (current := self._watcher.current.find(entry.key)) is not None and current.enabled
        ]
        self._unresolved.clear()
        await self._start_entries(rt, entries)

    async def _start_entries(self, rt: _Runtime, entries: Iterable[ChatEntry]) -> None:
        pending = tuple(entries)
        if not pending:
            return
        results = await resolve_entries(self._require_gateway(), pending)
        workers: list[ChatWorker] = []
        for entry in self._absorb(results):
            _, resolved = self._active[entry.key]
            worker = self._register(rt, entry, resolved)
            if worker is not None:
                workers.append(worker)
        self._launch(rt, workers)

    async def _release(self, rt: _Runtime, entry: ChatEntry) -> None:
        self._unresolved.pop(entry.key, None)
        self._clear_error(f"resolve:{entry.key}")
        item = self._active.pop(entry.key, None)
        if item is None or item[1].chat_id is None:
            return
        chat_id = item[1].chat_id
        if any(other[1].chat_id == chat_id for other in self._active.values()):
            return
        controller = rt.registry.remove(chat_id)
        if controller is not None:
            await controller.stop()

    def _runtime(self) -> _Runtime:
        if self._rt is None:
            raise ChatImportError("the service is not running or is restarting")
        return self._rt

    def _chat_arg(self, args: dict[str, Any]) -> int | None:
        value = args.get("chat")
        if value is None or value == "":
            return None
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        return resolve_chat_selector(self._ctx, str(value))

    def _targets(self, args: dict[str, Any]) -> list[ChatController]:
        rt = self._runtime()
        chat_id = self._chat_arg(args)
        if chat_id is None:
            return rt.registry.all()
        controller = rt.registry.get(chat_id)
        if controller is None:
            raise ChatImportError("that chat is not tracked by the running service")
        return [controller]

    async def _cmd_trim(self, args: dict[str, Any]) -> CommandResult:
        rt = self._runtime()
        report = await rt.trimmer.trim_percent(int(args["pct"]), self._chat_arg(args))
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

    async def _cmd_pause(self, args: dict[str, Any]) -> CommandResult:
        targets = self._targets(args)
        for controller in targets:
            controller.pause()
        return CommandResult(True, f"paused {len(targets)} chats")

    async def _cmd_resume(self, args: dict[str, Any]) -> CommandResult:
        targets = self._targets(args)
        for controller in targets:
            controller.resume()
        return CommandResult(True, f"resumed {len(targets)} chats")

    async def _cmd_recheck(self, args: dict[str, Any]) -> CommandResult:
        rt = self._runtime()
        days = args.get("days")
        if days is not None and int(days) < 1:
            raise ChatImportError("days must be at least 1")
        count = await rt.scheduler.trigger_now(
            None if days is None else int(days), self._chat_arg(args)
        )
        return CommandResult(True, f"recheck requested for {count} chats", {"chats": count})

    async def _cmd_refetch(self, args: dict[str, Any]) -> CommandResult:
        targets = self._targets(args)
        for controller in targets:
            controller.request_refetch()
        return CommandResult(True, f"refetch requested for {len(targets)} chats")

    async def _cmd_status(self, args: dict[str, Any]) -> CommandResult:
        data = self._runtime().status.build()
        return CommandResult(True, format_status_lines(data)[0], data)

    async def _cmd_reload_config(self, args: dict[str, Any]) -> CommandResult:
        config = load_config(self._ctx.paths.config_file)
        self._config = config
        self._ctx = replace(self._ctx, config=config)
        return CommandResult(True, "config reloaded; new chats use it, a restart applies the rest")

    async def _cmd_shutdown(self, args: dict[str, Any]) -> CommandResult:
        self.request_shutdown()
        return CommandResult(True, "shutting down")

    async def _cmd_deeper(self, args: dict[str, Any]) -> CommandResult:
        targets = self._targets(args)
        lowered = 0
        for controller in targets:
            async with controller.lock:
                if lower_floor_state(controller.folder, self._clock.now()):
                    lowered += 1
            controller.resume_backfill()
        return CommandResult(True, f"lowered the floor of {lowered} chats", {"chats": lowered})

    async def _cmd_check(self, args: dict[str, Any]) -> CommandResult:
        from chatimport.integrity import check_root

        repair = bool(args.get("repair", False))
        async with AsyncExitStack() as stack:
            if repair:
                for controller in self._runtime().registry.all():
                    await stack.enter_async_context(controller.lock)
            issues = await asyncio.to_thread(
                check_root, self._ctx.root, repair=repair, now=self._clock.now()
            )
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

    async def _cmd_set_root(self, args: dict[str, Any]) -> CommandResult:
        raw = args.get("path")
        if not isinstance(raw, str) or not raw.strip():
            raise ChatImportError("path is required")
        move = bool(args.get("move", False))
        new = normalize_root(raw.strip())
        async with self._reconfig:
            old = self._ctx.root
            if new == old:
                return CommandResult(True, "the folder is unchanged")
            warnings = await asyncio.to_thread(validate_new_root, new, old)
            await self._stop_runtime()
            try:
                await move_root(old, new, move=move)
            except BaseException:
                self._start_runtime(old)
                raise
            try:
                set_output_root(self._ctx.paths.config_file, new)
            except (OSError, ValueError) as error:
                self._adopt_root(new)
                raise ChatImportError(
                    f"data is now in {new} but config.toml was not updated: {error}"
                ) from error
            self._adopt_root(new)
        if os.environ.get(ROOT_ENV):
            warnings.append(f"{ROOT_ENV} is set and overrides the saved folder on restart")
        if not move:
            warnings.append("the data was not moved; chats are fetched again into the new folder")
        return CommandResult(
            True, "; ".join([f"output folder is now {new}", *warnings]), {"path": str(new)}
        )

    def _adopt_root(self, new: Path) -> None:
        self._ctx = replace(self._ctx, root=new)
        self._start_runtime(new)
