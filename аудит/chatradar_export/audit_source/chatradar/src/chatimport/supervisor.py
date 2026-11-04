"""Runs long-lived tasks and restarts the ones that fail, with exponential backoff."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from typing import TYPE_CHECKING

from chatimport.ports import SessionRevoked
from chatimport.runtime import Level

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from chatimport.ports import Clock
    from chatimport.runtime import Notifier

log = logging.getLogger(__name__)

FIRST_DELAY = 1.0
MAX_DELAY = 300.0
STABLE_AFTER = 60.0


class Supervisor:
    def __init__(self, clock: Clock, notifier: Notifier) -> None:
        self._clock = clock
        self._notifier = notifier
        self._tasks: list[asyncio.Task[None]] = []
        self._errors: dict[str, str] = {}
        self.fatal: BaseException | None = None
        self.fatal_event = asyncio.Event()

    def spawn(
        self,
        name: str,
        factory: Callable[[], Awaitable[None]],
        *,
        restart: bool = True,
    ) -> asyncio.Task[None]:
        task = asyncio.create_task(self._run(name, factory, restart), name=name)
        self._tasks = [t for t in self._tasks if not t.done()]
        self._tasks.append(task)
        return task

    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    async def wait_fatal(self) -> None:
        await self.fatal_event.wait()

    async def stop_all(self) -> None:
        tasks = list(self._tasks)
        self._tasks.clear()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _run(self, name: str, factory: Callable[[], Awaitable[None]], restart: bool) -> None:
        delay = FIRST_DELAY
        while True:
            started = time.monotonic()
            self._errors.pop(name, None)
            try:
                await factory()
            except asyncio.CancelledError:
                raise
            except SessionRevoked as exc:
                self._errors[name] = _describe(exc)
                self.fatal = exc
                self.fatal_event.set()
                self._notifier.notify(
                    Level.ERROR, "Telegram session revoked", "run `chatimport login`"
                )
                log.error("task %s stopped: session revoked", name)
                return
            except Exception as exc:
                self._errors[name] = _describe(exc)
                log.exception("task %s failed", name)
                if not restart:
                    return
                if time.monotonic() - started >= STABLE_AFTER:
                    delay = FIRST_DELAY
                await self._clock.sleep(delay)
                delay = min(delay * 2, MAX_DELAY)
            else:
                self._errors.pop(name, None)
                return


def _describe(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"
