from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from chatradar.connectors.tg_export.parser import ExportFormatError, parse_export
from chatradar.domain.models import ChatKind, RawKind, Source
from tests.unit.connectors.fakes import FIXTURES, NOW

if TYPE_CHECKING:
    from pathlib import Path


def test_single_chat_export() -> None:
    [(chat, records)] = parse_export(
        FIXTURES / "supergroup_result.json", fetched_at=NOW, username="@expats_demo"
    )

    assert chat.chat_id == "-1001700000001"
    assert chat.kind is ChatKind.SUPERGROUP
    assert chat.title == "Expats Montevideo (synthetic)"
    assert chat.username == "expats_demo"
    assert len(records) == 60
    assert {r.kind for r in records} == {RawKind.TG_DESKTOP}
    assert {r.source for r in records} == {Source.TELEGRAM}
    assert {r.chat_id for r in records} == {chat.chat_id}
    assert all(r.fetched_at == NOW for r in records)


def test_payload_is_the_message_object_unchanged() -> None:
    source = json.loads((FIXTURES / "supergroup_result.json").read_text(encoding="utf-8"))
    [(_, records)] = parse_export(FIXTURES / "supergroup_result.json", fetched_at=NOW)

    assert [r.payload for r in records] == source["messages"]


def test_full_account_export() -> None:
    parsed = parse_export(FIXTURES / "full_account_result.json", fetched_at=NOW)

    assert [(c.chat_id, c.kind, len(r)) for c, r in parsed] == [
        ("-4200000001", ChatKind.GROUP, 4),
        ("-1001700000002", ChatKind.SUPERGROUP, 3),
    ]
    assert all(c.username is None for c, _ in parsed)


def test_username_with_several_chats_is_rejected() -> None:
    with pytest.raises(ExportFormatError, match="single chat"):
        parse_export(FIXTURES / "full_account_result.json", fetched_at=NOW, username="x")


@pytest.mark.parametrize(
    ("chat_type", "chat_id", "kind"),
    [
        ("public_supergroup", "-10077", ChatKind.SUPERGROUP),
        ("private_supergroup", "-10077", ChatKind.SUPERGROUP),
        ("public_channel", "-10077", ChatKind.CHANNEL),
        ("private_channel", "-10077", ChatKind.CHANNEL),
        ("private_group", "-77", ChatKind.GROUP),
        ("personal_chat", "77", ChatKind.PRIVATE),
        ("bot_chat", "77", ChatKind.PRIVATE),
        ("saved_messages", "77", ChatKind.PRIVATE),
    ],
)
def test_chat_id_marked_form(tmp_path: Path, chat_type: str, chat_id: str, kind: ChatKind) -> None:
    path = tmp_path / "result.json"
    path.write_text(json.dumps({"type": chat_type, "id": 77, "messages": []}), encoding="utf-8")

    [(chat, records)] = parse_export(path, fetched_at=NOW)

    assert (chat.chat_id, chat.kind) == (chat_id, kind)
    assert chat.title
    assert records == []


@pytest.mark.parametrize(
    ("content", "error"),
    [
        ("not json", "not valid JSON"),
        ("[1, 2]", "not an object"),
        ('{"about": "x"}', "neither"),
        ('{"type": "public_supergroup", "messages": []}', "numeric id"),
        ('{"type": "secret_chat", "id": 1, "messages": []}', "unknown chat type"),
        ('{"type": "public_supergroup", "id": 1, "messages": {}}', "not a list"),
    ],
)
def test_malformed_exports(tmp_path: Path, content: str, error: str) -> None:
    path = tmp_path / "result.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ExportFormatError, match=error):
        parse_export(path, fetched_at=NOW)
