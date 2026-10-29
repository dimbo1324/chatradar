"""Recover on start (spec §10.2): the JSONL files are the truth, `state.json` is a cache."""

from __future__ import annotations

import contextlib
import logging
import os
from dataclasses import replace
from typing import TYPE_CHECKING

from chatimport.records import MessageRecord, record_from_line
from chatimport.storage.layout import list_parts
from chatimport.storage.state import (
    PHASE_RECOVER,
    BackfillState,
    ChatState,
    ChunkInfo,
    load_state,
    new_state,
    save_state,
)
from chatimport.storage.writer import iter_part_records, scan_part

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

__all__ = ["recover_chat", "scan_part"]

log = logging.getLogger(__name__)

FLOOR_REASON_MANUAL_DELETE = "manual_delete"


def _parses(raw: bytes) -> bool:
    try:
        record_from_line(raw.decode("utf-8"))
    except ValueError, KeyError, TypeError:
        return False
    return True


def _repair_tail(path: Path) -> bool:
    """Cut a broken last line; a valid last line missing its newline gets one."""
    data = path.read_bytes()
    if not data:
        return False
    body = data[:-1] if data.endswith(b"\n") else data
    cut = body.rfind(b"\n") + 1
    last = body[cut:]
    if not last.strip() or _parses(last):
        if data.endswith(b"\n"):
            return False
        keep: bytes = data + b"\n"
    else:
        keep = data[:cut]
    with path.open("r+b") as handle:
        handle.seek(0)
        handle.write(keep)
        handle.truncate(len(keep))
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _first_message(parts: list[Path]) -> MessageRecord | None:
    for path in parts:
        for record in iter_part_records(path):
            if isinstance(record, MessageRecord):
                return record
    return None


def recover_chat(
    folder: Path,
    *,
    now: datetime,
    fallback_chat_id: int | None = None,
    fallback_title: str | None = None,
) -> ChatState:
    for stale in folder.glob(".*.tmp"):
        with contextlib.suppress(OSError):
            stale.unlink()

    parts = list_parts(folder)
    for path in parts:
        if _repair_tail(path):
            log.warning("repaired the last line of a part", extra={"part": path.name})

    scanned: dict[str, ChunkInfo] = {path.stem: scan_part(path) for path in parts}
    file_ids = [info.first_id for info in scanned.values() if info.first_id]
    min_file_id = min(file_ids, default=0)
    max_file_id = max((info.last_id for info in scanned.values()), default=0)

    state = load_state(folder)
    if state is None:
        first = _first_message(parts)
        chat_id = first.chat_id if first is not None else fallback_chat_id
        if chat_id is None:
            raise ValueError(f"cannot recover {folder.name}: no chat_id in records or fallback")
        title = fallback_title if fallback_title is not None else folder.name
        state = replace(
            new_state(chat_id, title, None, now),
            phase=PHASE_RECOVER,
            floor_id=min_file_id,
            backfill=BackfillState(done=False),
        )
        log.warning("state.json rebuilt from parts", extra={"folder": folder.name})
    else:
        missing = set(state.chunks) - set(scanned)
        if missing:
            log.warning("parts missing on disk", extra={"parts": sorted(missing)})
            state = replace(
                state,
                floor_id=max(state.floor_id, min_file_id),
                floor_reason=FLOOR_REASON_MANUAL_DELETE,
            )

    last_id = max(state.last_id, max_file_id)
    if state.chunks and not scanned:
        state = replace(
            state,
            floor_id=max(state.floor_id, last_id),
            floor_reason=FLOOR_REASON_MANUAL_DELETE,
        )

    repaired = replace(state, last_id=last_id, chunks=scanned, updated_at=now)
    save_state(folder, repaired)
    return repaired
