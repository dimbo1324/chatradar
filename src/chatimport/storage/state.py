"""`state.json` (spec §6.3): a cache of the JSONL files, always written atomically."""

from __future__ import annotations

import contextlib
import json
import logging
import os
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Final

from chatimport.records import format_dt, parse_dt
from chatimport.storage.layout import STATE_FILE

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

log = logging.getLogger(__name__)

PHASE_RECOVER: Final = "recover"
PHASE_HEAD_BACKFILL: Final = "head_backfill"
PHASE_CATCH_UP: Final = "catch_up"
PHASE_LIVE: Final = "live"
PHASE_PAUSED: Final = "paused"
PHASE_NO_ACCESS: Final = "no_access"

STATE_VERSION: Final = 1


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
            chunks={
                k: ChunkInfo.from_dict(v)
                for k, v in dict[str, Any](data.get("chunks") or {}).items()
            },
            updated_at=parse_dt(data["updated_at"]),
        )


def new_state(chat_id: int, title: str, username: str | None, now: datetime) -> ChatState:
    return ChatState(
        chat_id=chat_id,
        title=title,
        username=username,
        phase=PHASE_HEAD_BACKFILL,
        updated_at=now,
    )


def load_state(folder: Path) -> ChatState | None:
    path = folder / STATE_FILE
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("state.json is not an object")
        return ChatState.from_dict(data)  # pyright: ignore[reportUnknownArgumentType]
    except FileNotFoundError:
        return None
    except OSError, ValueError, KeyError, TypeError, AttributeError:
        log.warning("state.json is unreadable", extra={"folder": folder.name})
        return None


def atomic_write_bytes(path: Path, data: bytes) -> None:
    """Temp file in the same folder, fsync, then `os.replace` (atomic on one volume)."""
    tmp = path.with_name(f".{path.name}.tmp")
    try:
        with tmp.open("wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        tmp.replace(path)
    except BaseException:
        with contextlib.suppress(OSError):
            tmp.unlink(missing_ok=True)
        raise


def save_state(folder: Path, state: ChatState) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state.to_dict(), ensure_ascii=False, indent=2) + "\n"
    atomic_write_bytes(folder / STATE_FILE, payload.encode("utf-8"))
