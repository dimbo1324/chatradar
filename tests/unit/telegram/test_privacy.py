from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

from chatimport.ports import ResolveStatus
from chatimport.telegram import client as client_mod
from chatimport.telegram import mapper
from chatimport.telegram.resolve import resolve_ref
from tests.fakes import NOW

if TYPE_CHECKING:
    import pytest

CAFE_NFC = "Caf\u00e9 Espa\u00f1a"
CAFE_NFD = "Cafe\u0301 Espan\u0303a"


def message_with_personal_raw() -> SimpleNamespace:
    raw: dict[str, Any] = {
        "_": "Message",
        "id": 10,
        "message": "hello",
        "post_author": "Signature Person",
        "fwd_from": {"_": "MessageFwdHeader", "from_name": "Hidden Author", "date": NOW},
        "media": {
            "_": "MessageMediaContact",
            "phone_number": "+000111222",
            "first_name": "Contact",
            "last_name": "Person",
            "vcard": "BEGIN:VCARD",
            "user_id": 5,
        },
        "entities": [{"_": "MessageEntityMentionName", "user_id": 5, "username": "someone"}],
    }
    return SimpleNamespace(
        id=10,
        date=datetime(2026, 10, 1, 8, 30, 15, tzinfo=UTC),
        message="hello",
        to_dict=lambda: raw,
    )


def keys_at_any_depth(value: Any) -> set[str]:
    if isinstance(value, dict):
        mapping: dict[str, Any] = value  # pyright: ignore[reportUnknownVariableType]
        found = set(mapping)
        for item in mapping.values():
            found |= keys_at_any_depth(item)
        return found
    if isinstance(value, list):
        items: list[Any] = value  # pyright: ignore[reportUnknownVariableType]
        found: set[str] = set()
        for item in items:
            found |= keys_at_any_depth(item)
        return found
    return set()


def mapped(*, names: bool) -> Any:
    return mapper.map_message(
        message_with_personal_raw(),
        chat_id=-1001,
        chat_username=None,
        fetched_at=NOW,
        include_sender_names=names,
        include_raw=True,
    ).raw


def test_raw_is_scrubbed_without_sender_names() -> None:
    raw = mapped(names=False)
    assert keys_at_any_depth(raw).isdisjoint(mapper.PERSONAL_RAW_KEYS)
    text = json.dumps(raw)
    for secret in ("Hidden Author", "Signature Person", "+000111222", "someone", "VCARD"):
        assert secret not in text
    assert raw["media"]["user_id"] == 5
    assert set(raw["fwd_from"]) == {"_", "date"}


def test_raw_keeps_everything_when_sender_names_are_on() -> None:
    raw = mapped(names=True)
    assert raw["fwd_from"]["from_name"] == "Hidden Author"
    assert raw["media"]["phone_number"] == "+000111222"


async def test_resolve_title_matches_nfd_ref() -> None:
    entity = type("Channel", (), {"title": CAFE_NFC, "megagroup": True, "pid": -1001})()

    class Lookup:
        async def get_entity_by_username(self, username: str) -> Any:
            return None

        async def check_invite(self, invite_hash: str) -> Any:
            return None

        async def dialog_entities(self) -> list[Any]:
            return [entity, type("Channel", (), {"title": None, "pid": -2})()]

        def peer_id(self, entity: Any) -> int:
            return entity.pid

    result = await resolve_ref(CAFE_NFD, Lookup())
    assert (result.status, result.chat_id) == (ResolveStatus.FOUND, -1001)
    upper = await resolve_ref(CAFE_NFD.upper(), Lookup())
    assert upper.status is ResolveStatus.NOT_FOUND


def session_files(tmp_path: Path) -> list[Path]:
    session = tmp_path / "chatimport.session"
    companions = [session, tmp_path / "chatimport.session-journal"]
    for path in companions:
        path.write_bytes(b"")
    return companions


def test_protect_session_makes_the_session_owner_only_on_posix(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = session_files(tmp_path)
    monkeypatch.setattr(sys, "platform", "linux")
    client_mod.protect_session(files[0])
    if os.name != "nt":
        for path in files:
            assert path.stat().st_mode & 0o077 == 0


def test_protect_session_leaves_windows_acls_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    files = session_files(tmp_path)
    monkeypatch.setattr(sys, "platform", "win32")

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("chmod on Windows")

    monkeypatch.setattr(Path, "chmod", refuse)
    client_mod.protect_session(files[0])
