from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any

import pytest
from telethon.tl import types as tl
from telethon.tl.custom import Message as TlMessage

from chatimport.records import MessageRecord
from chatimport.telegram import mapper
from tests.fakes import NOW

FETCHED = NOW
PRIVATE_CHAT = -1001234567890


def fake_message(**kw: Any) -> SimpleNamespace:
    base: dict[str, Any] = {
        "id": 10,
        "date": datetime(2026, 10, 1, 8, 30, 15, tzinfo=UTC),
        "message": "hello",
        "to_dict": dict,
    }
    base.update(kw)
    return SimpleNamespace(**base)


def do_map(
    message: Any,
    *,
    chat_id: int = PRIVATE_CHAT,
    username: str | None = None,
    names: bool = True,
    raw: bool = False,
) -> MessageRecord:
    return mapper.map_message(
        message,
        chat_id=chat_id,
        chat_username=username,
        fetched_at=FETCHED,
        include_sender_names=names,
        include_raw=raw,
    )


def action(name: str) -> Any:
    return type(name, (), {})()


@pytest.mark.parametrize(
    ("chat_id", "username", "expected"),
    [
        (PRIVATE_CHAT, None, "https://t.me/c/1234567890/7"),
        (PRIVATE_CHAT, "", "https://t.me/c/1234567890/7"),
        (PRIVATE_CHAT, "pub_chat", "https://t.me/pub_chat/7"),
        (-123456, None, None),
        (-123456, "pub_chat", "https://t.me/pub_chat/7"),
        (123456, None, None),
        (-(10**12 + 1234567), None, "https://t.me/c/1234567/7"),
        (-(10**12 + 1), None, "https://t.me/c/1/7"),
        (-(10**12 + 2_000_000_000), None, "https://t.me/c/2000000000/7"),
    ],
)
def test_message_link(chat_id: int, username: str | None, expected: str | None) -> None:
    assert mapper.message_link(chat_id, username, 7) == expected


@pytest.mark.parametrize(
    ("action_name", "expected"),
    [
        ("MessageActionChatAddUser", "join"),
        ("MessageActionChatJoinedByLink", "join"),
        ("MessageActionChatJoinedByRequest", "join"),
        ("MessageActionChatDeleteUser", "leave"),
        ("MessageActionPinMessage", "pin"),
        ("MessageActionChatEditTitle", "title_change"),
        ("MessageActionChatEditPhoto", "photo_change"),
        ("MessageActionChatDeletePhoto", "delete_photo"),
        ("MessageActionChatCreate", "created"),
        ("MessageActionChannelCreate", "created"),
        ("MessageActionChatMigrateTo", "migrate"),
        ("MessageActionChannelMigrateFrom", "migrate"),
        ("MessageActionTopicCreate", "topic_create"),
        ("MessageActionTopicEdit", "topic_edit"),
        ("MessageActionPhoneCall", "call"),
        ("MessageActionGroupCall", "call"),
        ("MessageActionGroupCallScheduled", "call"),
        ("MessageActionBrandNewFeature", "other"),
        ("MessageActionEmpty", "other"),
        ("", "other"),
    ],
)
def test_service_action_kinds(action_name: str, expected: str) -> None:
    record = do_map(fake_message(action=action(action_name), message=None))
    assert record.service == expected
    assert record.text == ""


def test_regular_message_has_no_service_kind() -> None:
    assert do_map(fake_message(action=None)).service is None
    assert do_map(fake_message()).service is None


@pytest.mark.parametrize(
    ("present", "expected"),
    [
        (["photo"], "photo"),
        (["sticker"], "sticker"),
        (["voice"], "voice"),
        (["video_note"], "video_note"),
        (["video"], "video"),
        (["audio"], "audio"),
        (["document"], "document"),
        (["photo", "document"], "photo"),
        (["sticker", "document", "video"], "sticker"),
        (["voice", "audio", "document"], "voice"),
        (["video_note", "video", "document"], "video_note"),
        (["video", "gif", "document"], "video"),
        (["audio", "document"], "audio"),
        (["gif", "document"], "document"),
        ([], None),
    ],
)
def test_media_type_precedence(present: list[str], expected: str | None) -> None:
    props = {name: object() for name in present}
    media = mapper.map_media(fake_message(**props))
    assert (media.type if media else None) == expected


