from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
from typing import Any

import pytest

from chatradar.connectors.tg_export.mapper import map_record
from chatradar.connectors.tg_export.parser import parse_export
from chatradar.domain.models import MediaType, Message, RawKind, RawRecord, Source
from chatradar.domain.text import content_hash
from tests.unit.connectors.fakes import FIXTURES, NOW, chat

CHAT = chat()
PRIVATE = chat("-1001700000009", username=None)
BASE: dict[str, Any] = {
    "id": 10,
    "type": "message",
    "date": "2026-09-01T09:00:00",
    "date_unixtime": "1788264000",
    "from": "Member 1",
    "from_id": "user1000001",
    "text": "hello",
}


def _map(payload: dict[str, Any], target: Any = CHAT) -> Message | None:
    record = RawRecord(
        source=Source.TELEGRAM,
        kind=RawKind.TG_DESKTOP,
        chat_id=target.chat_id,
        fetched_at=NOW,
        payload=payload,
    )
    return map_record(record, target)


def _mapped(**changes: Any) -> Message:
    message = _map({**BASE, **changes})
    assert message is not None
    return message


def test_plain_message() -> None:
    message = _mapped(text="  Hola\r\n\r\n\r\n\r\nmundo  ")

    assert message.key == (Source.TELEGRAM, "-1001700000001", "10")
    assert message.author_id == "1000001"
    assert message.date == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert message.text == "Hola\n\nmundo"
    assert message.text_raw == "  Hola\r\n\r\n\r\n\r\nmundo  "
    assert message.link == "https://t.me/expats_demo/10"
    assert message.content_hash == content_hash(
        text_raw=message.text_raw, media_type="none", reply_to=None
    )
    assert not message.is_forward
    assert not message.is_service
    assert message.edited_at is None


def test_private_supergroup_link() -> None:
    message = _map(BASE, PRIVATE)

    assert message is not None
    assert message.link == "https://t.me/c/1700000009/10"


@pytest.mark.parametrize(
    ("changes", "field", "expected"),
    [
        ({"from_id": "user42"}, "author_id", "42"),
        ({"from_id": "channel42"}, "author_id", "-10042"),
        ({"from_id": "chat42"}, "author_id", "-42"),
        ({"from_id": "weird"}, "author_id", None),
        ({"from_id": None}, "author_id", None),
        ({"reply_to_message_id": 7}, "reply_to", "7"),
        ({"forwarded_from": "Some Channel"}, "is_forward", True),
        ({"forwarded_from": None}, "is_forward", True),
        (
            {"text": ["see ", {"type": "link", "text": "https://x.example"}, "!"]},
            "text",
            "see https://x.example!",
        ),
        ({"text": [{"type": "bold", "text": "bold"}, " and plain"]}, "text_raw", "bold and plain"),
        ({"text": 12}, "text", ""),
        ({"photo": "photos/1.jpg"}, "media_type", MediaType.PHOTO),
        ({"media_type": "sticker", "file": "x"}, "media_type", MediaType.STICKER),
        ({"media_type": "voice_message", "file": "x"}, "media_type", MediaType.VOICE),
        ({"media_type": "video_message", "file": "x"}, "media_type", MediaType.VIDEO_NOTE),
        ({"media_type": "video_file", "file": "x"}, "media_type", MediaType.VIDEO),
        ({"media_type": "animation", "file": "x"}, "media_type", MediaType.VIDEO),
        ({"media_type": "audio_file", "file": "x"}, "media_type", MediaType.DOCUMENT),
        ({"media_type": "something_new"}, "media_type", MediaType.OTHER),
        ({"file": "files/a.pdf"}, "media_type", MediaType.DOCUMENT),
        ({"poll": {"question": "?"}}, "media_type", MediaType.OTHER),
        ({"location_information": {}}, "media_type", MediaType.OTHER),
        (
            {"edited": "2026-09-01T10:00:00", "edited_unixtime": "1788267600"},
            "edited_at",
            datetime(2026, 9, 1, 13, 0, tzinfo=UTC),
        ),
        ({"date_unixtime": None}, "date", datetime(2026, 9, 1, 9, 0, tzinfo=UTC)),
    ],
)
def test_fields(changes: dict[str, Any], field: str, expected: object) -> None:
    assert getattr(_mapped(**changes), field) == expected


def test_service_message_takes_actor_and_action() -> None:
    message = _mapped(
        type="service", actor="Member 5", actor_id="user5", action="join_group_by_link", text=""
    )

    assert message.is_service
    assert message.author_id == "5"
    assert message.text == "join_group_by_link"


@pytest.mark.parametrize(
    "payload",
    [
        {**BASE, "type": "unsupported"},
        {**BASE, "id": "10"},
        {key: value for key, value in BASE.items() if key != "id"},
        {**BASE, "date_unixtime": None, "date": None},
        {**BASE, "date_unixtime": None, "date": "yesterday"},
    ],
)
def test_skipped(payload: dict[str, Any]) -> None:
    assert _map(payload) is None


def test_media_and_reply_change_the_hash() -> None:
    plain = _mapped()

    assert _mapped(photo="p.jpg").content_hash != plain.content_hash
    assert _mapped(reply_to_message_id=3).content_hash != plain.content_hash
    assert _mapped(edited_unixtime="1788267600").content_hash == plain.content_hash


def test_whole_fixture_maps() -> None:
    [(target, records)] = parse_export(
        FIXTURES / "supergroup_result.json", fetched_at=NOW, username="expats_demo"
    )
    messages = [m for r in records if (m := map_record(r, target)) is not None]

    assert len(messages) == len(records)
    assert sum(m.is_service for m in messages) == 2
    assert sum(m.is_forward for m in messages) == 1
    assert sum(m.edited_at is not None for m in messages) == 1
    assert sum(m.reply_to is not None for m in messages) >= 25
    media = {m.media_type for m in messages}
    assert {MediaType.STICKER, MediaType.VOICE, MediaType.PHOTO, MediaType.DOCUMENT} <= media
    by_hash = Counter(m.content_hash for m in messages if m.media_type is MediaType.NONE)
    assert sorted(by_hash.values())[-1] == 2, "the fixture holds one exact duplicate"
    assert all(m.date.tzinfo is UTC for m in messages)
    assert [m.date for m in messages] == sorted(m.date for m in messages)
