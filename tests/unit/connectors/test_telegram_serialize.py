from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone

from chatradar.connectors.telegram.serialize import to_jsonable


class _Opaque:
    def __str__(self) -> str:
        return "opaque"


def test_nested_message_dict() -> None:
    local = timezone(timedelta(hours=-3))
    value = {
        "_": "Message",
        "id": 1,
        "date": datetime(2026, 10, 1, 7, 0, tzinfo=local),
        "naive": datetime(2026, 10, 1, 10, 0),  # noqa: DTZ001 - Telethon never sends one; checks the fallback
        "file_reference": b"\x00\xffab",
        "buffer": bytearray(b"hi"),
        "flags": (True, None, 1.5),
        "peers": {"ids": {3}},
        3: "int key",
        "other": _Opaque(),
    }

    result = to_jsonable(value)

    assert result == {
        "_": "Message",
        "id": 1,
        "date": "2026-10-01T10:00:00+00:00",
        "naive": "2026-10-01T10:00:00+00:00",
        "file_reference": "AP9hYg==",
        "buffer": "aGk=",
        "flags": [True, None, 1.5],
        "peers": {"ids": [3]},
        "3": "int key",
        "other": "opaque",
    }
    assert json.loads(json.dumps(result)) == result


def test_round_trip_date_is_utc() -> None:
    serialized = to_jsonable(datetime(2026, 1, 1, tzinfo=UTC))

    assert isinstance(serialized, str)
    assert datetime.fromisoformat(serialized) == datetime(2026, 1, 1, tzinfo=UTC)
