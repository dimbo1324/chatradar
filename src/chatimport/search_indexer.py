"""The incremental scanner that feeds the search index from the stored parts.

One *pass* lists every chat folder and compares each part's size and mtime with its watermark
(`PartMark`: bytes consumed, checksums of the first and last bytes before that point). A part
that only grew is read from its watermark; a part that is new is read from the start; a part
that is gone (a trim) drops the messages below the oldest retained one; a part whose consumed
prefix no longer matches (rewritten or cut) makes the whole chat *reconcile*. Work happens in
`step()` calls of at most `BATCH_RECORDS` records, one transaction each, chat by chat, so the
first searches work on the finished part of a long initial build.

A chat with a `.<month>.commit.json` journal is mid-rewrite and is left for a later pass.
"""

from __future__ import annotations

import logging
import os
import zlib
from collections import deque
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chatimport.search_fold import clean_text
from chatimport.search_index import ChatRow, PartMark, SearchIndex
from chatimport.search_types import IndexState
from chatimport.storage.layout import iter_chat_folders, parse_part_name
from chatimport.storage.month_commit import JOURNAL_SUFFIX
from chatimport.storage.reader import decode_line, first_message
from chatimport.storage.state import ChatState, StateUnreadable, load_state

if TYPE_CHECKING:
    from collections.abc import Callable
    from datetime import datetime
    from pathlib import Path

    from chatimport.records import Record

log = logging.getLogger(__name__)

BATCH_RECORDS: Final = 2000
BLOCK_BYTES: Final = 1024 * 1024
WINDOW: Final = 4096
EVERYTHING: Final = 2**63 - 1
UNFINISHED: Final = -1


@dataclass(frozen=True, slots=True)
class StepResult:
    more: bool
    state: IndexState
    indexed: int
    total: int
    updated_at: datetime | None


def _crc(data: bytes) -> int:
    return zlib.crc32(data)


@dataclass(slots=True)
class PartCursor:
    """A read position in one part with the first and last bytes seen, for the fingerprint."""

    path: Path
    size: int
    mtime_ns: int
    offset: int = 0
    head: bytes = b""
    tail: bytes = b""

    @classmethod
    def resume(cls, path: Path, size: int, mtime_ns: int, mark: PartMark) -> PartCursor | None:
        """The cursor at `mark.offset`, or None when the part no longer starts and ends (at
        that point) with the bytes that were indexed."""
        if size < mark.offset:
            return None
        with path.open("rb") as handle:
            head = handle.read(min(mark.offset, WINDOW))
            handle.seek(max(0, mark.offset - WINDOW))
            tail = handle.read(min(mark.offset, WINDOW))
        if _crc(head) != mark.head_crc or _crc(tail) != mark.tail_crc:
            return None
        return cls(path, size, mtime_ns, mark.offset, head, tail)

    def read_lines(self, limit: int) -> list[bytes] | None:
        """The non-empty lines among the complete lines from the offset on (about `limit`
        bytes); None when no complete line is left (a line still being written stays unread)."""
        with self.path.open("rb") as handle:
            handle.seek(self.offset)
            data = handle.read(limit)
            end = data.rfind(b"\n") + 1
            if end == 0 and len(data) == limit:
                data += handle.read()
                end = data.rfind(b"\n") + 1
        if end == 0:
            return None
        chunk = data[:end]
        self.offset += end
        if len(self.head) < WINDOW:
            self.head = (self.head + chunk)[:WINDOW]
        self.tail = (self.tail + chunk)[-WINDOW:]
        return [line for line in chunk.split(b"\n") if line.strip()]

    def mark(self, *, complete: bool) -> PartMark:
        """The watermark; `size` is only recorded once the part was read to its last complete
        line, so a part left half read never looks up to date after a restart."""
        size = self.size if complete else UNFINISHED
        return PartMark(
            self.path.name, self.offset, size, self.mtime_ns, _crc(self.head), _crc(self.tail)
        )


@dataclass(frozen=True, slots=True)
class _PartInfo:
    path: Path
    size: int
    mtime_ns: int


@dataclass(slots=True)
class _Item:
    chat_id: int
    todo: list[_PartInfo]
    all_parts: list[_PartInfo]
    reconcile: bool
    marks: dict[str, PartMark]
    cursor: PartCursor | None = None


def _listing(folder: Path) -> list[_PartInfo] | None:
    """The parts of a folder with size and mtime; None while a month rewrite is journalled."""
    parts: list[_PartInfo] = []
    with os.scandir(folder) as entries:
        for entry in entries:
            if entry.name.endswith(JOURNAL_SUFFIX):
                return None
            if parse_part_name(entry.name) is not None and entry.is_file():
                info = entry.stat()
                parts.append(_PartInfo(folder / entry.name, info.st_size, info.st_mtime_ns))
    return sorted(parts, key=lambda p: p.path.name)


