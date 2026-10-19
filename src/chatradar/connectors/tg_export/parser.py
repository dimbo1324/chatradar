"""Read a Telegram Desktop JSON export ("Export chat history" or "Export Telegram data")."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any, cast

from chatradar.domain.models import ChatInfo, ChatKind, RawKind, RawRecord, Source

if TYPE_CHECKING:
    from datetime import datetime
    from pathlib import Path

_KINDS: dict[str, ChatKind] = {
    "personal_chat": ChatKind.PRIVATE,
    "bot_chat": ChatKind.PRIVATE,
    "saved_messages": ChatKind.PRIVATE,
    "private_group": ChatKind.GROUP,
    "private_supergroup": ChatKind.SUPERGROUP,
    "public_supergroup": ChatKind.SUPERGROUP,
    "private_channel": ChatKind.CHANNEL,
    "public_channel": ChatKind.CHANNEL,
}


class ExportFormatError(ValueError):
    """The file is not a Telegram Desktop JSON export."""


def parse_export(
    path: Path, *, fetched_at: datetime, username: str | None = None
) -> list[tuple[ChatInfo, list[RawRecord]]]:
    """Every chat of the export with one raw record per message, payload unchanged.

    `username` makes public `t.me` links possible; the export does not carry it, so it is
    accepted only for an export of a single chat.
    """
    data = _load(path)
    chat_objects = _chat_objects(data)
    if username is not None and len(chat_objects) != 1:
        raise ExportFormatError("a username applies only to an export of a single chat")
    result: list[tuple[ChatInfo, list[RawRecord]]] = []
    for chat_object in chat_objects:
        chat = _chat_info(chat_object, username)
        records = [
            RawRecord(
                source=Source.TELEGRAM,
                kind=RawKind.TG_DESKTOP,
                chat_id=chat.chat_id,
                fetched_at=fetched_at,
                payload=message,
            )
            for message in _messages(chat_object)
        ]
        result.append((chat, records))
    return result


def _load(path: Path) -> dict[str, Any]:
    try:
        data: object = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ExportFormatError(f"{path.name} is not valid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise ExportFormatError(f"{path.name}: the top level is not an object")
    return cast("dict[str, Any]", data)


def _chat_objects(data: dict[str, Any]) -> list[dict[str, Any]]:
    if "messages" in data:
        return [data]
    chats: object = data.get("chats")
    if isinstance(chats, dict):
        items: object = cast("dict[str, Any]", chats).get("list")
        if isinstance(items, list):
            return [
                cast("dict[str, Any]", item)
                for item in cast("list[object]", items)
                if isinstance(item, dict)
            ]
    raise ExportFormatError("neither a single-chat export nor a full-account export")


def _chat_info(chat_object: dict[str, Any], username: str | None) -> ChatInfo:
    raw_id: object = chat_object.get("id")
    chat_type = str(chat_object.get("type", ""))
    if not isinstance(raw_id, int | str) or not str(raw_id).lstrip("-").isdigit():
        raise ExportFormatError(f"chat without a numeric id (type {chat_type!r})")
    if chat_type not in _KINDS:
        raise ExportFormatError(f"unknown chat type {chat_type!r}")
    kind = _KINDS[chat_type]
    plain_id = str(raw_id).lstrip("-")
    if kind in (ChatKind.SUPERGROUP, ChatKind.CHANNEL):
        chat_id = f"-100{plain_id}"
    elif kind is ChatKind.GROUP:
        chat_id = f"-{plain_id}"
    else:
        chat_id = plain_id
    title = chat_object.get("name")
    return ChatInfo(
        source=Source.TELEGRAM,
        chat_id=chat_id,
        title=str(title) if title else chat_type.replace("_", " ").capitalize(),
        username=username.lstrip("@") if username else None,
        kind=kind,
    )


def _messages(chat_object: dict[str, Any]) -> list[dict[str, Any]]:
    messages: object = chat_object.get("messages", [])
    if not isinstance(messages, list):
        raise ExportFormatError("`messages` is not a list")
    return [
        cast("dict[str, Any]", message)
        for message in cast("list[object]", messages)
        if isinstance(message, dict)
    ]