def test_poll_and_other_unlisted_media_map_to_none() -> None:
    message = fake_message(poll=object(), geo=object(), contact=object(), web_preview=object())
    assert mapper.map_media(message) is None
    assert do_map(message).media is None


def test_falsy_media_properties_are_ignored() -> None:
    assert mapper.map_media(fake_message(photo=None, video=0, document="")) is None


def test_media_file_details_are_copied() -> None:
    file = SimpleNamespace(
        mime_type="audio/ogg", size=48213, duration=14, width=None, height=None, name=None
    )
    media = mapper.map_media(fake_message(voice=object(), document=object(), file=file))
    assert media is not None
    assert media.to_dict() == {
        "type": "voice",
        "mime": "audio/ogg",
        "size": 48213,
        "duration": 14,
        "width": None,
        "height": None,
        "file_name": None,
        "file": None,
    }


def test_media_without_file_object_has_empty_details() -> None:
    media = mapper.map_media(fake_message(photo=object()))
    assert media is not None
    assert (media.mime, media.size, media.duration, media.width, media.height) == (None,) * 5
    assert media.file_name is None


def test_media_file_numbers_are_whole_numbers() -> None:
    file = SimpleNamespace(mime_type="video/mp4", size=2**40, duration=12.7, width=640, height=360)
    media = mapper.map_media(fake_message(video=object(), file=file))
    assert media is not None
    assert (media.size, media.duration, media.width, media.height) == (2**40, 12, 640, 360)


def test_media_file_name_is_kept_verbatim() -> None:
    file = SimpleNamespace(
        name="\u043e\u0442\u0447\u0451\u0442 \U0001f600.pdf", mime_type="application/pdf"
    )
    media = mapper.map_media(fake_message(document=object(), file=file))
    assert media is not None
    assert media.file_name == "\u043e\u0442\u0447\u0451\u0442 \U0001f600.pdf"


@pytest.mark.parametrize(
    ("sender", "expected"),
    [
        (None, None),
        (SimpleNamespace(first_name="Ann", last_name="Lee"), "Ann Lee"),
        (SimpleNamespace(first_name="Ann", last_name=None), "Ann"),
        (SimpleNamespace(first_name=None, last_name="Lee"), "Lee"),
        (SimpleNamespace(first_name="", last_name="Lee"), "Lee"),
        (SimpleNamespace(first_name=None, last_name=None), None),
        (SimpleNamespace(first_name="", last_name=""), None),
        (SimpleNamespace(), None),
        (SimpleNamespace(title="News Channel"), "News Channel"),
        (SimpleNamespace(title="Chan", first_name="Ann"), "Chan"),
        (SimpleNamespace(title="", first_name="Ann", last_name="Lee"), "Ann Lee"),
        (
            SimpleNamespace(
                first_name="\u0414\u0438\u043c\u0430",
                last_name="\u0401\u043b\u043a\u0438\u043d \U0001f384",
            ),
            "\u0414\u0438\u043c\u0430 \u0401\u043b\u043a\u0438\u043d \U0001f384",
        ),
    ],
)
def test_sender_display_name(sender: Any, expected: str | None) -> None:
    assert mapper.sender_display_name(sender) == expected


def test_sender_fields_are_recorded() -> None:
    sender = SimpleNamespace(first_name="Ann", last_name="Lee", username="ann_l")
    record = do_map(fake_message(sender=sender, sender_id=42))
    assert (record.sender_id, record.sender_name, record.sender_username) == (
        42,
        "Ann Lee",
        "ann_l",
    )


@pytest.mark.parametrize(
    "sender",
    [
        SimpleNamespace(first_name="Ann", last_name="Lee", username="ann_l"),
        SimpleNamespace(title="Chan", username="chan"),
        None,
    ],
)
def test_disabling_sender_names_drops_name_and_username_but_keeps_id(sender: Any) -> None:
    record = do_map(fake_message(sender=sender, sender_id=42), names=False)
    assert record.sender_id == 42
    assert record.sender_name is None
    assert record.sender_username is None
    assert "Ann" not in json.dumps(record.to_dict())


