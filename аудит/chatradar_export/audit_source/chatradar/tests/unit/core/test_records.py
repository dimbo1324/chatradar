from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import Any

import pytest

from chatimport.records import (
    DETECTED_RECHECK,
    KIND_DELETE,
    KIND_EDIT,
    KIND_MEDIA_SAVED,
    KIND_MESSAGE,
    SCHEMA_VERSION,
    DeleteRecord,
    EditRecord,
    MediaInfo,
    MediaSavedRecord,
    MessageRecord,
    Record,
    format_dt,
    parse_dt,
    record_chat_id,
    record_event_date,
    record_from_dict,
    record_from_line,
    record_sort_id,
    record_to_line,
    utc_now,
)

T0 = datetime(2026, 10, 29, 21, 3, 11, tzinfo=UTC)
T1 = datetime(2026, 10, 29, 21, 10, 2, tzinfo=UTC)
T2 = datetime(2026, 10, 29, 21, 11, 0, tzinfo=UTC)

FULL_MEDIA = MediaInfo(
    type="video",
    mime="video/mp4",
    size=2**40,
    duration=12,
    width=640,
    height=480,
    file_name="\u0432\u0438\u0434\u0435\u043e.mp4",
    file="2026-10/42.mp4",
)


def full_message(**overrides: Any) -> MessageRecord:
    base: dict[str, Any] = {
        "chat_id": -1001234567890,
        "msg_id": 4512,
        "date": T0,
        "fetched_at": T1,
        "text": "hello",
        "edit_date": T1,
        "sender_id": 777000111,
        "sender_name": "Example Person",
        "sender_username": "example_user",
        "reply_to_msg_id": 4507,
        "topic_id": 12,
        "grouped_id": 2**62,
        "forwarded": True,
        "service": "pin",
        "link": "https://t.me/c/1234567890/4512",
        "media": FULL_MEDIA,
    }
    base.update(overrides)
    return MessageRecord(**base)


ALL_RECORDS: list[Record] = [
    full_message(),
    MessageRecord(chat_id=1, msg_id=1, date=T0, fetched_at=T0),
    EditRecord(chat_id=-5, msg_id=9, edit_date=T1, fetched_at=T2, text="new", media=FULL_MEDIA),
    EditRecord(chat_id=-5, msg_id=9, edit_date=T1, fetched_at=T2, detected_by=DETECTED_RECHECK),
    DeleteRecord(chat_id=-5, msg_ids=(3, 1, 2), fetched_at=T2),
    DeleteRecord(chat_id=-5, msg_ids=(), fetched_at=T2, detected_by=DETECTED_RECHECK),
    MediaSavedRecord(chat_id=-5, msg_id=9, file="2026-10/9_2.jpg", fetched_at=T2),
]


@pytest.mark.parametrize("record", ALL_RECORDS)
def test_every_record_round_trips_through_a_line(record: Record) -> None:
    assert record_from_line(record_to_line(record)) == record


@pytest.mark.parametrize("record", ALL_RECORDS)
def test_line_is_compact_single_line_json_with_schema_version(record: Record) -> None:
    line = record_to_line(record)
    assert "\n" not in line
    assert "\r" not in line
    assert ": " not in line.split('"text"')[0]
    data = json.loads(line)
    assert data["v"] == SCHEMA_VERSION
    assert data["kind"] == record.kind


def test_kinds_are_the_documented_strings() -> None:
    assert (KIND_MESSAGE, KIND_EDIT, KIND_DELETE, KIND_MEDIA_SAVED) == (
        "message",
        "edit",
        "delete",
        "media_saved",
    )
    assert [r.kind for r in ALL_RECORDS[::2]] == ["message", "edit", "delete", "media_saved"]


def test_message_has_exactly_the_documented_keys() -> None:
    data = full_message().to_dict()
    assert set(data) == {
        "v",
        "kind",
        "source",
        "chat_id",
        "msg_id",
        "date",
        "edit_date",
        "fetched_at",
        "sender_id",
        "sender_name",
        "sender_username",
        "text",
        "reply_to_msg_id",
        "topic_id",
        "grouped_id",
        "forwarded",
        "service",
        "link",
        "media",
    }
    assert data["source"] == "telegram"


def test_edit_delete_and_media_saved_have_the_documented_keys() -> None:
    assert set(ALL_RECORDS[2].to_dict()) == {
        "v",
        "kind",
        "chat_id",
        "msg_id",
        "edit_date",
        "text",
        "media",
        "detected_by",
        "fetched_at",
    }
    assert set(ALL_RECORDS[4].to_dict()) == {
        "v",
        "kind",
        "chat_id",
        "msg_ids",
        "detected_by",
        "fetched_at",
    }
    assert set(ALL_RECORDS[6].to_dict()) == {
        "v",
        "kind",
        "chat_id",
        "msg_id",
        "file",
        "fetched_at",
    }


