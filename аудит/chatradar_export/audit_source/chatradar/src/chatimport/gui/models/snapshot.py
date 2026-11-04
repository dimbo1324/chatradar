"""The status snapshot as typed values: tolerant of old or partial snapshots, Qt-free.

The service writes plain JSON (`StatusWriter.build`); the pages never index that dict directly.
A missing or malformed field becomes its neutral value, so a snapshot from an older service or
a half-started one still renders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Final, cast

from chatimport.runtime import BackfillState

if TYPE_CHECKING:
    from collections.abc import Mapping

PHASE_LIVE: Final = "live"
PHASE_PAUSED: Final = "paused"
PHASE_NO_ACCESS: Final = "no_access"
RESOLVE_PREFIX: Final = "resolve:"


def parse_dt(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        moment = datetime.fromisoformat(value)
    except ValueError:
        return None
    return moment.astimezone(UTC) if moment.tzinfo else moment.replace(tzinfo=UTC)


def _mapping(value: object) -> Mapping[str, Any]:
    return cast("Mapping[str, Any]", value) if isinstance(value, dict) else {}


def _int(value: object, default: int = 0) -> int:
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _number(value: object) -> float | None:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return None
    return float(value)


def _text(value: object) -> str | None:
    return value if isinstance(value, str) and value else None


def _items(value: object) -> list[object]:
    return cast("list[object]", value) if isinstance(value, list) else []


def _int_list(value: object) -> tuple[int, ...]:
    return tuple(item for item in _items(value) if isinstance(item, int))


def _state(value: object) -> BackfillState:
    try:
        return BackfillState(value)
    except ValueError:
        return BackfillState.IDLE


@dataclass(frozen=True, slots=True)
class BackfillView:
    state: BackfillState = BackfillState.IDLE
    progress: float | None = None
    month: str | None = None
    retry_at: datetime | None = None
    detail: str | None = None


@dataclass(frozen=True, slots=True)
class ChatRow:
    chat_id: int
    title: str
    phase: str
    last_id: int = 0
    records: int = 0
    paused: bool = False
    backfill_done: bool = False
    oldest_date: datetime | None = None
    newest_date: datetime | None = None
    last_contact_at: datetime | None = None
    error: str | None = None
    backfill: BackfillView = field(default_factory=BackfillView)

    @property
    def has_access(self) -> bool:
        return self.phase != PHASE_NO_ACCESS and self.backfill.state is not BackfillState.NO_ACCESS

    @property
    def is_paused(self) -> bool:
        return self.paused or self.phase == PHASE_PAUSED

    @property
    def has_problem(self) -> bool:
        return (
            not self.has_access
            or self.error is not None
            or self.backfill.state is BackfillState.RETRYING
        )


def parse_chat(raw: Mapping[str, Any]) -> ChatRow | None:
    chat_id = raw.get("chat_id")
    if not isinstance(chat_id, int) or isinstance(chat_id, bool):
        return None
    info = _mapping(raw.get("backfill"))
    return ChatRow(
        chat_id=chat_id,
        title=_text(raw.get("title")) or str(chat_id),
        phase=_text(raw.get("phase")) or "",
        last_id=_int(raw.get("last_id")),
        records=_int(raw.get("records")),
        paused=raw.get("paused") is True,
        backfill_done=raw.get("backfill_done") is True,
        oldest_date=parse_dt(raw.get("oldest_date")),
        newest_date=parse_dt(raw.get("newest_date")),
        last_contact_at=parse_dt(raw.get("last_contact_at")),
        error=_text(raw.get("error")),
        backfill=BackfillView(
            state=_state(info.get("state")),
            progress=_number(info.get("progress")),
            month=_text(info.get("month")),
            retry_at=parse_dt(info.get("retry_at")),
            detail=_text(info.get("detail")),
        ),
    )


@dataclass(frozen=True, slots=True)
class ServiceError:
    source: str
    message: str

    @property
    def is_resolve(self) -> bool:
        return self.source.startswith(RESOLVE_PREFIX)


@dataclass(frozen=True, slots=True)
class GlobalBackfill:
    limit: int = 1
    active: tuple[int, ...] = ()
    waiting: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class SnapshotView:
    service: str = "stopped"
    updated_at: datetime | None = None
    disk_path: str = ""
    free_gb: float | None = None
    low_watermark_gb: float | None = None
    total_bytes: int = 0
    backfill: GlobalBackfill = field(default_factory=GlobalBackfill)
    chats: tuple[ChatRow, ...] = ()
    errors: tuple[ServiceError, ...] = ()

    def chat(self, chat_id: int) -> ChatRow | None:
        return next((row for row in self.chats if row.chat_id == chat_id), None)


def parse_snapshot(raw: Mapping[str, Any] | None) -> SnapshotView:
    if not raw:
        return SnapshotView()
    disk = _mapping(raw.get("disk"))
    block = _mapping(raw.get("backfill"))
    chats = tuple(
        row
        for item in _items(raw.get("chats"))
        if isinstance(item, dict)
        and (row := parse_chat(cast("Mapping[str, Any]", item))) is not None
    )
    errors = tuple(
        ServiceError(_text(entry.get("source")) or "", _text(entry.get("message")) or "")
        for item in _items(raw.get("errors"))
        if isinstance(item, dict)
        for entry in (cast("Mapping[str, Any]", item),)
    )
    return SnapshotView(
        service=_text(raw.get("service")) or "stopped",
        updated_at=parse_dt(raw.get("updated_at")),
        disk_path=_text(disk.get("path")) or "",
        free_gb=_number(disk.get("free_gb")),
        low_watermark_gb=_number(disk.get("low_watermark_gb")),
        total_bytes=_int(raw.get("total_bytes")),
        backfill=GlobalBackfill(
            limit=max(_int(block.get("limit"), 1), 1),
            active=_int_list(block.get("active")),
            waiting=_int_list(block.get("waiting")),
        ),
        chats=chats,
        errors=errors,
    )
