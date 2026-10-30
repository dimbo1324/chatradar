"""Record formats written to JSONL (spec §6) and their (de)serialization.

Dates are timezone-aware UTC in memory and `...Z` ISO strings on disk. A `MessageRecord`
without sender names (`include_sender_names = false`) carries `None` in both name fields.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

SCHEMA_VERSION: Final = 1

KIND_MESSAGE: Final = "message"
KIND_EDIT: Final = "edit"
KIND_DELETE: Final = "delete"
KIND_MEDIA_SAVED: Final = "media_saved"

DETECTED_EVENT: Final = "event"
DETECTED_RECHECK: Final = "recheck"


DECODE_ERRORS: Final = (ValueError, KeyError, TypeError, RecursionError)
"""Everything a hostile or damaged JSONL line can raise while being decoded into a record."""

_LONE_SURROGATES: Final = dict.fromkeys(range(0xD800, 0xE000), 0xFFFD)
_LINE_BREAKS: Final = {0x2028: "\\u2028", 0x2029: "\\u2029", 0x85: "\\u0085"}


def format_dt(value: datetime) -> str:
    """UTC ISO 8601 with a `Z` suffix and whole seconds."""
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value).astimezone(UTC)


def utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class MediaInfo:
    type: str
    mime: str | None = None
    size: int | None = None
    duration: int | None = None
    width: int | None = None
    height: int | None = None
    file_name: str | None = None
    file: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "mime": self.mime,
            "size": self.size,
            "duration": self.duration,
            "width": self.width,
            "height": self.height,
            "file_name": self.file_name,
            "file": self.file,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaInfo:
        return cls(
            type=str(data["type"]),
            mime=data.get("mime"),
            size=data.get("size"),
            duration=data.get("duration"),
            width=data.get("width"),
            height=data.get("height"),
            file_name=data.get("file_name"),
            file=data.get("file"),
        )


@dataclass(frozen=True, slots=True)
class MessageRecord:
    chat_id: int
    msg_id: int
    date: datetime
    fetched_at: datetime
    text: str = ""
    edit_date: datetime | None = None
    sender_id: int | None = None
    sender_name: str | None = None
    sender_username: str | None = None
    reply_to_msg_id: int | None = None
    topic_id: int | None = None
    grouped_id: int | None = None
    forwarded: bool = False
    service: str | None = None
    link: str | None = None
    media: MediaInfo | None = None
    raw: dict[str, Any] | None = None

    kind: str = field(default=KIND_MESSAGE, init=False)

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "v": SCHEMA_VERSION,
            "kind": KIND_MESSAGE,
            "source": "telegram",
            "chat_id": self.chat_id,
            "msg_id": self.msg_id,
            "date": format_dt(self.date),
            "edit_date": format_dt(self.edit_date) if self.edit_date else None,
            "fetched_at": format_dt(self.fetched_at),
            "sender_id": self.sender_id,
            "sender_name": self.sender_name,
            "sender_username": self.sender_username,
            "text": self.text,
            "reply_to_msg_id": self.reply_to_msg_id,
            "topic_id": self.topic_id,
            "grouped_id": self.grouped_id,
            "forwarded": self.forwarded,
            "service": self.service,
            "link": self.link,
            "media": self.media.to_dict() if self.media else None,
        }
        if self.raw is not None:
            data["raw"] = self.raw
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MessageRecord:
        edit_date = data.get("edit_date")
        media = data.get("media")
        return cls(
            chat_id=int(data["chat_id"]),
            msg_id=int(data["msg_id"]),
            date=parse_dt(data["date"]),
            fetched_at=parse_dt(data["fetched_at"]),
            text=data.get("text") or "",
            edit_date=parse_dt(edit_date) if edit_date else None,
            sender_id=data.get("sender_id"),
            sender_name=data.get("sender_name"),
            sender_username=data.get("sender_username"),
            reply_to_msg_id=data.get("reply_to_msg_id"),
            topic_id=data.get("topic_id"),
            grouped_id=data.get("grouped_id"),
            forwarded=bool(data.get("forwarded", False)),
            service=data.get("service"),
            link=data.get("link"),
            media=MediaInfo.from_dict(media) if media else None,
            raw=data.get("raw"),
        )


@dataclass(frozen=True, slots=True)
class EditRecord:
    chat_id: int
    msg_id: int
    edit_date: datetime
    fetched_at: datetime
    text: str = ""
    media: MediaInfo | None = None
    detected_by: str = DETECTED_EVENT

    kind: str = field(default=KIND_EDIT, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": SCHEMA_VERSION,
            "kind": KIND_EDIT,
            "chat_id": self.chat_id,
            "msg_id": self.msg_id,
            "edit_date": format_dt(self.edit_date),
            "text": self.text,
            "media": self.media.to_dict() if self.media else None,
            "detected_by": self.detected_by,
            "fetched_at": format_dt(self.fetched_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> EditRecord:
        media = data.get("media")
        return cls(
            chat_id=int(data["chat_id"]),
            msg_id=int(data["msg_id"]),
            edit_date=parse_dt(data["edit_date"]),
            fetched_at=parse_dt(data["fetched_at"]),
            text=data.get("text") or "",
            media=MediaInfo.from_dict(media) if media else None,
            detected_by=data.get("detected_by", DETECTED_EVENT),
        )


@dataclass(frozen=True, slots=True)
class DeleteRecord:
    chat_id: int
    msg_ids: tuple[int, ...]
    fetched_at: datetime
    detected_by: str = DETECTED_EVENT

    kind: str = field(default=KIND_DELETE, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": SCHEMA_VERSION,
            "kind": KIND_DELETE,
            "chat_id": self.chat_id,
            "msg_ids": list(self.msg_ids),
            "detected_by": self.detected_by,
            "fetched_at": format_dt(self.fetched_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> DeleteRecord:
        return cls(
            chat_id=int(data["chat_id"]),
            msg_ids=tuple(int(i) for i in data["msg_ids"]),
            fetched_at=parse_dt(data["fetched_at"]),
            detected_by=data.get("detected_by", DETECTED_EVENT),
        )


@dataclass(frozen=True, slots=True)
class MediaSavedRecord:
    chat_id: int
    msg_id: int
    file: str
    fetched_at: datetime

    kind: str = field(default=KIND_MEDIA_SAVED, init=False)

    def to_dict(self) -> dict[str, Any]:
        return {
            "v": SCHEMA_VERSION,
            "kind": KIND_MEDIA_SAVED,
            "chat_id": self.chat_id,
            "msg_id": self.msg_id,
            "file": self.file,
            "fetched_at": format_dt(self.fetched_at),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> MediaSavedRecord:
        return cls(
            chat_id=int(data["chat_id"]),
            msg_id=int(data["msg_id"]),
            file=str(data["file"]),
            fetched_at=parse_dt(data["fetched_at"]),
        )


type Record = MessageRecord | EditRecord | DeleteRecord | MediaSavedRecord


def escape_line_breaks(text: str) -> str:
    """JSON text with U+2028, U+2029 and U+0085 written as escapes (same value when parsed)."""
    if "\u2028" in text or "\u2029" in text or "\x85" in text:
        return text.translate(_LINE_BREAKS)
    return text


def json_line(data: object) -> str:
    """Compact JSON on one physical line for every reader: non-ASCII text stays readable,
    U+2028, U+2029 and U+0085 (line breaks to `str.splitlines`) and lone surrogates do not."""
    return json_line_bytes(data)[:-1].decode("utf-8")


def json_line_bytes(data: object) -> bytes:
    """`json_line` plus the newline, UTF-8 encoded; the text is encoded only once."""
    line = escape_line_breaks(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n")
    try:
        return line.encode("utf-8")
    except UnicodeEncodeError:
        return line.translate(_LONE_SURROGATES).encode("utf-8")


def record_to_line(record: Record) -> str:
    """One JSONL line without the trailing newline."""
    return json_line(record.to_dict())


def record_to_bytes(record: Record) -> bytes:
    """One JSONL line with its newline, ready to write."""
    return json_line_bytes(record.to_dict())


def record_from_dict(data: dict[str, Any]) -> Record:
    if not isinstance(data, dict):  # pyright: ignore[reportUnnecessaryIsInstance]
        raise ValueError(f"a record must be a JSON object, not {type(data).__name__}")
    kind = data.get("kind")
    if kind == KIND_MESSAGE:
        return MessageRecord.from_dict(data)
    if kind == KIND_EDIT:
        return EditRecord.from_dict(data)
    if kind == KIND_DELETE:
        return DeleteRecord.from_dict(data)
    if kind == KIND_MEDIA_SAVED:
        return MediaSavedRecord.from_dict(data)
    raise ValueError(f"unknown record kind: {kind!r}")


def record_from_line(line: str) -> Record:
    return record_from_dict(json.loads(line))


def record_chat_id(record: Record) -> int:
    return record.chat_id


def record_event_date(record: Record) -> datetime:
    """The moment that decides which month file a record belongs to."""
    match record:
        case MessageRecord():
            return record.date
        case EditRecord():
            return record.edit_date
        case _:
            return record.fetched_at


def record_sort_id(record: Record) -> int:
    """`msg_id` for ordering inside a part; a delete sorts by its highest id."""
    match record:
        case DeleteRecord():
            return max(record.msg_ids, default=0)
        case _:
            return record.msg_id
