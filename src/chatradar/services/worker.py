"""Use case: the background loop — sync tracked chats, process, sleep, repeat."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Protocol

from chatradar.logs import get_logger
from chatradar.services.process import process
from chatradar.services.sync import sync_chats

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable
    from contextlib import AbstractAsyncContextManager

    from chatradar.services.container import Runtime
    from chatradar.services.sync import LiveConnector

log = get_logger(__name__)

RECHECK_EVERY = timedelta(days=1)


class ConnectorFactory(Protocol):
    def __call__(self) -> AbstractAsyncContextManager[LiveConnector]: ...


async def run_once(
    runtime: Runtime,
    connect: ConnectorFactory | None,
    *,
    recheck: bool,
) -> None:
    """One cycle. Without a connector (Telegram not configured) only processing runs."""
    settings = runtime.settings
    if connect is not None:
        async with connect() as connector:
            report = await sync_chats(
                connector,
                raw=runtime.raw,
                chats=runtime.repo,
                messages=runtime.repo,
                pause_sec=settings.worker.pause_between_chats_sec,
                batch_size=settings.worker.batch_size,
                recheck_days=settings.worker.recheck_days if recheck else None,
            )
        log.info("worker.synced", stage="sync", count=report.fetched, chats=len(report.chats))
    processed = await process(runtime.stage_deps, batch_size=settings.worker.batch_size)
    log.info("worker.processed", stage="process", processed=processed)


async def run_forever(
    runtime: Runtime,
    connect: ConnectorFactory | None,
    *,
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
    cycles: int | None = None,
) -> None:
    """Loop until cancelled (`cycles` bounds it in tests). A failed cycle is logged and
    retried on the next tick instead of killing the worker."""
    interval = runtime.settings.worker.sync_interval_hours * 3600
    last_recheck: datetime | None = None
    done = 0
    while cycles is None or done < cycles:
        now = datetime.now(UTC)
        recheck = last_recheck is None or now - last_recheck >= RECHECK_EVERY
        try:
            await run_once(runtime, connect, recheck=recheck)
            if recheck:
                last_recheck = now
        except Exception:  # the loop must survive network and FloodWait errors
            log.exception("worker.cycle_failed")
        done += 1
        if cycles is None or done < cycles:
            log.info("worker.sleep", seconds=interval)
            await sleep(interval)
