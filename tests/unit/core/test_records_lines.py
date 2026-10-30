from __future__ import annotations

import json

import pytest

from chatimport.records import (
    DECODE_ERRORS,
    MessageRecord,
    escape_line_breaks,
    json_line,
    json_line_bytes,
    record_from_line,
    record_to_bytes,
    record_to_line,
)
from tests.fakes import msg

LINE_BREAKS = chr(0x2028) + chr(0x2029) + chr(0x85)
CYRILLIC = "".join(map(chr, (0x41F, 0x440, 0x438, 0x432, 0x435, 0x442)))


def test_record_line_has_no_unicode_line_breaks_and_round_trips() -> None:
    record = msg(1, text=f"a{chr(0x2028)}b{chr(0x2029)}c{chr(0x85)}d {CYRILLIC}")
    line = record_to_line(record)
    assert len(line.splitlines()) == 1
    assert not set(LINE_BREAKS) & set(line)
    assert CYRILLIC in line
    decoded = record_from_line(line)
    assert isinstance(decoded, MessageRecord)
    assert decoded.text == record.text


@pytest.mark.parametrize(
    "text",
    ["plain", CYRILLIC, "emoji \U0001f600", f"breaks {LINE_BREAKS}", "lone \ud800 surrogate"],
)
def test_record_to_bytes_equals_the_encoded_line(text: str) -> None:
    record = msg(7, text=text)
    assert record_to_bytes(record) == (record_to_line(record) + "\n").encode("utf-8")


def test_lone_surrogates_become_the_replacement_character_only_when_present() -> None:
    assert json_line({"t": "a\ud800b"}) == '{"t":"a' + chr(0xFFFD) + 'b"}'
    assert json_line({"t": "ab"}) == '{"t":"ab"}'


def test_json_line_bytes_ends_with_exactly_one_newline() -> None:
    data = json_line_bytes({"k": [1, 2]})
    assert data == b'{"k":[1,2]}\n'


def test_escape_line_breaks_keeps_the_json_value() -> None:
    text = json.dumps({"t": LINE_BREAKS}, ensure_ascii=False)
    escaped = escape_line_breaks(text)
    assert escaped != text
    assert json.loads(escaped) == json.loads(text)
    assert escape_line_breaks("{}") == "{}"


def test_deeply_nested_line_raises_one_of_the_decode_errors() -> None:
    with pytest.raises(DECODE_ERRORS):
        record_from_line("[" * 100_000 + "]" * 100_000)
