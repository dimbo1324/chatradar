from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone

import pytest

from chatradar.domain import text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("  hello  ", "hello"),
        ("a\r\nb", "a\nb"),
        ("a   \nb", "a\nb"),
        ("a\n\n\n\nb", "a\n\nb"),
        ("Café", "Café"),
        ("", ""),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert text.normalize_text(raw) == expected


def test_content_hash_changes_with_meaningful_fields() -> None:
    base = text.content_hash(text_raw="hi", media_type="none", reply_to=None)

    assert base == text.content_hash(text_raw="hi", media_type="none", reply_to=None)
    assert base != text.content_hash(text_raw="hi!", media_type="none", reply_to=None)
    assert base != text.content_hash(text_raw="hi", media_type="photo", reply_to=None)
    assert base != text.content_hash(text_raw="hi", media_type="none", reply_to="5")


def test_fingerprint_ignores_case_punctuation_and_spacing() -> None:
    assert text.fingerprint("Thanks, a LOT!") == text.fingerprint("thanks a lot")
    assert text.fingerprint("thanks") != text.fingerprint("thanks a lot")


@pytest.mark.parametrize(
    ("chat_id", "username", "expected"),
    [
        ("-1001234", "public_chat", "https://t.me/public_chat/7"),
        ("-1001234", "@public_chat", "https://t.me/public_chat/7"),
        ("-1001234", None, "https://t.me/c/1234/7"),
        ("-5678", None, None),
        ("42", None, None),
    ],
)
def test_message_link(chat_id: str, username: str | None, expected: str | None) -> None:
    assert text.message_link(chat_id, "7", username) == expected


def test_ensure_utc() -> None:
    naive = datetime(2026, 10, 19, 12, 0)  # noqa: DTZ001 — naive on purpose
    plus3 = datetime(2026, 10, 19, 15, 0, tzinfo=timezone(timedelta(hours=3)))

    assert text.ensure_utc(naive) == datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    assert text.ensure_utc(plus3) == datetime(2026, 10, 19, 12, 0, tzinfo=UTC)
    assert text.ensure_utc(plus3).tzinfo is UTC


def test_thread_id_for() -> None:
    assert text.thread_id_for("-100123", "42") == "-100123:42"
