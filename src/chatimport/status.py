"""The `_status.json` snapshot that the CLI and the tray read."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from typing import TYPE_CHECKING, Any, Final, cast

from chatimport.config import GIB
from chatimport.records import format_dt
from chatimport.storage.layout import MEDIA_DIR, SERVICE_PREFIX
from chatimport.storage.state import atomic_write_bytes

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.ports import Clock, DiskUsage
    from chatimport.runtime import BackfillSlots, ChatRegistry
    from chatimport.supervisor import Supervisor

log = logging.getLogger(__name__)

STATUS_FILE: Final = "_status.json"
INTERVAL_SECONDS: Final = 60
GB: Final = GIB


class StatusWriter:
    def __init__(
        self,
        root: Path,
        registry: ChatRegistry,
        supervisor: Supervisor,
        *,
        clock: Clock,
        disk: DiskUsage,
        low_watermark_gb: int,
        service_state: Callable[[], str],
        slots: BackfillSlots | None = None,
    ) -> None:
        self._root = root
        self._registry = registry
        self._supervisor = supervisor
        self._clock = clock
        self._disk = disk
        self._low_watermark_gb = low_watermark_gb
        self._service_state = service_state
        self._slots = slots
        self._extra_errors: dict[str, str] = {}
        self._last_total: int | None = None

    def add_error(self, key: str, text: str) -> None:
        self._extra_errors[key] = text

    def clear_error(self, key: str) -> None:
        self._extra_errors.pop(key, None)

    def build(self, total_bytes: int | None = None) -> dict[str, Any]:
        """Without `total_bytes` the total of the last periodic write is reused, so an
        on-demand `status` does not walk the tree again."""
        if total_bytes is None:
            total_bytes = self._last_total
        if total_bytes is None:
            total_bytes = _total_jsonl_bytes(self._root)
        chats: list[dict[str, Any]] = []
        for controller in self._registry:
            status = controller.status()
            chat: dict[str, Any] = {
                "chat_id": status.chat_id,
                "title": status.title,
                "phase": status.phase,
                "last_id": status.last_id,
                "backfill_done": status.backfill_done,
                "oldest_date": _fmt_opt(status.oldest_date),
                "records": status.records,
                "paused": status.paused,
                "newest_date": _fmt_opt(status.newest_date),
                "last_contact_at": _fmt_opt(status.last_contact_at),
                "backfill": {
                    "state": status.backfill.state.value,
                    "progress": status.backfill.progress,
                    "month": status.backfill.month,
                    "retry_at": _fmt_opt(status.backfill.retry_at),
                    "detail": status.backfill.detail,
                },
            }
            if status.error:
                chat["error"] = status.error
            chats.append(chat)
        errors = [
            {"source": key, "message": text}
            for key, text in {**self._supervisor.errors(), **self._extra_errors}.items()
        ]
        free_bytes = self._disk.free_bytes(self._root)
        return {
            "updated_at": format_dt(self._clock.now()),
            "service": self._service_state(),
            "disk": {
                "path": str(self._root),
                "free_gb": round(free_bytes / GB, 1),
                "low_watermark_gb": self._low_watermark_gb,
            },
            "total_bytes": total_bytes,
            "backfill": self._slots_block(),
            "chats": chats,
            "errors": errors,
        }

    def _slots_block(self) -> dict[str, Any]:
        slots = self._slots
        if slots is None:
            return {"limit": 1, "active": [], "waiting": []}
        return {
            "limit": slots.limit,
            "active": list(slots.holders),
            "waiting": list(slots.waiting),
        }

    async def write(self) -> None:
        if not self._root.exists():
            return
        total = await asyncio.to_thread(_total_jsonl_bytes, self._root)
        self._last_total = total
        data = json.dumps(self.build(total), ensure_ascii=False, indent=2).encode()
        await asyncio.to_thread(atomic_write_bytes, self._root / STATUS_FILE, data)

    async def run(self) -> None:
        while True:
            try:
                await self.write()
            except OSError:
                log.exception("could not write %s", STATUS_FILE)
            await self._clock.sleep(INTERVAL_SECONDS)


def _fmt_opt(value: datetime | None) -> str | None:
    return format_dt(value) if value else None


def _skipped_dir(name: str) -> bool:
    """Media folders hold only downloads and `_`-folders are the service's own: neither holds
    parts, and media can hold tens of thousands of files."""
    return name == MEDIA_DIR or name.startswith(SERVICE_PREFIX)


def _total_jsonl_bytes(root: Path) -> int:
    total = 0
    stack = [str(root)]
    while stack:
        try:
            with os.scandir(stack.pop()) as entries:
                for entry in entries:
                    try:
                        if entry.is_dir(follow_symlinks=False):
                            if not _skipped_dir(entry.name):
                                stack.append(entry.path)
                        elif entry.name.endswith(".jsonl"):
                            total += entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        continue
        except OSError:
            continue
    return total


def read_snapshot(root: Path) -> dict[str, Any] | None:
    """The last `_status.json` under `root`; None when it is missing or unreadable."""
    try:
        loaded: object = json.loads((root / STATUS_FILE).read_text(encoding="utf-8"))
    except OSError, ValueError:
        return None
    return cast("dict[str, Any]", loaded) if isinstance(loaded, dict) else None


def format_chat_lines(data: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    for chat in data.get("chats", []):
        extra = ", paused" if chat.get("paused") else ""
        done = "done" if chat.get("backfill_done") else "in progress"
        lines.append(
            f"  {chat.get('chat_id')} {chat.get('title', '')}: {chat.get('phase')}, "
            f"last_id {chat.get('last_id')}, backfill {done}, "
            f"{chat.get('records', 0)} records{extra}"
        )
    return lines


def format_status_lines(data: dict[str, Any]) -> list[str]:
    chats: list[dict[str, Any]] = data.get("chats", [])
    service = str(data.get("service", "unknown"))
    state = "live" if service == "running" else service
    total_gb = data.get("total_bytes", 0) / GB
    free_gb = data.get("disk", {}).get("free_gb", 0)
    noun = "chat" if len(chats) == 1 else "chats"
    lines = [f"{len(chats)} {noun} · {state} · {total_gb:.1f} GB · {free_gb:g} GB free"]
    lines.extend(f"error [{e['source']}]: {e['message']}" for e in data.get("errors", []))
    return lines
