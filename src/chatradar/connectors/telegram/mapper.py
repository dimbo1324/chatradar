"""Map one Telethon `Message.to_dict()` payload (already JSON) to `Message`. Pure, no I/O."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, cast

from chatradar.domain.models import MediaType, Message
from chatradar.domain.text import content_hash, ensure_utc, message_link, normalize_text

if TYPE_CHECKING:
    from chatradar.domain.models import ChatInfo, RawRecord

_PLAIN_MEDIA: dict[str, MediaType] = {
    "MessageMediaEmpty": MediaType.NONE,
    "MessageMediaWebPage": MediaType.NONE,  # a link preview; the URL is in the text
    "MessageMediaPhoto": MediaType.PHOTO,
}


def map_record(record: RawRecord, chat: ChatInfo) -> Message | None:
    """`Mapper` for `RawKind.TELETHON`; None for `MessageEmpty` and malformed payloads."""
    payload = record.payload
    constructor = payload.get("_")
    msg_id = payload.get("id")
    if constructor not in ("Message", "MessageService") or not isinstance(msg_id, int):
        return None
    date = _moment(payload.get("date"))
    if date is None:
        return None
    is_service = constructor == "MessageService"
    if is_service:
        text_raw = str(_as_dict(payload.get("action")).get("_", ""))
        media_type = MediaType.NONE
    else:
        text_raw = str(payload.get("message") or "")
        media_type = _media_type(payload.get("media"))
    reply_to, topic_id = _reply(payload.get("reply_to"))
    message_id = str(msg_id)
    return Message(
        source=record.source,
        chat_id=record.chat_id,
        msg_id=message_id,
        author_id=_author(payload),
        date=date,
        text=normalize_text(text_raw),
        text_raw=text_raw,
        reply_to=reply_to,
        topic_id=topic_id,
        media_type=media_type,
        is_forward=payload.get("fwd_from") is not None,
        is_service=is_service,
        edited_at=_moment(payload.get("edit_date")),
        link=message_link(record.chat_id, message_id, chat.username),
        content_hash=content_hash(text_raw=text_raw, media_type=media_type, reply_to=reply_to),
    )


def _as_dict(value: object) -> dict[str, Any]:
    return cast("dict[str, Any]", value) if isinstance(value, dict) else {}


def _moment(value: object) -> datetime | None:
    if isinstance(value, datetime):
        return ensure_utc(value)
    if isinstance(value, str) and value:
        try:
            return ensure_utc(datetime.fromisoformat(value))
        except ValueError:
            return None
    return None


def _int(value: object) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def _peer(value: object) -> str | None:
    """A `Peer*` object in Telethon's marked form."""
    peer = _as_dict(value)
    if (user_id := _int(peer.get("user_id"))) is not None:
        return str(user_id)
    if (channel_id := _int(peer.get("channel_id"))) is not None:
        return f"-100{channel_id}"
    if (chat_id := _int(peer.get("chat_id"))) is not None:
        return f"-{chat_id}"
    return None


def _author(payload: dict[str, Any]) -> str | None:
    """`from_id`; in a private chat an incoming message has none, the peer is the author."""
    author = _peer(payload.get("from_id"))
    if author is None and not payload.get("out"):
        peer = _as_dict(payload.get("peer_id"))
        if peer.get("_") == "PeerUser":
            author = _peer(peer)
    return author


def _reply(value: object) -> tuple[str | None, str | None]:
    """(reply_to, topic_id). In a forum a bare reply to the topic root only names the topic."""
    header = _as_dict(value)
    if header.get("_") != "MessageReplyHeader":
        return None, None
    msg_id = _int(header.get("reply_to_msg_id"))
    top_id = _int(header.get("reply_to_top_id"))
    if header.get("forum_topic"):
        if top_id is not None:
            return _str(msg_id), str(top_id)
        return None, _str(msg_id)
    return _str(msg_id), None


def _str(value: int | None) -> str | None:
    return None if value is None else str(value)


def _media_type(value: object) -> MediaType:
    media = _as_dict(value)
    constructor = media.get("_")
    if constructor is None:
        return MediaType.NONE
    if constructor in _PLAIN_MEDIA:
        return _PLAIN_MEDIA[constructor]
    if constructor != "MessageMediaDocument":
        return MediaType.OTHER
    if media.get("voice"):
        return MediaType.VOICE
    if media.get("round"):
        return MediaType.VIDEO_NOTE
    attributes = cast("list[object]", _as_dict(media.get("document")).get("attributes") or [])
    names = {_as_dict(attribute).get("_"): _as_dict(attribute) for attribute in attributes}
    if "DocumentAttributeSticker" in names:
        return MediaType.STICKER
    if names.get("DocumentAttributeAudio", {}).get("voice"):
        return MediaType.VOICE
    if "DocumentAttributeVideo" in names:
        if names["DocumentAttributeVideo"].get("round_message"):
            return MediaType.VIDEO_NOTE
        return MediaType.VIDEO
    if "DocumentAttributeAnimated" in names:
        return MediaType.VIDEO
    return MediaType.DOCUMENT