def test_disabling_sender_names_does_not_touch_the_sender_object() -> None:
    class Exploding:
        def __getattr__(self, name: str) -> Any:
            raise AssertionError(name)

    message = fake_message(sender=Exploding(), sender_id=1)
    assert do_map(message, names=False).sender_id == 1


def test_deleted_account_sender_has_no_name() -> None:
    sender = SimpleNamespace(first_name=None, last_name=None, username=None, deleted=True)
    record = do_map(fake_message(sender=sender, sender_id=99))
    assert (record.sender_id, record.sender_name, record.sender_username) == (99, None, None)


def test_channel_post_uses_the_channel_title_as_sender_name() -> None:
    sender = SimpleNamespace(title="Channel Title", username="chan")
    record = do_map(fake_message(sender=sender, sender_id=-1001234567890))
    assert record.sender_name == "Channel Title"
    assert record.sender_username == "chan"


def test_anonymous_admin_has_no_sender_id() -> None:
    record = do_map(fake_message(sender=None, sender_id=None))
    assert (record.sender_id, record.sender_name, record.sender_username) == (None, None, None)


def test_bot_sender_is_recorded_like_a_user() -> None:
    sender = SimpleNamespace(
        first_name="HelperBot", last_name=None, username="helper_bot", bot=True
    )
    record = do_map(fake_message(sender=sender, sender_id=5))
    assert (record.sender_name, record.sender_username) == ("HelperBot", "helper_bot")


def test_empty_username_becomes_none() -> None:
    sender = SimpleNamespace(first_name="Ann", username="")
    assert do_map(fake_message(sender=sender)).sender_username is None


def test_message_without_optional_attributes_maps() -> None:
    record = do_map(SimpleNamespace(id=1, date=NOW, to_dict=dict))
    assert (record.text, record.sender_id, record.reply_to_msg_id, record.grouped_id) == (
        "",
        None,
        None,
        None,
    )
    assert (record.forwarded, record.service, record.media, record.edit_date) == (
        False,
        None,
        None,
        None,
    )


@pytest.mark.parametrize(
    "text",
    [
        None,
        "",
        "   ",
        "\n\n",
        "  padded  ",
        "emoji \U0001f600\U0001f389 and ZWJ \U0001f468\u200d\U0001f469\u200d\U0001f467",
        "\u05e9\u05dc\u05d5\u05dd \u05e2\u05d5\u05dc\u05dd \u0645\u0631\u062d\u0628\u0627",
        "line1\r\nline2\rline3\u2028line4",
        "tab\tinside",
        "null\x00byte",
        "x" * 100_000,
    ],
)
def test_text_is_kept_as_is_and_survives_jsonl(text: str | None) -> None:
    record = do_map(fake_message(message=text))
    assert record.text == (text or "")
    line = json.dumps(record.to_dict(), ensure_ascii=False)
    assert "\n" not in line
    assert MessageRecord.from_dict(json.loads(line)).text == (text or "")


@pytest.mark.parametrize(
    ("date", "expected"),
    [
        (datetime(2026, 10, 1, 8, 0, 0), datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)),  # noqa: DTZ001 naive on purpose
        (
            datetime(2026, 10, 1, 8, 0, 0, tzinfo=timezone(timedelta(hours=3))),
            datetime(2026, 10, 1, 5, 0, 0, tzinfo=UTC),
        ),
        (
            datetime(2026, 10, 1, 0, 30, 0, tzinfo=timezone(timedelta(hours=5, minutes=30))),
            datetime(2026, 9, 30, 19, 0, 0, tzinfo=UTC),
        ),
        (datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC), datetime(2026, 10, 1, 8, 0, 0, tzinfo=UTC)),
    ],
)
def test_dates_become_utc_aware(date: datetime, expected: datetime) -> None:
    record = do_map(fake_message(date=date, edit_date=date))
    assert record.date == expected
    assert record.date.utcoffset() == timedelta(0)
    assert record.edit_date == expected
    assert record.edit_date is not None
    assert record.edit_date.utcoffset() == timedelta(0)


