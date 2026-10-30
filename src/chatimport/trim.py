"""Trimming (spec §8.5, §8.6): whole oldest parts, one cut boundary part, media, the trim log.

Folders of chats that are on disk but not active (a disabled library entry) are trimmed too,
under a lock of their own: nothing else writes into them.
"""

from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from chatimport.ports import ChatImportError
from chatimport.records import MessageRecord, escape_line_breaks, format_dt, record_event_date
from chatimport.storage.fileio import append_line, unlink_file
from chatimport.storage.layout import MEDIA_DIR, iter_chat_folders, parse_part_name
from chatimport.storage.media_files import delete_media, media_month_dir
from chatimport.storage.reader import iter_part_records, read_part_lines
from chatimport.storage.state import (
    ChatState,
    ChunkInfo,
    StateUnreadable,
    atomic_write_bytes,
    load_state,
    save_state,
)
from chatimport.storage.writer import scan_part

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import Clock
    from chatimport.runtime import ChatHandle, ChatRegistry

__all__ = ["ALLOWED_PERCENTS", "MEDIA_DIR", "TRIM_LOG", "TrimReport", "TrimmedPart", "Trimmer"]

log = logging.getLogger(__name__)

TRIM_LOG: Final = "_trim_log.jsonl"
ALLOWED_PERCENTS: Final = (25, 50, 75)
FLOOR_REASON_DISK: Final = "disk"


@dataclass(frozen=True, slots=True)
class TrimmedPart:
    chat_id: int
    part: str
    records: int
    first_id: int
    last_id: int
    bytes: int


@dataclass(slots=True)
class TrimReport:
    deleted_parts: list[TrimmedPart] = field(default_factory=list[TrimmedPart])
    trimmed_records: int = 0
    freed_bytes: int = 0
    per_chat: dict[int, int] = field(default_factory=dict[int, int])


@dataclass(frozen=True, slots=True)
class _FolderHandle:
    """A chat folder with no active worker (`runtime.ChatHandle`)."""

    chat_id: int
    folder: Path
    lock: asyncio.Lock


@dataclass(frozen=True, slots=True)
class _Candidate:
    handle: ChatHandle
    first_date: datetime


@dataclass(frozen=True, slots=True)
class _Oldest:
    """A chat's oldest part that is old enough for the disk trim, and the state it is in."""

    first_date: datetime
    state: ChatState
    key: str


@dataclass(slots=True)
class _ChatTrim:
    """What one manual trim of one chat has done so far; persisted even when it fails."""

    deleted: list[TrimmedPart] = field(default_factory=list[TrimmedPart])
    removed: int = 0
    freed: int = 0
    boundary_key: str | None = None

    @property
    def changed(self) -> bool:
        return bool(self.deleted) or self.boundary_key is not None


def _month_of(key: str) -> str:
    return key.rsplit("_", 1)[0]


def _month_start(month: str) -> datetime:
    return datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)


def _next_month_start(month: str) -> datetime:
    start = _month_start(month)
    return (
        start.replace(year=start.year + 1, month=1)
        if start.month == 12
        else start.replace(month=start.month + 1)
    )


def _message_ids(path: Path) -> set[int]:
    return {r.msg_id for r in iter_part_records(path) if isinstance(r, MessageRecord)}


def _existing_chunks(folder: Path, state: ChatState) -> dict[str, ChunkInfo]:
    """The listed parts that are real part files of this folder, oldest first."""
    return {
        key: info
        for key, info in sorted(state.chunks.items())
        if parse_part_name(f"{key}.jsonl") is not None and (folder / f"{key}.jsonl").is_file()
    }


def _first_remaining_id(folder: Path, chunks: dict[str, ChunkInfo]) -> int | None:
    for key in sorted(chunks):
        for record in iter_part_records(folder / f"{key}.jsonl"):
            if isinstance(record, MessageRecord):
                return record.msg_id
    return None


def _drop_part(folder: Path, chat_id: int, key: str, info: ChunkInfo) -> TrimmedPart:
    """Delete one whole part and the media of its messages. The part is decoded only when
    its month has a media folder."""
    path = folder / f"{key}.jsonl"
    size = path.stat().st_size
    month = _month_of(key)
    ids = _message_ids(path) if media_month_dir(folder, month).is_dir() else set[int]()
    unlink_file(path)
    delete_media(folder, month, ids)
    return TrimmedPart(chat_id, key, info.records, info.first_id, info.last_id, size)


