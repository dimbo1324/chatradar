"""Routes Telegram events to chat workers by `chat_id`; the rest is dropped.

Deletions in basic groups and private dialogs arrive without a chat id. Their ids (nothing
else) go to `_unrouted_deletes.jsonl`, which is capped: past `UNROUTED_MAX_BYTES` only the
newest `UNROUTED_KEEP_BYTES` are kept. The file is written in a worker thread, so its fsync
never stalls the event loop.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Final

from chatimport.ports import DeletedMessagesEvent
from chatimport.records import (
    DETECTED_EVENT,
    KIND_DELETE,
    SCHEMA_VERSION,
    format_dt,
    json_line_bytes,
)
from chatimport.storage.fileio import append_line, atomic_write_bytes

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import ChatEvent, Clock
    from chatimport.runtime import ChatRegistry

log = logging.getLogger(__name__)

UNROUTED_DELETES_FILE: Final = "_unrouted_deletes.jsonl"
UNROUTED_MAX_BYTES: Final = 2 * 1024 * 1024
UNROUTED_KEEP_BYTES: Final = 1024 * 1024


def cap_jsonl(path: Path, max_bytes: int, keep_bytes: int) -> bool:
    """Once `path` is larger than `max_bytes`, keep only its newest whole lines that fit in
    `keep_bytes` (`keep_bytes` < `max_bytes`); True when the file was shortened."""
    if path.stat().st_size <= max_bytes:
        return False
    data = path.read_bytes()
    first_line = data.find(b"\n", len(data) - keep_bytes - 1) + 1
    atomic_write_bytes(path, data[first_line:])
    return True


class Router:
    def __init__(self, registry: ChatRegistry, root: Path, *, clock: Clock) -> None:
        self._registry = registry
        self._root = root
        self._clock = clock

    async def handle(self, event: ChatEvent) -> None:
        try:
            if isinstance(event, DeletedMessagesEvent):
                if event.chat_id is None:
                    await asyncio.to_thread(self._append_unrouted, event.msg_ids)
                    return
                chat_id = event.chat_id
            else:
                chat_id = event.record.chat_id
            controller = self._registry.get(chat_id)
            if controller is not None:
                controller.submit(event)
        except Exception:
            log.exception("router failed on %s", type(event).__name__)

    def _append_unrouted(self, msg_ids: tuple[int, ...]) -> None:
        line = {
            "v": SCHEMA_VERSION,
            "kind": KIND_DELETE,
            "chat_id": None,
            "msg_ids": list(msg_ids),
            "detected_by": DETECTED_EVENT,
            "fetched_at": format_dt(self._clock.now()),
        }
        path = self._root / UNROUTED_DELETES_FILE
        append_line(path, json_line_bytes(line))
        if cap_jsonl(path, UNROUTED_MAX_BYTES, UNROUTED_KEEP_BYTES):
            log.info("unrouted deletes file capped", extra={"bytes": UNROUTED_KEEP_BYTES})
        log.info("unrouted delete stored: %d ids", len(msg_ids))
