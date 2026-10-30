from __future__ import annotations

import asyncio
import itertools
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Any

from chatimport.app import ChatImportApp, ServiceContext
from chatimport.config import parse_config
from chatimport.paths import AppPaths
from chatimport.ports import ResolvedChat, ResolveStatus
from tests.fakes import NOW, FakeDisk, RecordingNotifier
from tests.fakes import FakeGateway as BaseGateway

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from chatimport.control import CommandResult
    from chatimport.ports import ChatEvent


class ManualClock:
    """`sleep` parks the caller until the test advances time past its wake-up moment."""

    def __init__(self, start: datetime = NOW) -> None:
        self._now = start
        self._ids = itertools.count()
        self._waiters: list[tuple[datetime, int, asyncio.Future[None]]] = []
        self.sleeps: list[float] = []

    def now(self) -> datetime:
        return self._now

    async def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        waiter: asyncio.Future[None] = asyncio.get_running_loop().create_future()
        self._waiters.append((self._now + timedelta(seconds=seconds), next(self._ids), waiter))
        await waiter

    async def advance(self, seconds: float) -> None:
        target = self._now + timedelta(seconds=seconds)
        for _ in range(100_000):
            due = sorted((w for w in self._waiters if w[0] <= target), key=lambda w: (w[0], w[1]))
            if not due:
                break
            first = due[0]
            self._waiters.remove(first)
            self._now = max(self._now, first[0])
            if not first[2].done():
                first[2].set_result(None)
            for _ in range(4):
                await asyncio.sleep(0)
        self._now = target
        await asyncio.sleep(0)


class SpyGateway(BaseGateway):
    """A fake gateway that notes how many event handlers were registered at each call."""

    def __init__(self) -> None:
        super().__init__()
        self.handlers_at: list[tuple[str, int]] = []

    async def newest_id(self, chat_id: int) -> int:
        self.handlers_at.append(("newest_id", len(self.handlers)))
        return await super().newest_id(chat_id)


FAST_CONFIG: dict[str, Any] = {
    "backfill": {"pause_between_requests_sec": 0.0, "pause_between_chats_sec": 0},
    "recheck": {"enabled": False},
}


@dataclass
class Env:
    tmp: Path
    ctx: ServiceContext
    gateway: SpyGateway
    clock: ManualClock
    notifier: RecordingNotifier
    disk: FakeDisk
    app: ChatImportApp
    task: asyncio.Task[None] | None = None
    extra: dict[str, Any] = field(default_factory=dict[str, Any])

    @property
    def root(self) -> Path:
        return self.ctx.root

    def write_library(self, text: str) -> None:
        self.ctx.library_file.write_text(text, encoding="utf-8")

    def start(self) -> asyncio.Task[None]:
        self.task = asyncio.create_task(self.app.run())
        return self.task

    async def until(
        self, predicate: Callable[[], bool], *, step: float = 1.0, real_seconds: float = 10.0
    ) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + real_seconds
        while not predicate():
            if loop.time() > deadline:
                raise AssertionError("condition not reached in time")
            await self.clock.advance(step)
            await asyncio.sleep(0.003)

    async def until_async(self, check: Callable[[], Any], *, step: float = 1.0) -> None:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while not await check():
            if loop.time() > deadline:
                raise AssertionError("condition not reached in time")
            await self.clock.advance(step)
            await asyncio.sleep(0.003)

    async def status(self) -> dict[str, Any] | None:
        result = await self.app.execute("status", {})
        return result.data if result.ok else None

    async def chats(self) -> dict[int, dict[str, Any]]:
        data = await self.status()
        return {} if data is None else {c["chat_id"]: c for c in data["chats"]}

    async def wait_running(self) -> None:
        async def ready() -> bool:
            return await self.status() is not None

        await self.until_async(ready)

    async def wait_live(self, *chat_ids: int) -> None:
        async def ready() -> bool:
            chats = await self.chats()
            return all(
                cid in chats and chats[cid]["phase"] == "live" and chats[cid]["backfill_done"]
                for cid in chat_ids
            )

        await self.until_async(ready)

    async def stop(self) -> None:
        assert self.task is not None
        self.app.request_shutdown()
        await asyncio.wait_for(self.task, 15)

    async def run_command(self, name: str, **args: Any) -> CommandResult:
        return await self.app.execute(name, args)

    async def call(self, name: str, **args: Any) -> CommandResult:
        """Run a command while the manual clock is pumped, for commands that sleep."""
        task = asyncio.create_task(self.app.execute(name, args))
        loop = asyncio.get_running_loop()
        deadline = loop.time() + 10
        while not task.done():
            if loop.time() > deadline:
                task.cancel()
                raise AssertionError("command did not finish")
            await self.clock.advance(1)
            await asyncio.sleep(0.003)
        return task.result()

    async def fire(self, event: ChatEvent) -> None:
        await self.gateway.fire(event)


def make_env(
    tmp: Path,
    *,
    config: dict[str, Any] | None = None,
    library: str | None = "",
    chats: dict[str, tuple[int, str]] | None = None,
    messages: dict[int, int] | None = None,
    free_bytes: int = 10**15,
) -> Env:
    """`chats` maps a ref to `(chat_id, title)`; `messages` maps chat_id to a message count."""
    base = tmp / "appdata"
    paths = AppPaths(base)
    paths.ensure()
    merged: dict[str, Any] = {k: dict(v) for k, v in FAST_CONFIG.items()}
    for section, values in (config or {}).items():
        merged.setdefault(section, {}).update(values)
    cfg = parse_config(merged)
    ctx = ServiceContext(
        config=cfg, paths=paths, root=tmp / "ChatImport", library_file=base / "chats.toml"
    )
    gateway = SpyGateway()
    for ref, (chat_id, title) in (chats or {}).items():
        gateway.refs[ref] = ResolvedChat(
            ref, ResolveStatus.FOUND, chat_id=chat_id, title=title, username=ref.removeprefix("@")
        )
        gateway.add_chat(chat_id, range(1, (messages or {}).get(chat_id, 3) + 1))
    if library is not None:
        ctx.library_file.write_text(library, encoding="utf-8")
    clock, notifier, disk = ManualClock(), RecordingNotifier(), FakeDisk(free_bytes)
    app = ChatImportApp(ctx, notifier=notifier, gateway=gateway, clock=clock, disk=disk)
    return Env(tmp, ctx, gateway, clock, notifier, disk, app)


def library_text(*entries: tuple[str, str | None, bool]) -> str:
    out: list[str] = []
    for ref, name, enabled in entries:
        out.append("[[chat]]")
        out.append(f'ref = "{ref}"')
        if name is not None:
            out.append(f'name = "{name}"')
        out.append(f"enabled = {'true' if enabled else 'false'}")
        out.append("")
    return "\n".join(out)