class Trimmer:
    def __init__(
        self,
        root: Path,
        registry: ChatRegistry,
        *,
        clock: Clock,
        max_chunk_bytes: int,
    ) -> None:
        self.root = root
        self.registry = registry
        self.max_chunk_bytes = max_chunk_bytes
        self._clock = clock
        self._locks: dict[int, asyncio.Lock] = {}

    def _handles(self) -> list[ChatHandle]:
        """Active chats first, then every other chat folder under the root."""
        handles: list[ChatHandle] = list(self.registry.all())
        known = {handle.chat_id for handle in handles}
        for folder in iter_chat_folders(self.root):
            try:
                state = load_state(folder)
            except StateUnreadable:
                log.warning(
                    "skipped a chat whose state is unreadable", extra={"folder": folder.name}
                )
                continue
            if state is None or state.chat_id in known:
                continue
            known.add(state.chat_id)
            lock = self._locks.setdefault(state.chat_id, asyncio.Lock())
            handles.append(_FolderHandle(state.chat_id, folder, lock))
        return handles

    def _still_free(self, handle: ChatHandle) -> bool:
        """A folder handle may be used only while no worker took the chat over."""
        return not isinstance(handle, _FolderHandle) or self.registry.get(handle.chat_id) is None

    async def trim_percent(self, pct: int, chat_id: int | None = None) -> TrimReport:
        if pct not in ALLOWED_PERCENTS:
            raise ValueError(f"pct must be one of {ALLOWED_PERCENTS}, got {pct}")
        handles = self._handles()
        if chat_id is not None:
            handles = [h for h in handles if h.chat_id == chat_id]
            if not handles:
                raise ChatImportError(f"no chat {chat_id} to trim")
        report = TrimReport()
        for handle in handles:
            async with handle.lock:
                if self._still_free(handle):
                    self._trim_chat(handle, pct, report)
        return report

    def _trim_chat(self, handle: ChatHandle, pct: int, report: TrimReport) -> None:
        folder = handle.folder
        if not folder.is_dir():
            return
        state = load_state(folder)
        if state is None:
            return
        chunks = _existing_chunks(folder, state)
        target = sum(c.records for c in chunks.values()) * pct // 100
        if target <= 0:
            return
        done = _ChatTrim()
        keys = iter(chunks)
        try:
            key = next(keys)
            while done.removed + chunks[key].records <= target:
                part = _drop_part(folder, handle.chat_id, key, chunks[key])
                done.deleted.append(part)
                done.removed += part.records
                done.freed += part.bytes
                key = next(keys)
            skip = target - done.removed
            if skip > 0:
                freed_cut, cut_ids = self._cut_boundary(folder / f"{key}.jsonl", skip)
                done.boundary_key = key
                done.removed += skip
                done.freed += freed_cut
                delete_media(folder, _month_of(key), cut_ids)
        except BaseException:
            if done.changed:
                self._save_manual_trim(handle, state, chunks, pct, done, report)
            raise
        self._save_manual_trim(handle, state, chunks, pct, done, report)

    def _save_manual_trim(
        self,
        handle: ChatHandle,
        state: ChatState,
        chunks: dict[str, ChunkInfo],
        pct: int,
        done: _ChatTrim,
        report: TrimReport,
    ) -> None:
        folder = handle.folder
        deleted_keys = {d.part for d in done.deleted}
        remaining = {k: v for k, v in chunks.items() if k not in deleted_keys}
        if done.boundary_key is not None:
            remaining[done.boundary_key] = scan_part(folder / f"{done.boundary_key}.jsonl")
        reason = f"manual_trim_{pct}"
        self._save_trimmed(folder, state, remaining, reason)
        report.deleted_parts.extend(done.deleted)
        report.trimmed_records += done.removed
        report.freed_bytes += done.freed
        report.per_chat[handle.chat_id] = done.removed
        self._log_entry(
            kind="manual",
            chat_id=handle.chat_id,
            pct=pct,
            parts=[d.part for d in done.deleted],
            records=done.removed,
            freed=done.freed,
            reason=reason,
        )
        log.info(
            "manual trim done",
            extra={
                "chat_id": handle.chat_id,
                "pct": pct,
                "records": done.removed,
                "bytes": done.freed,
            },
        )

    def _save_trimmed(
        self, folder: Path, state: ChatState, remaining: dict[str, ChunkInfo], reason: str
    ) -> None:
        first_id = _first_remaining_id(folder, remaining)
        floor = first_id if first_id is not None else state.last_id
        save_state(
            folder,
            replace(
                state,
                chunks=remaining,
                floor_id=max(state.floor_id, floor),
                floor_reason=reason,
                updated_at=self._clock.now(),
            ),
        )

    @staticmethod
    def _cut_boundary(path: Path, skip: int) -> tuple[int, set[int]]:
        """Drop the first `skip` records; the kept lines are copied byte for byte."""
        lines = read_part_lines(path)
        old_size = path.stat().st_size
        seen = 0
        cut = 0
        ids: set[int] = set()
        while cut < len(lines) and seen < skip:
            record = lines[cut].record
            if record is not None:
                seen += 1
                if isinstance(record, MessageRecord):
                    ids.add(record.msg_id)
            cut += 1
        payload = b"".join(line.data for line in lines[cut:])
        atomic_write_bytes(path, payload)
        return max(0, old_size - len(payload)), ids

    async def delete_oldest_part(self, protect_recent_days: int) -> TrimmedPart | None:
        cutoff = self._clock.now() - timedelta(days=protect_recent_days)
        candidates: list[_Candidate] = []
        for handle in self._handles():
            async with handle.lock:
                oldest = self._oldest_eligible(handle, cutoff)
            if oldest is not None:
                candidates.append(_Candidate(handle, oldest.first_date))
        for candidate in sorted(candidates, key=lambda c: c.first_date):
            async with candidate.handle.lock:
                oldest = self._oldest_eligible(candidate.handle, cutoff)
                if oldest is not None and self._still_free(candidate.handle):
                    return self._delete_oldest(candidate.handle, oldest)
        return None

    def _oldest_eligible(self, handle: ChatHandle, cutoff: datetime) -> _Oldest | None:
        """First message date of the chat's oldest part, if the whole part is older than
        cutoff. A month that ends before the cutoff is read only up to its first message."""
        folder = handle.folder
        if not folder.is_dir():
            return None
        try:
            state = load_state(folder)
        except StateUnreadable:
            log.warning("disk trim skipped an unreadable state", extra={"chat_id": handle.chat_id})
            return None
        if state is None:
            return None
        chunks = _existing_chunks(folder, state)
        if not chunks:
            return None
        key = next(iter(chunks))
        month = _month_of(key)
        whole_month_is_old = _next_month_start(month) <= cutoff
        first_date: datetime | None = None
        last_date = _month_start(month)
        for record in iter_part_records(folder / f"{key}.jsonl"):
            last_date = max(last_date, record_event_date(record))
            if first_date is None and isinstance(record, MessageRecord):
                first_date = record.date
                if whole_month_is_old:
                    break
        if last_date >= cutoff:
            return None
        return _Oldest(first_date or _month_start(month), state, key)

    def _delete_oldest(self, handle: ChatHandle, oldest: _Oldest) -> TrimmedPart:
        folder = handle.folder
        state, key = oldest.state, oldest.key
        chunks = _existing_chunks(folder, state)
        info = chunks[key]
        part = _drop_part(folder, handle.chat_id, key, info)
        remaining = {k: v for k, v in chunks.items() if k != key}
        next_first = next((v.first_id for v in remaining.values() if v.first_id), None)
        floor = next_first if next_first is not None else info.last_id
        save_state(
            folder,
            replace(
                state,
                chunks=remaining,
                floor_id=max(state.floor_id, floor),
                floor_reason=FLOOR_REASON_DISK,
                updated_at=self._clock.now(),
            ),
        )
        self._log_entry(
            kind="disk",
            chat_id=handle.chat_id,
            pct=None,
            parts=[key],
            records=info.records,
            freed=part.bytes,
            reason=FLOOR_REASON_DISK,
        )
        log.info(
            "disk trim deleted a part",
            extra={"chat_id": handle.chat_id, "part": key, "bytes": part.bytes},
        )
        return part

    def _log_entry(
        self,
        *,
        kind: str,
        chat_id: int,
        pct: int | None,
        parts: list[str],
        records: int,
        freed: int,
        reason: str,
    ) -> None:
        entry = {
            "when": format_dt(self._clock.now()),
            "kind": kind,
            "chat_id": chat_id,
            "pct": pct,
            "parts": parts,
            "records": records,
            "bytes": freed,
            "reason": reason,
        }
        line = escape_line_breaks(json.dumps(entry, ensure_ascii=False)) + "\n"
        append_line(self.root / TRIM_LOG, line.encode("utf-8"))
