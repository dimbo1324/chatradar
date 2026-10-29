"""Writing and reading month parts. No file stays open between calls (Windows deletes them)."""

from __future__ import annotations

import logging
import os
from dataclasses import replace
from itertools import groupby
from typing import TYPE_CHECKING

from chatimport.records import (
    MessageRecord,
    Record,
    record_event_date,
    record_from_line,
    record_sort_id,
    record_to_line,
    utc_now,
)
from chatimport.storage.layout import (
    MAX_PART_NUMBER,
    list_parts,
    month_key,
    parse_part_name,
    part_file_name,
    part_key,
)
from chatimport.storage.state import ChatState, ChunkInfo, atomic_write_bytes, save_state

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Iterator, Sequence
    from datetime import datetime
    from pathlib import Path

log = logging.getLogger(__name__)

_EMPTY_CHUNK = ChunkInfo(records=0, first_id=0, last_id=0, bytes=0)


def _decode(raw: bytes) -> Record | None:
    try:
        return record_from_line(raw.decode("utf-8"))
    except ValueError, KeyError, TypeError:
        return None


def iter_part_records(path: Path) -> Iterator[Record]:
    """Yield the records of one part; lines that do not parse (a cut last line) are skipped."""
    skipped = 0
    with path.open("rb") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            record = _decode(line)
            if record is None:
                skipped += 1
                continue
            yield record
    if skipped:
        log.warning("skipped unparsable lines", extra={"part": path.name, "lines": skipped})


def iter_records(folder: Path, parts: Iterable[Path] | None = None) -> Iterator[Record]:
    for path in list_parts(folder) if parts is None else parts:
        yield from iter_part_records(path)


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for raw in handle if raw.strip())


def _chunk_from(records: Iterable[Record], size: int, base: ChunkInfo = _EMPTY_CHUNK) -> ChunkInfo:
    count = base.records
    ids = [base.first_id, base.last_id] if base.first_id else []
    for record in records:
        count += 1
        if isinstance(record, MessageRecord):
            ids.append(record.msg_id)
    return ChunkInfo(
        records=count,
        first_id=min(ids, default=0),
        last_id=max(ids, default=0),
        bytes=size,
    )


def scan_part(path: Path) -> ChunkInfo:
    return _chunk_from(iter_part_records(path), path.stat().st_size)


def _encode(records: Iterable[Record]) -> bytes:
    return "".join(record_to_line(record) + "\n" for record in records).encode("utf-8")


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
            base = chunks.get(key)
            if base is None:
                base = scan_part(path) if path.exists() else _EMPTY_CHUNK
            with path.open("ab") as handle:
                handle.write(_encode(batch))
                handle.flush()
                os.fsync(handle.fileno())
            chunks[key] = _chunk_from(batch, path.stat().st_size, base)
            last_id = max(
                [last_id, *(r.msg_id for r in batch if isinstance(r, MessageRecord))],
            )
        return self.update_state(replace(state, chunks=chunks, last_id=last_id))

    def write_month(
        self, state: ChatState, month: str, records: Sequence[MessageRecord]
    ) -> ChatState:
        """Backfill: replace all parts of `month`; every part appears atomically."""
        by_id = {record.msg_id: record for record in reversed(records)}
        if not by_id:
            return state
        return self._write_records(state, month, [by_id[msg_id] for msg_id in sorted(by_id)])

    def merge_month(
        self, state: ChatState, month: str, messages: Sequence[MessageRecord]
    ) -> ChatState:
        """Add messages to a month that may already hold parts, keeping every existing record
        (messages, edits, deletes, media marks); known `msg_id`s are not replaced."""
        existing: list[Record] = []
        for path in self._month_parts(month):
            existing.extend(iter_part_records(path))
        if not existing:
            return self.write_month(state, month, messages)
        known = {r.msg_id for r in existing if isinstance(r, MessageRecord)}
        fresh = {m.msg_id: m for m in reversed(messages) if m.msg_id not in known}
        if not fresh:
            return state
        combined = sorted(
            [*existing, *fresh.values()],
            key=lambda r: (record_sort_id(r), 0 if isinstance(r, MessageRecord) else 1),
        )
        return self._write_records(state, month, combined)

    def _write_records(self, state: ChatState, month: str, records: Sequence[Record]) -> ChatState:
        self.folder.mkdir(parents=True, exist_ok=True)

        groups: list[list[Record]] = []
        current: list[Record] = []
        size = 0
        for record in records:
            current.append(record)
            size += len(_encode([record]))
            if size >= self.max_chunk_bytes:
                groups.append(current)
                current, size = [], 0
        if current:
            groups.append(current)
        if len(groups) > MAX_PART_NUMBER:
            raise ValueError(f"month {month} needs more than {MAX_PART_NUMBER} parts")

        chunks = dict(state.chunks)
        for number, group in enumerate(groups, start=1):
            payload = _encode(group)
            atomic_write_bytes(self.folder / part_file_name(month, number), payload)
            chunks[part_key(month, number)] = _chunk_from(group, len(payload))

        for path in self._month_parts(month):
            parsed = parse_part_name(path.name)
            if parsed is not None and parsed[1] > len(groups):
                path.unlink()
                chunks.pop(path.stem, None)
        return self.update_state(replace(state, chunks=chunks))

    def _month_parts(self, month: str) -> list[Path]:
        return [
            p
            for p in list_parts(self.folder)
            if (parsed := parse_part_name(p.name)) is not None and parsed[0] == month
        ]

    def _append_target(self, month: str) -> Path:
        parts = self._month_parts(month)
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
