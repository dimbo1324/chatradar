"""Reading month parts. Every reader opens, reads and closes; no file stays open."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from chatimport.records import DECODE_ERRORS, MessageRecord, Record, record_from_line
from chatimport.storage.layout import list_parts
from chatimport.storage.state import ChunkInfo

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator
    from pathlib import Path

log = logging.getLogger(__name__)

EMPTY_CHUNK: Final = ChunkInfo(records=0, first_id=0, last_id=0, bytes=0)


@dataclass(frozen=True, slots=True)
class PartLine:
    """One non-empty line of a part: its bytes (newline included) and the record, or None
    when the line does not parse (a cut line, or a kind from a newer version)."""

    data: bytes
    record: Record | None


def decode_line(raw: bytes) -> Record | None:
    try:
        return record_from_line(raw.decode("utf-8"))
    except DECODE_ERRORS:
        return None


def iter_part_records(path: Path) -> Iterator[Record]:
    """Yield the records of one part; lines that do not parse (a cut last line) are skipped."""
    skipped = 0
    with path.open("rb") as handle:
        for raw in handle:
            line = raw.strip()
            if not line:
                continue
            record = decode_line(line)
            if record is None:
                skipped += 1
                continue
            yield record
    if skipped:
        log.warning("skipped unparsable lines", extra={"part": path.name, "lines": skipped})


def iter_records(folder: Path, parts: Iterable[Path] | None = None) -> Iterator[Record]:
    for path in list_parts(folder) if parts is None else parts:
        yield from iter_part_records(path)


def read_part_lines(path: Path) -> list[PartLine]:
    """Every non-empty line with its original bytes, so a rewrite can keep lines it does not
    understand exactly as they were."""
    lines: list[PartLine] = []
    with path.open("rb") as handle:
        for raw in handle:
            line = raw.strip()
            if line:
                lines.append(PartLine(line + b"\n", decode_line(line)))
    return lines


def read_appended(path: Path, start: int) -> tuple[list[Record], int]:
    """Records of the complete lines from byte `start` on, and the offset after the last
    complete line; a line still being written is left for the next call."""
    with path.open("rb") as handle:
        handle.seek(start)
        data = handle.read()
    end = data.rfind(b"\n") + 1
    records = [
        record
        for raw in data[:end].split(b"\n")
        if (line := raw.strip()) and (record := decode_line(line)) is not None
    ]
    return records, start + end


def count_lines(path: Path) -> int:
    with path.open("rb") as handle:
        return sum(1 for raw in handle if raw.strip())


def chunk_info(records: Iterable[Record], size: int, base: ChunkInfo = EMPTY_CHUNK) -> ChunkInfo:
    """Accounting for a part: `base` plus `records`, with the part's size in bytes."""
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
    return chunk_info(iter_part_records(path), path.stat().st_size)


def first_message(paths: Iterable[Path], *, skip_unreadable: bool = False) -> MessageRecord | None:
    """The first message of the first part that has one; `skip_unreadable` passes over parts
    that cannot be opened instead of raising."""
    for path in paths:
        try:
            for record in iter_part_records(path):
                if isinstance(record, MessageRecord):
                    return record
        except OSError:
            if not skip_unreadable:
                raise
    return None
