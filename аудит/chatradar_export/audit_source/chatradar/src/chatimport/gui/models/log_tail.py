"""Reads the service log from the end and follows it. Pure file work, no Qt.

`load_tail` reads backwards in chunks until it holds enough whole records; `load_older` keeps
going backwards, into the rotated files. `poll` reads only new bytes by offset and notices a
rotation (the first line of the file changed), a truncation and a file that vanished or does
not exist yet. Only complete lines are consumed: a half-written last line waits for the next
poll. Bytes that are not UTF-8 are replaced, never fatal.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, BinaryIO, Final

from chatimport.gui.models.log_parser import LogParser, LogRecord, parse_text
from chatimport.logging_setup import BACKUP_COUNT, LOG_FILE

if TYPE_CHECKING:
    from pathlib import Path

CHUNK_BYTES: Final = 256 * 1024
MAX_BACK_BYTES: Final = 16 * 1024 * 1024
MAX_POLL_BYTES: Final = 1024 * 1024
SIGNATURE_BYTES: Final = 256
START: Final = re.compile(rb"^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}", re.MULTILINE)


@dataclass(frozen=True, slots=True)
class OlderBatch:
    records: list[LogRecord]
    exhausted: bool


@dataclass(slots=True)
class PollResult:
    records: list[LogRecord] = field(default_factory=lambda: [])
    exists: bool = True
    rotated: bool = False
    more: bool = False


def _signature(handle: BinaryIO) -> bytes | None:
    """The file's first line: stable for the life of a file, different after a rotation."""
    handle.seek(0)
    head = handle.read(SIGNATURE_BYTES)
    newline = head.find(b"\n")
    if newline >= 0:
        return head[: newline + 1]
    return None if len(head) < SIGNATURE_BYTES else head


def _complete_end(path: Path) -> int:
    """Size of the file up to and including its last newline (0 when it has none)."""
    with path.open("rb") as handle:
        size = handle.seek(0, 2)
        window = min(size, CHUNK_BYTES)
        handle.seek(size - window)
        tail = handle.read(window)
    newline = tail.rfind(b"\n")
    return 0 if newline < 0 else size - window + newline + 1


def _decode(data: bytes) -> str:
    return data.decode("utf-8", errors="replace")


def read_back(path: Path, end: int, target: int) -> tuple[list[LogRecord], int]:
    """Records of `path[start:end]` holding at least `target` of them when the file has that
    many; `start` is the byte offset of a record's first line (0 once the file is used up)."""
    with path.open("rb") as handle:
        position, data = end, b""
        while position > 0 and len(data) < MAX_BACK_BYTES:
            step = min(CHUNK_BYTES, position)
            position -= step
            handle.seek(position)
            data = handle.read(step) + data
            if len(START.findall(data)) > target:
                break
    skip = 0
    if position > 0:
        newline = data.find(b"\n")
        skip = len(data) if newline < 0 else newline + 1
    first = START.search(data, skip)
    if first is None:
        return [], 0
    cut = first.start()
    _, records = parse_text(_decode(data[cut:]))
    return records, position + cut if position + cut > 0 else 0


class LogTail:
    def __init__(self, directory: Path, name: str = LOG_FILE, backups: int = BACKUP_COUNT) -> None:
        self._directory = directory
        self._name = name
        self._backups = backups
        self._lock = threading.Lock()
        self._offset = 0
        self._signature: bytes | None = None
        self._parser = LogParser()
        self._older_file = 0
        self._older_end: int | None = None

    @property
    def path(self) -> Path:
        return self._directory / self._name

    def _file(self, index: int) -> Path:
        return self.path if index == 0 else self._directory / f"{self._name}.{index}"

    @property
    def has_older(self) -> bool:
        return self._older_file <= self._backups

    def forget_older(self) -> None:
        with self._lock:
            self._older_file = self._backups + 1

    def load_tail(self, target: int) -> list[LogRecord]:
        with self._lock:
            self._offset, self._signature = 0, None
            self._parser = LogParser()
            self._older_file, self._older_end = 0, None
            path = self.path
            try:
                end = _complete_end(path)
                with path.open("rb") as handle:
                    self._signature = _signature(handle)
            except OSError:
                return []
            self._offset = end
            records, start = read_back(path, end, target)
            self._older_end = start
            if start == 0:
                self._older_file, self._older_end = 1, None
            return records

    def load_older(self, target: int) -> OlderBatch:
        with self._lock:
            batches: list[list[LogRecord]] = []
            total = 0
            while self._older_file <= self._backups and total < target:
                path = self._file(self._older_file)
                try:
                    end = self._older_end if self._older_end is not None else _complete_end(path)
                    records, start = read_back(path, end, target - total)
                except OSError:
                    self._older_file, self._older_end = self._older_file + 1, None
                    continue
                if start == 0:
                    self._older_file, self._older_end = self._older_file + 1, None
                else:
                    self._older_end = start
                batches.append(records)
                total += len(records)
            merged = [record for batch in reversed(batches) for record in batch]
            return OlderBatch(merged, not self.has_older)

    def poll(self) -> PollResult:
        if not self._lock.acquire(blocking=False):
            return PollResult()
        try:
            return self._poll()
        except OSError:
            return PollResult(exists=self.path.exists())
        finally:
            self._lock.release()

    def _poll(self) -> PollResult:
        result = PollResult()
        path = self.path
        if not path.exists():
            result.exists = False
            self._flush_into(result)
            self._offset, self._signature = 0, None
            return result
        with path.open("rb") as handle:
            size = handle.seek(0, 2)
            signature = _signature(handle)
            replaced = (
                self._signature is not None
                and signature is not None
                and signature != self._signature
            )
            if replaced:
                self._drain_rotated(result)
                self._offset, result.rotated = 0, True
                self._older_file += 1
            elif size < self._offset:
                self._flush_into(result)
                self._offset, result.rotated = 0, True
            if signature is not None:
                self._signature = signature
            handle.seek(self._offset)
            data = handle.read(MAX_POLL_BYTES)
        newline = data.rfind(b"\n")
        if newline < 0:
            self._flush_into(result)
            return result
        self._offset += newline + 1
        result.more = len(data) >= MAX_POLL_BYTES
        result.records.extend(self._parser.feed(_decode(data[: newline + 1]).splitlines()))
        self._parser.orphans.clear()
        if not result.more:
            self._flush_into(result)
        return result

    def _flush_into(self, result: PollResult) -> None:
        record = self._parser.flush()
        if record is not None:
            result.records.append(record)

    def _drain_rotated(self, result: PollResult) -> None:
        """Read what the rotation cut off: the old file is now `.1` (or further down)."""
        self._flush_into(result)
        if self._signature is None:
            return
        for index in range(1, self._backups + 1):
            candidate = self._file(index)
            try:
                with candidate.open("rb") as handle:
                    if _signature(handle) != self._signature:
                        continue
                    handle.seek(self._offset)
                    data = handle.read()
            except OSError:
                continue
            newline = data.rfind(b"\n")
            if newline >= 0:
                result.records.extend(self._parser.feed(_decode(data[: newline + 1]).splitlines()))
                self._parser.orphans.clear()
                self._flush_into(result)
            return
