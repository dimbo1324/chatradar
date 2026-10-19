from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest

from chatradar.connectors.telegram.mapper import map_record
from chatradar.domain.models import MediaType, Message, RawKind, RawRecord, Source
from chatradar.domain.text import content_hash
from tests.unit.connectors.fakes import NOW, chat

CHAT = chat()
BASE: dict[str, Any] = {
    "_": "Message",
    "id": 501,
    "peer_id": {"_": "PeerChannel", "channel_id": 1700000001},
    "date": "2026-10-01T10:00:00+00:00",
    "message": "Hola, ¿qué tal?",
    "out": False,
    "from_id": {"_": "PeerUser", "user_id": 42},
    "fwd_from": None,
    "reply_to": None,
    "media": None,
    "edit_date": None,
}


def _map(payload: dict[str, Any]) -> Message | None:
    record = RawRecord(
        source=Source.TELEGRAM,
        kind=RawKind.TELETHON,
        chat_id=CHAT.chat_id,
        fetched_at=NOW,
        payload=payload,
    )
    return map_record(record, CHAT)


def _mapped(**changes: Any) -> Message:
    message = _map({**BASE, **changes})
    assert message is not None
    return message


def _document(*attributes: dict[str, Any], **flags: Any) -> dict[str, Any]:
    return {
        "_": "MessageMediaDocument",
        "document": {"_": "Document", "mime_type": "x/y", "attributes": list(attributes)},
        **flags,
    }


def _reply(msg_id: int | None, top_id: int | None = None, *, forum: bool = False) -> dict[str, Any]:
    return {
        "_": "MessageReplyHeader",
        "reply_to_msg_id": msg_id,
        "reply_to_top_id": top_id,
        "forum_topic": forum,
    }


def test_plain_message() -> None:
    message = _mapped()

    assert message.key == (Source.TELEGRAM, "-1001700000001", "501")
    assert message.author_id == "42"
    assert message.date == datetime(2026, 10, 1, 10, 0, tzinfo=UTC)
    assert message.text == "Hola, ¿qué tal?"
    assert message.link == "https://t.me/expats_demo/501"
    assert message.content_hash == content_hash(
        text_raw="Hola, ¿qué tal?", media_type="none", reply_to=None
    )
    assert (message.reply_to, message.topic_id, message.media_type) == (None, None, MediaType.NONE)


@pytest.mark.parametrize(
    ("changes", "field", "expected"),
    [
        (
            {"date": datetime(2026, 10, 1, 10, 0, tzinfo=UTC)},
            "date",
            datetime(2026, 10, 1, 10, 0, tzinfo=UTC),
        ),
        ({"date": "2026-10-01T13:00:00+03:00"}, "date", datetime(2026, 10, 1, 10, 0, tzinfo=UTC)),
        ({"message": None}, "text", ""),
        ({"message": "  a  \n\n\n\nb "}, "text", "a\n\nb"),
        ({"from_id": {"_": "PeerChannel", "channel_id": 9}}, "author_id", "-1009"),
        ({"from_id": {"_": "PeerChat", "chat_id": 9}}, "author_id", "-9"),
        ({"from_id": None}, "author_id", None),
        (
            {"from_id": None, "peer_id": {"_": "PeerUser", "user_id": 7}},
            "author_id",
            "7",
        ),
        (
            {"from_id": None, "out": True, "peer_id": {"_": "PeerUser", "user_id": 7}},
            "author_id",
            None,
        ),
        (
            {"fwd_from": {"_": "MessageFwdHeader", "date": "2026-01-01T00:00:00+00:00"}},
            "is_forward",
            True,
        ),
        ({"reply_to": _reply(480)}, "reply_to", "480"),
        ({"reply_to": _reply(480)}, "topic_id", None),
        ({"reply_to": _reply(480, 300, forum=True)}, "reply_to", "480"),
        ({"reply_to": _reply(480, 300, forum=True)}, "topic_id", "300"),
        ({"reply_to": _reply(300, forum=True)}, "reply_to", None),
        ({"reply_to": _reply(300, forum=True)}, "topic_id", "300"),
        ({"reply_to": {"_": "MessageReplyStoryHeader", "story_id": 1}}, "reply_to", None),
        (
            {"edit_date": "2026-10-02T08:30:00+00:00"},
            "edited_at",
            datetime(2026, 10, 2, 8, 30, tzinfo=UTC),
        ),
        ({"edit_date": "garbage"}, "edited_at", None),
        ({"media": {"_": "MessageMediaPhoto"}}, "media_type", MediaType.PHOTO),
        ({"media": {"_": "MessageMediaWebPage"}}, "media_type", MediaType.NONE),
        ({"media": {"_": "MessageMediaEmpty"}}, "media_type", MediaType.NONE),
        ({"media": {"_": "MessageMediaGeo"}}, "media_type", MediaType.OTHER),
        ({"media": {"_": "MessageMediaPoll"}}, "media_type", MediaType.OTHER),
        (
            {"media": _document({"_": "DocumentAttributeSticker", "alt": "x"})},
            "media_type",
            MediaType.STICKER,
        ),
        (
            {"media": _document({"_": "DocumentAttributeAudio", "voice": True})},
            "media_type",
            MediaType.VOICE,
        ),
        (
            {"media": _document({"_": "DocumentAttributeAudio", "voice": False})},
            "media_type",
            MediaType.DOCUMENT,
        ),
        ({"media": _document(voice=True)}, "media_type", MediaType.VOICE),
        ({"media": _document(round=True)}, "media_type", MediaType.VIDEO_NOTE),
        (
            {"media": _document({"_": "DocumentAttributeVideo", "round_message": True})},
            "media_type",
            MediaType.VIDEO_NOTE,
        ),
        (
            {"media": _document({"_": "DocumentAttributeVideo", "round_message": False})},
            "media_type",
            MediaType.VIDEO,
        ),
        ({"media": _document({"_": "DocumentAttributeAnimated"})}, "media_type", MediaType.VIDEO),
        (
            {"media": _document({"_": "DocumentAttributeFilename", "file_name": "a.pdf"})},
            "media_type",
            MediaType.DOCUMENT,
        ),
        (
            {"media": {"_": "MessageMediaDocument", "document": None}},
            "media_type",
            MediaType.DOCUMENT,
        ),
    ],
)
def test_fields(changes: dict[str, Any], field: str, expected: object) -> None:
    assert getattr(_mapped(**changes), field) == expected


def test_service_message() -> None:
    message = _mapped(
        **{"_": "MessageService", "action": {"_": "MessageActionChatJoinedByLink", "inviter_id": 1}}
    )

    assert message.is_service
    assert message.text == "MessageActionChatJoinedByLink"
    assert message.media_type is MediaType.NONE


@pytest.mark.parametrize(
    "payload",
    [
        {"_": "MessageEmpty", "id": 5},
        {**BASE, "id": None},
        {**BASE, "id": "501"},
        {**BASE, "date": None},
        {**BASE, "date": "not a date"},
    ],
)
def test_skipped(payload: dict[str, Any]) -> None:
    assert _map(payload) is None


def test_edit_changes_the_hash_only_through_content() -> None:
    original = _mapped()

    assert _mapped(edit_date="2026-10-02T00:00:00+00:00").content_hash == original.content_hash
    assert _mapped(message="Hola!").content_hash != original.content_hash
