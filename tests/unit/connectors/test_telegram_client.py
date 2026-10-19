"""The connector over a fake Telethon client: no network, no session file."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Any

import pytest

from chatradar.config import Settings
from chatradar.connectors.telegram.client import (
    TelegramConnector,
    TelegramNotConfiguredError,
    TelegramNotLoggedInError,
    chat_info,
    login,
    make_client,
)
from chatradar.domain.models import ChatInfo, ChatKind, RawKind, Source

if TYPE_CHECKING:
    from collections.abc import AsyncIterator


@dataclass
class Channel:
    id: int
    title: str
    username: str | None = None
    megagroup: bool = True


@dataclass
class Chat:
    id: int
    title: str


@dataclass
class User:
    id: int
    first_name: str | None = None
    username: str | None = None


@dataclass
class Dialog:
    entity: object


@dataclass
class FakeMessage:
    id: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "_": "Message",
            "id": self.id,
            "date": datetime(2026, 10, 1, 10, self.id, tzinfo=UTC),
            "message": f"message {self.id}",
            "file_reference": b"\x01",
        }


@dataclass
class FakeClient:
    authorized: bool = True
    entities: dict[object, object] = field(default_factory=dict[object, object])
    dialogs: list[Dialog] = field(default_factory=list[Dialog])
    messages: list[FakeMessage] = field(default_factory=list[FakeMessage])
    calls: list[tuple[str, Any]] = field(default_factory=list[tuple[str, Any]])
    me: object = None

    async def connect(self) -> None:
        self.calls.append(("connect", None))

    async def disconnect(self) -> None:
        self.calls.append(("disconnect", None))

    async def is_user_authorized(self) -> bool:
        return self.authorized

    async def start(self) -> None:
        self.calls.append(("start", None))

    async def get_me(self) -> object:
        return self.me

    async def get_entity(self, ref: object) -> object:
        self.calls.append(("get_entity", ref))
        return self.entities[ref]

    async def iter_dialogs(self) -> AsyncIterator[Dialog]:
        for dialog in self.dialogs:
            yield dialog

    async def iter_messages(self, entity: object, **kwargs: Any) -> AsyncIterator[FakeMessage]:
        self.calls.append(("iter_messages", (entity, kwargs)))
        min_id = kwargs.get("min_id", 0)
        for message in self.messages:
            if message.id > min_id:
                yield message


def _connector(client: FakeClient) -> TelegramConnector:
    return TelegramConnector(Settings(), client_factory=lambda _settings: client)


SUPERGROUP = ChatInfo(
    source=Source.TELEGRAM, chat_id="-1001700000001", title="Expats", username="expats_demo"
)


@pytest.mark.parametrize(
    ("entity", "expected"),
    [
        (Channel(17, "Group", "grp"), ("-10017", ChatKind.SUPERGROUP, "Group", "grp")),
        (Channel(17, "News", megagroup=False), ("-10017", ChatKind.CHANNEL, "News", None)),
        (Chat(17, "Old group"), ("-17", ChatKind.GROUP, "Old group", None)),
        (User(17, "Member 1"), ("17", ChatKind.PRIVATE, "Member 1", None)),
        (User(17), ("17", ChatKind.PRIVATE, "17", None)),
    ],
)
def test_chat_info(entity: object, expected: tuple[str, ChatKind, str, str | None]) -> None:
    info = chat_info(entity)

    assert info is not None
    assert (info.chat_id, info.kind, info.title, info.username) == expected


def test_chat_info_ignores_other_entities() -> None:
    assert chat_info(Dialog(entity=None)) is None


async def test_context_manager_connects_and_disconnects() -> None:
    client = FakeClient()

    async with _connector(client) as connector:
        assert connector.source is Source.TELEGRAM

    assert client.calls == [("connect", None), ("disconnect", None)]


async def test_requires_a_logged_in_session() -> None:
    client = FakeClient(authorized=False)

    with pytest.raises(TelegramNotLoggedInError):
        async with _connector(client):
            pass

    assert client.calls[-1] == ("disconnect", None)


async def test_list_chats_skips_private_dialogs() -> None:
    client = FakeClient(
        dialogs=[Dialog(Channel(1, "A")), Dialog(User(2, "Member 2")), Dialog(Chat(3, "C"))]
    )

    chats = await _connector(client).list_chats()

    assert [c.chat_id for c in chats] == ["-1001", "-3"]


@pytest.mark.parametrize(
    ("ref", "lookup"),
    [
        ("@expats_demo", "expats_demo"),
        ("https://t.me/expats_demo", "expats_demo"),
        ("t.me/expats_demo", "expats_demo"),
        ("-1001700000001", -1001700000001),
    ],
)
async def test_resolve(ref: str, lookup: object) -> None:
    client = FakeClient(entities={lookup: Channel(1700000001, "Expats", "expats_demo")})

    chat = await _connector(client).resolve(ref)

    assert chat.chat_id == "-1001700000001"
    assert ("get_entity", lookup) in client.calls


async def test_resolve_rejects_non_chats() -> None:
    client = FakeClient(entities={"thing": object()})

    with pytest.raises(ValueError, match="not a chat"):
        await _connector(client).resolve("thing")


async def test_fetch_yields_serialized_raw_records() -> None:
    client = FakeClient(messages=[FakeMessage(1), FakeMessage(2), FakeMessage(3)])

    records = [r async for r in _connector(client).fetch(SUPERGROUP, "1")]

    assert [r.payload["id"] for r in records] == [2, 3]
    assert {(r.kind, r.chat_id) for r in records} == {(RawKind.TELETHON, "-1001700000001")}
    assert records[0].payload["date"] == "2026-10-01T10:02:00+00:00"
    assert records[0].payload["file_reference"] == "AQ=="
    assert client.calls[0] == ("iter_messages", ("expats_demo", {"min_id": 1, "reverse": True}))


async def test_fetch_by_id_without_username() -> None:
    client = FakeClient()
    private = SUPERGROUP.model_copy(update={"username": None})

    assert [r async for r in _connector(client).fetch(private, None)] == []
    assert client.calls[0] == ("iter_messages", (-1001700000001, {"min_id": 0, "reverse": True}))


async def test_fetch_recent_uses_offset_date() -> None:
    client = FakeClient(messages=[FakeMessage(1)])

    records = [r async for r in _connector(client).fetch_recent(SUPERGROUP, 7)]

    assert len(records) == 1
    _, (entity, kwargs) = client.calls[0]
    assert entity == "expats_demo"
    assert kwargs["reverse"] is True
    expected = datetime.now(UTC) - timedelta(days=7)
    assert abs(kwargs["offset_date"] - expected) < timedelta(minutes=1)


@pytest.mark.parametrize(
    ("me", "handle"),
    [
        (User(5, "Member 5", "member_five"), "@member_five"),
        (User(5, "Member 5"), "Member 5"),
        (User(5), "5"),
    ],
)
async def test_login_returns_the_handle(me: User, handle: str) -> None:
    client = FakeClient(me=me)

    assert await login(Settings(), client_factory=lambda _settings: client) == handle
    assert client.calls == [("start", None), ("disconnect", None)]


def test_make_client_needs_api_credentials() -> None:
    with pytest.raises(TelegramNotConfiguredError):
        make_client(Settings())


def test_make_client_puts_the_session_under_data_dir(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CHATRADAR_TELEGRAM__API_ID", "12345")
    monkeypatch.setenv("CHATRADAR_TELEGRAM__API_HASH", "not-a-real-hash")
    monkeypatch.setenv("CHATRADAR_TELEGRAM__FLOOD_SLEEP_THRESHOLD", "30")
    settings = Settings()

    client = make_client(settings)
    try:
        assert client.flood_sleep_threshold == 30
        assert settings.sessions_dir.is_dir()
        assert client.session.filename == str(settings.sessions_dir / "collector.session")
    finally:
        client.session.close()
