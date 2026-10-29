"""Routes Telegram events to chat workers by `chat_id`; the rest is dropped."""

from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING

from chatimport.ports import DeletedMessagesEvent
from chatimport.records import DETECTED_EVENT, KIND_DELETE, SCHEMA_VERSION, format_dt

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import ChatEvent, Clock
    from chatimport.runtime import ChatRegistry

log = logging.getLogger(__name__)

UNROUTED_DELETES_FILE = "_unrouted_deletes.jsonl"


class Router:
    def __init__(self, registry: ChatRegistry, root: Path, *, clock: Clock) -> None:
        self._registry = registry
        self._root = root
        self._clock = clock

    async def handle(self, event: ChatEvent) -> None:
        try:
            if isinstance(event, DeletedMessagesEvent):
                if event.chat_id is None:
                    self._append_unrouted(event.msg_ids)
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
        data = (json.dumps(line, ensure_ascii=False, separators=(",", ":")) + "\n").encode()
        self._root.mkdir(parents=True, exist_ok=True)
        with (self._root / UNROUTED_DELETES_FILE).open("ab") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        log.info("unrouted delete stored: %d ids", len(msg_ids))
