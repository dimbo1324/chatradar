"""Map one message object of a Telegram Desktop export to `Message`. Pure, no I/O."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, cast

from chatradar.domain.models import MediaType, Message
from chatradar.domain.text import content_hash, ensure_utc, message_link, normalize_text

if TYPE_CHECKING:
    from chatradar.domain.models import ChatInfo, RawRecord

_MEDIA_TYPES: dict[str, MediaType] = {
    "sticker": MediaType.STICKER,
    "voice_message": MediaType.VOICE,
    "video_message": MediaType.VIDEO_NOTE,
    "video_file": MediaType.VIDEO,
    "animation": MediaType.VIDEO,
    "audio_file": MediaType.DOCUMENT,
}
_OTHER_MEDIA_KEYS = ("poll", "location_information", "contact_information", "place_name")


def map_record(record: RawRecord, chat: ChatInfo) -> Message | None:
    """`Mapper` for `RawKind.TG_DESKTOP`; None for objects that are not messages."""
    payload = record.payload
    kind = payload.get("type")
    msg_id = payload.get("id")
    if kind not in ("message", "service") or not isinstance(msg_id, int):
        return None
    date = _moment(payload, "date")
    if date is None:
        return None
    is_service = kind == "service"
    text_raw = _text(payload.get("text"))
    if is_service and not text_raw:
        text_raw = str(payload.get("action", ""))
    media_type = _media_type(payload)
    reply_to = _optional_id(payload.get("reply_to_message_id"))
    message_id = str(msg_id)
    return Message(
        source=record.source,
        chat_id=record.chat_id,
        msg_id=message_id,
        author_id=_peer_id(payload.get("actor_id" if is_service else "from_id")),
        date=date,
        text=normalize_text(text_raw),
        text_raw=text_raw,
        reply_to=reply_to,
        media_type=media_type,
        is_forward="forwarded_from" in payload,
        is_service=is_service,
        edited_at=_moment(payload, "edited"),
        link=message_link(record.chat_id, message_id, chat.username),
        content_hash=content_hash(text_raw=text_raw, media_type=media_type, reply_to=reply_to),
    )


def _moment(payload: dict[str, Any], field: str) -> datetime | None:
    """`<field>_unixtime` is UTC; `<field>` is the exporter's local time, a last resort."""
    unixtime = payload.get(f"{field}_unixtime")
    if isinstance(unixtime, int | str) and str(unixtime).isdigit():
        return datetime.fromtimestamp(int(unixtime), UTC)
    local = payload.get(field)
    if isinstance(local, str) and local:
        try:
            return ensure_utc(datetime.fromisoformat(local))
        except ValueError:
            return None
    return None


def _text(value: object) -> str:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        parts: list[str] = []
        for part in cast("list[object]", value):
            if isinstance(part, str):
                parts.append(part)
            elif isinstance(part, dict):
                parts.append(str(cast("dict[str, Any]", part).get("text", "")))
        return "".join(parts)
    return ""


def _peer_id(value: object) -> str | None:
    """`user123` → `123`, `channel123` → `-100123`, `chat123` → `-123`."""
    if not isinstance(value, str):
        return None
    for prefix, marked in (("user", ""), ("channel", "-100"), ("chat", "-")):
        rest = value.removeprefix(prefix)
        if rest != value and rest.isdigit():
            return f"{marked}{rest}"
    return None


def _optional_id(value: object) -> str | None:
    return str(value) if isinstance(value, int) else None


def _media_type(payload: dict[str, Any]) -> MediaType:
    if "photo" in payload:
        return MediaType.PHOTO
    media = payload.get("media_type")
    if isinstance(media, str):
        return _MEDIA_TYPES.get(media, MediaType.OTHER)
    if "file" in payload:
        return MediaType.DOCUMENT
    if any(key in payload for key in _OTHER_MEDIA_KEYS):
        return MediaType.OTHER
    return MediaType.NONE
