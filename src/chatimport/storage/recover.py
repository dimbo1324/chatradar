"""Recover on start (spec §10.2): the JSONL files are the truth, `state.json` is a cache.

A part whose size still matches its `state.json` entry is trusted without being decoded, so a
normal start costs one `stat` per part instead of reading the whole archive.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import replace
from typing import TYPE_CHECKING, Final

from chatimport.records import DECODE_ERRORS
from chatimport.storage.layout import list_parts
from chatimport.storage.month_commit import replay_commits
from chatimport.storage.reader import first_message, scan_part
from chatimport.storage.state import (
    PHASE_RECOVER,
    BackfillState,
    ChatState,
    ChunkInfo,
    load_state,
    new_state,
    save_state,
)

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

__all__ = ["FLOOR_REASON_MANUAL_DELETE", "recover_chat", "scan_part"]

log = logging.getLogger(__name__)

FLOOR_REASON_MANUAL_DELETE: Final = "manual_delete"
_TAIL_WINDOW: Final = 64 * 1024


def _is_json_object(raw: bytes) -> bool:
    """A line a newer version may have written (an unknown kind or field) is a JSON object;
    it is kept. Anything else at the end of a part is a cut write."""
    try:
        return isinstance(json.loads(raw.decode("utf-8")), dict)
    except DECODE_ERRORS:
        return False


def _read_tail(path: Path, size: int) -> tuple[int, bytes]:
    """Start offset and bytes of a window that holds the whole last line."""
    window = _TAIL_WINDOW
    with path.open("rb") as handle:
        while True:
            start = max(0, size - window)
            handle.seek(start)
            data = handle.read()
            body = data[:-1] if data.endswith(b"\n") else data
            if start == 0 or b"\n" in body:
                return start, data
            window *= 2


def _repair_tail(path: Path) -> bool:
    """Cut a broken last line; a valid last line missing its newline gets one. Only the end
    of the part is read, and the part is never rewritten as a whole."""
    size = path.stat().st_size
    if size == 0:
        return False
    start, data = _read_tail(path, size)
    body = data[:-1] if data.endswith(b"\n") else data
    cut = body.rfind(b"\n") + 1
    last = body[cut:]
    keep_last = not last.strip() or _is_json_object(last.strip())
    if keep_last and data.endswith(b"\n"):
        return False
    with path.open("r+b") as handle:
        if keep_last:
            handle.seek(0, os.SEEK_END)
            handle.write(b"\n")
        else:
            handle.truncate(start + cut)
        handle.flush()
        os.fsync(handle.fileno())
    return True


def _scan(
    parts: list[Path], known: dict[str, ChunkInfo], repaired: set[str]
) -> dict[str, ChunkInfo]:
    scanned: dict[str, ChunkInfo] = {}
    for path in parts:
        cached = known.get(path.stem)
        if cached is not None and path.stem not in repaired and path.stat().st_size == cached.bytes:
            scanned[path.stem] = cached
        else:
            scanned[path.stem] = scan_part(path)
    return scanned


def recover_chat(
    folder: Path,
    *,
    now: datetime,
    fallback_chat_id: int | None = None,
    fallback_title: str | None = None,
) -> ChatState:
    """Realign `state.json` with the parts and save it. Raises `StateUnreadable` (and
    changes nothing) when `state.json` exists but cannot be read right now."""
    state = load_state(folder)
    for stale in folder.glob(".*.tmp"):
        with contextlib.suppress(OSError):
            stale.unlink()
    replayed = replay_commits(folder)

    parts = list_parts(folder)
    repaired: set[str] = set()
    for path in parts:
        if _repair_tail(path):
            repaired.add(path.stem)
            log.warning("repaired the last line of a part", extra={"part": path.name})

    known = {} if state is None else state.chunks
    trusted = {k: v for k, v in known.items() if k.rsplit("_", 1)[0] not in replayed}
    scanned = _scan(parts, trusted, repaired)
    file_ids = [info.first_id for info in scanned.values() if info.first_id]
    min_file_id = min(file_ids, default=0)
    max_file_id = max((info.last_id for info in scanned.values()), default=0)

    if state is None:
        first = first_message(parts)
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

    repaired_state = replace(state, last_id=last_id, chunks=scanned, updated_at=now)
    save_state(folder, repaired_state)
    return repaired_state
