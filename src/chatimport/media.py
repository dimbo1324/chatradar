"""MediaDownloader (spec §12): one file at a time, with its own pause, for chosen media types.

Files go to `media/<YYYY-MM>/<msg_id>[_<n>]<ext>`; the name starts with the message id because
trimming deletes media by a part's id range. A `media_saved` record is appended afterwards.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from chatimport.ports import AccessLost, FloodWait
from chatimport.records import MediaSavedRecord, MessageRecord
from chatimport.storage.layout import list_parts, month_key
from chatimport.storage.state import load_state
from chatimport.storage.writer import ChunkWriter, iter_part_records

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import MediaConfig
    from chatimport.ports import Clock, TelegramGateway
    from chatimport.records import MediaInfo
    from chatimport.runtime import ChatController, ChatRegistry

log = logging.getLogger(__name__)

DOWNLOAD_PAUSE_SECONDS: Final = 2.0
IDLE_SECONDS: Final = 5.0
MAX_ATTEMPTS: Final = 3
_MIB: Final = 1024 * 1024


@dataclass(slots=True)
class _Pending:
    month: str
    info: MediaInfo


@dataclass(slots=True)
class _ChatScan:
    parts: tuple[tuple[str, int], ...] = ()
    done: set[int] = field(default_factory=set[int])
    pending: dict[int, _Pending] = field(default_factory=dict[int, _Pending])


class MediaDownloader:
    def __init__(
        self,
        registry: ChatRegistry,
        gateway: TelegramGateway,
        config: MediaConfig,
        *,
        clock: Clock,
        max_chunk_bytes: int,
    ) -> None:
        self._registry = registry
        self._gateway = gateway
        self._config = config
        self._clock = clock
        self._max_chunk_bytes = max_chunk_bytes
        self._paused = False
        self._scans: dict[int, _ChatScan] = {}
        self._attempts: dict[tuple[int, int], int] = {}
        self._no_access: set[int] = set()
        self._cursor = 0

    def pause(self) -> None:
        self._paused = True

    def resume(self) -> None:
        self._paused = False

    @property
    def paused(self) -> bool:
        return self._paused

    async def run(self) -> None:
        while True:
            if not self._config.enabled or self._paused or len(self._registry) == 0:
                await self._clock.sleep(IDLE_SECONDS)
                continue
            if await self._download_next():
                await self._clock.sleep(DOWNLOAD_PAUSE_SECONDS)
            else:
                await self._clock.sleep(IDLE_SECONDS)

    async def _download_next(self) -> bool:
        controllers = self._registry.all()
        count = len(controllers)
        for offset in range(count):
            if self._paused:
                return False
            controller = controllers[(self._cursor + offset) % count]
            if controller.chat_id in self._no_access:
                continue
            if await self._download_one(controller):
                self._cursor = (self._cursor + offset + 1) % count
                return True
        return False

    def _wanted(self, info: MediaInfo) -> bool:
        if info.type not in self._config.types:
            return False
        return info.size is None or info.size <= self._config.max_file_mb * _MIB

    async def _refresh(self, controller: ChatController) -> _ChatScan:
        scan = self._scans.setdefault(controller.chat_id, _ChatScan())
        await asyncio.to_thread(self._scan_parts, controller.folder, scan)
        return scan

    def _scan_parts(self, folder: Path, scan: _ChatScan) -> None:
        paths = list_parts(folder)
        signature = tuple((p.name, _size_of(p)) for p in paths)
        cached = scan.parts
        same_names = len(signature) >= len(cached) and all(
            old[0] == new[0] for old, new in zip(cached, signature, strict=False)
        )
        if cached and same_names:
            start = next(
                (
                    n
                    for n, (old, new) in enumerate(zip(cached, signature, strict=False))
                    if old != new
                ),
                len(cached) - 1,
            )
        else:
            scan.done.clear()
            scan.pending.clear()
            start = 0
        for path in paths[start:]:
            for record in iter_part_records(path):
                if isinstance(record, MediaSavedRecord):
                    scan.done.add(record.msg_id)
                    scan.pending.pop(record.msg_id, None)
                elif (
                    isinstance(record, MessageRecord)
                    and record.media is not None
                    and record.msg_id not in scan.done
                    and self._wanted(record.media)
                ):
                    scan.pending[record.msg_id] = _Pending(month_key(record.date), record.media)
        scan.parts = signature

    async def _download_one(self, controller: ChatController) -> bool:
        scan = await self._refresh(controller)
        chat_id = controller.chat_id
        state = load_state(controller.folder)
        if state is None:
            return False
        floor = state.floor_id
        for msg_id in sorted(scan.pending):
            if msg_id < floor or self._attempts.get((chat_id, msg_id), 0) >= MAX_ATTEMPTS:
                continue
            pending = scan.pending[msg_id]
            try:
                await self._fetch(controller, scan, msg_id, pending)
            except FloodWait as exc:
                log.warning("media FloodWait", extra={"chat_id": chat_id, "seconds": exc.seconds})
                await self._clock.sleep(exc.seconds)
                return False
            except AccessLost:
                log.warning("media: no access to chat", extra={"chat_id": chat_id})
                self._no_access.add(chat_id)
                return False
            except Exception:
                self._fail(chat_id, msg_id)
                return True
            return True
        return False

    def _fail(self, chat_id: int, msg_id: int) -> None:
        key = (chat_id, msg_id)
        self._attempts[key] = self._attempts.get(key, 0) + 1
        log.warning(
            "media download failed",
            extra={"chat_id": chat_id, "msg_id": msg_id, "attempt": self._attempts[key]},
            exc_info=True,
        )

    async def _fetch(
        self, controller: ChatController, scan: _ChatScan, msg_id: int, pending: _Pending
    ) -> None:
        chat_id = controller.chat_id
        target_dir = controller.folder / "media" / pending.month
        target_dir.mkdir(parents=True, exist_ok=True)
        downloaded = await self._gateway.download_media(chat_id, msg_id, target_dir)
        if downloaded is None:
            scan.done.add(msg_id)
            scan.pending.pop(msg_id, None)
            log.info("media unavailable", extra={"chat_id": chat_id, "msg_id": msg_id})
            return
        final = _unique_name(downloaded, msg_id)
        if final != downloaded:
            downloaded.replace(final)
        relative = f"media/{pending.month}/{final.name}"
        async with controller.lock:
            state = load_state(controller.folder)
            if state is None or msg_id < state.floor_id:
                final.unlink(missing_ok=True)
                scan.pending.pop(msg_id, None)
                return
            record = MediaSavedRecord(
                chat_id=chat_id, msg_id=msg_id, file=relative, fetched_at=self._clock.now()
            )
            writer = ChunkWriter(controller.folder, self._max_chunk_bytes, self._clock.now)
            writer.append(state, [record])
        scan.done.add(msg_id)
        scan.pending.pop(msg_id, None)
        log.info("media saved", extra={"chat_id": chat_id, "msg_id": msg_id})


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return -1


def _unique_name(downloaded: Path, msg_id: int) -> Path:
    """`<msg_id><ext>`, or `<msg_id>_<n><ext>` when that name is taken by another file."""
    suffix = downloaded.suffix
    number = 0
    while True:
        stem = str(msg_id) if number == 0 else f"{msg_id}_{number}"
        candidate = downloaded.with_name(f"{stem}{suffix}")
        if candidate == downloaded or not candidate.exists():
            return candidate
        number += 1