def test_message_without_raw_has_no_raw_key() -> None:
    assert "raw" not in full_message().to_dict()


@pytest.mark.parametrize("raw", [{}, {"a": 1}, {"nested": {"x": [1, None, "\u0436"]}}])
def test_raw_is_written_even_when_empty_and_round_trips(raw: dict[str, Any]) -> None:
    record = full_message(raw=raw)
    assert record.to_dict()["raw"] == raw
    assert record_from_line(record_to_line(record)) == record


def test_raw_with_a_non_serialisable_value_fails_loudly() -> None:
    with pytest.raises(TypeError):
        record_to_line(full_message(raw={"b": b"bytes"}))


@pytest.mark.parametrize(
    "text",
    [
        "",
        " ",
        "line1\nline2",
        "crlf\r\nline",
        "lone\rcr",
        "\n",
        "tab\there",
        "nul\x00inside",
        "esc\x1b[0m",
        "\x7fdel",
        'quote" and \\ backslash',
        "\u0420\u0443\u0441\u0441\u043a\u0438\u0439 \u0442\u0435\u043a\u0441\u0442",
        "\U0001f600 emoji \U0001f468\u200d\U0001f469\u200d\U0001f467",
        "\u05e9\u05dc\u05d5\u05dd \u0645\u0631\u062d\u0628\u0627",
        "\u202eRTL override",
        "ls\u2028ps\u2029nel\x85",
        "\ufeffbom inside",
        "\u4e2d\u6587",
        "x" * 100_000,
    ],
)
def test_text_survives_and_never_breaks_the_line(text: str) -> None:
    record = full_message(text=text)
    line = record_to_line(record)
    assert "\n" not in line
    assert "\r" not in line
    assert line.encode("utf-8").decode("utf-8") == line
    restored = record_from_line(line)
    assert isinstance(restored, MessageRecord)
    assert restored.text == text


def test_line_written_as_text_file_reads_back_as_exactly_one_line(tmp_path: Any) -> None:
    text = "a\nb\r\nc\u2028d\x00"
    path = tmp_path / "x.jsonl"
    with path.open("w", encoding="utf-8", newline="") as handle:
        handle.write(record_to_line(full_message(text=text)) + "\n")
    with path.open("r", encoding="utf-8") as handle:
        lines = list(handle)
    assert len(lines) == 1
    restored = record_from_line(lines[0])
    assert isinstance(restored, MessageRecord)
    assert restored.text == text


def test_non_ascii_stays_readable_on_disk() -> None:
    assert "\u043f\u0440\u0438\u0432\u0435\u0442" in record_to_line(
        full_message(text="\u043f\u0440\u0438\u0432\u0435\u0442")
    )


def test_lone_surrogate_in_text_does_not_make_the_line_unwritable() -> None:
    line = record_to_line(full_message(text="broken \ud83d half"))
    line.encode("utf-8")


def test_none_text_from_disk_becomes_empty_string() -> None:
    data = full_message().to_dict()
    data["text"] = None
    record = record_from_dict(data)
    assert isinstance(record, MessageRecord)
    assert record.text == ""


def test_microseconds_are_truncated_not_rounded() -> None:
    value = datetime(2026, 1, 1, 0, 0, 59, 999_999, tzinfo=UTC)
    assert format_dt(value) == "2026-01-01T00:00:59Z"
    record = full_message(date=value, edit_date=None)
    restored = record_from_line(record_to_line(record))
    assert isinstance(restored, MessageRecord)
    assert restored.date == value.replace(microsecond=0)


def test_format_dt_always_uses_z_suffix() -> None:
    assert format_dt(T0) == "2026-10-29T21:03:11Z"
    assert "+00:00" not in format_dt(T0)


@pytest.mark.parametrize(
    ("offset_hours", "offset_minutes"), [(5, 30), (-3, 0), (14, 0), (-12, 0), (0, 45)]
)
def test_non_utc_offsets_are_normalised_to_the_same_instant(
    offset_hours: int, offset_minutes: int
) -> None:
    zone = timezone(timedelta(hours=offset_hours, minutes=offset_minutes))
    local = T0.astimezone(zone)
    assert local.utcoffset() != timedelta(0) or offset_hours == 0
    text = format_dt(local)
    assert text.endswith("Z")
    assert parse_dt(text) == T0


def test_day_boundary_is_decided_in_utc() -> None:
    zone = timezone(timedelta(hours=-3))
    local = datetime(2026, 1, 31, 22, 0, 0, tzinfo=zone)
    assert format_dt(local) == "2026-02-01T01:00:00Z"