def test_dates_are_written_with_z() -> None:
    data = do_map(fake_message(edit_date=NOW)).to_dict()
    assert data["date"] == "2026-10-01T08:30:15Z"
    assert data["edit_date"] == "2026-10-29T12:00:00Z"
    assert data["fetched_at"] == "2026-10-29T12:00:00Z"


def test_unedited_message_has_no_edit_date() -> None:
    assert do_map(fake_message(edit_date=None)).edit_date is None
    assert do_map(fake_message()).edit_date is None


def test_forwarded_flag() -> None:
    assert do_map(fake_message(fwd_from=object())).forwarded is True
    assert do_map(fake_message(fwd_from=None)).forwarded is False
    assert do_map(fake_message()).forwarded is False


def test_album_grouped_id() -> None:
    album = 13_000_000_000_000_001
    assert do_map(fake_message(grouped_id=album)).grouped_id == album
    assert do_map(fake_message(grouped_id=None)).grouped_id is None


@pytest.mark.parametrize(
    ("reply_to", "reply", "topic"),
    [
        (None, None, None),
        (SimpleNamespace(reply_to_msg_id=7), 7, None),
        (SimpleNamespace(reply_to_msg_id=7, reply_to_top_id=3, forum_topic=False), 7, None),
        (SimpleNamespace(reply_to_msg_id=7, reply_to_top_id=3, forum_topic=True), 7, 3),
        (SimpleNamespace(reply_to_msg_id=3, reply_to_top_id=3, forum_topic=True), None, 3),
        (SimpleNamespace(reply_to_msg_id=3, reply_to_top_id=None, forum_topic=True), None, 3),
        (SimpleNamespace(reply_to_msg_id=None, reply_to_top_id=3, forum_topic=True), None, 3),
        (SimpleNamespace(reply_to_msg_id=None, reply_to_top_id=None, forum_topic=True), None, None),
        (SimpleNamespace(reply_to_msg_id=None), None, None),
        (
            SimpleNamespace(reply_to_msg_id=2**45, reply_to_top_id=2**44, forum_topic=True),
            2**45,
            2**44,
        ),
    ],
)
def test_reply_and_forum_topic(reply_to: Any, reply: int | None, topic: int | None) -> None:
    record = do_map(fake_message(reply_to=reply_to))
    assert (record.reply_to_msg_id, record.topic_id) == (reply, topic)


def test_huge_ids_are_kept_exactly() -> None:
    big = 2**63 - 1
    record = do_map(fake_message(id=big, sender_id=big), chat_id=-big)
    assert record.msg_id == big
    assert record.sender_id == big
    assert record.chat_id == -big
    assert MessageRecord.from_dict(json.loads(json.dumps(record.to_dict()))).msg_id == big


def test_message_id_given_as_text_is_converted() -> None:
    assert do_map(fake_message(id="77")).msg_id == 77


def test_record_carries_chat_context() -> None:
    record = do_map(fake_message(id=5), chat_id=-1001234567890, username="pub")
    assert record.chat_id == -1001234567890
    assert record.link == "https://t.me/pub/5"
    assert record.fetched_at == FETCHED


def test_raw_is_absent_unless_requested() -> None:
    def explode() -> dict[str, Any]:
        raise AssertionError("to_dict must not be called")

    record = do_map(fake_message(to_dict=explode), raw=False)
    assert record.raw is None
    assert "raw" not in record.to_dict()