class IndexBuilder:
    """Drives passes over the data root. Not thread-safe: one thread at a time."""

    def __init__(
        self,
        index: SearchIndex,
        root: Path,
        now: Callable[[], datetime],
        batch: int = BATCH_RECORDS,
    ) -> None:
        self._index = index
        self._root = root
        self._now = now
        self._batch = batch
        self._queue: deque[_Item] | None = None
        self._ready = False
        self._changed = False
        self._incomplete = False
        self._total = 0
        self._updated: datetime | None = None

    def step(self) -> StepResult:
        """One bounded unit of work; `more` says whether another call has work to do."""
        try:
            return self._step()
        except BaseException:
            self._queue = None
            self._incomplete = False
            raise

    def _step(self) -> StepResult:
        if self._queue is None:
            self._queue = self._plan_pass()
        if self._queue:
            if self._advance(self._queue[0]):
                self._queue.popleft()
            self._changed = True
            if not self._ready:
                self._status(IndexState.BUILDING)
            return self._result(more=True)
        self._queue = None
        incomplete, self._incomplete = self._incomplete, False
        if not incomplete and (self._changed or not self._ready):
            self._ready = True
            self._changed = False
            self._status(IndexState.READY)
        return self._result(more=False)

    def _figures(self) -> tuple[IndexState, int, int]:
        indexed = self._index.indexed_count()
        if self._ready:
            return IndexState.READY, indexed, indexed
        return IndexState.BUILDING, indexed, max(self._total, indexed)

    def _status(self, state: IndexState) -> None:
        _, _, total = self._figures()
        self._updated = self._now()
        self._index.set_status(state, total, self._updated)

    def _result(self, *, more: bool) -> StepResult:
        state, indexed, total = self._figures()
        return StepResult(more, state, indexed, total, self._updated)

    def _plan_pass(self) -> deque[_Item]:
        queue: deque[_Item] = deque()
        rows = self._index.chat_rows()
        seen: set[int] = set()
        total = 0
        if not self._root.is_dir():
            return queue
        try:
            for folder in iter_chat_folders(self._root):
                try:
                    state = load_state(folder)
                except StateUnreadable:
                    self._incomplete = True
                    continue
                if state is None or state.chat_id in seen:
                    continue
                seen.add(state.chat_id)
                total += state.total_records
                item = self._plan_chat(folder, state, rows.get(state.chat_id))
                if item is not None:
                    queue.append(item)
        except OSError:
            log.warning("search index could not list the data folder")
            self._incomplete = True
            return queue
        for chat_id, row in rows.items():
            if chat_id not in seen and not (self._root / row.folder).is_dir():
                self._index.drop_chat(chat_id)
                self._changed = True
        self._total = total
        return queue

    def _plan_chat(self, folder: Path, state: ChatState, row: ChatRow | None) -> _Item | None:
        try:
            parts = _listing(folder)
        except OSError:
            parts = None
        if parts is None:
            self._incomplete = True
            return None
        identity = (clean_text(state.title), state.username, folder.name)
        if row is None or (row.title, row.username, row.folder) != identity:
            self._index.upsert_chat(state.chat_id, state.title, state.username, folder.name)
        marks = self._index.marks(state.chat_id)
        removed = sorted(set(marks) - {p.path.name for p in parts})
        if removed and not self._forget(state, parts, removed):
            return None
        todo = [
            p
            for p in parts
            if (mark := marks.get(p.path.name)) is None
            or (mark.size, mark.mtime_ns) != (p.size, p.mtime_ns)
        ]
        reconciling = row is not None and row.reconciling
        if not todo and not reconciling:
            return None
        return _Item(state.chat_id, todo, parts, reconciling, marks)

    def _forget(self, state: ChatState, parts: list[_PartInfo], removed: list[str]) -> bool:
        try:
            first = first_message(p.path for p in parts)
        except OSError:
            self._incomplete = True
            return False
        floor = EVERYTHING if first is None else max(state.floor_id, first.msg_id)
        self._index.remove_below(state.chat_id, floor)
        self._index.forget_parts(state.chat_id, removed)
        self._changed = True
        log.info(
            "search index dropped trimmed history",
            extra={"chat_id": state.chat_id, "parts": len(removed)},
        )
        return True

    def _restart(self, item: _Item) -> None:
        log.info("search index re-reads a rewritten chat", extra={"chat_id": item.chat_id})
        self._index.begin_reconcile(item.chat_id)
        item.todo = list(item.all_parts)
        item.marks = {}
        item.cursor = None
        item.reconcile = True

    def _cursor(self, item: _Item, info: _PartInfo) -> PartCursor | None:
        if item.cursor is not None:
            return item.cursor
        mark = item.marks.get(info.path.name)
        if mark is None:
            return PartCursor(info.path, info.size, info.mtime_ns)
        return PartCursor.resume(info.path, info.size, info.mtime_ns, mark)

    def _advance(self, item: _Item) -> bool:
        """Index up to one batch of `item`; True when the chat is finished for this pass."""
        records: list[Record] = []
        marks: list[PartMark] = []
        budget = self._batch
        try:
            while item.todo and budget > 0:
                cursor = self._cursor(item, item.todo[0])
                if cursor is None:
                    self._restart(item)
                    return False
                item.cursor = cursor
                lines = cursor.read_lines(BLOCK_BYTES)
                if lines is None:
                    marks.append(cursor.mark(complete=True))
                    item.todo.pop(0)
                    item.cursor = None
                    continue
                budget -= max(len(lines), 1)
                records.extend(r for line in lines if (r := decode_line(line.strip())) is not None)
        except OSError:
            log.warning("search index could not read a part", extra={"chat_id": item.chat_id})
            self._incomplete = True
            return True
        if item.cursor is not None:
            marks.append(item.cursor.mark(complete=False))
        if records or marks:
            self._index.apply(item.chat_id, records, marks)
        done = not item.todo
        if done and item.reconcile:
            self._index.finish_reconcile(item.chat_id)
        return done
