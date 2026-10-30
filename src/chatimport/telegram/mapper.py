"""Pure mapping of a Telethon message to a `MessageRecord` (spec §6.1).

Messages are duck-typed (`Any`): no client call is made, so every field read here must
already be loaded on the object.
"""

from __future__ import annotations

import base64
from datetime import UTC, datetime
from typing import Any, Final

from chatimport.records import MediaInfo, MessageRecord, format_dt

_CHANNEL_ID_BASE: Final = 10**12

_SERVICE_BY_ACTION: Final[dict[str, str]] = {
    "MessageActionChatAddUser": "join",
    "MessageActionChatJoinedByLink": "join",
    "MessageActionChatJoinedByRequest": "join",
    "MessageActionChatDeleteUser": "leave",
    "MessageActionPinMessage": "pin",
    "MessageActionChatEditTitle": "title_change",
    "MessageActionChatEditPhoto": "photo_change",
    "MessageActionChatDeletePhoto": "delete_photo",
    "MessageActionChatCreate": "created",
    "MessageActionChannelCreate": "created",
    "MessageActionChatMigrateTo": "migrate",
    "MessageActionChannelMigrateFrom": "migrate",
    "MessageActionTopicCreate": "topic_create",
    "MessageActionTopicEdit": "topic_edit",
    "MessageActionPhoneCall": "call",
    "MessageActionGroupCall": "call",
    "MessageActionGroupCallScheduled": "call",
}

_MEDIA_PROPERTIES: Final[tuple[str, ...]] = (
    "photo",
    "sticker",
    "voice",
    "video_note",
    "video",
    "audio",
    "document",
)


def message_link(chat_id: int, username: str | None, msg_id: int) -> str | None:
    if username:
        return f"https://t.me/{username}/{msg_id}"
    if chat_id <= -_CHANNEL_ID_BASE:
        return f"https://t.me/c/{-chat_id - _CHANNEL_ID_BASE}/{msg_id}"
    return None


def service_kind(action: Any) -> str | None:
    if action is None:
        return None
    return _SERVICE_BY_ACTION.get(type(action).__name__, "other")


def sender_display_name(sender: Any) -> str | None:
    if sender is None:
        return None
    title = getattr(sender, "title", None)
    if title:
        return str(title)
    parts = [getattr(sender, "first_name", None), getattr(sender, "last_name", None)]
    name = " ".join(str(part) for part in parts if part)
    return name or None


def map_media(message: Any) -> MediaInfo | None:
    if (
        type(getattr(message, "media", None)).__name__ == "MessageMediaWebPage"
        or getattr(message, "action", None) is not None
    ):
        return None
    media_type = next((name for name in _MEDIA_PROPERTIES if getattr(message, name, None)), None)
    if media_type is None:
        return None
    file = getattr(message, "file", None)
    return MediaInfo(
        type=media_type,
        mime=getattr(file, "mime_type", None),
        size=_as_int(getattr(file, "size", None)),
        duration=_as_int(getattr(file, "duration", None)),
        width=_as_int(getattr(file, "width", None)),
        height=_as_int(getattr(file, "height", None)),
        file_name=getattr(file, "name", None),
    )


def map_message(
    message: Any,
    *,
    chat_id: int,
    chat_username: str | None,
    fetched_at: datetime,
    include_sender_names: bool,
    include_raw: bool,
) -> MessageRecord:
    msg_id = int(message.id)
    sender = getattr(message, "sender", None) if include_sender_names else None
    reply_to_msg_id, topic_id = _reply_and_topic(getattr(message, "reply_to", None))
    return MessageRecord(
        chat_id=chat_id,
        msg_id=msg_id,
        date=_as_utc(message.date),
        fetched_at=fetched_at,
        text=getattr(message, "message", None) or "",
        edit_date=_as_utc(message.edit_date) if getattr(message, "edit_date", None) else None,
        sender_id=_as_int(getattr(message, "sender_id", None)),
        sender_name=sender_display_name(sender),
        sender_username=getattr(sender, "username", None) or None,
        reply_to_msg_id=reply_to_msg_id,
        topic_id=topic_id,
        grouped_id=_as_int(getattr(message, "grouped_id", None)),
        forwarded=getattr(message, "fwd_from", None) is not None,
        service=service_kind(getattr(message, "action", None)),
        link=message_link(chat_id, chat_username, msg_id),
        media=map_media(message),
        raw=_jsonable(message.to_dict()) if include_raw else None,
    )


def _reply_and_topic(reply_to: Any) -> tuple[int | None, int | None]:
    if reply_to is None:
        return None, None
    replied = _as_int(getattr(reply_to, "reply_to_msg_id", None))
    if not getattr(reply_to, "forum_topic", False):
        return replied, None
    top = _as_int(getattr(reply_to, "reply_to_top_id", None))
    topic = top if top is not None else replied
    return (None if replied == topic else replied), topic


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_dt(_as_utc(value))
    if isinstance(value, bytes):
        return base64.b64encode(value).decode("ascii")
    if isinstance(value, dict):
        mapping: dict[Any, Any] = value  # pyright: ignore[reportUnknownVariableType]
        return {str(key): _jsonable(item) for key, item in mapping.items()}
    if isinstance(value, list | tuple):
        items: list[Any] = list(value)  # pyright: ignore[reportUnknownArgumentType, reportUnknownVariableType]
        return [_jsonable(item) for item in items]
    if value is None or isinstance(value, bool | int | float | str):
        return value
    return str(value)