def test_raw_is_converted_to_json_types() -> None:
    class Opaque:
        def __str__(self) -> str:
            return "opaque!"

    payload: dict[Any, Any] = {
        "_": "Message",
        "date": datetime(2026, 10, 1, 8, 0, 0, 123456),  # noqa: DTZ001 naive on purpose
        "aware": datetime(2026, 10, 1, 11, 0, 0, tzinfo=timezone(timedelta(hours=3))),
        "blob": b"\x00\xff\x10",
        "nested": {"list": [1, (2, 3), {"deep": b"a"}], 5: "int key"},
        "flag": True,
        "none": None,
        "float": 1.5,
        "text": "\u043f\u0440\u0438\u0432\u0435\u0442 \U0001f600",
        "opaque": Opaque(),
        "big": 2**70,
    }
    record = do_map(fake_message(to_dict=lambda: payload), raw=True)
    assert record.raw == {
        "_": "Message",
        "date": "2026-10-01T08:00:00Z",
        "aware": "2026-10-01T08:00:00Z",
        "blob": "AP8Q",
        "nested": {"list": [1, [2, 3], {"deep": "YQ=="}], "5": "int key"},
        "flag": True,
        "none": None,
        "float": 1.5,
        "text": "\u043f\u0440\u0438\u0432\u0435\u0442 \U0001f600",
        "opaque": "opaque!",
        "big": 2**70,
    }
    assert json.loads(json.dumps(record.to_dict()))["raw"] == record.raw


def test_raw_empty_dict_is_kept_as_empty_object() -> None:
    record = do_map(fake_message(to_dict=dict), raw=True)
    assert record.raw == {}
    assert record.to_dict()["raw"] == {}


def tl_message(media: Any = None, **kw: Any) -> TlMessage:
    return TlMessage(
        id=5,
        peer_id=tl.PeerChannel(1),
        date=datetime(2026, 10, 1, tzinfo=UTC),
        message=kw.pop("message", ""),
        media=media,
        **kw,
    )


def document(attributes: list[Any], mime: str, size: int) -> tl.MessageMediaDocument:
    doc = tl.Document(
        id=1,
        access_hash=2,
        file_reference=b"",
        date=datetime(2026, 10, 1, tzinfo=UTC),
        mime_type=mime,
        size=size,
        dc_id=1,
        attributes=attributes,
    )
    return tl.MessageMediaDocument(document=doc)


def photo_object() -> tl.Photo:
    return tl.Photo(
        id=1,
        access_hash=2,
        file_reference=b"x",
        date=datetime(2026, 10, 1, tzinfo=UTC),
        sizes=[tl.PhotoSize(type="x", w=10, h=10, size=1)],
        dc_id=1,
    )


def test_real_telethon_voice_message() -> None:
    media_obj = document([tl.DocumentAttributeAudio(duration=14, voice=True)], "audio/ogg", 48213)
    media = do_map(tl_message(media_obj)).media
    assert media is not None
    assert (media.type, media.mime, media.size, media.duration) == ("voice", "audio/ogg", 48213, 14)


def test_real_telethon_video_note_and_video() -> None:
    round_video = tl.DocumentAttributeVideo(duration=3, w=240, h=240, round_message=True)
    note = do_map(tl_message(document([round_video], "video/mp4", 5))).media
    assert note is not None
    assert (note.type, note.width, note.height, note.duration) == ("video_note", 240, 240, 3)
    plain = tl.DocumentAttributeVideo(duration=9, w=1280, h=720)
    video = do_map(tl_message(document([plain], "video/mp4", 5))).media
    assert video is not None
    assert (video.type, video.width, video.height) == ("video", 1280, 720)


def test_real_telethon_plain_document_keeps_file_name() -> None:
    attrs = [tl.DocumentAttributeFilename(file_name="a.pdf")]
    media = do_map(tl_message(document(attrs, "application/pdf", 77))).media
    assert media is not None
    assert (media.type, media.file_name, media.size) == ("document", "a.pdf", 77)


def test_real_telethon_text_only_message_has_no_media() -> None:
    assert do_map(tl_message(None, message="just text")).media is None


def test_link_preview_with_a_photo_is_not_an_attachment() -> None:
    page = tl.WebPage(
        id=1, url="https://e.test", display_url="e.test", hash=0, photo=photo_object()
    )
    record = do_map(tl_message(tl.MessageMediaWebPage(webpage=page), message="see https://e.test"))
    assert record.media is None


def test_chat_photo_change_service_message_has_no_attachment() -> None:
    message = tl.MessageService(
        id=6,
        peer_id=tl.PeerChannel(1),
        date=datetime(2026, 10, 1, tzinfo=UTC),
        action=tl.MessageActionChatEditPhoto(photo=photo_object()),
    )
    record = do_map(message)
    assert record.service == "photo_change"
    assert record.media is None
