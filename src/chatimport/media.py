"""MediaDownloader (spec §12): one file at a time, with its own pause, for chosen media types.

Files go to `media/<YYYY-MM>/<msg_id>[_<n>]<ext>` (`storage.media_files`); a `media_saved`
record is appended afterwards. Finding the pending media re-reads only what was appended to
the newest part since the last look; any other change to the parts starts a full rescan.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from chatimport.ports import AccessLost, FloodWait
from chatimport.records import MediaSavedRecord, MessageRecord
from chatimport.storage.layout import MEDIA_DIR, list_parts, month_key
from chatimport.storage.media_files import mark_downloaded, media_month_dir, unique_media_path
from chatimport.storage.reader import read_appended
from chatimport.storage.state import StateUnreadable, load_state
from chatimport.storage.writer import ChunkWriter

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.config import MediaConfig
    from chatimport.ports import Clock, TelegramGateway
    from chatimport.records import MediaInfo, Record
    from chatimport.runtime import ChatHandle, ChatRegistry

log = logging.getLogger(__name__)

DOWNLOAD_PAUSE_SECONDS: Final = 2.0
IDLE_SECONDS: Final = 5.0
MAX_ATTEMPTS: Final = 3


@dataclass(slots=True)
class _Pending:
    month: str
    info: MediaInfo


@dataclass(frozen=True, slots=True)
class _PartMark:
    """What a scan saw of one part: identity, size and how far it was read."""

    name: str
    size: int
    ino: int
    offset: int = 0

    def same_file(self, other: _PartMark) -> bool:
        return (self.name, self.ino) == (other.name, other.ino)


@dataclass(slots=True)
class _ChatScan:
    parts: tuple[_PartMark, ...] = ()
    done: set[int] = field(default_factory=set[int])
    pending: dict[int, _Pending] = field(default_factory=dict[int, _Pending])


def _identity(path: Path) -> tuple[int, int]:
    try:
        stat = path.stat()
    except OSError:
        return -1, 0
    return stat.st_size, stat.st_ino


def _resume_index(cached: tuple[_PartMark, ...], current: list[_PartMark]) -> int | None:
    """Index of the part to continue reading from when only the newest cached part grew in
    place (and maybe new parts followed it); None when a full rescan is needed."""
    if not cached or len(current) < len(cached):
        return None
    last = len(cached) - 1
    for old, new in zip(cached[:last], current, strict=False):
        if (old.name, old.size, old.ino) != (new.name, new.size, new.ino):
            return None
    tail, now = cached[last], current[last]
    if not tail.same_file(now) or now.size < tail.size:
        return None
    return last


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
        return info.size is None or info.size <= self._config.max_file_bytes

    async def _refresh(self, handle: ChatHandle) -> _ChatScan:
        scan = self._scans.setdefault(handle.chat_id, _ChatScan())
        await asyncio.to_thread(self._scan_parts, handle.folder, scan)
        return scan

    def _scan_parts(self, folder: Path, scan: _ChatScan) -> None:
        paths = list_parts(folder)
        current = [_PartMark(p.name, *_identity(p)) for p in paths]
        start = _resume_index(scan.parts, current)
        previous = scan.parts
        if start is None:
            scan.done.clear()
            scan.pending.clear()
            start, previous = 0, ()
        marks = list(previous[:start])
        for index in range(start, len(paths)):
            offset = previous[index].offset if index < len(previous) else 0
            records, end = read_appended(paths[index], offset)
            self._absorb(scan, records)
            marks.append(
                _PartMark(current[index].name, current[index].size, current[index].ino, end)
            )
        scan.parts = tuple(marks)

    def _absorb(self, scan: _ChatScan, records: list[Record]) -> None:
        for record in records:
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

    async def _download_one(self, handle: ChatHandle) -> bool:
        scan = await self._refresh(handle)
        chat_id = handle.chat_id
        try:
            state = load_state(handle.folder)
        except StateUnreadable:
            return False
        if state is None:
            return False
        floor = state.floor_id
        for msg_id in sorted(scan.pending):
            if msg_id < floor or self._attempts.get((chat_id, msg_id), 0) >= MAX_ATTEMPTS:
                continue
            pending = scan.pending[msg_id]
            try:
                await self._fetch(handle, scan, msg_id, pending)
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
        self, handle: ChatHandle, scan: _ChatScan, msg_id: int, pending: _Pending
    ) -> None:
        chat_id = handle.chat_id
        target_dir = media_month_dir(handle.folder, pending.month)
        target_dir.mkdir(parents=True, exist_ok=True)
        downloaded = await self._gateway.download_media(chat_id, msg_id, target_dir)
        if downloaded is None:
            scan.done.add(msg_id)
            scan.pending.pop(msg_id, None)
            log.info("media unavailable", extra={"chat_id": chat_id, "msg_id": msg_id})
            return
        final = unique_media_path(downloaded, msg_id, pending.info.type)
        if final != downloaded:
            downloaded.replace(final)
        mark_downloaded(final)
        relative = f"{MEDIA_DIR}/{pending.month}/{final.name}"
        async with handle.lock:
            state = load_state(handle.folder)
            if state is None or msg_id < state.floor_id:
                final.unlink(missing_ok=True)
                scan.pending.pop(msg_id, None)
                return
            record = MediaSavedRecord(
                chat_id=chat_id, msg_id=msg_id, file=relative, fetched_at=self._clock.now()
            )
            writer = ChunkWriter(handle.folder, self._max_chunk_bytes, self._clock.now)
            writer.append(state, [record])
        scan.done.add(msg_id)
        scan.pending.pop(msg_id, None)
        log.info("media saved", extra={"chat_id": chat_id, "msg_id": msg_id})