def test_aware_datetime_with_any_offset_round_trips_as_utc() -> None:
    zone = timezone(timedelta(hours=9))
    record = full_message(date=datetime(2026, 5, 5, 7, 0, 0, tzinfo=zone), edit_date=None)
    restored = record_from_line(record_to_line(record))
    assert isinstance(restored, MessageRecord)
    assert restored.date == record.date
    assert restored.date.utcoffset() == timedelta(0)


def test_naive_datetime_is_read_as_local_time_consistently() -> None:
    naive = datetime(2026, 6, 1, 12, 0, 0)  # noqa: DTZ001
    assert format_dt(naive) == format_dt(naive.astimezone(UTC))


@pytest.mark.parametrize(
    "text", ["2026-10-29T21:03:11Z", "2026-10-29T21:03:11+00:00", "2026-10-29T23:03:11+02:00"]
)
def test_parse_dt_accepts_z_and_offsets(text: str) -> None:
    assert parse_dt(text) == T0
    assert parse_dt(text).utcoffset() == timedelta(0)


@pytest.mark.parametrize("text", ["", "not a date", "2026-13-01T00:00:00Z", "2026-10-29T25:00:00Z"])
def test_parse_dt_rejects_garbage(text: str) -> None:
    with pytest.raises(ValueError, match=r"."):
        parse_dt(text)


def test_utc_now_is_aware_utc() -> None:
    assert utc_now().utcoffset() == timedelta(0)


def test_media_info_round_trip_and_defaults() -> None:
    assert MediaInfo.from_dict(FULL_MEDIA.to_dict()) == FULL_MEDIA
    bare = MediaInfo(type="photo")
    assert bare.to_dict() == {
        "type": "photo",
        "mime": None,
        "size": None,
        "duration": None,
        "width": None,
        "height": None,
        "file_name": None,
        "file": None,
    }
    assert MediaInfo.from_dict({"type": "photo"}) == bare


def test_media_info_without_type_is_rejected() -> None:
    with pytest.raises(KeyError):
        MediaInfo.from_dict({"mime": "x"})


def test_empty_media_object_is_read_as_no_media() -> None:
    data = full_message().to_dict()
    data["media"] = {}
    record = record_from_dict(data)
    assert isinstance(record, MessageRecord)
    assert record.media is None


def test_message_missing_optional_keys_loads_with_defaults() -> None:
    record = record_from_dict(
        {
            "kind": "message",
            "chat_id": 1,
            "msg_id": 2,
            "date": "2026-01-01T00:00:00Z",
            "fetched_at": "2026-01-01T00:00:01Z",
        }
    )
    assert record == MessageRecord(
        chat_id=1,
        msg_id=2,
        date=datetime(2026, 1, 1, tzinfo=UTC),
        fetched_at=datetime(2026, 1, 1, 0, 0, 1, tzinfo=UTC),
    )


def test_unknown_extra_keys_are_ignored() -> None:
    data = full_message().to_dict()
    data["future_field"] = {"x": 1}
    assert record_from_dict(data) == full_message()


def test_integer_strings_are_converted_for_keys() -> None:
    data = full_message().to_dict()
    data["chat_id"] = "-1001234567890"
    data["msg_id"] = "4512"
    record = record_from_dict(data)
    assert isinstance(record, MessageRecord)
    assert (record.chat_id, record.msg_id) == (-1001234567890, 4512)


def test_delete_ids_given_as_strings_are_converted() -> None:
    record = record_from_dict(
        {
            "kind": "delete",
            "chat_id": "-5",
            "msg_ids": ["3", 4],
            "fetched_at": "2026-01-01T00:00:00Z",
        }
    )
    assert isinstance(record, DeleteRecord)
    assert record.msg_ids == (3, 4)
    assert record.chat_id == -5


@pytest.mark.parametrize("kind", [None, "", "Message", "MESSAGE", "other", 5, ["message"]])
def test_unknown_or_missing_kind_is_rejected(kind: object) -> None:
    data = full_message().to_dict()
    data["kind"] = kind
    with pytest.raises(ValueError, match="unknown record kind"):
        record_from_dict(data)


def test_missing_kind_key_is_rejected() -> None:
    data = full_message().to_dict()
    del data["kind"]
    with pytest.raises(ValueError, match="unknown record kind"):
        record_from_dict(data)


@pytest.mark.parametrize("missing", ["chat_id", "msg_id", "date", "fetched_at"])
def test_message_missing_required_key_is_rejected(missing: str) -> None:
    data = full_message().to_dict()
    del data[missing]
    with pytest.raises(KeyError):
        record_from_dict(data)


