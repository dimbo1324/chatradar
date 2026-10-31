"""Writing month parts. No file stays open between calls (Windows deletes them).

The reading helpers live in `storage.reader` and are re-exported here for older imports.
"""

from __future__ import annotations

import logging
from dataclasses import replace
from itertools import groupby
from typing import TYPE_CHECKING

from chatimport.ports import ChatImportError
from chatimport.records import (
    MessageRecord,
    Record,
    record_event_date,
    record_sort_id,
    record_to_bytes,
    utc_now,
)
from chatimport.storage.fileio import append_line
from chatimport.storage.layout import MAX_PART_NUMBER, month_key, parse_part_name, part_file_name
from chatimport.storage.month_commit import commit_month, month_parts, replay_month
from chatimport.storage.reader import (
    EMPTY_CHUNK,
    PartLine,
    chunk_info,
    count_lines,
    decode_line,
    first_message,
    iter_part_records,
    iter_records,
    read_part_lines,
    scan_part,
)
from chatimport.storage.state import ChatState, atomic_write_bytes, later, save_state

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Sequence
    from datetime import datetime
    from pathlib import Path

__all__ = [
    "ChunkWriter",
    "PartMissing",
    "count_lines",
    "decode_line",
    "first_message",
    "iter_part_records",
    "iter_records",
    "scan_part",
]

log = logging.getLogger(__name__)


class PartMissing(ChatImportError):
    """`state.json` lists the part an append would extend, but the file is gone (deleted by
    hand). The caller must recover the folder first, so the deletion is accounted for."""

    def __init__(self, part: str) -> None:
        super().__init__(f"part {part} is listed in state.json but missing on disk")
        self.part = part


def _message_order(record: Record) -> tuple[int, int]:
    return record_sort_id(record), 0 if isinstance(record, MessageRecord) else 1


def _newest_message_date(records: Iterable[Record | None]) -> datetime | None:
    dates = [r.date for r in records if isinstance(r, MessageRecord)]
    return max(dates, default=None)


def _sorted_lines(lines: Sequence[PartLine]) -> list[PartLine]:
    """Sort by message order; a line that does not parse keeps its place after the line
    that preceded it."""
    keyed: list[tuple[tuple[int, int], int, PartLine]] = []
    key = (0, 0)
    for position, line in enumerate(lines):
        if line.record is not None:
            key = _message_order(line.record)
        keyed.append((key, position, line))
    keyed.sort(key=lambda item: (item[0], item[1]))
    return [line for _, _, line in keyed]


class ChunkWriter:
    def __init__(
        self,
        folder: Path,
        max_chunk_bytes: int,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self.folder = folder
        self.max_chunk_bytes = max_chunk_bytes
        self._clock = clock

    def update_state(self, state: ChatState) -> ChatState:
        state = replace(state, updated_at=self._clock())
        save_state(self.folder, state)
        return state

    def append(self, state: ChatState, records: Sequence[Record]) -> ChatState:
        """Live append; the state file is saved only after the data is fsynced and closed."""
        if not records:
            return state
        self.folder.mkdir(parents=True, exist_ok=True)

        def month_of(record: Record) -> str:
            return month_key(record_event_date(record))

        ordered = sorted(records, key=lambda r: (month_of(r), record_sort_id(r)))
        chunks = dict(state.chunks)
        last_id = state.last_id
        for month, group in groupby(ordered, key=month_of):
            batch = list(group)
            path = self._append_target(month)
            key = path.stem
            exists = path.exists()
            if key in chunks and not exists:
                raise PartMissing(key)
            base = chunks.get(key) or (scan_part(path) if exists else EMPTY_CHUNK)
            append_line(path, b"".join(record_to_bytes(record) for record in batch))
            chunks[key] = chunk_info(batch, path.stat().st_size, base)
            last_id = max(
                [last_id, *(r.msg_id for r in batch if isinstance(r, MessageRecord))],
            )
        newest = later(state.newest_date, _newest_message_date(ordered))
        return self.update_state(replace(state, chunks=chunks, last_id=last_id, newest_date=newest))

    def write_month(
        self, state: ChatState, month: str, records: Sequence[MessageRecord]
    ) -> ChatState:
        """Backfill: replace all parts of `month` in one crash-safe step."""
        by_id = {record.msg_id: record for record in reversed(records)}
        if not by_id:
            return state
        replay_month(self.folder, month)
        lines = [PartLine(record_to_bytes(by_id[i]), by_id[i]) for i in sorted(by_id)]
        return self._write_lines(state, month, lines)

    def merge_month(
        self, state: ChatState, month: str, messages: Sequence[MessageRecord]
    ) -> ChatState:
        """Add messages to a month that may already hold parts, keeping every existing line
        byte for byte (messages, edits, deletes, media marks, lines this version cannot read);
        known `msg_id`s are not replaced."""
        replay_month(self.folder, month)
        existing = [
            line for path in month_parts(self.folder, month) for line in read_part_lines(path)
        ]
        if not existing:
            return self.write_month(state, month, messages)
        known = {line.record.msg_id for line in existing if isinstance(line.record, MessageRecord)}
        fresh = {m.msg_id: m for m in reversed(messages) if m.msg_id not in known}
        if not fresh:
            return state
        added = [PartLine(record_to_bytes(m), m) for m in fresh.values()]
        return self._write_lines(state, month, _sorted_lines([*existing, *added]))

    def _write_lines(self, state: ChatState, month: str, lines: Sequence[PartLine]) -> ChatState:
        self.folder.mkdir(parents=True, exist_ok=True)
        groups: list[list[PartLine]] = []
        current: list[PartLine] = []
        size = 0
        for line in lines:
            current.append(line)
            size += len(line.data)
            if size >= self.max_chunk_bytes:
                groups.append(current)
                current, size = [], 0
        if current:
            groups.append(current)
        if len(groups) > MAX_PART_NUMBER:
            raise ValueError(f"month {month} needs more than {MAX_PART_NUMBER} parts")

        payloads = [b"".join(line.data for line in group) for group in groups]
        commit_month(
            self.folder, month, payloads, lambda path, data: atomic_write_bytes(path, data)
        )
        chunks = {k: v for k, v in state.chunks.items() if not k.startswith(f"{month}_")}
        for number, (group, payload) in enumerate(zip(groups, payloads, strict=True), start=1):
            records = [line.record for line in group if line.record is not None]
            chunks[f"{month}_{number:03d}"] = chunk_info(records, len(payload))
        newest = later(state.newest_date, _newest_message_date(line.record for line in lines))
        return self.update_state(replace(state, chunks=chunks, newest_date=newest))

    def _append_target(self, month: str) -> Path:
        parts = month_parts(self.folder, month)
        if not parts:
            return self.folder / part_file_name(month, 1)
        last = parts[-1]
        if last.stat().st_size < self.max_chunk_bytes:
            return last
        parsed = parse_part_name(last.name)
        number = parsed[1] if parsed else len(parts)
        if number >= MAX_PART_NUMBER:
            raise ValueError(f"month {month} already has {MAX_PART_NUMBER} parts")
        return self.folder / part_file_name(month, number + 1)
