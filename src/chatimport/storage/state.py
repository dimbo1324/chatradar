"""`state.json` (spec §6.3): a cache of the JSONL files, always written atomically."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Any, Final

from chatimport.ports import ChatImportError
from chatimport.records import DECODE_ERRORS, escape_line_breaks, format_dt, parse_dt
from chatimport.storage.fileio import atomic_write_bytes
from chatimport.storage.layout import STATE_FILE, parse_part_name

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

__all__ = [
    "PHASE_CATCH_UP",
    "PHASE_HEAD_BACKFILL",
    "PHASE_LIVE",
    "PHASE_NO_ACCESS",
    "PHASE_PAUSED",
    "PHASE_RECOVER",
    "STATE_VERSION",
    "BackfillState",
    "ChatState",
    "ChunkInfo",
    "Phase",
    "StateUnreadable",
    "atomic_write_bytes",
    "load_state",
    "new_state",
    "save_state",
]

log = logging.getLogger(__name__)


class Phase(StrEnum):
    """A chat worker's phase as stored in `state.json`; the values are the on-disk strings."""

    RECOVER = "recover"
    HEAD_BACKFILL = "head_backfill"
    CATCH_UP = "catch_up"
    LIVE = "live"
    PAUSED = "paused"
    NO_ACCESS = "no_access"


PHASE_RECOVER: Final = Phase.RECOVER
PHASE_HEAD_BACKFILL: Final = Phase.HEAD_BACKFILL
PHASE_CATCH_UP: Final = Phase.CATCH_UP
PHASE_LIVE: Final = Phase.LIVE
PHASE_PAUSED: Final = Phase.PAUSED
PHASE_NO_ACCESS: Final = Phase.NO_ACCESS

STATE_VERSION: Final = 1


class StateUnreadable(ChatImportError):
    """`state.json` exists but cannot be read right now (a sharing violation, a permission or
    I/O error). Unlike a missing or broken file it must not be rebuilt over: retry later."""

    def __init__(self, folder: Path, error: OSError) -> None:
        super().__init__(f"state.json of {folder.name} cannot be read now: {error}")
        self.folder = folder


def _opt_dt(value: str | None) -> datetime | None:
    return parse_dt(value) if value else None


def _fmt_opt(value: datetime | None) -> str | None:
    return format_dt(value) if value else None


@dataclass(frozen=True, slots=True)
class ChunkInfo:
    records: int
    first_id: int
    last_id: int
    bytes: int

    def to_dict(self) -> dict[str, int]:
        return {
            "records": self.records,
            "first_id": self.first_id,
            "last_id": self.last_id,
            "bytes": self.bytes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChunkInfo:
        return cls(
            records=int(data["records"]),
            first_id=int(data["first_id"]),
            last_id=int(data["last_id"]),
            bytes=int(data["bytes"]),
        )


@dataclass(frozen=True, slots=True)
class BackfillState:
    done: bool = False
    head_id: int = 0
    oldest_done_id: int = 0
    started_at: datetime | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "done": self.done,
            "head_id": self.head_id,
            "oldest_done_id": self.oldest_done_id,
            "started_at": _fmt_opt(self.started_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> BackfillState:
        return cls(
            done=bool(data.get("done", False)),
            head_id=int(data.get("head_id", 0)),
            oldest_done_id=int(data.get("oldest_done_id", 0)),
            started_at=_opt_dt(data.get("started_at")),
        )


@dataclass(frozen=True, slots=True)
class ChatState:
    chat_id: int
    title: str
    username: str | None
    phase: str
    updated_at: datetime
    last_id: int = 0
    floor_id: int = 0
    floor_reason: str | None = None
    last_recheck_at: datetime | None = None
    backfill: BackfillState = field(default_factory=BackfillState)
    chunks: dict[str, ChunkInfo] = field(default_factory=dict[str, ChunkInfo])
    v: int = STATE_VERSION

    @property
    def total_records(self) -> int:
        return sum(info.records for info in self.chunks.values())

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": self.v,
            "chat_id": self.chat_id,
            "title": self.title,
            "username": self.username,
            "phase": self.phase,
            "last_id": self.last_id,
            "floor_id": self.floor_id,
            "floor_reason": self.floor_reason,
            "last_recheck_at": _fmt_opt(self.last_recheck_at),
            "backfill": self.backfill.to_dict(),
            "chunks": {key: info.to_dict() for key, info in sorted(self.chunks.items())},
            "updated_at": format_dt(self.updated_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ChatState:
        return cls(
            v=int(data.get("v", STATE_VERSION)),
            chat_id=int(data["chat_id"]),
            title=str(data.get("title") or ""),
            username=data.get("username"),
            phase=str(data["phase"]),
            last_id=int(data.get("last_id", 0)),
            floor_id=int(data.get("floor_id", 0)),
            floor_reason=data.get("floor_reason"),
            last_recheck_at=_opt_dt(data.get("last_recheck_at")),
            backfill=BackfillState.from_dict(data.get("backfill") or {}),
            chunks=_valid_chunks(int(data["chat_id"]), dict[str, Any](data.get("chunks") or {})),
            updated_at=parse_dt(data["updated_at"]),
        )


def _valid_chunks(chat_id: int, raw: dict[str, Any]) -> dict[str, ChunkInfo]:
    """Only keys that name a part file in this folder; anything else (`../x`, an absolute
    path) would let a trim reach outside the chat folder, so it counts as missing."""
    parsed = {key: ChunkInfo.from_dict(value) for key, value in raw.items()}
    chunks = {key: info for key, info in parsed.items() if parse_part_name(f"{key}.jsonl")}
    dropped = len(parsed) - len(chunks)
    if dropped:
        log.warning(
            "state.json lists invalid part names", extra={"chat_id": chat_id, "keys": dropped}
        )
    return chunks


def new_state(chat_id: int, title: str, username: str | None, now: datetime) -> ChatState:
    return ChatState(
        chat_id=chat_id,
        title=title,
        username=username,
        phase=PHASE_HEAD_BACKFILL,
        updated_at=now,
    )


def load_state(folder: Path) -> ChatState | None:
    """None when `state.json` is missing or broken (rebuild it from the parts); raises
    `StateUnreadable` when the file exists but cannot be read at the moment."""
    path = folder / STATE_FILE
    try:
        raw = path.read_bytes()
    except FileNotFoundError, NotADirectoryError:
        return None
    except OSError as error:
        if path.is_dir():
            log.warning("state.json is a folder", extra={"folder": folder.name})
            return None
        raise StateUnreadable(folder, error) from error
    try:
        data = json.loads(raw.decode("utf-8-sig"))
        if not isinstance(data, dict):
            raise ValueError("state.json is not an object")
        return ChatState.from_dict(data)  # pyright: ignore[reportUnknownArgumentType]
    except (*DECODE_ERRORS, AttributeError):
        log.warning("state.json is broken", extra={"folder": folder.name})
        return None


def save_state(folder: Path, state: ChatState) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    text = escape_line_breaks(json.dumps(state.to_dict(), ensure_ascii=False, indent=2))
    atomic_write_bytes(folder / STATE_FILE, (text + "\n").encode("utf-8", "backslashreplace"))