def test_edit_and_delete_and_media_missing_required_keys_are_rejected() -> None:
    for record, key in (
        (ALL_RECORDS[2], "edit_date"),
        (ALL_RECORDS[4], "msg_ids"),
        (ALL_RECORDS[6], "file"),
    ):
        data = record.to_dict()
        del data[key]
        with pytest.raises(KeyError):
            record_from_dict(data)


@pytest.mark.parametrize("line", ["", "   ", "{", "[]", "null", "42", '"message"', "{broken"])
def test_garbage_lines_raise_an_error_the_readers_catch(line: str) -> None:
    with pytest.raises((ValueError, KeyError, TypeError)):
        record_from_line(line)


def test_trailing_newline_in_line_is_tolerated() -> None:
    line = record_to_line(ALL_RECORDS[1]) + "\n"
    assert record_from_line(line) == ALL_RECORDS[1]


def test_huge_ids_round_trip_exactly() -> None:
    huge = 2**80 + 1
    message = full_message(chat_id=-huge, msg_id=huge, grouped_id=huge, reply_to_msg_id=huge)
    assert record_from_line(record_to_line(message)) == message
    delete = DeleteRecord(chat_id=-huge, msg_ids=(huge, huge + 1), fetched_at=T2)
    assert record_from_line(record_to_line(delete)) == delete
    assert record_sort_id(delete) == huge + 1


def test_negative_and_zero_ids_round_trip() -> None:
    message = full_message(msg_id=0, chat_id=0)
    assert record_from_line(record_to_line(message)) == message


def test_records_are_immutable_and_hashable_only_where_possible() -> None:
    delete = DeleteRecord(chat_id=1, msg_ids=(1,), fetched_at=T0)
    with pytest.raises(AttributeError):
        delete.chat_id = 2  # type: ignore[misc]  # pyright: ignore[reportAttributeAccessIssue]
    assert hash(delete) == hash(DeleteRecord(chat_id=1, msg_ids=(1,), fetched_at=T0))


def test_kind_cannot_be_overridden_through_the_constructor() -> None:
    with pytest.raises(TypeError):
        MessageRecord(chat_id=1, msg_id=1, date=T0, fetched_at=T0, kind="edit")  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


def test_delete_ids_are_serialised_as_a_list_in_given_order() -> None:
    assert ALL_RECORDS[4].to_dict()["msg_ids"] == [3, 1, 2]


def test_record_chat_id_for_each_kind() -> None:
    assert [record_chat_id(r) for r in ALL_RECORDS] == [-1001234567890, 1, -5, -5, -5, -5, -5]


def test_event_date_of_each_kind() -> None:
    message = full_message(date=T0, edit_date=T2, fetched_at=T1)
    assert record_event_date(message) == T0
    assert record_event_date(EditRecord(chat_id=1, msg_id=1, edit_date=T1, fetched_at=T2)) == T1
    assert record_event_date(DeleteRecord(chat_id=1, msg_ids=(1,), fetched_at=T2)) == T2
    assert record_event_date(MediaSavedRecord(chat_id=1, msg_id=1, file="f", fetched_at=T2)) == T2


def test_sort_id_of_each_kind() -> None:
    assert record_sort_id(full_message(msg_id=77)) == 77
    assert record_sort_id(EditRecord(chat_id=1, msg_id=5, edit_date=T1, fetched_at=T2)) == 5
    assert record_sort_id(MediaSavedRecord(chat_id=1, msg_id=6, file="f", fetched_at=T2)) == 6


def test_sort_id_of_delete_is_its_highest_id() -> None:
    assert record_sort_id(DeleteRecord(chat_id=1, msg_ids=(4, 9, 2), fetched_at=T2)) == 9
    assert record_sort_id(DeleteRecord(chat_id=1, msg_ids=(-3, -1), fetched_at=T2)) == -1


def test_sort_id_of_empty_delete_is_zero() -> None:
    assert record_sort_id(DeleteRecord(chat_id=1, msg_ids=(), fetched_at=T2)) == 0


def test_edit_without_media_keeps_media_none() -> None:
    restored = record_from_line(record_to_line(ALL_RECORDS[3]))
    assert isinstance(restored, EditRecord)
    assert restored.media is None
    assert restored.detected_by == DETECTED_RECHECK


def test_edit_and_delete_default_detected_by_when_absent_on_disk() -> None:
    edit = ALL_RECORDS[2].to_dict()
    del edit["detected_by"]
    delete = ALL_RECORDS[4].to_dict()
    del delete["detected_by"]
    restored_edit = record_from_dict(edit)
    restored_delete = record_from_dict(delete)
    assert isinstance(restored_edit, EditRecord)
    assert isinstance(restored_delete, DeleteRecord)
    assert restored_edit.detected_by == "event"
    assert restored_delete.detected_by == "event"
