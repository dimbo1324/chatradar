from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import pytest
from pydantic import ValidationError

from chatradar.domain.models import MediaType, Message, Source


def _message(**overrides: Any) -> Message:
    data: dict[str, Any] = {
        "source": Source.TELEGRAM,
        "chat_id": "-100123",
        "msg_id": "42",
        "author_id": "7",
        "date": datetime(2026, 10, 18, 23, 50, tzinfo=UTC),
        "text": "Как записаться в Migración?",
        "content_hash": "abc",
    }
    return Message.model_validate(data | overrides)


def test_message_defaults_and_key() -> None:
    msg = _message()

    assert msg.media_type is MediaType.NONE
    assert msg.key == (Source.TELEGRAM, "-100123", "42")


def test_message_is_immutable() -> None:
    msg = _message()

    with pytest.raises(ValidationError):
        msg.text = "другое"  # type: ignore[misc]


def test_naive_datetime_is_rejected() -> None:
    with pytest.raises(ValidationError):
        _message(date=datetime(2026, 10, 18, 23, 50))  # noqa: DTZ001 — проверяем именно naive


def test_unknown_fields_are_rejected() -> None:
    with pytest.raises(ValidationError):
        _message(unexpected="x")
