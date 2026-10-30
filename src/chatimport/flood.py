"""Telegram FloodWait handling: wait as long as asked, then repeat the operation."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Final

from chatimport.ports import FloodWait
from chatimport.runtime import Level

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

    from chatimport.ports import Clock
    from chatimport.runtime import Notifier

log = logging.getLogger(__name__)

LONG_FLOOD_SECONDS: Final = 600


async def retry_on_flood[T](
    operation: Callable[[], Awaitable[T]],
    *,
    clock: Clock,
    on_wait: Callable[[int], None],
) -> T:
    """Run `operation` until it ends without a FloodWait; `on_wait` hears every wait first."""
    while True:
        try:
            return await operation()
        except FloodWait as wait:
            on_wait(wait.seconds)
            await clock.sleep(wait.seconds)


class FloodReporter:
    """Logs every FloodWait of a chat; tells the owner about waits over ten minutes."""

    def __init__(self, chat_id: int, title: str, notifier: Notifier) -> None:
        self._chat_id = chat_id
        self._title = title
        self._notifier = notifier

    def __call__(self, seconds: int) -> None:
        log.warning("FloodWait %s s in chat %s", seconds, self._chat_id)
        if seconds > LONG_FLOOD_SECONDS:
            self._notifier.notify(
                Level.WARNING, self._title, f"Telegram asked to wait {seconds} s; this chat sleeps"
            )
