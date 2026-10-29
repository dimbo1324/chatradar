"""Trimming (spec §8.5, §8.6): whole oldest parts, one cut boundary part, media, the trim log."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Final

from chatimport.records import MessageRecord, Record, format_dt, record_event_date, record_to_line
from chatimport.storage.layout import parse_part_name
from chatimport.storage.state import (
    ChatState,
    ChunkInfo,
    atomic_write_bytes,
    load_state,
    save_state,
)
from chatimport.storage.writer import iter_part_records, scan_part

if TYPE_CHECKING:
    from pathlib import Path

    from chatimport.ports import Clock
    from chatimport.runtime import ChatController, ChatRegistry

__all__ = ["TRIM_LOG", "TrimReport", "TrimmedPart", "Trimmer"]

log = logging.getLogger(__name__)

TRIM_LOG: Final = "_trim_log.jsonl"
ALLOWED_PERCENTS: Final = (25, 50, 75)
MEDIA_DIR: Final = "media"
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
class _Candidate:
    controller: ChatController
    first_date: datetime


def _month_start(month: str) -> datetime:
    return datetime.strptime(month, "%Y-%m").replace(tzinfo=UTC)


def _message_ids(records: list[Record]) -> set[int]:
    return {r.msg_id for r in records if isinstance(r, MessageRecord)}


def _media_id(name: str) -> int | None:
    digits = name.split(".", 1)[0].split("_", 1)[0]
    return int(digits) if digits.isdecimal() else None


def _delete_media(folder: Path, month: str, msg_ids: set[int]) -> None:
    month_dir = folder / MEDIA_DIR / month
    if not msg_ids or not month_dir.is_dir():
        return
    for entry in month_dir.iterdir():
        if entry.is_file() and _media_id(entry.name) in msg_ids:
            try:
                entry.unlink()
            except OSError:
                log.warning("cannot delete a media file", extra={"folder": folder.name})
    if not any(month_dir.iterdir()):
        try:
            month_dir.rmdir()
        except OSError:
            log.warning("cannot remove an empty media folder", extra={"folder": folder.name})


def _month_of(key: str) -> str:
    parsed = parse_part_name(f"{key}.jsonl")
    return parsed[0] if parsed is not None else key[:7]


def _existing_chunks(folder: Path, state: ChatState) -> dict[str, ChunkInfo]:
    return {k: v for k, v in sorted(state.chunks.items()) if (folder / f"{k}.jsonl").is_file()}


def _first_remaining_id(folder: Path, chunks: dict[str, ChunkInfo]) -> int | None:
    for key in sorted(chunks):
        for record in iter_part_records(folder / f"{key}.jsonl"):
            if isinstance(record, MessageRecord):
                return record.msg_id
    return None


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

    async def trim_percent(self, pct: int, chat_id: int | None = None) -> TrimReport:
        if pct not in ALLOWED_PERCENTS:
            raise ValueError(f"pct must be one of {ALLOWED_PERCENTS}, got {pct}")
        if chat_id is None:
            controllers = self.registry.all()
        else:
            found = self.registry.get(chat_id)
            controllers = [found] if found is not None else []
        report = TrimReport()
        for controller in controllers:
            async with controller.lock:
                self._trim_chat(controller, pct, report)
        return report

    def _trim_chat(self, controller: ChatController, pct: int, report: TrimReport) -> None:
        folder = controller.folder
        if not folder.is_dir():
            return
        state = load_state(folder)
        if state is None:
            return
        chunks = _existing_chunks(folder, state)
        total = sum(c.records for c in chunks.values())
        target = total * pct // 100
        if target <= 0:
            return

        deleted: list[TrimmedPart] = []
        removed = 0
        freed = 0
        boundary_key: str | None = None
        cut_ids: set[int] = set()
        for key, info in chunks.items():
            if removed + info.records <= target:
                path = folder / f"{key}.jsonl"
                size = path.stat().st_size
                ids = _message_ids(list(iter_part_records(path)))
                path.unlink()
                _delete_media(folder, _month_of(key), ids)
                deleted.append(
                    TrimmedPart(
                        controller.chat_id, key, info.records, info.first_id, info.last_id, size
                    )
                )
                removed += info.records
                freed += size
                continue
            skip = target - removed
            if skip > 0:
                boundary_key = key
                freed_cut, cut_ids = self._cut_boundary(folder / f"{key}.jsonl", skip)
                removed += skip
                freed += freed_cut
            break

        deleted_keys = {d.part for d in deleted}
        remaining = {k: v for k, v in chunks.items() if k not in deleted_keys}
        if boundary_key is not None:
            remaining[boundary_key] = scan_part(folder / f"{boundary_key}.jsonl")
            _delete_media(folder, _month_of(boundary_key), cut_ids)
        first_id = _first_remaining_id(folder, remaining)
        floor = first_id if first_id is not None else state.last_id
        reason = f"manual_trim_{pct}"
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

        report.deleted_parts.extend(deleted)
        report.trimmed_records += removed
        report.freed_bytes += freed
        report.per_chat[controller.chat_id] = removed
        self._log_entry(
            kind="manual",
            chat_id=controller.chat_id,
            pct=pct,
            parts=[d.part for d in deleted],
            records=removed,
            freed=freed,
            reason=reason,
        )
        log.info(
            "manual trim done",
            extra={"chat_id": controller.chat_id, "pct": pct, "records": removed, "bytes": freed},
        )

    @staticmethod
    def _cut_boundary(path: Path, skip: int) -> tuple[int, set[int]]:
        records = list(iter_part_records(path))
        old_size = path.stat().st_size
        payload = "".join(record_to_line(r) + "\n" for r in records[skip:]).encode("utf-8")
        atomic_write_bytes(path, payload)
        return max(0, old_size - len(payload)), _message_ids(records[:skip])

    async def delete_oldest_part(self, protect_recent_days: int) -> TrimmedPart | None:
        cutoff = self._clock.now() - timedelta(days=protect_recent_days)
        candidates: list[_Candidate] = []
        for controller in self.registry.all():
            async with controller.lock:
                first_date = self._oldest_eligible(controller, cutoff)
            if first_date is not None:
                candidates.append(_Candidate(controller, first_date))
        for candidate in sorted(candidates, key=lambda c: c.first_date):
            async with candidate.controller.lock:
                if self._oldest_eligible(candidate.controller, cutoff) is None:
                    continue
                part = self._delete_oldest(candidate.controller)
            if part is not None:
                return part
        return None

    def _oldest_eligible(self, controller: ChatController, cutoff: datetime) -> datetime | None:
        """First message date of the chat's oldest part, if the whole part is older than cutoff."""
        folder = controller.folder
        if not folder.is_dir():
            return None
        state = load_state(folder)
        if state is None:
            return None
        chunks = _existing_chunks(folder, state)
        if not chunks:
            return None
        key = next(iter(chunks))
        month_start = _month_start(_month_of(key))
        first_date: datetime | None = None
        last_date = month_start
        for record in iter_part_records(folder / f"{key}.jsonl"):
            last_date = max(last_date, record_event_date(record))
            if first_date is None and isinstance(record, MessageRecord):
                first_date = record.date
        if last_date >= cutoff:
            return None
        return first_date or month_start

    def _delete_oldest(self, controller: ChatController) -> TrimmedPart | None:
        folder = controller.folder
        state = load_state(folder)
        if state is None:
            return None
        chunks = _existing_chunks(folder, state)
        if not chunks:
            return None
        key = next(iter(chunks))
        info = chunks[key]
        path = folder / f"{key}.jsonl"
        size = path.stat().st_size
        ids = _message_ids(list(iter_part_records(path)))
        path.unlink()
        _delete_media(folder, _month_of(key), ids)
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
            chat_id=controller.chat_id,
            pct=None,
            parts=[key],
            records=info.records,
            freed=size,
            reason=FLOOR_REASON_DISK,
        )
        log.info(
            "disk trim deleted a part",
            extra={"chat_id": controller.chat_id, "part": key, "bytes": size},
        )
        return TrimmedPart(controller.chat_id, key, info.records, info.first_id, info.last_id, size)

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
        line = (json.dumps(entry, ensure_ascii=False) + "\n").encode("utf-8")
        self.root.mkdir(parents=True, exist_ok=True)
        with (self.root / TRIM_LOG).open("ab") as handle:
            handle.write(line)
            handle.flush()
            os.fsync(handle.fileno())
